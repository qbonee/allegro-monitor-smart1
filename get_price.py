# -*- coding: utf-8 -*-
"""
Allegro price watcher dla cron workera.

Format plików wejściowych (*.txt):
  1. linia:  'cena minimalna: 40zł'
  2..n linie: ID oferty Allegro (lub pełny URL https://allegro.pl/oferta/ID)

Eksportuje:
  - get_price_batch(*args, **kwargs)  # używane przez worker/main.py
  - main()                             # uruchomienie ręczne

ENV (wymagane SMTP):
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_TO
ENV (opcjonalne):
  MAIL_FROM, MAIL_FROM_NAME, EMAIL_SUBJECT, EMAIL_HTML,
  TARGET_FILE_BASENAME="Akwesan Starter",
  BASE_DELAY=0.8, JITTER=0.8, MAX_PER_RUN=0,
  BACKOFF_START=5, BACKOFF_MAX=900,
  STATE_PATH=/data/state.json
"""

import os, re, json, time, ssl, smtplib, pathlib, random
from email.mime.text import MIMEText
from typing import Optional, Dict, Any, Iterator, Tuple, Iterable
import requests

# ---- tempo / limity ----
BASE_DELAY = float(os.environ.get("BASE_DELAY", "0.8"))
JITTER     = float(os.environ.get("JITTER", "0.8"))
MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "0"))
BACKOFF_START = float(os.environ.get("BACKOFF_START", "5"))
BACKOFF_MAX   = float(os.environ.get("BACKOFF_MAX", "900"))

# ---- pliki / ścieżki ----
ROOT = pathlib.Path(__file__).parent.resolve()
STATE_PATH = pathlib.Path(os.environ.get("STATE_PATH", str(ROOT / "state.json")))
TARGET_FILE = os.environ.get("TARGET_FILE_BASENAME")  # np. "Akwesan Starter"

# ---- HTTP ----
UA   = "Mozilla/5.0 (compatible; AllegroWatcher/1.5; cron-worker)"
HDRS = {"User-Agent": UA, "Accept-Language": "pl-PL,pl;q=0.9"}
session = requests.Session()

# ---- regexy ----
RE_ID      = re.compile(r"(?:/oferta/)?(?P<id>\d{8,})")
RE_HEADER  = re.compile(r"cena\s*minimalna\s*:\s*([0-9][0-9 .,\t]*[0-9])\s*z?ł?", re.I)
RE_PLN     = re.compile(r"(\d{1,3}(?:[ .]\d{3})*(?:[.,]\d{2}))\s*zł", re.I)
RE_JSONLD  = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
RE_CAPTCHA = re.compile(r"captcha|nie\s*jesteś\s*robotem|przepraszamy.*zabezpieczenie", re.I)

class CaptchaSuspected(Exception):
    pass

def pl_to_float(s: str) -> float:
    s = s.strip().replace("\xa0", " ").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)

def load_state() -> Dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"alerts": {}}  # offer_id -> {"price": float, "ts": int}

def save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def find_txt_files() -> Iterable[pathlib.Path]:
    files = sorted(ROOT.glob("*.txt"))
    if TARGET_FILE:
        target_lower = TARGET_FILE.lower()
        for p in files:
            if p.stem.lower() == target_lower or p.name.lower() == f"{target_lower}.txt":
                return [p]
        raise FileNotFoundError(f"Nie znalazłem pliku '{TARGET_FILE}' w {ROOT}")
    return files

def read_threshold(path: pathlib.Path) -> float:
    txt = path.read_text(encoding="utf-8", errors="ignore")
    m = RE_HEADER.search(txt)
    if not m:
        raise ValueError(f"[{path.name}] Brak nagłówka 'cena minimalna: ...'")
    return pl_to_float(m.group(1))

def iter_ids_from_file(path: pathlib.Path) -> Iterator[Tuple[str, int]]:
    seen = set()
    for i, raw in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or RE_HEADER.search(line):
            continue
        m = RE_ID.search(line)
        if not m:
            continue
        offer_id = m.group("id")
        if offer_id in seen:
            continue
        seen.add(offer_id)
        yield offer_id, i

def polite_sleep():
    delay = BASE_DELAY + random.uniform(0, max(JITTER, 0))
    if delay > 0:
        time.sleep(delay)

def fetch_html(url: str) -> str:
    try:
        r = session.get(url, headers=HDRS, timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"HTTP request failed: {e}")
    if r.status_code in (403, 429):
        raise CaptchaSuspected(f"HTTP {r.status_code}")
    text = r.text
    if RE_CAPTCHA.search(text):
        raise CaptchaSuspected("captcha suspected in body")
    r.raise_for_status()
    return text

def price_from_jsonld(html: str) -> Optional[float]:
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
                if node.get("@type") in ("Offer","AggregateOffer"):
                    v = node.get("price") or node.get("lowPrice") or node.get("highPrice")
                    if v is not None:
                        try:
                            return pl_to_float(str(v))
                        except Exception:
                            pass
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return None

def price_from_text(html: str) -> Optional[float]:
    matches = RE_PLN.findall(html)
    if not matches:
        return None
    try:
        vals = [pl_to_float(m) for m in matches]
        return min(vals) if vals else None
    except Exception:
        return None

def get_offer_price(offer_id: str) -> Optional[float]:
    url = f"https://allegro.pl/oferta/{offer_id}"
    backoff = BACKOFF_START
    while True:
        try:
            html = fetch_html(url)
            return price_from_jsonld(html) or price_from_text(html)
        except CaptchaSuspected as e:
            print(f"[{offer_id}] Podejrzenie CAPTCHA/limitów: {e} → backoff {backoff:.0f}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
        except Exception as e:
            print(f"[{offer_id}] Błąd pobierania: {e}")
            return None

def send_email(to_addr: str, subject: str, html: str) -> None:
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ.get("SMTP_USER")
    pwd  = os.environ.get("SMTP_PASS")
    from_addr  = os.environ.get("MAIL_FROM", user)
    from_name  = os.environ.get("MAIL_FROM_NAME", "Allegro Price Watcher")

    if not all([host, port, user, pwd, from_addr, to_addr]):
        raise RuntimeError("Brak wymaganych zmiennych SMTP_* lub EMAIL_TO.")

    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to_addr

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
        s.login(user, pwd)
        s.sendmail(from_addr, [to_addr], msg.as_string())

def process_one_file(path: pathlib.Path, state: Dict[str, Any],
                     email_to: str, subject_tmpl: str, body_tmpl: str,
                     remaining_quota: int) -> Tuple[int, int]:
    """Przerób jeden plik. Zwraca (processed_count, alerts_count)."""
    try:
        threshold = read_threshold(path)
    except Exception as e:
        print(str(e))
        return 0, 0

    alerts = state.setdefault("alerts", {})
    processed = 0
    alerts_sent = 0

    for offer_id, line_no in iter_ids_from_file(path):
        if remaining_quota and processed >= remaining_quota:
            break

        url = f"https://allegro.pl/oferta/{offer_id}"
        price = get_offer_price(offer_id)
        polite_sleep()

        if price is None:
            print(f"[{offer_id}] Nie udało się odczytać ceny ({path.name}:{line_no}).")
            processed += 1
            continue

        print(f"[{offer_id}] Cena={price:.2f} zł | Próg={threshold:.2f} zł | {path.name}:{line_no}")

        last = alerts.get(offer_id, {}).get("price")
        should_alert = price <= threshold and (last is None or price < float(last))

        if should_alert:
            html = body_tmpl.format(
                offer_id=offer_id,
                price=f"{price:.2f}",
                threshold=f"{threshold:.2f}",
                url=url,
                file=path.name,
                line=line_no,
            )
            try:
                send_email(email_to, subject_tmpl.format(offer_id=offer_id), html)
                alerts[offer_id] = {"price": float(price), "ts": int(time.time())}
                alerts_sent += 1
                print(f"[{offer_id}] ALERT wysłany do {email_to}")
            except Exception as e:
                print(f"[{offer_id}] Błąd wysyłki maila: {e}")
        else:
            if last is None or price < float(last):
                alerts[offer_id] = {"price": float(price), "ts": int(time.time())}

        processed += 1

    return processed, alerts_sent

def run_once(target_file_basename: Optional[str] = None,
             max_per_run: int = None) -> Dict[str, int]:
    """Wykonaj jeden przebieg skanowania. Zwraca podsumowanie."""
    email_to = os.environ.get("EMAIL_TO")
    subject_tmpl = os.environ.get("EMAIL_SUBJECT", "🔥 Spadek ceny: {offer_id}")
    body_tmpl = os.environ.get(
        "EMAIL_HTML",
        "<h2>Oferta {offer_id} spadła do {price} zł (próg {threshold} zł)</h2>"
        "<p><a href='{url}'>Przejdź do oferty</a></p>"
        "<p>Plik: {file} (linia {line})</p>"
    )

    global TARGET_FILE
    if target_file_basename:  # pozwól nadpisać z argumentu
        TARGET_FILE = target_file_basename

    state = load_state()

    files = list(find_txt_files())
    if not files:
        print("Brak plików *.txt w katalogu roboczym.")
        return {"files": 0, "checked": 0, "alerts": 0}

    quota = max_per_run if (max_per_run is not None) else (MAX_PER_RUN if MAX_PER_RUN > 0 else 0)
    total_checked = 0
    total_alerts  = 0
    state_changed = False

    for path in files:
        before = json.dumps(state, ensure_ascii=False)
        processed, alerts_sent = process_one_file(
            path, state, email_to, subject_tmpl, body_tmpl, quota if quota else 0
        )
        total_checked += processed
        total_alerts  += alerts_sent
        after = json.dumps(state, ensure_ascii=False)
        if before != after:
            state_changed = True
        if quota:
            quota = max(quota - processed, 0)
            if quota == 0:
                print(f"Osiągnięto limit MAX_PER_RUN — kończę ten przebieg.")
                break

    if state_changed:
        save_state(state)

    return {"files": len(files), "checked": total_checked, "alerts": total_alerts}

# === API dla workera ===
def get_price_batch(*args, **kwargs) -> Dict[str, int]:
    """
    Funkcja oczekiwana przez Twój worker (`main.py`/`worker_loop.py`).
    Parametry są opcjonalne i ignorowane, żeby nie wiązać interfejsu.
    Zwraca słownik podsumowania: {'files': X, 'checked': Y, 'alerts': Z}
    """
    return run_once()

# === uruchomienie ręczne ===
def main():
    summary = run_once()
    print(f"Podsumowanie: {summary}")

if __name__ == "__main__":
    main()
