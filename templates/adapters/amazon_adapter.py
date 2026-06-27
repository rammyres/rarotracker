"""
Adapter para Amazon.

A Product Advertising API exige histórico de vendas de afiliado para
liberar acesso, então não é viável para um projeto novo. Em vez de fazer
scraping (contra os termos de uso da Amazon e detectado/bloqueado
rapidamente), este adapter apenas monta uma URL de busca por ISBN — você
abre o link e confere manualmente. `matched`/`available` ficam sempre
None aqui; a página do livro mostra isso como "verificar manualmente".
"""
from urllib.parse import quote_plus

from adapters.base import BaseAdapter, CheckResult


class AmazonSearchAdapter(BaseAdapter):
    kind = "amazon_search"

    def check(self, book) -> CheckResult:
        result = CheckResult()
        query = book.isbn13 or book.isbn10 or f"{book.title} {book.author}"
        result.product_url = f"https://{self.source.domain}/s?k={quote_plus(query)}"
        result.matched = None
        result.available = None
        result.shipping_note = "Amazon não monitorado automaticamente — abra o link e confira disponibilidade/frete manualmente."
        return result
