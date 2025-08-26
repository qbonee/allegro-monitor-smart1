import re
from typing import List, Dict, Tuple, Optional
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PRICE_SEL_CANDIDATES = [
    "span[data-testid='price']",
    "span[itemprop='price']",
    "meta[property='product:price:amount']",
    "meta[property='og:price:amount']",
]

COOKIE_BUTTONS = [
    "button[data-role='accept-consent']",
    "button:has-text('Przejdź do serwisu')",
    "button:has-text('OK')",
    "button:has-text('Akceptuję')",
    "button:has-text('Zgadzam się')",
]

def _norm_price(text: str) -> Optional[float]:
    if not text:
        return None
    t = text.strip().replace("\u00a0", " ").lower()
    m = re.search(r"(\d[\d\s]*[,\.]?\d*)", t)
    if not m:
        return None
    num = m.group(1).replace(" ", "").replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None

def _extract_meta(page) -> Optional[float]:
    for sel in ["meta[property='product:price:amount']",
                "meta[property='og:price:amount']"]:
        try:
            content = page.locator(sel).first.get_attribute("content", timeout=800)
            if content:
                v = _norm_price(content)
                if v is not None:
                    return v
        except Exception:
            pass
    return None

def _accept_cookies(page):
    for sel in COOKIE_BUTTONS:
        try:
            page.locator(sel).first.click(timeout=1500)
            return
        except Exception:
            continue

def get_price_for(page, auction_id: str) -> Optional[float]:
    url = f"https://allegro.pl/oferta/{auction_id}"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    _accept_cookies(page)

    v = _extract_meta(page)
    if v is not None:
        return v

    for sel in PRICE_SEL_CANDIDATES:
        try:
            loc = page.locator(sel).first
            txt = loc.inner_text(timeout=2500)
            v = _norm_price(txt)
            if v is not None:
                return v
        except PWTimeout:
            continue
        except Exception:
            continue

    try:
        body_text = page.inner_text("body", timeout=2500)
        v = _norm_price(body_text)
        if v is not None:
            return v
    except Exception:
        pass

    return None

def get_price_batch(auctions: List[Dict]) -> Tuple[List[Tuple[Dict, Optional[float]]], List[str]]:
    """Zwraca: [(auction, price|None), ...], [errors]"""
    results: List[Tuple[Dict, Optional[float]]] = []
    errors: List[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(
            locale="pl-PL",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
        )
        page = context.new_page()

        for a in auctions:
            try:
                price = get_price_for(page, a["id"])
                results.append((a, price))
            except Exception as e:
                errors.append(f"{a['product']} [{a['id']}]: {e}")
                results.append((a, None))

        context.close()
        browser.close()

    return results, errors
