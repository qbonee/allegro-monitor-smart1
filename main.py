# main.py
import os
import time
from typing import List, Dict

from get_price import get_price
from email_alert import send_alert


# ============ Helpers =========================================================

def parse_price(text: str) -> float:
    """'40zł' / '40 zł' / '40,00' -> 40.0"""
    t = (text or "").lower().replace("zł", "").replace("\xa0", "")
    t = t.replace(" ", "").replace(",", ".")
    return float(t)


def load_auctions_from_files(folder: str = ".") -> List[Dict]:
    """
    Obsługuje dwa formaty .txt:

    A) Nagłówek + ID:
       cena minimalna: 129 zł
       1234567890
       9876543210

    B) Wiersze 'ID;MIN':
       1234567890;129
       9876543210;199.90
    """
    auctions: List[Dict] = []
    txt_files = [f for f in os.listdir(folder) if f.endswith(".txt")]

    print(f"[INFO] Znaleziono pliki TXT: {txt_files}")

    for filename in txt_files:
        filepath = os.path.join(folder, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            if not lines:
                continue

            product = filename.replace(".txt", "")

            # Format B: ID;MIN
            if any(";" in ln for ln in lines):
                for ln in lines:
                    if ";" not in ln:
                        continue
                    auction_id, min_price = ln.split(";", 1)
                    auctions.append({
                        "id": auction_id.strip(),
                        "min_price": parse_price(min_price),
                        "product": product,
                    })
                continue

            # Format A: nagłówek + ID
            header = lines[0].lower()
            if header.startswith("cena minimalna:"):
                min_price = parse_price(header.split(":", 1)[1])
                for auction_id in lines[1:]:
                    auctions.append({
                        "id": auction_id.strip(),
                        "min_price": min_price,
                        "product": product,
                    })

        except Exception as e:
            print(f"[WARN] Nie udało się wczytać pliku {filename}: {e}")

    # de-duplikacja
    uniq: List[Dict] = []
    seen = set()
    for a in auctions:
        key = (a["product"], a["id"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(a)

    print(f"[INFO] Wczytano {len(uniq)} aukcji (po deduplikacji).")
    return uniq


# ============ Main ============================================================

def main():
    print("== Start programu ==")
    print(f"[INFO] Katalog roboczy: {os.getcwd()}")

    auctions = load_auctions_from_files(".")
    alerts: List[Dict] = []
    errors: List[str] = []

    for idx, a in enumerate(auctions, 1):
        print(f"[{idx}/{len(auctions)}] Sprawdzam {a['product']} ({a['id']})…")
        try:
            price = get_price(a["id"])
            print(f"    -> cena: {price:.2f} zł (min: {a['min_price']:.2f} zł)")
            if price < a["min_price"]:
                alerts.append({
                    "product": a["product"],
                    "id": a["id"],
                    "price": price,
                    "min": a["min_price"],
                })
        except Exception as e:
            msg = f"{a['product']}: błąd sprawdzania {a['id']}: {e}"
            print("[ERROR]", msg)
            errors.append(msg)

        # throttling – nie bombardujemy Allegro
        time.sleep(0.6)

    if alerts:
        print(f"[INFO] Znaleziono {len(alerts)} zaniżonych aukcji – wysyłam e-mail.")
        send_alert(alerts)
    else:
        print("[INFO] Brak zaniżonych cen – e-mail nie wysłany.")

    if errors:
        print("[BŁĘDY]\n" + "\n".join(errors))


if __name__ == "__main__":
    main()
