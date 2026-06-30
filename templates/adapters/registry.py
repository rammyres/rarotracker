"""
Registro de adapters por `kind`, e a lista padrão de sites monitorados.

A lista de sites foi levantada via pesquisa antes de construir o projeto:
- The Broken Binding, FairyLoot, Illumicrate, OwlCrate e Goldsboro Books
  rodam em Shopify -> usam o ShopifyAdapter (endpoints públicos, sem
  autenticação: /search/suggest.json, /products.json e Storefront GraphQL
  tokenless para frete).
- Amazon não tem API viável para um app novo (PA-API exige histórico de
  vendas de afiliado) -> usa AmazonSearchAdapter, que só gera o link de
  busca (sem checagem automática de disponibilidade/preço).

Para adicionar uma nova loja Shopify, basta inserir um Source com
kind="shopify" e o domínio — não precisa escrever código novo.
"""
from adapters.shopify_adapter import ShopifyAdapter
from adapters.amazon_adapter import AmazonSearchAdapter

ADAPTER_REGISTRY = {
    "shopify": ShopifyAdapter,
    "amazon_search": AmazonSearchAdapter,
}

DEFAULT_SOURCES = [
    {"name": "The Broken Binding", "domain": "thebrokenbindingsub.com", "kind": "shopify"},
    {"name": "FairyLoot", "domain": "fairyloot.com", "kind": "shopify"},
    {"name": "Illumicrate", "domain": "illumicrate.com", "kind": "shopify"},
    {"name": "OwlCrate", "domain": "owlcrate.com", "kind": "shopify"},
    {"name": "Goldsboro Books", "domain": "goldsborobooks.com", "kind": "shopify"},
    {"name": "Amazon.com", "domain": "www.amazon.com", "kind": "amazon_search",
     "notes": "Sem checagem automática — PA-API indisponível para apps novos."},
    {"name": "Amazon.com.br", "domain": "www.amazon.com.br", "kind": "amazon_search",
     "notes": "Sem checagem automática — PA-API indisponível para apps novos."},
]


def get_adapter(source):
    cls = ADAPTER_REGISTRY.get(source.kind)
    if not cls:
        raise ValueError(f"Nenhum adapter registrado para kind={source.kind}")
    return cls(source)
