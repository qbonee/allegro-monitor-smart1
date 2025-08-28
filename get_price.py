# -*- coding: utf-8 -*-
"""
get_price.py — warstwa pobierania cen dla main.py (bez omijania CAPTCHA)

API:
  get_price_batch(chunk: List[Dict]) -> (results: List[Dict], errors: List[str])

Zachowanie pro-sąsiedzkie:
- minimalne żądania HTTP,
- losowy, „normalny” User-Agent,
- dłuższe pauzy,
- na pierwszy 403/„captcha suspected” -> PRZERWIJ i ustaw globalny COOLDOWN
  (zapisany do pliku; kolejne wywołanie zwróci od razu błąd COOLDOWN i nic nie pobierze).

ENV (opcjonalne):
  BASE_DELAY=1.5        # bazowa pauza między żądaniami (sek)
  JITTER=1.5            # losowy dodatek 0..JITTER (sek)
  BACKOFF_START=15      # (sek) progresywny backoff zanim włączymy COOLDOWN w obrębie jednego przebiegu
  BACKOFF_MAX=120       # (sek) max backoff w obrębie jednego przebiegu

  COOLDOWN_FILE=/data/cooldown.json
  COOLDOWN_MIN=1800     # 30 min – minimalny globalny cooldown po 403
  COOLDOWN_MAX=3600     # 60 min – maksymalny globalny cooldown
  USER_AGENT=...        # jeśli chcesz wymusić jeden UA
"""

from __future__ import annotations
import os, re, json, time, random, pathlib
from typing import Dict, List, Tuple, Optional
import requests

# --- tempo / backoff ---
BASE_DELAY    = float(os.environ.get("BASE_DELAY", "1.5"))
JITTER        = float(os.environ.get("JITTER", "1.5"))
BACKOFF_START = float(os.environ.get("BACKOFF_START", "15"))
BACKOFF_MAX   = float(os.environ.get("BACKOFF_MAX", "120"))

# --- globalny cooldown ---
ROOT = pathlib.Path(__file__).parent.resolve()
COOLDOWN_FILE = pathlib.Path(os.environ.get("COOLDOWN_FILE", str(ROOT / "cooldown.json")))
COOLDOWN_MIN = int(os.environ.get("COOLDOWN_MIN", "1800"))  # 30 min
COOLDOWN_MAX = int(os.environ.get("COOLDOWN_MAX", "3600"))  # 60 min

def _load_cooldown() -> int:
    try:
        data = json.loads(COOLDOWN_FILE.read_text(encoding="utf-8"))
        return int(data.get("until_ts", 0))
    except Exception:
        return 0

def _set_cooldown(seconds: int, reason: str = ""):
    seconds = max(COOLDOWN_MIN, min(COOLDOWN_MAX, seconds))
    data = {"until_ts": int(time.time()) + int(seconds), "reason": reason, "set_at": int(time.time())}
    try:
        COOLDOWN_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

# --- HTTP ---
UA_LIST = [
    # losowe, „normalne” UA
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]
USER_AGENT = os.environ.get("USER_AGENT") or random.choice(UA_LIST)

HDRS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.6,en;q=0.4",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "close",
}

session = requests.Session()

# --- regexy ---
RE_ID       = re.compile(r"(?:/oferta/)?(?P<id>\d{8,})")
RE_PLN      = re.compile(r"(\d{1,3}(?:[ .]\d{3})*(?:[.,]\d{2}))\s*zł", re.I)
RE_JSONLD   = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
RE_CAPTCHA  = re.compile(r"captcha|nie\s*jesteś\s*robotem|przepraszamy.*zabezpieczenie", re.I)
RE_ENDED_TXT= re.compile(r"(zakończon|usunięt|nie\s*jest\s*już\s*dostępna|nie\s*znaleźli)", re.I)

# --- wyjątki ---
class EndedOfferError(Exception):
    pass

class CaptchaSuspected(Exception):
    pass

# --- helpers ---
def _polite_sleep():
    delay = BASE_DELAY + (random.uniform(0, JITTER) if JITTER > 0 else 0.0)
    if delay > 0:
        time.sleep(delay)

def _pl_to_float(s: str) -> float:
    s = s.strip().replace("\xa0", " ").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)

def _norm_id(raw: str) -> str:
    m = RE_ID.search(raw)
    if not m:
        raise ValueError(f"Nieprawidłowy ID/URL: {raw!r}")
    return m.group("id")

def _fetch_html(url: str) -> str:
    try:
        # rozdziel timeouts: (connect, read)
        r = session.get(url, headers=HDRS, timeout=(10, 40))
    except requests.RequestException as e:
        raise RuntimeError(f"HTTP request failed: {e}")
    if r.status_code in (404, 410):
        raise EndedOfferError(f"HTTP {r.status_code}")
    if r.status_code in (403, 429):
        raise CaptchaSuspected(f"HTTP {r.status_code}")
    txt = r.text
    if RE_CAPTCHA.search(txt):
        raise CaptchaSuspected("captcha suspected in body")
    if RE_ENDED_TXT.search(txt):
        raise EndedOfferError("strona wskazuje zakończenie/oferta niedostępna")
    r.raise_for_status()
    return txt

def _price_from_jsonld(html: str) -> Optional[float]:
    for m in RE_JSONLD.finditer(html):
        block = m.group(1)
        try:
            data = json.loads(block)
        except Exception:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if node.get("@type") in ("Offer", "AggregateOffer"):
                    val = node.get("price") or node.get("lowPrice") or node.get("highPrice")
                    if val is not None:
                        try:
                            return _pl_to_float(str(val))
                        except Exception:
                            pass
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return None

def _price_from_text(html: str) -> Optional[float]:
    matches = RE_PLN.findall(html)
    if not matches:
        return None
    try:
        vals = [_pl_to_float(x) for x in matches]
        return min(vals) if vals else None
    except Exception:
        return None

def _get_price_single(auction_id: str) -> float:
    url = f"https://allegro.pl/oferta/{auction_id}"
    backoff = BACKOFF_START
    while True:
        try:
            html = _fetch_html(url)
            price = _price_from_jsonld(html) or _price_from_text(html)
            if price is None:
                raise RuntimeError("brak ceny w HTML")
            return price
        except CaptchaSuspected as e:
            # narastający backoff, ale nie męczymy bez końca
            wait = min(backoff, BACKOFF_MAX)
            print(f"[{auction_id}] CAPTCHA/limit: {e} → lokalny backoff {wait:.0f}s")
            time.sleep(wait)
            # po pierwszym „odbiciu” nie idźmy dalej — przekaż wyżej
            raise
        # EndedOfferError i inne wyjątki zostawiamy wyżej

# --- główne API ---
def get_price_batch(chunk: List[Dict]) -> Tuple[List[Dict], List[str]]:
    """
    Zwraca:
      results: [{"id": "...", "price": float}, ...]
      errors:  ["COOLDOWN: ...", "123... ENDED: ...", "123... ERROR: ..."]
    """
    # najpierw sprawdź globalny cooldown
    until = _load_cooldown()
    now = int(time.time())
    if until > now:
        return [], [f"COOLDOWN: wstrzymane do {until} (UTC ts)"]

    results: List[Dict] = []
    errors:  List[str] = []

    for a in chunk:
        try:
            auction_id = _norm_id(str(a.get("id", "")))
        except Exception as e:
            errors.append(f"{a.get('id')} BAD_ID: {e}")
            continue

        try:
            price = _get_price_single(auction_id)
            results.append({"id": auction_id, "price": float(price)})
        except CaptchaSuspected as e:
            # ustaw długi, globalny cooldown i przerwij cały batch
            cd = random.randint(COOLDOWN_MIN, COOLDOWN_MAX)
            _set_cooldown(cd, reason=str(e))
            errors.append(f"COOLDOWN: {cd}s po CAPTCHA/limitach")
            break
        except EndedOfferError as e:
            errors.append(f"{auction_id} ENDED: {e}")
        except Exception as e:
            errors.append(f"{auction_id} ERROR: {e}")
        finally:
            _polite_sleep()

    return results, errors

# self-test (opcjonalnie)
if __name__ == "__main__":
    demo = [{"id": "1234567890", "min_price": 0.0, "product": "DEMO"}]
    print(get_price_batch(demo))
