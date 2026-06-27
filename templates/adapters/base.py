"""
Interface comum que todo adapter de site precisa implementar.

Cada adapter recebe um livro (título, autor, isbn) e tenta:
1. Achar o produto correspondente no site (match)
2. Checar disponibilidade e preço
3. Estimar custo de frete para o Brasil (quando o site permitir isso
   sem autenticação)

Retorna sempre um CheckResult — nunca lança exceção para fora; erros
de rede/parsing ficam registrados em `error`.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class CheckResult:
    matched: bool = False
    product_url: Optional[str] = None
    available: Optional[bool] = None
    price_amount: Optional[float] = None
    price_currency: Optional[str] = None
    ships_to_br: Optional[bool] = None
    shipping_cost_brl: Optional[float] = None
    shipping_method: Optional[str] = None
    shipping_note: Optional[str] = None
    error: Optional[str] = None


class BaseAdapter:
    kind = "base"

    def __init__(self, source):
        self.source = source  # models.Source

    def check(self, book) -> CheckResult:
        raise NotImplementedError
