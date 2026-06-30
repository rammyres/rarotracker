"""
Envio de alertas em três canais:
- E-mail: SMTP genérico, sendmail local, ou API HTTP da Resend
  (EMAIL_BACKEND escolhe qual)
- Telegram (Bot API, HTTP simples)
- Web Push (notificação do navegador, via pywebpush + VAPID)

Todos são "best effort": se um canal falhar ou não estiver configurado,
os outros continuam funcionando e o erro só é logado.
"""
import smtplib
import json
import logging
import subprocess
from email.mime.text import MIMEText

import requests
from pywebpush import webpush, WebPushException

from config import Config

logger = logging.getLogger("raro_tracker.notifications")


def _effective_alert_email():
    """DB (configurado pela UI em /settings) tem prioridade sobre .env."""
    from models import AppSettings
    settings = AppSettings.get()
    return settings.alert_email_to or Config.ALERT_EMAIL_TO


def _effective_telegram():
    from models import AppSettings
    settings = AppSettings.get()
    token = settings.telegram_bot_token or Config.TELEGRAM_BOT_TOKEN
    chat_id = settings.telegram_chat_id or Config.TELEGRAM_CHAT_ID
    return token, chat_id


def _send_via_smtp(msg):
    if not Config.SMTP_HOST:
        logger.warning("EMAIL_BACKEND=smtp mas SMTP_HOST não configurado — pulando alerta por e-mail.")
        return False
    try:
        with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT, timeout=15) as server:
            if Config.SMTP_USE_TLS:
                server.starttls()
            if Config.SMTP_USER:
                server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
            server.sendmail(Config.EMAIL_FROM, [msg["To"]], msg.as_string())
        return True
    except Exception as e:
        logger.error(f"Falha ao enviar e-mail via SMTP: {e}")
        return False


def _send_via_sendmail(msg):
    """Usa o MTA local (Postfix/Exim/msmtp) via o binário sendmail, sem
    precisar de host/porta/usuário — útil quando o próprio servidor já
    está configurado para enviar e-mail (ex: Postfix com SPF/rDNS ok)."""
    try:
        proc = subprocess.run(
            [Config.SENDMAIL_PATH, "-t", "-i"],
            input=msg.as_string().encode("utf-8"),
            capture_output=True,
            timeout=15,
        )
        if proc.returncode != 0:
            logger.error(
                f"sendmail saiu com código {proc.returncode}: {proc.stderr.decode(errors='replace')}"
            )
            return False
        return True
    except FileNotFoundError:
        logger.error(
            f"Binário sendmail não encontrado em {Config.SENDMAIL_PATH} — "
            "instale Postfix/Exim/msmtp ou mude EMAIL_BACKEND para 'smtp'."
        )
        return False
    except Exception as e:
        logger.error(f"Falha ao enviar e-mail via sendmail: {e}")
        return False


def send_telegram_alert(text):
    """Envia uma mensagem via Telegram Bot API (HTTP simples — não precisa
    da lib python-telegram-bot aqui, só enviamos, não recebemos comandos).
    Best-effort: se não configurado ou falhar, só loga e segue o jogo."""
    bot_token, chat_id = _effective_telegram()
    if not (bot_token and chat_id):
        logger.warning("Telegram não configurado (token/chat_id ausentes) — pulando.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
        if r.status_code != 200:
            logger.error(f"Telegram respondeu {r.status_code}: {r.text[:200]}")
            return False
        return True
    except requests.RequestException as e:
        logger.error(f"Falha ao enviar mensagem no Telegram: {e}")
        return False


def build_availability_telegram_text(book, listing, source):
    price = f"{listing.price_amount} {listing.price_currency}" if listing.price_amount else "preço não disponível"
    shipping = (
        f"R$ {listing.shipping_cost_brl:.2f}" if listing.shipping_cost_brl
        else (listing.shipping_note or "frete não verificado")
    )
    return (
        f"📚 <b>Disponível: {book.title}</b>\n"
        f"Autor: {book.author}\n"
        f"Loja: {source.name}\n"
        f"Preço: {price}\n"
        f"Frete p/ Brasil: {shipping}\n"
        f"{listing.product_url or ''}"
    )


def _send_via_resend(subject, body_html, to_addr):
    """Usa a API HTTP da Resend (https://api.resend.com/emails) — mais
    simples que SMTP, só precisa da API key. A Resend exige um header
    User-Agent em toda requisição (o requests já manda um por padrão,
    então não precisamos setar nada extra)."""
    if not Config.RESEND_API_KEY:
        logger.warning("EMAIL_BACKEND=resend mas RESEND_API_KEY não configurada — pulando alerta por e-mail.")
        return False
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {Config.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": Config.EMAIL_FROM or "onboarding@resend.dev",
                "to": to_addr,
                "subject": subject,
                "html": body_html,
            },
            timeout=15,
        )
        if r.status_code not in (200, 201):
            logger.error(f"Resend respondeu {r.status_code}: {r.text[:300]}")
            return False
        return True
    except requests.RequestException as e:
        logger.error(f"Falha ao enviar e-mail via Resend: {e}")
        return False


def send_email_alert(subject, body_html, body_text=None):
    to_addr = _effective_alert_email()
    if not to_addr:
        logger.warning("Nenhum e-mail de alerta configurado (nem em /settings, nem em ALERT_EMAIL_TO) — pulando.")
        return False

    if Config.EMAIL_BACKEND == "resend":
        return _send_via_resend(subject, body_html, to_addr)

    msg = MIMEText(body_html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = Config.EMAIL_FROM or "raro-tracker@localhost"
    msg["To"] = to_addr

    if Config.EMAIL_BACKEND == "sendmail":
        return _send_via_sendmail(msg)
    return _send_via_smtp(msg)


def send_push_alert(subscriptions, title, body, url=None):
    """`subscriptions` é uma lista de models.PushSubscription. Remove inscrições
    mortas (410/404) automaticamente."""
    if not (Config.VAPID_PRIVATE_KEY and Config.VAPID_PUBLIC_KEY):
        logger.warning("VAPID não configurado — pulando alerta por push.")
        return []

    dead_subscription_ids = []
    payload = json.dumps({"title": title, "body": body, "url": url or "/"})

    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=Config.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": Config.VAPID_CLAIM_EMAIL},
            )
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):
                dead_subscription_ids.append(sub.id)
            logger.error(f"Falha ao enviar push para {sub.endpoint[:50]}...: {e}")

    return dead_subscription_ids


def build_availability_email(book, listing, source):
    price = f"{listing.price_amount} {listing.price_currency}" if listing.price_amount else "preço não disponível"
    shipping = (
        f"R$ {listing.shipping_cost_brl:.2f}" if listing.shipping_cost_brl
        else (listing.shipping_note or "frete não verificado")
    )
    subject = f"📚 Disponível: {book.title} — {source.name}"
    body_html = f"""
    <h2>{book.title}</h2>
    <p><b>Autor:</b> {book.author}<br>
       <b>ISBN:</b> {book.display_isbn()}<br>
       <b>Loja:</b> {source.name}<br>
       <b>Preço:</b> {price}<br>
       <b>Frete estimado p/ Brasil:</b> {shipping}</p>
    <p><a href="{listing.product_url}">Abrir página do produto</a></p>
    """
    return subject, body_html
