import os
from typing import List, Dict

from email_alert import send_alert
from get_price import get_price_batch

# Pliki .txt z numerami aukcji i minimami leżą w katalogu głównym repo (".").

def parse_price(text: str) -> float:
    t = (text or "").lower().replace("zł", "").replace("\u00a0", " ")
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

            # Format B: ID;MIN
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

            # Format A: nagłówek + ID
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

    # de-duplikacja
    seen = set(); uniq: List[Dict] = []
    for a in auctions:
        key = (a["product"], a["id"])
        if key in seen: continue
        seen.add(key); uniq.append(a)
    return uniq

def main():
    auctions = load_auctions_from_files(".")
    print(f"[INFO] Wczytano {len(auctions)} wpisów .txt")

    alerts: List[Dict] = []
    errors: List[str] = []

    if auctions:
        results, errs = get_price_batch(auctions)
        errors.extend(errs)
        for a, price in results:
            if price is None:
                continue
            if price < a["min_price"]:
                alerts.append({
                    "product": a["product"],
                    "id": a["id"],
                    "price": price,
                    "min": a["min_price"],
                    "url": f"https://allegro.pl/oferta/{a['id']}",
                })

    if alerts:
        print(f"[INFO] ALERTY: {len(alerts)} – wysyłam e-mail.")
        send_alert(alerts)
    else:
        print("[INFO] Brak zaniżonych cen.")

    if errors:
        print("[BŁĘDY]\n" + "\n".join(errors))

if __name__ == "__main__":
    main()
