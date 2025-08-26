import os
import time
from get_price import get_price
from email_alert import send_alert

# ===== Helpers ===============================================================

def parse_price(text: str) -> float:
    t = (text or "").lower().replace("zł", "").replace(" ", "").replace(",", ".")
    return float(t)

def load_auctions_from_files(folder: str = "."):
    auctions = []
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
                continue

            header = lines[0].lower()
            if header.startswith("cena minimalna:"):
                min_price = parse_price(header.split(":", 1)[1])
                for auction_id in lines[1:]:
                    auctions.append({
                        "id": auction_id.strip(),
                        "min_price": min_price,
                        "product": product
                    })
        except Exception as e:
            print(f"[WARN] Nie udało się wczytać pliku {filename}: {e}")
    return auctions

# ===== Main ==================================================================
def main():
    print("== Start programu ==")
    auctions = load_auctions_from_files(".")
    print(f"Wczytano {len(auctions)} aukcji do sprawdzenia.")
    ...
