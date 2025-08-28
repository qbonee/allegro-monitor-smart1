# get_price.py
from __future__ import annotations

import json
import re
import time
from typing import Dict, List, Tuple, Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError


ALLEGRO_URL = "https://allegro.pl/oferta/{aid}"

# ------------------------------- utils ------------------------------------- #

class EndedOfferError(RuntimeError):
    """Aukcja zakończona/usunięta (HTTP 404/410 lub podobny sygnał)."""


def _parse_price_text(txt: str) -> Optional[float]:
    if not txt:
        return None
    t = txt.lower().replace("zł", "").replace("pln", "").replace("\u00a0", " ")
    t = re.sub(r"[^\d,.\s]", "", t).strip()
    m = re.search(r"(\d[\d\s]*[.,]\d{1,2}|\d[\d\s]*)", t)
    if not m:
        return None
    num = m.group(1).replace(" ", "").replace(",", ".")
    try:
        return float(num)
    except Exception:
        return None


def _json_find_price(obj) -> Optional[float]:
    """Przejdź po dowolnym dict/list i wyciągnij pierwszą sensowną cenę."""
    try:
        if obj is None:
            return None
        if isinstance(obj, (int, float)):
            # odrzuć zbyt małe wartości (np. 0/1)
            return float(obj) if obj > 0.01 else None
        if isinstance(obj, str):
            return _parse_price_text(obj)
        if isinstance(obj, dict):
            # popularne klucze na Allegro
            for k in ("price", "amount", "currentPrice", "sellingMode", "buyNowPrice", "minPrice", "value"):
                if k in obj:
                    v = obj[k]
                    if isinstance(v, dict):
                        # np. {"amount":"123.45","currency":"PLN"}
                        for kk in ("amount", "price", "value"):
                            if kk in v:
                                pv = _json_find_price(v[kk])
                                if pv is not None:
                                    return pv
                    else:
                        pv = _json_find_price(v)
                        if pv is not None:
                            return pv
            # generalny przegląd
            for v in obj.values():
                pv = _json_find_price(v)
                if pv is not None:
                    return pv
        if isinstance(obj, list):
            for v in obj:
                pv = _json_find_price(v)
                if pv is not None:
                    return pv
    except Exception:
        return None
    return None


def _extract_price_from_html(html: str) -> Optional[float]:
    # JSON-LD: "price":"123.45"
    m = re.search(r'"price"\s*:\s*"(?P<p>[\d.,\s]+)"', html)
    if m:
        v = _parse_price_text(m.group("p"))
        if v is not None:
            return v
    # JSON-LD: "price":123.45
    m = re.search(r'"price"\s*:\s*(?P<p>\d[\d.,\s]*)', html)
    if m:
        v = _parse_price_text(m.group("p"))
        if v is not None:
            return v
    # ... "currentPrice":{"amount":"123.45"...}
    m = re.search(r'"currentPrice"\s*:\s*\{[^}]*"amount"\s*:\s*"(?P<p>[\d.,]+)"', html)
    if m:
        v = _parse_price_text(m.group("p"))
        if v is not None:
            return v
    return None


def _click_consent_everywhere(page) -> None:
    """Kliknij zgody zarówno w głównej stronie jak i w iframach."""
    def try_click(p):
        try:
            texts = [
                r"Zgadzam się", r"Akceptuj", r"Akceptuję", r"Przejdź dalej",
                r"OK", r"Rozumiem", r"Zaakceptuj wszystko", r"Przejdź do serwisu",
                r"Accept all", r"Agree", r"I accept",
            ]
            for t in texts:
                b = p.get_by_role("button", name=re.compile(t, re.I))
                if b.count() > 0:
                    b.first.click(timeout=1000)
                    return True
            # alternatywnie klik po tekście
            loc = p.locator("text=/Zgadzam|Akceptuj|Przejdź dalej|Rozumiem|Accept/i").first
            if loc.count() > 0:
                loc.click(timeout=1000)
                return True
        except Exception:
            return False
        return False

    clicked = try_click(page)
    if clicked:
        time.sleep(0.3)

    # czasem baner jest w iframie (np. consent manager)
    try:
        for fr in page.frames:
            if fr is page.main_frame:
                continue
            if try_click(fr):
                time.sleep(0.3)
                break
    except Exception:
        pass


def _wait_price_visible(page, timeout_ms: int = 9000) -> None:
    sels = [
        '[data-testid="uc-price"]',
        '[data-testid="price"]',
        '[data-testid="price-value"]',
        '[data-testid="price-primary"]',
        '[itemprop="price"]',
        'meta[itemprop="price"]',
        'span[class*="price"]',
    ]
    end = time.time() + timeout_ms / 1000.0
    while time.time() < end:
        for s in sels:
            try:
                if s.startswith("meta"):
                    loc = page.locator(s).first
                    if loc.count() and _parse_price_text(loc.get_attribute("content") or "") is not None:
                        return
                else:
                    page.wait_for_selector(s, timeout=400, state="attached")
                    txt = (page.locator(s).first.inner_text(timeout=400) or "").strip()
                    if _parse_price_text(txt) is not None:
                        return
            except Exception:
                pass
        time.sleep(0.15)


def _extract_price_dom(page) -> Optional[float]:
    candidates = [
        '[itemprop="price"]',
        '[data-testid="uc-price"]',
        '[data-testid="price"]',
        '[data-testid="price-value"]',
        '[data-testid="price-primary"]',
        'div[data-testid="price-section"]',
        'div[data-testid="price-wrapper"]',
        'meta[itemprop="price"]',
        'span[class*="price"]',
        '[aria-label*="zł"]',
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if not loc or loc.count() == 0:
                continue
            txt = ""
            try:
                txt = (loc.inner_text(timeout=600) or "").strip()
            except Exception:
                pass
            v = _parse_price_text(txt)
            if v is not None:
                return v
            content = (loc.get_attribute("content") or "").strip()
            v = _parse_price_text(content)
            if v is not None:
                return v
            aria = (loc.get_attribute("aria-label") or "").strip()
            v = _parse_price_text(aria)
            if v is not None:
                return v
        except Exception:
            continue

    # Fallback: HTML
    try:
        html = page.content()
        v = _extract_price_from_html(html)
        if v is not None:
            return v
    except Exception:
        pass

    # Ostateczny: skan tekstu strony
    try:
        body_txt = page.inner_text("body", timeout=800)
        m = re.search(r"(\d[\d\s]*[.,]\d{1,2})\s*zł", body_txt.lower())
        if m:
            v = _parse_price_text(m.group(1))
            if v is not None:
                return v
    except Exception:
        pass

    return None


def _extract_price_via_js_state(page) -> Optional[float]:
    """Wyciągnij cenę z obiektów JS osadzonych na stronie."""
    try:
        js = """
        () => {
          const g = (w, keys) => {
            for (const k of keys) if (w && w[k]) return w[k];
            return null;
          };
        const w = window;
        const candidates = [
          g(w, ["__APP_STATE__", "__INITIAL_STATE__", "__NEXT_DATA__", "__STATE__"]),
          ...Array.from(document.querySelectorAll("script")).map(s => {
            try { return JSON.parse(s.textContent); } catch (e) { return null; }
          })
        ].filter(Boolean);
        return candidates;
        }
        """
        states = page.evaluate(js)
        if not isinstance(states, list):
            states = [states]
        for st in states:
            v = _json_find_price(st)
            if v is not None:
                return v
    except Exception:
        return None
    return None


def _get_single(page, auction: Dict) -> Dict:
    aid = str(auction["id"]).strip()
    url = ALLEGRO_URL.format(aid=aid)

    # 1) wejście: najpierw spróbuj mocniej dociągnąć sieć
    resp = None
    try:
        resp = page.goto(url, timeout=60000, wait_until="networkidle")
    except PWTimeoutError:
        # retry lżejszy
        resp = page.goto(url, timeout=30000, wait_until="domcontentloaded")

    status = None
    try:
        status = resp.status if resp else None
    except Exception:
        status = None

    if status in (404, 410):
        raise EndedOfferError(f"ENDED {aid} HTTP {status}")

    # 2) zgody (główna + iframy)
    _click_consent_everywhere(page)

    # 3) krótka pauza na hydrację
    time.sleep(0.4)

    # 4) czekaj aż pojawi się cena (jeśli ma się pojawić w DOM)
    try:
        _wait_price_visible(page, timeout_ms=9000)
    except Exception:
        pass

    # 5) najpierw spróbuj z JS state
    price = _extract_price_via_js_state(page)
    if price is None:
        # 6) DOM/HTML/tekst
        price = _extract_price_dom(page)

    if price is None:
        raise RuntimeError(f"Playwright: brak ceny dla {url}")

    return {"id": aid, "price": float(price)}


# ----------------------------- public API ---------------------------------- #

def get_price_batch(auctions: List[Dict]) -> Tuple[List[Dict], List[str]]:
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
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            extra_http_headers={"Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8"},
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
