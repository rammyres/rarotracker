"""
Configuração central do Raro Tracker.
Tudo sensível (SMTP, VAPID keys) vem de variáveis de ambiente — nada fica
hardcoded no código. Use um arquivo .env (veja .env.example) em dev,
e variáveis de ambiente reais (systemd EnvironmentFile=) em produção.
"""
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'raro_tracker.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- E-mail (SMTP genérico — funciona com Gmail app password, Resend, etc.) ---
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
    EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USER)
    ALERT_EMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "")  # destinatário padrão (uso single-user)

    # --- Web Push (VAPID) ---
    VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
    VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
    VAPID_CLAIM_EMAIL = os.environ.get("VAPID_CLAIM_EMAIL", "mailto:admin@example.com")

    # --- Destino de entrega (para cálculo de frete) ---
    SHIP_TO_COUNTRY_CODE = "BR"
    SHIP_TO_ZIP = os.environ.get("SHIP_TO_ZIP", "64280-000")  # CEP usado como referência p/ frete
    SHIP_TO_PROVINCE = os.environ.get("SHIP_TO_PROVINCE", "PI")

    # --- HTTP ---
    HTTP_TIMEOUT = 15
    USER_AGENT = "RaroTrackerBot/1.0 (+personal book availability tracker)"
