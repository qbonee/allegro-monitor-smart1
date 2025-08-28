# get_price.py
from __future__ import annotations
import json
import re
import time
from typing import Dict, List, Tuple, Any

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


ALLEGRO_BASE = "https://allegro.pl/oferta/"
NAV_TIMEOUT_MS = 30000
SEL_TIMEOUT_MS = 8000

# Teksty/oznaki zakończonych/usuniętych ofert
ENDED_HINTS = [
    "oferta zakończona",
    "oferta została zakończona",
    "ogłoszenie zakończone",
    "oferta nie istnieje",
    "strona nie została znaleziona",
    "404",
    "410",
]


class EndedOfferError(RuntimeError):
    """Rzucane gdy oferta wygląda na zakończoną/usuniętą."""


def _to_float_price(s: str | None) -> float | None:
    if not s:
        return None
    t = s.lower()
    # usuń zł, spacje, twarde spacje, separatory tys., zamień przecinek na kropkę
    t = t.replace("zł", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    # wyciągnij pierwszą liczbę
    m = re.search(r"(\d+(?:\.\d+)?)", t)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _click_cookies(page) -> None:
    # Allegro ma różne warianty CMP; próbujemy kilka popularnych przycisków
    candidates = [
        r"text=/.*(Zgadzam się|Akceptuj|Przejdź do serwisu|Akceptuję).*/i",
        r'button:has-text("Zgadzam się")',
        r'button:has-text("Akceptuj")',
        r'button:has-text("Akceptuję")',
        r'button:has-text("Przejdź do serwisu")',
        r'[data-role="accept-consent"]',
    ]
    for sel in candidates:
        try:
            el = page.locator(sel)
            if el.count() > 0:
                el.first.click(timeout=2000)
                # mała pauza, by DOM się zaktualizował
                page.wait_for_timeout(200)
                return
        except Exception:
            pass


def _detect_ended(page) -> bool:
    txt = (page.content() or "").lower()
    return any(h in txt for h in ENDED_HINTS)


def _extract_price(page) -> float | None:
    # 1) Meta tag opengraph/product
    try:
        m = page.locator('meta[property="product:price:amount"]')
        if m.count():
            val = m.first.get_attribute("content")
            p = _to_float_price(val)
            if p is not None:
                return p
    except Exception:
        pass

    # 2) JSON-LD (offers.price)
    try:
        scripts = page.locator('script[type="application/ld+json"]')
        for i in range(min(scripts.count(), 10)):
            raw = scripts.nth(i).text_content() or ""
            # Na stronach bywa kilka JSON-ów, czasem połączonych -> parsuj łagodnie
            for chunk in _json_chunks(raw):
                try:
                    data = json.loads(chunk)
                except Exception:
                    continue
                # czasem to lista
                nodes = data if isinstance(data, list) else [data]
                for node in nodes:
                    price = _find_price_in_ldjson(node)
                    if price is not None:
                        return price
    except Exception:
        pass

        # 3) Znane atrybuty w DOM (rozszerzona lista)
    candidates = [
        '[itemprop="price"]',
        '[data-testid="price"]',
        '[data-testid="price-value"]',
        '[data-testid="price-primary"]',
        '[data-testid="uc-price"]',
        '[data-test="price"]',
        '[data-box-name="price"]',
        '[data-role="price"]',
        'div[data-testid="price-section"]',
        'div[data-testid="price-wrapper"]',
        'span[class*="price"]',
        'div:has-text("Cena") >> ..',
    ]

    ]
    for sel in candidates:
        try:
            el = page.locator(sel)
            if el.count():
                txt = el.first.text_content() or el.first.get_attribute("content") or ""
                p = _to_float_price(txt)
                if p is not None:
                    return p
        except Exception:
            pass

    # 4) Awaryjnie – poszukaj „zł” w widocznym tekście strony
    try:
        txt = page.inner_text("body")
        # znajdź pierwszą liczbę zakończoną „zł”
        m = re.search(r"(\d+[.,]?\d*)\s*zł", txt.lower())
        if m:
            return _to_float_price(m.group(1))
    except Exception:
        pass

    return None


def _json_chunks(raw: str) -> List[str]:
    """
    Niektóre strony mają kilka bloków JSON sklejonych; ta funkcja stara się
    wydzielić „sensowne” fragmenty do json.loads.
    """
    chunks: List[str] = []
    buf = []
    depth = 0
    in_str = False
    esc = False
    for ch in raw:
        buf.append(ch)
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    chunks.append("".join(buf).strip())
                    buf = []
    if chunks:
        return chunks
    # jeśli nie udało się, zwróć cały tekst — może i tak parsowalny
    return [raw]


def _find_price_in_ldjson(node: Any) -> float | None:
    # Szukaj pól offers -> price / priceSpecification -> price
    try:
        offers = node.get("offers")
        if isinstance(offers, list):
            for o in offers:
                p = _pull_price_from_offer(o)
                if p is not None:
                    return p
        elif isinstance(offers, dict):
            p = _pull_price_from_offer(offers)
            if p is not None:
                return p
    except Exception:
        pass
    # Czasem cena siedzi bezpośrednio w „price”
    try:
        if "price" in node:
            return _to_float_price(str(node["price"]))
    except Exception:
        pass
    return None


def _pull_price_from_offer(o: Dict[str, Any]) -> float | None:
    if not isinstance(o, dict):
        return None
    # price
    if "price" in o:
        p = _to_float_price(str(o["price"]))
        if p is not None:
            return p
    # priceSpecification.price
    ps = o.get("priceSpecification")
    if isinstance(ps, dict) and "price" in ps:
        p = _to_float_price(str(ps["price"]))
        if p is not None:
            return p
    return None


def _nav_and_prepare(page, url: str) -> None:
    page.set_default_navigation_timeout(NAV_TIMEOUT_MS)
    page.set_default_timeout(SEL_TIMEOUT_MS)
    page.goto(url, wait_until="domcontentloaded")
    # akceptuj cookies (jeśli są)
    _click_cookies(page)
    # szybkie sprawdzenie, czy oferta nie jest zakończona
    if _detect_ended(page):
        raise EndedOfferError(f"ENDED: {url}")


def _build_url(auction_id: str) -> str:
    # pozwala przekazać pełny URL albo samo ID
    if auction_id.startswith("http://") or auction_id.startswith("https://"):
        return auction_id
    return f"{ALLEGRO_BASE}{auction_id}"


def get_price_single(page, auction: Dict[str, Any]) -> Dict[str, Any]:
    """
    Zwraca {"id": "...", "price": float} albo rzuca EndedOfferError / RuntimeError.
    """
    aid = str(auction["id"])
    url = _build_url(aid)

    try:
        _nav_and_prepare(page, url)

        # czasem Allegro dosyła cenę po chwili — dajmy mu odrobinę czasu
        price = None
        for _ in range(3):
            price = _extract_price(page)
            if price is not None:
                break
            page.wait_for_timeout(500)

        if price is None:
            # ostatnia próba po małym scrollu
            try:
                page.mouse.wheel(0, 600)
                page.wait_for_timeout(300)
                price = _extract_price(page)
            except Exception:
                pass

        if price is None:
            raise RuntimeError(f"Playwright: brak ceny dla {url}")

        return {"id": aid, "price": float(price)}

    except PlaywrightTimeoutError:
        raise RuntimeError(f"Page.goto: Timeout {NAV_TIMEOUT_MS}ms exceeded.\nCall log:\n  - navigating to \"{url}\", waiting until \"domcontentloaded\"")
    except EndedOfferError:
        # propaguj, żeby main mógł miękko oznaczyć w cache
        raise
    except Exception as e:
        raise RuntimeError(str(e))


def get_price_batch(auctions: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Wejście: lista dictów co najmniej z kluczami: id, min_price, product
    Wyjście: (results, errors)
      - results: [{"id": "...", "price": float}, ...]
      - errors:  [str, str, ...]  (czytelne komunikaty do logów)
    """
    results: List[Dict[str, Any]] = []
    errors: List[str] = []

    if not auctions:
        return results, errors

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            locale="pl-PL",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            for a in auctions:
                try:
                    res = get_price_single(page, a)
                    results.append(res)
                except EndedOfferError as e:
                    # oddajemy w errors — main i tak oznaczy ENDED miękko w cache
                    errors.append(f"{a.get('product', '?')}: {str(e)}")
                except Exception as e:
                    errors.append(f"{a.get('product', '?')}: {str(e)}")
                # drobna pauza, by nie walić w serwis zbyt szybko
                page.wait_for_timeout(150)
        finally:
            context.close()
            browser.close()

    return results, errors

