"""
Lógica central de checagem — usada tanto pelo script do systemd timer
(scheduler/check_availability.py, 3x/dia) quanto pelo botão "checar agora"
na página do livro.

Regra de notificação: só alerta quando o estado muda de
"não disponível / não encontrado" para "disponível" (evita alertas
repetidos a cada execução enquanto o item continua disponível).
"""
import logging
from datetime import datetime

from models import db, Listing, NotificationLog
from adapters.registry import get_adapter
from notifications import send_email_alert, send_push_alert, build_availability_email

logger = logging.getLogger("raro_tracker.checker")


def check_book_against_source(book, source):
    listing = Listing.query.filter_by(book_id=book.id, source_id=source.id).first()
    if not listing:
        listing = Listing(book_id=book.id, source_id=source.id)
        db.session.add(listing)

    was_available = bool(listing.available)

    adapter = get_adapter(source)
    result = adapter.check(book)

    listing.matched = result.matched
    listing.last_checked_at = datetime.utcnow()
    listing.last_error = result.error

    if result.product_url:
        listing.product_url = result.product_url
    if result.available is not None:
        listing.available = result.available
    if result.price_amount is not None:
        listing.price_amount = result.price_amount
        listing.price_currency = result.price_currency
    if result.ships_to_br is not None:
        listing.ships_to_br = result.ships_to_br
    if result.shipping_cost_brl is not None:
        listing.shipping_cost_brl = result.shipping_cost_brl
    if result.shipping_method:
        listing.shipping_method = result.shipping_method
    if result.shipping_note:
        listing.shipping_note = result.shipping_note

    became_available = result.available and not was_available
    if became_available:
        listing.last_available_at = datetime.utcnow()

    db.session.commit()
    return listing, became_available


def notify_availability(book, listing, source, push_subscriptions):
    subject, body_html = build_availability_email(book, listing, source)
    send_email_alert(subject, body_html)

    dead_ids = send_push_alert(
        push_subscriptions,
        title=f"📚 Disponível: {book.title}",
        body=f"{source.name} — confira agora",
        url=f"/book/{book.id}",
    )
    if dead_ids:
        from models import PushSubscription
        PushSubscription.query.filter(PushSubscription.id.in_(dead_ids)).delete(
            synchronize_session=False
        )
        db.session.commit()

    db.session.add(NotificationLog(book_id=book.id, source_id=source.id, channel="email"))
    db.session.add(NotificationLog(book_id=book.id, source_id=source.id, channel="push"))
    db.session.commit()


def run_full_check():
    """Roda a checagem para todos os livros 'tracking' contra todas as fontes habilitadas."""
    from models import Book, Source, PushSubscription

    books = Book.query.filter_by(status="tracking").all()
    sources = Source.query.filter_by(enabled=True).all()
    push_subscriptions = PushSubscription.query.all()

    summary = {"checked": 0, "newly_available": 0, "errors": 0}

    for book in books:
        for source in sources:
            try:
                listing, became_available = check_book_against_source(book, source)
                summary["checked"] += 1
                if listing.last_error:
                    summary["errors"] += 1
                if became_available:
                    summary["newly_available"] += 1
                    notify_availability(book, listing, source, push_subscriptions)
            except Exception as e:
                logger.exception(f"Erro checando livro={book.id} fonte={source.id}: {e}")
                summary["errors"] += 1

    return summary
