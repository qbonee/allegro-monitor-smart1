# get_price.py
# HYBRYDA: 1) szybki HTTP (requests) + regex  2) fallback Playwright.
# Eksport:
#   get_price(auction_id) -> float
#   get_price_batch(auctions) -> (results:[{id,price,product}], errors:[str])

from typing import List, Tuple, Dict, Optional
import re, time, random, os
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- USTAWIENIA (możesz nadpisać ENV-ami) ---
FAST_HTTP_ENABLED   = os.getenv("FAST_HTTP_ENABLED", "1") == "1"
HTTP_TIMEOUT        = float(os.getenv("HTTP_TIMEOUT", "6"))       # s
MAX_HTTP_WORKERS    = int(os.getenv("MAX_HTTP_WORKERS", "8"))     # równoległe HTTP GET
PLAY_NAV_TIMEOUT    = int(os.getenv("PLAY_NAV_TIMEOUT_MS", "15000"))
PLAY_DEF_TIMEOUT    = int(os.getenv("PLAY_DEF_TIMEOUT_MS", "8000"))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/122.0.0.0 Safari/537.36")

ALLEGRO_URL_TMPL = "https://allegro.pl/oferta/{id}"

# ---------- WZORCE CENY ----------
PRICE_PATTERNS = [
    re.compile(r'"price"\s*:\s*\{\s*"amount"\s*:\s*"(?P<val>\d+(?:[.,]\d+)?)"', re.I),
    re.compile(r'property=["\']og:price:amount["\']\s+content=["\'](?P<val>[^"\']+)["\']', re.I),
    re.compile(r'"amount"\s*:\s*"(?P<val>\d+(?:[.,]\d+)?)"', re.I),
    re.compile(r'(?P<val>\d{1,6}(?:[.,]\d{1,2})?)\s*zł', re.I),
]

def _to_float(s: str) -> float:
    return float(s.replace("\xa0", "").replace(" ", "").replace(",", "."))

# ---------- SZYBKI HTTP ----------
_HTTP = requests.Session()
_HTTP.headers.update({
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
})

def _extract_price_from_html(html: str) -> Optional[float]:
    for rx in PRICE_PATTERNS:
        m = rx.search(html)
        if m:
            val = m.groupdict().get("val") or m.group(1)
            return _to_float(val)
    return None

def _http_price(auction_id: str) -> float:
    url = ALLEGRO_URL_TMPL.format(id=auction_id)
    r = _HTTP.get(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    p = _extract_price_from_html(r.text)
    if p is None:
        raise ValueError("HTTP: nie znaleziono ceny")
    return p

# ---------- PLAYWRIGHT (fallback) ----------
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

def _new_context(p):
    browser = p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"]
    )
    ctx = browser.new_context(
        locale="pl-PL",
        user_agent=UA,
    )
    page = ctx.new_page()

    def _route_handler(route):
        t = (route.request.resource_type or "").lower()
        if t in ("image", "media", "font", "stylesheet"):
            return route.abort()
        return route.continue_()
    page.route("**/*", _route_handler)

    page.set_default_navigation_timeout(PLAY_NAV_TIMEOUT)
    page.set_default_timeout(PLAY_DEF_TIMEOUT)
    return browser, ctx, page

def _play_price(page, auction_id: str) -> float:
    url = ALLEGRO_URL_TMPL.format(id=auction_id)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=PLAY_NAV_TIMEOUT)
    except PWTimeout:
        page.goto(url, wait_until="domcontentloaded", timeout=PLAY_NAV_TIMEOUT)

    # meta[itemprop=price]
    try:
        meta = page.locator("meta[itemprop='price']")
        if meta.count() > 0:
            val = meta.first.get_attribute("content")
            if val:
                return _to_float(val)
    except Exception:
        pass

    # selektory
    for sel in [
        "[data-testid='price-value']",
        "[data-testid='price-primary']",
        "span[data-testid*='price']",
        "[itemprop='price']",
        "[data-box-name='BuyNow'] [data-testid='price-value']",
    ]:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                txt = loc.first.inner_text(timeout=2000)
                if txt and re.search(r"\d", txt):
                    return _to_float(txt)
        except Exception:
            pass

    # fallback: HTML
    html = page.content()
    p = _extract_price_from_html(html)
    if p is not None:
        return p
    raise RuntimeError(f"Playwright: brak ceny dla {url}")

# ---------- API: single ----------
def get_price(auction_id: str) -> float:
    auction_id = str(auction_id).strip()
    if not auction_id.isdigit():
        raise ValueError(f"Niepoprawne ID: {auction_id}")

    # szybka ścieżka
    if FAST_HTTP_ENABLED:
        try:
            return _http_price(auction_id)
        except Exception:
            pass  # fallback

    # fallback przeglądarka
    with sync_playwright() as p:
        browser, ctx, page = _new_context(p)
        try:
            return _play_price(page, auction_id)
        finally:
            ctx.close(); browser.close()

# ---------- API: batch ----------
def get_price_batch(auctions: List[Dict]) -> Tuple[List[Dict], List[str]]:
    results: List[Dict] = []
    errors: List[str]  = []

    # 1) HTTP wątkowo
    pending_for_play: List[Dict] = []
    if FAST_HTTP_ENABLED:
        with ThreadPoolExecutor(max_workers=MAX_HTTP_WORKERS) as pool:
            fut2item = {}
            for a in auctions:
                aid = str(a.get("id","")).strip()
                fut = pool.submit(_http_price, aid)
                fut2item[fut] = a
            for fut in as_completed(fut2item):
                a = fut2item[fut]
                aid = str(a.get("id","")).strip()
                try:
                    price = fut.result()
                    results.append({"id": aid, "price": float(price), "product": a.get("product","")})
                except Exception as e:
                    # do Playwrighta
                    pending_for_play.append(a)

    else:
        pending_for_play = list(auctions)

    # 2) Fallback: Playwright dla braków
    if pending_for_play:
        with sync_playwright() as p:
            browser, ctx, page = _new_context(p)
            try:
                for a in pending_for_play:
                    aid = str(a.get("id","")).strip()
                    try:
                        price = _play_price(page, aid)
                        results.append({"id": aid, "price": float(price), "product": a.get("product","")})
                    except Exception as e:
                        errors.append(f"{a.get('product','')}: Błąd sprawdzania aukcji {aid}: {e}")
            finally:
                ctx.close(); browser.close()

    return results, errors
