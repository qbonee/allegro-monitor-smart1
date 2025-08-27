# get_price.py
# Playwright 1.54.x — pobieranie ceny pojedynczej oferty Allegro po ID.
# Eksportuje:
#   - get_price(auction_id) -> float
#   - get_price_batch(auctions: List[dict]) -> (results: List[dict], errors: List[str])
#
# Wynik batcha: results = [{"id": "...", "price": 123.45, "product": "..."}]

from typing import List, Tuple
import re
from playwright.sync_api import sync_playwright, Page

# ------------------ utils ------------------

def _parse_price_str(s: str) -> float:
    """
    '1 234,56' -> 1234.56
    '1,234.56' -> 1234.56
    '1234,56'  -> 1234.56
    """
    s = (s or "").strip()
    s = s.replace("\xa0", " ").replace(" ", "")
    s = s.replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        raise ValueError(f"Nie znaleziono liczby w '{s}'")
    return float(m.group(1))

def _extract_price_from_page(page: Page, auction_id: str) -> float:
    url = f"https://allegro.pl/oferta/{auction_id}"
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)

    # 1) meta[itemprop=price]
    try:
        meta = page.locator("meta[itemprop='price']")
        if meta.count() > 0:
            val = meta.first.get_attribute("content")
            if val:
                return _parse_price_str(val)
    except Exception:
        pass

    # 2) popularne selektory "price"
    candidates = [
        "[data-testid='price-value']",
        "[data-testid='price-primary']",
        "span[data-testid*='price']",
        "[itemprop='price']",
        "[data-box-name='BuyNow'] [data-testid='price-value']",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                txt = loc.first.inner_text(timeout=2_000)
                if txt and re.search(r"\d", txt):
                    return _parse_price_str(txt)
        except Exception:
            pass

    # 3) fallback: HTML/JSON
    try:
        html = page.content()
        patterns = [
            r'"price"\s*:\s*{"amount"\s*:\s*"([\d.,\s]+)"',
            r'"amount"\s*:\s*"([\d.,\s]+)"\s*,\s*"currency"',
            r'content="([\d.,\s]+)"\s+itemprop="price"',
        ]
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                return _parse_price_str(m.group(1))
    except Exception:
        pass

    raise RuntimeError(f"Nie udało się znaleźć ceny na stronie {url}")

# ------------------ API: single ------------------

def get_price(auction_id: str) -> float:
    if not auction_id or not str(auction_id).strip().isdigit():
        raise ValueError(f"Niepoprawne ID aukcji: {auction_id!r}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            return _extract_price_from_page(page, str(auction_id).strip())
        finally:
            ctx.close()
            browser.close()

# ------------------ API: batch ------------------

def get_price_batch(auctions: List[dict]) -> Tuple[List[dict], List[str]]:
    """
    auctions: [{"id": "<ID>", "product": "<nazwa>", "min_price": <float>}, ...]
    Zwraca:
      results: [{"id":"...", "price": 123.45, "product":"..."}]
      errors:  ["opis błędu", ...]
    """
    results: List[dict] = []
    errors: List[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            for a in auctions:
                aid = str(a.get("id", "")).strip()
                product = a.get("product", "")
                try:
                    price = _extract_price_from_page(page, aid)
                    results.append({"id": aid, "price": float(price), "product": product})
                except Exception as e:
                    errors.append(f"{product}: Błąd sprawdzania aukcji {aid}: {e}")
        finally:
            ctx.close()
            browser.close()

    return results, errors
