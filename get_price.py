# get_price.py
# Hybryda: 1) szybki HTTP + regex (większość przypadków), 2) fallback Playwright (z retry i cookies).
# Eksport:
#   - EndedOfferError
#   - get_price(auction_id) -> float
#   - get_price_batch(auctions) -> (results:[{id,price,product}], errors:[str])

from typing import List, Tuple, Dict, Optional
import re, os, html
import requests
from contextlib import suppress
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Page

# ===== Konfiguracja (możesz nadpisać ENV-ami) =================================

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/123.0.0.0 Safari/537.36")

ALLEGRO_URL_TMPL = "https://allegro.pl/oferta/{id}"

FAST_HTTP_ENABLED     = os.getenv("FAST_HTTP_ENABLED", "1") == "1"
HTTP_TIMEOUT          = float(os.getenv("HTTP_TIMEOUT", "8"))        # s

PLAY_NAV_TIMEOUT_MS   = int(os.getenv("PLAY_NAV_TIMEOUT_MS", "30000"))
PLAY_DEF_TIMEOUT_MS   = int(os.getenv("PLAY_DEF_TIMEOUT_MS", "8000"))
PLAY_RETRIES          = int(os.getenv("PLAY_RETRIES", "2"))
PLAY_AFTER_GOTO_WAIT  = int(os.getenv("PLAY_AFTER_GOTO_WAIT_MS", "350"))  # krótkie odsapnięcie po goto

# ===== Specjalny wyjątek ======================================================

class EndedOfferError(Exception):
    """Aukcja zakończona/usunięta (stan miękki; sprawdź ponownie później)."""
    pass

# ===== Wzorce wykrywania ceny i zakończenia ==================================

PRICE_PATTERNS = [
    # JSON-y ze stanu strony
    re.compile(r'"currentPrice"\s*:\s*\{\s*"amount"\s*:\s*"(?P<val>\d+(?:[.,]\d+)?)"', re.I),
    re.compile(r'"lowestPrice"\s*:\s*\{\s*"amount"\s*:\s*"(?P<val>\d+(?:[.,]\d+)?)"', re.I),
    re.compile(r'"price"\s*:\s*\{\s*"amount"\s*:\s*"(?P<val>\d+(?:[.,]\d+)?)"', re.I),
    re.compile(r'"amount"\s*:\s*"(?P<val>\d+(?:[.,]\d+)?)"\s*,\s*"currency"', re.I),
    # meta OG
    re.compile(r'property=["\']og:price:amount["\']\s+content=["\'](?P<val>[^"\']+)["\']', re.I),
    # fallback z tekstu: „od 39,99 zł”, „39,99–49,99 zł”
    re.compile(r'(?P<val>\d{1,6}(?:[.,]\d{1,2})?)\s*(?:–|-|do)?\s*\d{0,6}(?:[.,]\d{1,2})?\s*zł', re.I),
]

ENDED_PATTERNS = [
    re.compile(r'oferta (?:zosta[ła|l]a )?zakończona', re.I),
    re.compile(r'nie znaleziono oferty', re.I),
    re.compile(r'oferta została usunięta', re.I),
    re.compile(r'\b404\b', re.I),
    re.compile(r'\b410\b', re.I),
]

# ===== Utils =================================================================

def _to_float(s: str) -> float:
    return float((s or "").replace("\xa0", "").replace(" ", "").replace(",", "."))

def _extract_price_from_html(html_text: str) -> Optional[float]:
    txt = html.unescape(html_text or "")
    for rx in PRICE_PATTERNS:
        m = rx.search(txt)
        if m:
            g = m.groupdict().get("val") or m.group(1)
            return _to_float(g)
    return None

def _is_ended(html_text: str) -> bool:
    txt = html.unescape(html_text or "")
    return any(rx.search(txt) for rx in ENDED_PATTERNS)

# ===== Szybka ścieżka HTTP ===================================================

_HTTP = requests.Session()
_HTTP.headers.update({
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
})

def _http_price(auction_id: str) -> float:
    url = ALLEGRO_URL_TMPL.format(id=auction_id)
    r = _HTTP.get(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
    if r.status_code in (404, 410):
        raise EndedOfferError(f"HTTP {r.status_code}")
    r.raise_for_status()
    if _is_ended(r.text):
        raise EndedOfferError("oferta zakończona/usunięta")
    price = _extract_price_from_html(r.text)
    if price is None:
        raise ValueError("HTTP: nie znaleziono ceny")
    return price

# ===== Playwright =============================================================

def _new_context(p):
    browser = p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
        ],
    )
    ctx = browser.new_context(
        locale="pl-PL",
        user_agent=UA,
        viewport={"width": 1366, "height": 900},
    )
    page = ctx.new_page()

    # przyspieszenie: blokuj ciężkie zasoby
    def _route_handler(route):
        t = (route.request.resource_type or "").lower()
        if t in ("image", "media", "font", "stylesheet"):
            return route.abort()
        return route.continue_()
    page.route("**/*", _route_handler)

    page.set_default_navigation_timeout(PLAY_NAV_TIMEOUT_MS)
    page.set_default_timeout(PLAY_DEF_TIMEOUT_MS)
    return browser, ctx, page

def _accept_cookies_if_present(page: Page):
    # próbujemy kilka wariantów — bez błędów jeśli brak
    selectors = [
        "button[data-role='accept-consent']",
        "button:has-text('Przejdź do serwisu')",
        "button:has-text('Akceptuj')",
        "[data-testid='consent-modal'] button:has-text('Akcept')",
    ]
    for sel in selectors:
        with suppress(Exception):
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click(timeout=1500)
                page.wait_for_timeout(150)  # krótko, żeby UI się domknął
                break

def _try_get_price_ui(page: Page) -> Optional[float]:
    # zestaw szeroki — Allegro często zmienia testID-y
    ui_selectors = [
        "meta[itemprop='price']@content",  # notacja specjalna -> atrybut
        "[data-testid='price-value']",
        "[data-testid='price-primary']",
        "span[data-testid*='price']",
        "[itemprop='price']",
        "[data-box-name='BuyNow'] [data-testid='price-value']",
        "[data-box-name='Summary'] [data-testid*='price']",
        "div[aria-label*='Cena']",
    ]

    # a) meta content
    if "@content" in ui_selectors[0]:
        with suppress(Exception):
            meta = page.locator("meta[itemprop='price']")
            if meta.count() > 0:
                val = meta.first.get_attribute("content")
                if val:
                    return _to_float(val)

    # b) widoczne elementy
    for sel in ui_selectors[1:]:
        with suppress(Exception):
            loc = page.locator(sel)
            if loc.count() == 0:
                continue
            txt = loc.first.inner_text(timeout=2500)
            if txt and re.search(r"\d", txt):
                return _to_float(txt)

    return None

def _play_price_once(page: Page, auction_id: str) -> float:
    url = ALLEGRO_URL_TMPL.format(id=auction_id)
    page.goto(url, wait_until="domcontentloaded", timeout=PLAY_NAV_TIMEOUT_MS)
    page.wait_for_timeout(PLAY_AFTER_GOTO_WAIT)
    _accept_cookies_if_present(page)

    html_text = page.content()
    if _is_ended(html_text):
        raise EndedOfferError("oferta zakończona/usunięta")

    # 1) UI
    p = _try_get_price_ui(page)
    if p is not None:
        return p

    # 2) fallback: parsuj HTML (JSON-y osadzone)
    p = _extract_price_from_html(html_text)
    if p is not None:
        return p

    # 3) ostania próba — dociągnij jeszcze trochę sieci
    with suppress(Exception):
        page.wait_for_load_state("networkidle", timeout=3500)
        page.wait_for_timeout(200)
        html_text = page.content()
        p = _extract_price_from_html(html_text)
        if p is not None:
            return p

    raise RuntimeError(f"Playwright: brak ceny dla {url}")

def _play_price(page: Page, auction_id: str) -> float:
    last_exc = None
    for attempt in range(1, PLAY_RETRIES + 1):
        try:
            return _play_price_once(page, auction_id)
        except EndedOfferError:
            raise
        except PWTimeout as e:
            last_exc = e
            continue
        except Exception as e:
            last_exc = e
            # szybka re-proba — Allegro bywa kapryśne
            continue
    raise RuntimeError(str(last_exc) if last_exc else "Playwright: nieznany błąd")

# ===== API: single ============================================================

def get_price(auction_id: str) -> float:
    auction_id = str(auction_id).strip()
    if not auction_id.isdigit():
        raise ValueError(f"Niepoprawne ID: {auction_id}")

    if FAST_HTTP_ENABLED:
        try:
            return _http_price(auction_id)
        except EndedOfferError:
            raise
        except Exception:
            pass  # cichy fallback

    with sync_playwright() as p:
        browser, ctx, page = _new_context(p)
        try:
            return _play_price(page, auction_id)
        finally:
            with suppress(Exception):
                ctx.close()
                browser.close()

# ===== API: batch =============================================================

def get_price_batch(auctions: List[Dict]) -> Tuple[List[Dict], List[str]]:
    """
    Zwraca:
      results: [{"id":"...", "price": 123.45, "product":"..."}]
      errors:  ["opis błędu", ...]  # także ENDED
    """
    results: List[Dict] = []
    errors:  List[str] = []

    # 1) HTTP najpierw (sekwencyjnie — stabilnie na hostingu)
    pending: List[Dict] = []
    if FAST_HTTP_ENABLED:
        for a in auctions:
            aid = str(a.get("id","")).strip()
            try:
                p = _http_price(aid)
                results.append({"id": aid, "price": float(p), "product": a.get("product","")})
            except EndedOfferError as e:
                errors.append(f"{a.get('product','')}: Błąd sprawdzania aukcji {aid}: ENDED: {e}")
            except Exception:
                pending.append(a)
    else:
        pending = list(auctions)

    # 2) Fallback: Playwright tylko dla trudnych przypadków
    if pending:
        with sync_playwright() as p:
            browser, ctx, page = _new_context(p)
            try:
                for a in pending:
                    aid = str(a.get("id","")).strip()
                    try:
                        pr = _play_price(page, aid)
                        results.append({"id": aid, "price": float(pr), "product": a.get("product","")})
                    except EndedOfferError as e:
                        errors.append(f"{a.get('product','')}: Błąd sprawdzania aukcji {aid}: ENDED: {e}")
                    except Exception as e:
                        errors.append(f"{a.get('product','')}: Błąd sprawdzania aukcji {aid}: {e}")
            finally:
                with suppress(Exception):
                    ctx.close()
                    browser.close()

    return results, errors
