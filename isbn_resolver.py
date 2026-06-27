"""
Resolve título+autor em edições candidatas (com ISBN), usando APIs públicas
e gratuitas — sem necessidade de chave de API:

- Google Books API (volumes?q=...)
- Open Library (search.json + work/editions)

O objetivo é dar ao usuário uma lista curta de edições reais (com ISBN-13,
editora, formato e capa) para que ele escolha a edição canônica antes de
começarmos a rastrear disponibilidade nos sites.
"""
import requests
from config import Config

HEADERS = {"User-Agent": Config.USER_AGENT}


def _get(url, params=None):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=Config.HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def search_google_books(title, author, max_results=8):
    query = f'intitle:"{title}" inauthor:"{author}"'
    data = _get(
        "https://www.googleapis.com/books/v1/volumes",
        params={"q": query, "maxResults": max_results},
    )
    results = []
    if not data or "items" not in data:
        return results

    for item in data["items"]:
        info = item.get("volumeInfo", {})
        identifiers = info.get("industryIdentifiers", [])
        isbn13 = next((i["identifier"] for i in identifiers if i["type"] == "ISBN_13"), None)
        isbn10 = next((i["identifier"] for i in identifiers if i["type"] == "ISBN_10"), None)
        if not isbn13 and not isbn10:
            continue  # sem ISBN não dá pra rastrear de forma confiável

        results.append(
            {
                "isbn13": isbn13,
                "isbn10": isbn10,
                "title": info.get("title"),
                "publisher": info.get("publisher"),
                "published_date": info.get("publishedDate"),
                "format_desc": info.get("printType"),
                "cover_url": (info.get("imageLinks") or {}).get("thumbnail"),
                "source_api": "google_books",
            }
        )
    return results


def search_open_library(title, author, max_results=8):
    data = _get(
        "https://openlibrary.org/search.json",
        params={"title": title, "author": author, "limit": max_results, "fields": (
            "title,author_name,isbn,publisher,first_publish_year,cover_i,edition_key"
        )},
    )
    results = []
    if not data or "docs" not in data:
        return results

    for doc in data["docs"]:
        isbns = doc.get("isbn") or []
        isbn13 = next((i for i in isbns if len(i) == 13), None)
        isbn10 = next((i for i in isbns if len(i) == 10), None)
        if not isbn13 and not isbn10:
            continue

        cover_id = doc.get("cover_i")
        cover_url = f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg" if cover_id else None
        publishers = doc.get("publisher") or []

        results.append(
            {
                "isbn13": isbn13,
                "isbn10": isbn10,
                "title": doc.get("title"),
                "publisher": publishers[0] if publishers else None,
                "published_date": str(doc.get("first_publish_year") or ""),
                "format_desc": None,
                "cover_url": cover_url,
                "source_api": "open_library",
            }
        )
    return results


def lookup_by_isbn(isbn):
    """Usado quando o usuário já sabe o ISBN exato e quer pular a clarificação."""
    data = _get(
        "https://www.googleapis.com/books/v1/volumes", params={"q": f"isbn:{isbn}"}
    )
    if data and data.get("items"):
        info = data["items"][0].get("volumeInfo", {})
        return {
            "isbn13": isbn if len(isbn) == 13 else None,
            "isbn10": isbn if len(isbn) == 10 else None,
            "title": info.get("title"),
            "publisher": info.get("publisher"),
            "published_date": info.get("publishedDate"),
            "format_desc": info.get("printType"),
            "cover_url": (info.get("imageLinks") or {}).get("thumbnail"),
            "source_api": "google_books",
        }
    return None


def dedupe_candidates(candidates):
    """Remove duplicatas pelo ISBN-13 (preferência) ou ISBN-10, mantendo o primeiro encontrado."""
    seen = set()
    unique = []
    for c in candidates:
        key = c.get("isbn13") or c.get("isbn10")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(c)
    return unique


def find_candidate_editions(title, author):
    candidates = search_google_books(title, author) + search_open_library(title, author)
    return dedupe_candidates(candidates)
