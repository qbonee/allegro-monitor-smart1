# get_price.py
# Kompatybilne z Playwright 1.54.0 (python)
# Zwraca: (results, errors) dla get_price_batch oraz float dla get_price

from typing import List, Tuple, Any
import re

from playwright.sync_api import sync_playwright, Page


def _parse_price_str(s: str) -> float:
    """
    '1 234,56' -> 1234.56
    '1,234.56' -> 1234.56
    '1234,56'  -> 1234.56
    """
    s = (s or "").strip()
    # usuń spacje tysięcy
    s = s.replace("\xa0", " ").replace(" ", "")
    # zamień przecinek na kropkę
    s = s.replace(",", ".")
    # wyciągnij pierwszą liczbę
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        raise ValueError(f"Nie znaleziono liczby w '{s}'")
    return float(m.group(1))


def get_price_single_with_page(page: Page, auction_id: str) -> float:
    """
    Pobiera cenę dla pojedynczej aukcji używając już otwartej strony.
    Zwraca float (cena) lub rzuca wyjątek z opisem problemu.
    """
    # Najczęstszy format URL na Allegro:
    # - https://allegro.pl/oferta/<AUCTION_ID>
    # Jeśli masz inny format w swoich danych – zmień poniższą linię.
    url = f"https://allegro.pl/oferta/{auction_id}"

    # przejście na stronę
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)

    # 1) meta[itemprop="price"] – często obecne
    try:
        meta = page.locator("meta[itemprop='price']")
        if meta.count() > 0:
            val = meta.first.get_attribute("content")
            if val:
                return _parse_price_str(val)
    except Exception:
        pass

    # 2) Popularne testID-y Allegro (różnie bywa)
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
            # próbujemy kolejne selektory
            pass

    # 3) Ostateczny fallback: parsuj HTML (czasem w JSON-ie)
    try:
        html = page.content()
        # przykładowe wzorce; możesz dodać kolejne, jeśli zauważysz inne struktury
        patterns = [
            r'"price"\s*:\s*{"amount"\s*:\s*"([\d.,\s]+)"',
            r'"amount"\s*:\s*"([\d.,\s]+)"\s*,\s*"currency"',  # inny JSON
            r'content="([\d.,\s]+)"\s+itemprop="price"',        # meta
        ]
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                return _parse_price_str(m.group(1))
    except Exception:
        pass

    raise RuntimeError(f"Nie udało się znaleźć ceny na stronie {url}")


def get_price(auction_id: str) -> float:
    """
    Wariant jednorazowy – otwiera przeglądarkę, pobiera cenę i zamyka.
    Używany sporadycznie; produkcyjnie lepszy jest get_price_batch.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            price = get_price_single_with_page(page, auction_id)
            return price
        finally:
            ctx.close()
            browser.close()


def get_price_batch(auctions: List[dict]) -> Tuple[List[Tuple[Any, float, bool]], List[str]]:
    """
    Batchowy pobór cen.
    Parametr `auctions` – lista słowników w formacie:
        {"id": "<AUCTION_ID>", "min_price": <float>, "product": "<nazwa>"}

    Zwraca:
        results: lista tupli (auction_dict, price_float, ok_bool)
        errors:  lista napisów z opisem błędu
    """
    results: List[Tuple[Any, float, bool]] = []
    errors: List[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            for a in auctions:
                aid = str(a.get("id", "")).strip()
                product = a.get("product", "")
                try:
                    price = get_price_single_with_page(page, aid)
                    results.append((a, price, True))
                except Exception as e:
                    msg = f"{product}: Błąd sprawdzania aukcji {aid}: {e}"
                    errors.append(msg)
                    results.append((a, 0.0, False))
        finally:
            ctx.close()
            browser.close()

    return results, errors
