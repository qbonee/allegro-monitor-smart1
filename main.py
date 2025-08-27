import os
import time
import importlib
from typing import List, Dict

# ===== Helpers ===============================================================

def parse_price(text: str) -> float:
    """'40zł' / '40 zł' / '40,00' -> 40.0"""
    t = (text or "").lower().replace("zł", "").replace(" ", "").replace(",", ".")
    return float(t)

def load_auctions_from_files(folder: str = ".") -> List[Dict]:
    """
    A) Nagłówek + ID:
       cena minimalna: 129 zł
       1234567890
       9876543210

    B) Wiersze 'ID;MIN':
       1234567890;129
       9876543210;199.90
    """
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

    # de-duplikacja
    seen = set()
    uniq: List[Dict] = []
    for a in auctions:
        key = (a["product"], a["id"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(a)
    return uniq

def _chunk(lst: List[Dict], n: int) -> List[List[Dict]]:
    return [lst[i:i+n] for i in range(0, len(lst), n)]

# ===== Main ==================================================================

def main():
    print("== Start programu (main.py) ==")

    # wymuszamy batch – to jest krytyczne dla szybkości
    try:
        gp = importlib.import_module("get_price")
        get_price_batch = getattr(gp, "get_price_batch")
    except Exception as e:
        print(f"[FATAL] Brak get_price_batch w get_price.py ({e})")
        raise

    auctions = load_auctions_from_files(".")
    total = len(auctions)
    print(f"[INFO] Wczytano {total} wpisów .txt")
    if total == 0:
        print("[INFO] Nic do sprawdzenia.")
        return

    alerts: List[Dict] = []
    errors: List[str] = []

    BATCH_SIZE = int(os.getenv("BATCH_SIZE", "25"))
    SLEEP_BETWEEN_BATCH = float(os.getenv("SLEEP_BETWEEN_BATCH", "0.5"))

    chunks = _chunk(auctions, BATCH_SIZE)
    all_batches = len(chunks)
    print(f"[INFO] Tryb BATCH: {all_batches} partii po maks {BATCH_SIZE} aukcji")

    processed = 0
    for i, chunk in enumerate(chunks, 1):
        t0 = time.time()
        results, errs = get_price_batch(chunk)  # type: ignore
        dt = time.time() - t0

        if errs:
            errors.extend(errs)

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
        print(f"[PROGRESS] Batch {i}/{all_batches} OK w {dt:.1f}s — przetworzono {processed}/{total}")
        time.sleep(SLEEP_BETWEEN_BATCH)

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
