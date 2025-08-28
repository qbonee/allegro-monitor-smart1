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
    "Pragma": "
