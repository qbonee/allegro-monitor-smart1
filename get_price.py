import re
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

def _to_float(txt: str) -> float:
    return float(txt.replace(" ", "").replace("\xa0", "").replace(",", ".").strip())

def get_price(auction_id: str) -> float:
    url = f"https://allegro.pl/oferta/{auction_id}"
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    # 1) meta z ceną (najpewniejsze)
    meta = soup.select_one('meta[itemprop="price"]')
    if meta and meta.get("content"):
        return _to_float(meta["content"])

    # 2) widoczny span z ceną
    el = soup.select_one('span[data-testid="price"]')
    if el:
        return _to_float(el.get_text(" ", strip=True))

    # 3) awaryjnie regex
    m = re.search(r"(\d+[.,]\d{2})\s*z[łl]", r.text, re.IGNORECASE)
    if m:
        return _to_float(m.group(1))

    raise Exception("Nie znaleziono ceny na stronie")
