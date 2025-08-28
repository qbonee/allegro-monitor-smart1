# get_price.py
from __future__ import annotations

import re
import time
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
    Fallback: spróbuj z ld+json / price w treści HTML lub strukturach stanowych.
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

    # Często w danych aplikacji:
    # ..."currentPrice":{"amount":"123.45"...}
    m = re.search(r'"currentPrice"\s*:\s*\{[^}]*"amount"\s*:\s*"(?P<p>[\d.,]+)"', html)
    if m:
        val = _parse_price_text(m.group("p"))
        if val is not None:
            return val

    return None


def _click_consent_if_present(page) -> None:
    """
    Kliknij baner zgód, jeśli jest. Obsługa kilku wariantów.
    Nie rzuca wyjątków.
    """
    try:
        # typowe teksty na Allegro/OneTrust itp.
        texts = [
            r"Zgadzam się", r"Akceptuj", r"Akceptuję", r"Przejdź dalej",
            r"OK", r"Rozumiem", r"Zaakceptuj wszystko", r"Przejdź do serwisu",
        ]
        for t in texts:
            btn = page.get_by_role("button", name=re.compile(t, re.I))
            if btn.count() > 0:
                btn.first.click(timeout=1500)
                # po kliknięciu daj chwilę na re-render
                time.sleep(0.3)
                break
    except Exception:
        pass

    # czasem to nie jest button:
    try:
        loc = page.locator("text=/Zgadzam|Akceptuj|Przejdź dalej|Rozumiem/i").first
        if loc.count() > 0:
            loc.click(timeout=1500)
            time.sleep(0.3)
    except Exception:
        pass


def _wait_price_visible(page, timeout_ms: int = 8000) -> None:
    """
    Spróbuj doczekać się pojawienia ceny w którymś z typowych selektorów.
    """
    sels = [
        '[data-testid="uc-price"]',
        '[data-testid="price"]',
        '[data-testid="price-value"]',
        '[data-testid="price-primary"]',
        '[itemprop="price"]',
        'meta[itemprop="price"]',
    ]
    t_end = time.time() + (timeout_ms / 1000.0)
    last_err = None
    while time.time() < t_end:
        for s in sels:
            try:
                loc = page.locator(s).first
                if loc.count() == 0:
                    continue
                # jeżeli meta – nie czekamy na visible
                if s.startswith("meta"):
                    content = (loc.get_attribute("content") or "").strip()
                    if _parse_price_text(content) is not None:
                        return
                else:
                    # czekaj aż pojawi się niepusty tekst
                    txt = (loc.inner_text(timeout=500) or "").strip()
                    if _parse_price_text(txt) is not None:
                        return
            except Exception as e:
                last_err = e
                continue
        time.sleep(0.15)
    if last_err:
        raise last_err


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
        'meta[itemprop="price"]',   # atrybut content
        'span[class*="price"]',
        '[aria-label*="zł"]',
    ]

    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if not loc or loc.count() == 0:
                continue

            # tekst
            try:
                txt = (loc.inner_text(timeout=600) or "").strip()
            except Exception:
                txt = ""
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
        val = _extract_price_from_html(html)
        if val is not None:
            return val
    except Exception:
        pass

    # Ostateczny ratunek: przeskanuj widoczny tekst strony
    try:
        body_txt = page.inner_text("body", timeout=800).lower()
        m = re.search(r"(\d[\d\s]*[.,]\d{1,2})\s*zł", body_txt)
        if m:
            val = _parse_price_text(m.group(1))
            if val is not None:
                return val
    except Exception:
        pass

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

    # kliknij zgody, jeśli są
    _click_consent_if_present(page)

    # Allegro bywa ciężkie – krótki oddech pomaga
    time.sleep(0.3)

    # spróbuj doczekać się sensownej ceny
    try:
        _wait_price_visible(page, timeout_ms=7000)
    except Exception:
        # pomiń – i tak spróbujemy zczytać fallbackami
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
                errors.append(f"{product}: Aukcja zakończona {aid} ({e})")
            except PWTimeoutError:
                errors.append(
                    f"{product}: Page.goto: Timeout 30000ms exceeded.\n"
                    f"Call log:\n  - navigating to \"{ALLEGRO_URL.format(aid=aid)}\", waiting until \"domcontentloaded\""
                )
            except Exception as e:
                errors.append(f"{product}: {e}")

        try:
            context.close()
        finally:
            browser.close()

    return results, errors
