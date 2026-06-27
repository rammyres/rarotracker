import os
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash

from config import Config
from models import db, Book, CandidateEdition, Source, Listing, PushSubscription
from adapters.registry import DEFAULT_SOURCES
import isbn_resolver
from checker import check_book_against_source, notify_availability


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    os.makedirs(os.path.join(os.path.dirname(__file__), "instance"), exist_ok=True)
    db.init_app(app)

    with app.app_context():
        db.create_all()
        _seed_default_sources()

    register_routes(app)
    return app


def _seed_default_sources():
    """Insere a lista padrão de lojas monitoradas, se a tabela estiver vazia."""
    if Source.query.count() > 0:
        return
    for s in DEFAULT_SOURCES:
        db.session.add(Source(
            name=s["name"], domain=s["domain"], kind=s["kind"],
            notes=s.get("notes"), enabled=True,
        ))
    db.session.commit()


def register_routes(app):

    @app.route("/")
    def dashboard():
        books = Book.query.order_by(Book.updated_at.desc()).all()
        return render_template("dashboard.html", books=books)

    # ---------- Adicionar livro / clarificação de edição ----------

    @app.route("/add", methods=["GET", "POST"])
    def add_book():
        if request.method == "GET":
            return render_template("add.html")

        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        manual_isbn = request.form.get("isbn", "").strip().replace("-", "")

        if not title or not author:
            flash("Título e autor são obrigatórios.", "error")
            return render_template("add.html")

        book = Book(title=title, author=author, status="pending_clarification")
        db.session.add(book)
        db.session.commit()

        # Se o usuário já informou o ISBN, pula a clarificação
        if manual_isbn:
            info = isbn_resolver.lookup_by_isbn(manual_isbn)
            _confirm_edition(book, {
                "isbn13": manual_isbn if len(manual_isbn) == 13 else (info or {}).get("isbn13"),
                "isbn10": manual_isbn if len(manual_isbn) == 10 else (info or {}).get("isbn10"),
                "publisher": (info or {}).get("publisher"),
                "format_desc": (info or {}).get("format_desc"),
                "cover_url": (info or {}).get("cover_url"),
            })
            return redirect(url_for("book_detail", book_id=book.id))

        candidates = isbn_resolver.find_candidate_editions(title, author)
        if not candidates:
            flash("Nenhuma edição com ISBN foi encontrada automaticamente. Informe o ISBN manualmente.", "warning")
            return render_template("clarify.html", book=book, candidates=[])

        for c in candidates:
            db.session.add(CandidateEdition(book_id=book.id, **c))
        db.session.commit()

        return redirect(url_for("clarify_book", book_id=book.id))

    @app.route("/clarify/<int:book_id>", methods=["GET", "POST"])
    def clarify_book(book_id):
        book = Book.query.get_or_404(book_id)

        if request.method == "POST":
            candidate_id = request.form.get("candidate_id")
            manual_isbn = request.form.get("isbn", "").strip().replace("-", "")

            if candidate_id:
                candidate = CandidateEdition.query.get_or_404(int(candidate_id))
                _confirm_edition(book, {
                    "isbn13": candidate.isbn13, "isbn10": candidate.isbn10,
                    "publisher": candidate.publisher, "format_desc": candidate.format_desc,
                    "cover_url": candidate.cover_url,
                })
            elif manual_isbn:
                info = isbn_resolver.lookup_by_isbn(manual_isbn) or {}
                _confirm_edition(book, {
                    "isbn13": manual_isbn if len(manual_isbn) == 13 else info.get("isbn13"),
                    "isbn10": manual_isbn if len(manual_isbn) == 10 else info.get("isbn10"),
                    "publisher": info.get("publisher"), "format_desc": info.get("format_desc"),
                    "cover_url": info.get("cover_url"),
                })
            else:
                flash("Escolha uma edição ou informe um ISBN manualmente.", "error")
                return redirect(url_for("clarify_book", book_id=book.id))

            return redirect(url_for("book_detail", book_id=book.id))

        candidates = book.candidates.all()
        return render_template("clarify.html", book=book, candidates=candidates)

    def _confirm_edition(book, edition):
        book.isbn13 = edition.get("isbn13")
        book.isbn10 = edition.get("isbn10")
        book.publisher = edition.get("publisher")
        book.edition_format = edition.get("format_desc")
        book.cover_url = edition.get("cover_url")
        book.status = "tracking"
        book.updated_at = datetime.utcnow()
        db.session.commit()

        # Cria listagens vazias para todas as fontes habilitadas
        for source in Source.query.filter_by(enabled=True).all():
            if not Listing.query.filter_by(book_id=book.id, source_id=source.id).first():
                db.session.add(Listing(book_id=book.id, source_id=source.id))
        db.session.commit()

    # ---------- Página do livro ----------

    @app.route("/book/<int:book_id>")
    def book_detail(book_id):
        book = Book.query.get_or_404(book_id)
        listings = Listing.query.filter_by(book_id=book.id).all()
        return render_template("book.html", book=book, listings=listings, vapid_public_key=Config.VAPID_PUBLIC_KEY)

    @app.route("/book/<int:book_id>/check-now", methods=["POST"])
    def check_now(book_id):
        book = Book.query.get_or_404(book_id)
        push_subs = PushSubscription.query.all()
        for source in Source.query.filter_by(enabled=True).all():
            listing, became_available = check_book_against_source(book, source)
            if became_available:
                notify_availability(book, listing, source, push_subs)
        flash("Checagem manual concluída.", "success")
        return redirect(url_for("book_detail", book_id=book.id))

    @app.route("/book/<int:book_id>/delete", methods=["POST"])
    def delete_book(book_id):
        book = Book.query.get_or_404(book_id)
        db.session.delete(book)
        db.session.commit()
        flash("Livro removido.", "success")
        return redirect(url_for("dashboard"))

    # ---------- Fontes (sites monitorados) ----------

    @app.route("/sources")
    def sources_list():
        sources = Source.query.order_by(Source.name).all()
        return render_template("sources.html", sources=sources)

    @app.route("/sources/<int:source_id>/toggle", methods=["POST"])
    def toggle_source(source_id):
        source = Source.query.get_or_404(source_id)
        source.enabled = not source.enabled
        db.session.commit()
        return redirect(url_for("sources_list"))

    # ---------- Web Push ----------

    @app.route("/push/subscribe", methods=["POST"])
    def push_subscribe():
        data = request.get_json(force=True)
        endpoint = data.get("endpoint")
        keys = data.get("keys", {})
        if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
            return jsonify({"ok": False, "error": "payload inválido"}), 400

        existing = PushSubscription.query.filter_by(endpoint=endpoint).first()
        if not existing:
            db.session.add(PushSubscription(
                endpoint=endpoint, p256dh=keys["p256dh"], auth=keys["auth"],
            ))
            db.session.commit()
        return jsonify({"ok": True})

    @app.route("/push/vapid-public-key")
    def push_vapid_public_key():
        return jsonify({"publicKey": Config.VAPID_PUBLIC_KEY})

    @app.route("/sw.js")
    def service_worker():
        # Servido na raiz (não em /static/) para que o escopo cubra o site todo.
        sw_path = os.path.join(app.static_folder, "sw.js")
        with open(sw_path, "r", encoding="utf-8") as f:
            content = f.read()
        resp = app.response_class(content, mimetype="application/javascript")
        resp.headers["Service-Worker-Allowed"] = "/"
        return resp


app = create_app()

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5050)
