"""
Adapter genérico para lojas Shopify (a maioria das lojas de "rare/special
editions" — The Broken Binding, FairyLoot, Illumicrate, OwlCrate, Goldsboro
Books — usa Shopify). Usa apenas endpoints públicos, sem autenticação:

1. Match do produto:
   - GET /search/suggest.json?q=<query>&resources[type]=product  (busca rápida)
   - fallback: paginar /products.json e comparar título / ISBN no campo
     `barcode` das variantes (livrarias quase sempre colocam o ISBN aqui)

2. Disponibilidade e preço:
   - vem direto do JSON do produto (`variants[].available`, `variants[].price`)

3. Frete para o Brasil:
   - Storefront GraphQL API (tokenless access, sem precisar de App/API key)
   - monta um cart com a variante, atualiza o buyerIdentity com endereço BR
     e lê `deliveryGroups[].deliveryOptions[].estimatedCost`
   - se a loja não permitir acesso tokenless ou não entregar no Brasil,
     marca ships_to_br=False ou deixa shipping_note explicando
"""
import difflib
import requests

from adapters.base import BaseAdapter, CheckResult
from config import Config

HEADERS = {"User-Agent": Config.USER_AGENT, "Accept": "application/json"}


def _get_json(url, params=None):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=Config.HTTP_TIMEOUT)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code} em {url}"
        return r.json(), None
    except requests.RequestException as e:
        return None, str(e)


def _title_score(a, b):
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


class ShopifyAdapter(BaseAdapter):
    kind = "shopify"

    def __init__(self, source):
        super().__init__(source)
        self.base = f"https://{source.domain}"

    # ---------- 1. Encontrar o produto ----------

    def _search_suggest(self, query):
        data, err = _get_json(
            f"{self.base}/search/suggest.json",
            params={"q": query, "resources[type]": "product", "resources[limit]": 10},
        )
        if not data:
            return [], err
        products = (data.get("resources", {}).get("results", {}) or {}).get("products", [])
        return products, None

    def _scan_products_json(self, isbn13, isbn10, title, max_pages=8):
        """Fallback: percorre /products.json procurando ISBN no barcode das variantes."""
        for page in range(1, max_pages + 1):
            data, err = _get_json(f"{self.base}/products.json", params={"limit": 250, "page": page})
            if not data:
                return None, err
            products = data.get("products", [])
            if not products:
                break
            for product in products:
                for variant in product.get("variants", []):
                    barcode = (variant.get("barcode") or "").replace("-", "").strip()
                    if barcode and (barcode == isbn13 or barcode == isbn10):
                        return product, None
            # fallback adicional por similaridade de título, caso nenhum ISBN bata
        return None, None

    def _fetch_full_product(self, handle):
        """suggest.json só traz dados leves (sem variants/barcode/available).
        Depois de achar o handle, buscamos o produto completo para ter
        variantes reais."""
        data, err = _get_json(f"{self.base}/products/{handle}.json")
        if data and "product" in data:
            return data["product"], None
        return None, err

    def find_product(self, book):
        query = f"{book.title} {book.author}"
        suggestions, err = self._search_suggest(query)
        best = None
        best_score = 0.0
        for p in suggestions:
            score = _title_score(p.get("title", ""), book.title)
            if score > best_score:
                best, best_score = p, score

        if best and best_score >= 0.45 and best.get("handle"):
            full_product, fetch_err = self._fetch_full_product(best["handle"])
            if full_product:
                return full_product, None
            err = err or fetch_err  # cai pro fallback abaixo se o detalhe falhar

        # fallback: varrer o catálogo procurando o ISBN exato no barcode
        if book.isbn13 or book.isbn10:
            product, err2 = self._scan_products_json(book.isbn13, book.isbn10, book.title)
            if product:
                return product, None
            err = err or err2

        return None, err

    # ---------- 2. Disponibilidade / preço ----------

    def _pick_variant(self, product, book):
        variants = product.get("variants", [])
        if not variants:
            return None
        if book.isbn13 or book.isbn10:
            for v in variants:
                barcode = (v.get("barcode") or "").replace("-", "").strip()
                if barcode and barcode in (book.isbn13, book.isbn10):
                    return v
        return variants[0]

    # ---------- 3. Frete para o Brasil (Storefront GraphQL, tokenless) ----------

    def _estimate_shipping_to_br(self, product, variant):
        variant_gid = f"gid://shopify/ProductVariant/{variant.get('id')}"
        endpoint = f"{self.base}/api/2024-10/graphql.json"
        query = """
        mutation cartCreate($input: CartInput!) {
          cartCreate(input: $input) {
            cart {
              id
              deliveryGroups(first: 5) {
                edges {
                  node {
                    deliveryOptions {
                      title
                      estimatedCost { amount currencyCode }
                    }
                  }
                }
              }
            }
            userErrors { message }
          }
        }
        """
        variables = {
            "input": {
                "lines": [{"merchandiseId": variant_gid, "quantity": 1}],
                "buyerIdentity": {
                    "countryCode": Config.SHIP_TO_COUNTRY_CODE,
                    "deliveryAddressPreferences": [
                        {
                            "deliveryAddress": {
                                "country": "BR",
                                "province": Config.SHIP_TO_PROVINCE,
                                "zip": Config.SHIP_TO_ZIP,
                            }
                        }
                    ],
                },
            }
        }
        try:
            r = requests.post(
                endpoint,
                json={"query": query, "variables": variables},
                headers={**HEADERS, "Content-Type": "application/json"},
                timeout=Config.HTTP_TIMEOUT,
            )
            if r.status_code != 200:
                return None, None, f"frete: HTTP {r.status_code} (provavelmente Storefront API exige token nesta loja)"
            payload = r.json()
            cart = (payload.get("data") or {}).get("cartCreate", {}).get("cart")
            if not cart:
                errors = (payload.get("data") or {}).get("cartCreate", {}).get("userErrors", [])
                msg = "; ".join(e.get("message", "") for e in errors) or "sem detalhes"
                return None, None, f"frete indisponível: {msg}"

            groups = cart.get("deliveryGroups", {}).get("edges", [])
            cheapest = None
            for g in groups:
                for opt in g["node"].get("deliveryOptions", []):
                    cost = opt.get("estimatedCost", {})
                    amount = cost.get("amount")
                    if amount is None:
                        continue
                    amount = float(amount)
                    if cheapest is None or amount < cheapest[0]:
                        cheapest = (amount, cost.get("currencyCode"), opt.get("title"))

            if cheapest is None:
                return None, None, "sem opções de entrega para o Brasil (provavelmente não envia para o BR)"

            amount, currency, method = cheapest
            # Conversão simples: se já vier em BRL, ótimo; senão deixamos o valor
            # na moeda original e marcamos no shipping_note — conversão de câmbio
            # ao vivo fica fora do escopo p/ evitar mostrar número impreciso.
            if currency == "BRL":
                return amount, method, None
            return None, method, f"frete estimado: {amount} {currency} (cotação não convertida — confira no site)"

        except requests.RequestException as e:
            return None, None, f"frete: erro de rede ({e})"

    # ---------- entrada principal ----------

    def check(self, book) -> CheckResult:
        result = CheckResult()
        product, err = self.find_product(book)
        if err:
            result.error = err
        if not product:
            result.matched = False
            return result

        result.matched = True
        handle = product.get("handle")
        result.product_url = f"{self.base}/products/{handle}" if handle else self.base

        variant = self._pick_variant(product, book)
        if variant:
            result.available = bool(variant.get("available"))
            try:
                result.price_amount = float(variant.get("price"))
            except (TypeError, ValueError):
                result.price_amount = None
            result.price_currency = product.get("currency") or "USD"

            shipping_brl, method, note = self._estimate_shipping_to_br(product, variant)
            result.shipping_cost_brl = shipping_brl
            result.shipping_method = method
            result.shipping_note = note
            result.ships_to_br = (
                True if shipping_brl is not None or (note and "frete estimado" in note)
                else (False if note and "não envia" in note else None)
            )

        return result
