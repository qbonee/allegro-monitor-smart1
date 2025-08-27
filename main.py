import os
import json
import time
import importlib
from datetime import datetime, timedelta
from typing import List, Dict

ENDED_CACHE_PATH = os.getenv("ENDED_CACHE_PATH", "ended_cache.json")
RECHECK_ENDED_HOURS = int(os.getenv("RECHECK_ENDED_HOURS", "72"))  # po ilu godzinach ponownie sprawdzać

# ===== Helpers ===============================================================

def parse_price(text: str) -> float:
    t = (text or "").lower().replace("zł", "").replace(" ", "").replace(",", ".")
    return float(t)

def load_auctions_from_files(folder: str = ".") -> List[Dict]:
    auctions: List[Dict] = []
    for filename in os.listdir(folder):
        if not filename.endswith(".txt"):
            continue
        filepath = os.path.join(folder, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            if not lines:
                continue
            product = filename.replace(".txt", "")
            if any(";" in ln for ln in lines):  # Format B
                for ln in lines:
                    if ";" not in ln:
                        continue
                    auction_id, min_price = ln.split(";", 1)
                    auctions.append({"id": auction_id.strip(), "min_price": parse_price(min_price), "product": product})
                continue
            header = lines[0].lower()  # Format A
            if header.startswith("cena minimalna:"):
                min_price = parse_price(header.split(":", 1)[1])
                for auction_id in lines[1:]:
                    auctions.append({"id": auction_id.strip(), "min_price": min_price, "product": product})
        except Exception as e:
            print(f"[WARN] Nie udało się wczytać pliku {filename}: {e}")

    # de-duplikacja (po parze produkt+id; ustaw GLOBAL_DEDUP=1 aby deduplikować po samym id)
    global_dedup = os.getenv("GLOBAL_DEDUP", "0") == "1"
    seen = set()
    uniq: List[Dict] = []
    for a in auctions:
        key = a["id"] if global_dedup else (a["product"], a["id"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(a)
    return uniq

def _chunk(lst: List[Dict], n: int) -> List[List[Dict]]:
    return [lst[i:i+n] for i in range(0, len(lst), n)]

# ===== Ended cache ===========================================================

def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def _parse_iso(s: str) -> datetime:
    # prosty parser ISO z 'Z'
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

    # załaduj moduł get_price
    try:
        gp = importlib.import_module("get_price")
        get_price_batch = getattr(gp, "get_price_batch")
        EndedOfferError = getattr(gp, "EndedOfferError", RuntimeError)  # fallback: jakby ktoś usunął klasę
    except Exception as e:
        print(f"[FATAL] Nie mogę zaimportować 'get_price': {e}")
        raise

    auctions = load_auctions_from_files(".")
    total = len(auctions)
    print(f"[INFO] Wczytano {total} wpisów .txt")
    if total == 0:
        print("[INFO] Nic do sprawdzenia.")
        return

    # załaduj cache zakończonych i odfiltruj „świeżo zakończone”
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

    BATCH_SIZE = int(os.getenv("BATCH_SIZE", "25"))
    SLEEP_BETWEEN_BATCH = float(os.getenv("SLEEP_BETWEEN_BATCH", "0.5"))

    chunks = _chunk(to_check, BATCH_SIZE)
    all_batches = len(chunks)
    print(f"[INFO] Tryb BATCH: {all_batches} partii po maks {BATCH_SIZE} aukcji")

    processed = 0
    for i, chunk in enumerate(chunks, 1):
        t0 = time.time()
        results, errs = get_price_batch(chunk)  # type: ignore
        dt = time.time() - t0

        # przetwórz błędy (miękko traktuj zakończone)
        for e in errs or []:
            msg = str(e)
            # jeśli get_price_batch pakowało już stringi, a nie wyjątki, sprawdzamy frazy
            if "ENDED" in msg or "zakończon" in msg or "usunięt" in msg:
                # spróbuj wyciągnąć ID z wiadomości (ostatnie cyfry)
                # a jak się nie uda – oznacz wszystkie z chunku
                found = False
                for a in chunk:
                    if a["id"] in msg:
                        mark_ended(a["id"], ended_cache)
                        found = True
                        break
                if not found:
                    for a in chunk:
                        mark_ended(a["id"], ended_cache)
                print("[INFO] Pomijam zakończoną/usuniętą ofertę ->", msg)
            else:
                errors.append(msg)

        # results -> sprawdzamy progi
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
        time.sleep(SLEEP_BETWEEN_BATCH)

    # zapisz cache (żeby przy kolejnym uruchomieniu nie męczyć świeżo zakończonych)
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
