from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Book(db.Model):
    """Um livro raro sendo rastreado pelo usuário."""

    __tablename__ = "books"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    author = db.Column(db.String(300), nullable=False)

    # Preenchido somente após a etapa de clarificação (escolha da edição canônica)
    isbn13 = db.Column(db.String(20))
    isbn10 = db.Column(db.String(20))
    publisher = db.Column(db.String(300))
    edition_format = db.Column(db.String(120))  # ex: "Special Edition Hardcover"
    cover_url = db.Column(db.String(1000))

    # pending_clarification -> esperando o usuário escolher a edição
    # tracking -> sendo monitorado nos sites
    status = db.Column(db.String(40), default="pending_clarification", nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    candidates = db.relationship(
        "CandidateEdition", backref="book", cascade="all, delete-orphan", lazy="dynamic"
    )
    listings = db.relationship(
        "Listing", backref="book", cascade="all, delete-orphan", lazy="dynamic"
    )

    def display_isbn(self):
        return self.isbn13 or self.isbn10 or "—"


class CandidateEdition(db.Model):
    """Edição candidata sugerida durante a etapa de clarificação (Google Books / Open Library)."""

    __tablename__ = "candidate_editions"

    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey("books.id"), nullable=False)

    isbn13 = db.Column(db.String(20))
    isbn10 = db.Column(db.String(20))
    title = db.Column(db.String(500))
    publisher = db.Column(db.String(300))
    published_date = db.Column(db.String(40))
    format_desc = db.Column(db.String(200))  # hardcover/paperback/etc, quando disponível
    cover_url = db.Column(db.String(1000))
    source_api = db.Column(db.String(40))  # "google_books" | "open_library" | "manual"


class Source(db.Model):
    """Uma loja/site monitorada (The Broken Binding, FairyLoot, Amazon, etc)."""

    __tablename__ = "sources"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    domain = db.Column(db.String(200), nullable=False)
    kind = db.Column(db.String(40), nullable=False)  # "shopify" | "amazon_search"
    enabled = db.Column(db.Boolean, default=True)
    notes = db.Column(db.String(500))

    listings = db.relationship("Listing", backref="source", cascade="all, delete-orphan")


class Listing(db.Model):
    """Estado mais recente de um livro em um site específico."""

    __tablename__ = "listings"

    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey("books.id"), nullable=False)
    source_id = db.Column(db.Integer, db.ForeignKey("sources.id"), nullable=False)

    product_url = db.Column(db.String(1000))
    matched = db.Column(db.Boolean, default=False)  # encontramos o produto no site?
    available = db.Column(db.Boolean, default=False)
    price_amount = db.Column(db.Float)
    price_currency = db.Column(db.String(10))

    ships_to_br = db.Column(db.Boolean)  # None = desconhecido, True/False = checado
    shipping_cost_brl = db.Column(db.Float)
    shipping_method = db.Column(db.String(200))
    shipping_note = db.Column(db.String(300))  # ex: "verificar no checkout"

    last_checked_at = db.Column(db.DateTime)
    last_available_at = db.Column(db.DateTime)
    last_error = db.Column(db.String(500))

    __table_args__ = (db.UniqueConstraint("book_id", "source_id", name="uq_book_source"),)


class PushSubscription(db.Model):
    """Inscrição de notificação push do navegador (Web Push)."""

    __tablename__ = "push_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    endpoint = db.Column(db.String(1000), unique=True, nullable=False)
    p256dh = db.Column(db.String(300), nullable=False)
    auth = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AppSettings(db.Model):
    """Configuração de notificação editável pela UI (sobrepõe as variáveis
    de ambiente quando preenchida). Linha única (id=1)."""

    __tablename__ = "app_settings"

    id = db.Column(db.Integer, primary_key=True)

    alert_email_to = db.Column(db.String(300))
    telegram_bot_token = db.Column(db.String(300))
    telegram_chat_id = db.Column(db.String(100))

    @classmethod
    def get(cls):
        settings = cls.query.get(1)
        if not settings:
            settings = cls(id=1)
            db.session.add(settings)
            db.session.commit()
        return settings


class NotificationLog(db.Model):
    """Histórico de alertas enviados, para não notificar duplicado."""

    __tablename__ = "notification_log"

    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey("books.id"), nullable=False)
    source_id = db.Column(db.Integer, db.ForeignKey("sources.id"), nullable=False)
    channel = db.Column(db.String(20))  # "email" | "push"
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
