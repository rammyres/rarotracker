"""
Envio de alertas em dois canais:
- E-mail (SMTP genérico, via smtplib — funciona com Gmail app password,
  Resend, SendGrid SMTP relay, etc; só trocar as variáveis de ambiente)
- Web Push (notificação do navegador, via pywebpush + VAPID)

Ambos são "best effort": se um canal falhar (ex: SMTP não configurado),
o outro continua funcionando e o erro só é logado.
"""
import smtplib
import json
import logging
from email.mime.text import MIMEText

from pywebpush import webpush, WebPushException

from config import Config

logger = logging.getLogger("raro_tracker.notifications")


def send_email_alert(subject, body_html, body_text=None):
    if not (Config.SMTP_HOST and Config.ALERT_EMAIL_TO):
        logger.warning("E-mail não configurado (SMTP_HOST/ALERT_EMAIL_TO ausentes) — pulando alerta por e-mail.")
        return False

    msg = MIMEText(body_html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = Config.EMAIL_FROM
    msg["To"] = Config.ALERT_EMAIL_TO

    try:
        with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT, timeout=15) as server:
            if Config.SMTP_USE_TLS:
                server.starttls()
            if Config.SMTP_USER:
                server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
            server.sendmail(Config.EMAIL_FROM, [Config.ALERT_EMAIL_TO], msg.as_string())
        return True
    except Exception as e:
        logger.error(f"Falha ao enviar e-mail: {e}")
        return False


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
