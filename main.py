# main.py
import os
import json
import time
import importlib
from datetime import datetime, timedelta
from typing import List, Dict

# ===== Konfiguracja ===========================================================

ENDED_CACHE_PATH = os.getenv("ENDED_CACHE_PATH", "ended_cache.json")
RECHECK_ENDED_HOURS = int(os.getenv("RECHECK_ENDED_HOURS", "72"))  # po ilu godzinach znów sprawdzać
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "25"))
SLEEP_BETWEEN_BATCH = float(os.getenv("SLEEP_BETWEEN_BATCH", "0.5"))

# Czytaj TYLKO ten plik .txt (domyślnie: Akwesan GR 0,5.txt)
TARGET_FILE = os.getenv("TARGET_FILE", "Akwesan GR 0,5.txt")

# ===== Helpers ===============================================================

def parse_price(text: str) -> float:
    t = (text or "").lower().replace("zł", "").replace(" ", "").replace(",", ".")
    return float(t)

def load_auctions_from_files(folder: str = ".") -> List[Dict]:
    """
    Wczytuje TYLKO jeden plik z aukcjami: TARGET_FILE (np. 'Akwesan GR 0,5.txt').
    Obsługuje oba formaty:
      A) nagłówek 'cena minimalna:...' + ID w kolejnych liniach,
      B) wiersze 'ID;MIN_CENA'
    Usuwa duplikaty ID w ramach tego pliku.
    """
    filename = TARGET_FILE
    filepath = os.path.join(folder, filename)
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Nie znaleziono pliku: {filepath}")

    auctions: List[Dict] = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        if not lines:
            print(f"[WARN] Plik {filename} jest pusty.")
            return []

        product = filename.replace(".txt", "")

        # Format B (z separatorem ';')
        if any(";" in ln for ln in lines):
            for ln in lines:
                if ";" not in ln:
                    continue
                auction_id, min_price = ln.split(";", 1)
                auctions.append({
                    "id": auction_id.strip(),
                    "min_price": parse_price(min_price),
                    "product": product
                })
        else:
            # Format A (pierwsza linia 'cena minimalna: ...', reszta to ID)
            header = lines[0].lower()
            if header.startswith("cena minimalna:"):
                min_price = parse_price(header.split(":", 1)[1])
                for auction_id in lines[1:]:
                    auctions.append({
                        "id": auction_id.strip(),
                        "min_price": min_price,
                        "product": product
                    })
            else:
                raise ValueError(
                    f"Pierwsza linia w {filename} nie zaczyna się od 'cena minimalna:' "
                    f"i nie stwierdzono formatu z ';'."
                )

    except Exception as e:
        print(f"[WARN] Nie udało się wczytać pliku {filename}: {e}")
        return []

    # de-duplikacja po (product, id)
    seen = set()
    uniq: List[Dict] = []
    for a in auctions:
        key = (a["product"], a["id"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(a)

    print(f"[INFO] (Single-file) Wczytano {len(uniq)} aukcji z pliku '{filename}'")
    return uniq

def _chunk(lst: List[Dict], n: int) -> List[List[Dict]]:
    return [lst[i:i+n] for i in range(0, len(lst), n)]

# ===== Ended cache ===========================================================

def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", ""))

def load_ended_cache(path: str = ENDED_CACHE_PATH) -> Dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_ended_cache(cache: Dict[str, str], path: str = ENDED_CACHE_PATH) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] Nie zapisano {path}: {e}")

def ended_should_skip(auction_id: str, cache: Dict[str, str]) -> bool:
    ts = cache.get(auction_id)
    if not ts:
        return False
    try:
        seen = _parse_iso(ts)
    except Exception:
        return False
    return datetime.utcnow() - seen < timedelta(hours=RECHECK_ENDED_HOURS)

def mark_ended(auction_id: str, cache: Dict[str, str]) -> None:
    cache[auction_id] = _now_iso()

# ===== Main ==================================================================

def main():
    print("== Start programu (main.py) ==")

    # get_price (batch) + typ wyjątku zakończenia
    gp = importlib.import_module("get_price")
    get_price_batch = getattr(gp, "get_price_batch")
    EndedOfferError = getattr(gp, "EndedOfferError", RuntimeError)  # dostępny, gdyby był potrzebny

    auctions = load_auctions_from_files(".")
    total = len(auctions)
    print(f"[INFO] Wczytano {total} wpisów z pliku")
    if total == 0:
        print("[INFO] Nic do sprawdzenia.")
        return

    # cache zakończonych
    ended_cache = load_ended_cache()
    to_check: List[Dict] = []
    skipped_ended = 0
    for a in auctions:
        if ended_should_skip(a["id"], ended_cache):
            skipped_ended += 1
            continue
        to_check.append(a)
    if skipped_ended:
        print(f"[INFO] Pominięto tymczasowo {skipped_ended} zakończonych aukcji (TTL {RECHECK_ENDED_HOURS}h)")

    alerts: List[Dict] = []
    errors: List[str] = []

    # Przyjazne testom parametry dla jednego pliku (mniejsze batch i brak sleep)
    batch_size = min(BATCH_SIZE, 5)
    sleep_between = 0.0

    chunks = _chunk(to_check, batch_size)
    all_batches = len(chunks)
    print(f"[INFO] Tryb BATCH: {all_batches} partii po maks {batch_size} aukcji")

    processed = 0
    for i, chunk in enumerate(chunks, 1):
        t0 = time.time()
        results, errs = get_price_batch(chunk)  # type: ignore
        dt = time.time() - t0

        # błędy – miękko oznacz zakończone (szukamy fraz ENDED/zakończon/usunięt)
        for msg in errs or []:
            s = str(msg)
            if ("ENDED" in s) or ("zakończon" in s) or ("usunięt" in s) or ("HTTP 404" in s) or ("HTTP 410" in s):
                # spróbuj wyłuskać ID; jeśli nie, oznaczamy cały chunk
                found = False
                for a in chunk:
                    if a["id"] in s:
                        mark_ended(a["id"], ended_cache)
                        found = True
                        break
                if not found:
                    for a in chunk:
                        mark_ended(a["id"], ended_cache)
            else:
                errors.append(s)

        # sprawdź progi
        by_id = {r["id"]: r for r in results}
        for a in chunk:
            r = by_id.get(a["id"])
            if not r:
                continue
            price = float(r["price"])
            if price < a["min_price"]:
                alerts.append({"product": a["product"], "id": a["id"], "price": price, "min": float(a["min_price"])})

        processed += len(chunk)
        print(f"[PROGRESS] Batch {i}/{all_batches} OK w {dt:.1f}s — przetworzono {processed}/{len(to_check)}")
        time.sleep(sleep_between)

    # zapisz cache zakończonych
    save_ended_cache(ended_cache)

    # raport
    if alerts:
        print(f"[INFO] Znaleziono {len(alerts)} zaniżonych aukcji – wysyłam e-mail…")
        from email_alert import send_alert
        send_alert(alerts)
    else:
        print("[INFO] Brak zaniżonych cen.")

    if errors:
        print("[BŁĘDY]")
        for line in errors:
            print(" -", line)

if __name__ == "__main__":
    main()
