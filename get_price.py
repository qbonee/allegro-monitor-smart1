# get_price.py
import json
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _parse_price_text(txt: str) -> float:
    """
    '1 234,56 zł' -> 1234.56
    '1234.56'    -> 1234.56
    """
    if not txt:
        raise ValueError("Brak tekstu ceny")
    t = txt.strip().lower()
    t = t.replace("zł", "").replace(" ", "").replace("\xa0", "").replace(",", ".")
    # wyciągnij pierwszą liczbę (na wszelki wypadek)
    m = re.search(r"(\d+(\.\d+)?)", t)
    if not m:
        raise ValueError(f"Nie rozpoznano formatu ceny: {txt!r}")
    return float(m.group(1))


def _price_from_json_ld(html: str) -> Optional[float]:
    """
    Allegro zwykle osadza JSON-LD ze strukturą:
    {"@type":"Product", ... "offers":{"@type":"Offer","price":"123.45"}}
    """
    for m in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
                         html, flags=re.S | re.I):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue

        # czasem to lista kilku obiektów
        candidates = data if isinstance(data, list) else [data]
        for node in candidates:
            # product -> offers -> price
            offers = None
            if isinstance(node, dict):
                if node.get("@type") == "Product":
                    offers = node.get("offers")
                elif "offers" in node:
                    offers = node["offers"]
            if isinstance(offers, dict) and "price" in offers:
                return float(str(offers["price"]).replace(",", "."))
    return None


def _price_from_dom(html: str) -> Optional[float]:
    """
    Fallback: szukamy w drzewie DOM.
    Najpierw Allegro-owy znacznik testowy, potem regex.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Dość stabilny selektor na Allegro:
    el = soup.select_one("span[data-testid='price']") or soup.select_one("div[data-testid='price'] span")
    if el and el.get_text(strip=True):
        return _parse_price_text(el.get_text(" ", strip=True))

    # plan B: meta z ceną / regex po 'price":"123.45"'
    m = re.search(r'"price"\s*:\s*"(\d+(?:\.\d+)?)"', html)
    if m:
        return float(m.group(1))

    return None


def get_price(auction_id: str) -> float:
    """
    Pobiera stronę oferty i wyciąga cenę.
    """
    url = f"https://allegro.pl/oferta/{auction_id}"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} dla {url}")

    html = resp.text

    # 1) próbujemy JSON-LD (najpewniejsze)
    price = _price_from_json_ld(html)
    if price is not None:
        return price

    # 2) fallback na DOM/regex
    price = _price_from_dom(html)
    if price is not None:
        return price

    raise RuntimeError("Nie udało się znaleźć ceny na stronie")
