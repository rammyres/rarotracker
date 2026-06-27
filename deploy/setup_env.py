#!/usr/bin/env python3
"""
Assistente interativo para gerar o arquivo .env do Raro Tracker.

Uso:
    python3 deploy/setup_env.py

Pode ser rodado de novo a qualquer momento — se já existir um .env,
pergunta antes de sobrescrever (e oferece fazer backup).
"""
import os
import secrets
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def ask(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or default


def ask_yes_no(prompt, default_yes=True):
    default_label = "S/n" if default_yes else "s/N"
    val = input(f"{prompt} ({default_label}): ").strip().lower()
    if not val:
        return default_yes
    return val in ("s", "sim", "y", "yes")


def generate_vapid_keys():
    """Reaproveita a mesma lógica de deploy/generate_vapid_keys.py."""
    import base64
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    private_bytes = private_key.private_numbers().private_value.to_bytes(32, "big")
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return b64url(private_bytes), b64url(public_bytes)


def main():
    print("=== Assistente de configuração — Raro Tracker ===\n")

    if os.path.exists(ENV_PATH):
        if not ask_yes_no(f".env já existe em {ENV_PATH}. Sobrescrever?", default_yes=False):
            print("Cancelado. Nada foi alterado.")
            return
        backup = ENV_PATH + ".bak"
        shutil.copy(ENV_PATH, backup)
        print(f"Backup salvo em {backup}\n")

    env = {}
    env["SECRET_KEY"] = secrets.token_hex(32)
    print("✓ SECRET_KEY gerada automaticamente.\n")

    env["ALERT_EMAIL_TO"] = ask("E-mail que vai receber os alertas de disponibilidade")

    print("\n--- E-mail ---")
    print("1) SMTP (Gmail, Resend, SendGrid, etc — precisa de host/usuário/senha)")
    print("2) sendmail local (usa o Postfix/Exim/msmtp já configurado neste servidor)")
    print("3) Pular (não enviar e-mail, só notificação push no navegador)")
    choice = ask("Escolha", default="1")

    if choice == "2":
        env["EMAIL_BACKEND"] = "sendmail"
        env["SENDMAIL_PATH"] = ask("Caminho do binário sendmail", default="/usr/sbin/sendmail")
        env["EMAIL_FROM"] = ask("Endereço de 'From' nos e-mails", default="raro-tracker@localhost")
        print(
            "  Nota: a entregabilidade depende do MTA local ter SPF/rDNS/DKIM "
            "configurados; sem isso, os e-mails podem cair em spam."
        )
    elif choice == "3":
        env["EMAIL_BACKEND"] = "smtp"  # default, mas sem host configurado = desativado
        env["ALERT_EMAIL_TO"] = env.get("ALERT_EMAIL_TO", "")
        print("  E-mail desativado — você pode configurar depois rodando este assistente de novo.")
    else:
        env["EMAIL_BACKEND"] = "smtp"
        env["SMTP_HOST"] = ask("SMTP_HOST", default="smtp.gmail.com")
        env["SMTP_PORT"] = ask("SMTP_PORT", default="587")
        env["SMTP_USER"] = ask("SMTP_USER (seu e-mail)")
        env["SMTP_PASSWORD"] = ask("SMTP_PASSWORD (use uma 'senha de app' no Gmail, não a senha normal)")
        env["SMTP_USE_TLS"] = "true" if ask_yes_no("Usar TLS?", default_yes=True) else "false"
        env["EMAIL_FROM"] = ask("EMAIL_FROM", default=env["SMTP_USER"])

    print("\n--- Notificação push no navegador (opcional) ---")
    if ask_yes_no("Gerar chaves VAPID agora?", default_yes=True):
        priv, pub = generate_vapid_keys()
        env["VAPID_PRIVATE_KEY"] = priv
        env["VAPID_PUBLIC_KEY"] = pub
        env["VAPID_CLAIM_EMAIL"] = "mailto:" + (env.get("ALERT_EMAIL_TO") or "admin@example.com")
        print("✓ Chaves VAPID geradas.")
    else:
        env["VAPID_PRIVATE_KEY"] = ""
        env["VAPID_PUBLIC_KEY"] = ""
        print("  Push desativado por enquanto — rode este assistente de novo quando quiser ativar.")

    print("\n--- Endereço de referência para cálculo de frete (Brasil) ---")
    env["SHIP_TO_ZIP"] = ask("CEP", default="64280-000")
    env["SHIP_TO_PROVINCE"] = ask("UF", default="PI")

    lines = [
        "# Gerado por deploy/setup_env.py",
        "",
        f"SECRET_KEY={env['SECRET_KEY']}",
        "",
        "# --- E-mail ---",
        f"EMAIL_BACKEND={env.get('EMAIL_BACKEND', 'smtp')}",
    ]
    if env.get("EMAIL_BACKEND") == "sendmail":
        lines += [f"SENDMAIL_PATH={env.get('SENDMAIL_PATH', '/usr/sbin/sendmail')}"]
    else:
        lines += [
            f"SMTP_HOST={env.get('SMTP_HOST', '')}",
            f"SMTP_PORT={env.get('SMTP_PORT', '587')}",
            f"SMTP_USER={env.get('SMTP_USER', '')}",
            f"SMTP_PASSWORD={env.get('SMTP_PASSWORD', '')}",
            f"SMTP_USE_TLS={env.get('SMTP_USE_TLS', 'true')}",
        ]
    lines += [
        f"EMAIL_FROM={env.get('EMAIL_FROM', '')}",
        f"ALERT_EMAIL_TO={env.get('ALERT_EMAIL_TO', '')}",
        "",
        "# --- Web Push (VAPID) ---",
        f"VAPID_PRIVATE_KEY={env.get('VAPID_PRIVATE_KEY', '')}",
        f"VAPID_PUBLIC_KEY={env.get('VAPID_PUBLIC_KEY', '')}",
        f"VAPID_CLAIM_EMAIL={env.get('VAPID_CLAIM_EMAIL', 'mailto:admin@example.com')}",
        "",
        "# --- Frete (Brasil) ---",
        f"SHIP_TO_ZIP={env['SHIP_TO_ZIP']}",
        f"SHIP_TO_PROVINCE={env['SHIP_TO_PROVINCE']}",
        "",
    ]

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n✓ .env escrito em {ENV_PATH}")
    print("Pronto. Rode `python3 app.py` (dev) ou reinicie o systemd service (produção).")


if __name__ == "__main__":
    main()
