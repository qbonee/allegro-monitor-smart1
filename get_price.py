# get_price.py
from __future__ import annotations

import re
from typing import Dict, List, Tuple, Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError


ALLEGRO_URL = "https://allegro.pl/oferta/{aid}"

# ------------------------------- utils ------------------------------------- #

class EndedOfferError(RuntimeError):
    """Aukcja zakończona/usunięta (HTTP 404/410 lub podobny sygnał)."""


def _parse_price_text(txt: str) -> Optional[float]:
    """
    Przyjmuje tekst typu '123,45 zł' / '1 234,56' i zwraca float.
    Zwraca None, jeśli nie da się sparsować.
    """
    if not txt:
        return None
    t = txt.lower()
    t = t.replace("zł", "").replace("pln", "")
    t = t.replace("\u00a0", " ")  # nbsp
    t = t.strip()
    # wyciągnij pierwszą grupę cyfr z separatorem
    m = re.search(r"(\d[\d\s]*[.,]\d{1,2}|\d[\d\s]*)", t)
    if not m:
        return None
    num = m.group(1).replace(" ", "").replace(",", ".")
    try:
        return float(num)
    except Exception:
        return None


def _extract_price_from_html(html: str) -> Optional[float]:
    """
    Fallback: spróbuj z ld+json / price w treści HTML.
    """
    # JSON-LD: "price":"123.45"
    m = re.search(r'"price"\s*:\s*"(?P<p>[\d.,\s]+)"', html)
    if m:
        val = _parse_price_text(m.group("p"))
        if val is not None:
            return val

    # JSON-LD: "price":123.45
    m = re.search(r'"price"\s*:\s*(?P<p>\d[\d.,\s]*)', html)
    if m:
        val = _parse_price_text(m.group("p"))
        if val is not None:
            return val

    return None


def _extract_price_dom(page) -> Optional[float]:
    """
    Spróbuj znaleźć cenę po popularnych selektorach Allegro.
    Zwraca float lub None.
    """
    candidates = [
        '[itemprop="price"]',
        '[data-testid="uc-price"]',
        '[data-testid="price"]',
        '[data-testid="price-value"]',
        '[data-testid="price-primary"]',
        'div[data-testid="price-section"]',
        'div[data-testid="price-wrapper"]',
        'span[class*="price"]',
        # czasem aria-label zawiera cenę
        '[aria-label*="zł"]',
    ]

    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if not loc or loc.count() == 0:
                continue

            # tekst
            txt = (loc.inner_text(timeout=500) or "").strip()
            val = _parse_price_text(txt)
            if val is not None:
                return val

            # atrybut content (np. meta/og:title)
            content = (loc.get_attribute("content") or "").strip()
            val = _parse_price_text(content)
            if val is not None:
                return val

            # aria-label
            aria = (loc.get_attribute("aria-label") or "").strip()
            val = _parse_price_text(aria)
            if val is not None:
                return val
        except PWTimeoutError:
            continue
        except Exception:
            continue

    # Fallback: z całego HTML (ld+json)
    try:
        html = page.content()
        return _extract_price_from_html(html)
    except Exception:
        return None


def _get_single(page, auction: Dict) -> Dict:
    """
    Pobierz cenę jednej aukcji używając już otwartej strony.
    Zwraca dict: {"id": "...", "price": 123.45}
    """
    aid = str(auction["id"]).strip()
    url = ALLEGRO_URL.format(aid=aid)

    # wejście na stronę
    resp = page.goto(url, timeout=30000, wait_until="domcontentloaded")
    status = None
    try:
        status = resp.status if resp else None
    except Exception:
        status = None

    if status in (404, 410):
        raise EndedOfferError(f"ENDED {aid} HTTP {status}")

    # Allegro bywa ciężkie – delikatny wait na fragment DOM
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except PWTimeoutError:
        pass

    price = _extract_price_dom(page)

    if price is None:
        raise RuntimeError(f"Playwright: brak ceny dla {url}")

    return {"id": aid, "price": float(price)}


# ----------------------------- public API ---------------------------------- #

def get_price_batch(auctions: List[Dict]) -> Tuple[List[Dict], List[str]]:
    """
    Główna funkcja wołana przez main.py.
    Wejście: lista słowników z polami: id, product, min_price
    Wyjście:
      - results: list[{"id": "...", "price": float}]
      - errors:  list[str] (czytelne błędy do logów)
    """
    results: List[Dict] = []
    errors: List[str] = []

    if not auctions:
        return results, errors

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                " AppleWebKit/537.36 (KHTML, like Gecko)"
                " Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        for a in auctions:
            aid = str(a.get("id", "?"))
            product = str(a.get("product", "")) or "?"
            try:
                r = _get_single(page, a)
                results.append(r)
            except EndedOfferError as e:
                # sygnal zakończonej aukcji – nie traktujemy jako "twardy" błąd
                errors.append(f"{product}: Aukcja zakończona {aid} ({e})")
            except PWTimeoutError:
                errors.append(f"{product}: Page.goto: Timeout 30000ms exceeded.\nCall log:\n  - navigating to \"{ALLEGRO_URL.format(aid=aid)}\", waiting until \"domcontentloaded\"")
            except Exception as e:
                errors.append(f"{product}: {e}")

        try:
            context.close()
        finally:
            browser.close()

    return results, errors
