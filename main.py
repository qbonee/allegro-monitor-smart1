import os
from get_price import get_price
from email_alert import send_alert

# --- pomocnicze --------------------------------------------------------------

def parse_price(text: str) -> float:
    """
    Zamienia '40zł', '40 zł', '40,00' -> 40.0
    """
    t = text.lower().replace("zł", "").replace(" ", "").replace(",", ".")
    return float(t)

def load_auctions_from_files(folder: str = "."):
    """
    Czyta wszystkie .txt w folderze i obsługuje dwa formaty:

    A) Nagłówek + ID:
       cena minimalna: 129 zł
       1234567890
       9876543210

    B) Wiersze 'ID;MIN':
       1234567890;129
       9876543210;199.90

    Zwraca listę: [{id, min_price, product}, ...]
    """
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

            # Format B: "ID;MIN"
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

    return auctions

# --- główna logika -----------------------------------------------------------

def main():
    print("== Start programu ==")
    print("Pliki w katalogu roboczym:", os.listdir("."))

    auctions = load_auctions_from_files(".")
    print(f"Wczytano {len(auctions)} aukcji do sprawdzenia.")

    alerts = []   # tylko realne zaniżenia cen
    errors = []   # trafią do logów, NIE do e-maila

    for a in auctions:
        try:
            price = get_price(a["id"])
            # DEBUG: odkomentuj jeśli chcesz widzieć każdą decyzję
            # print(f"[DEBUG] {a['product']} ({a['id']}): cena={price:.2f} min={a['min_price']:.2f}")

            if price < a["min_price"]:
                alerts.append({
                    "product": a["product"],
                    "id": a["id"],
                    "price": price,
                    "min": a["min_price"],
                })
        except Exception as e:
            errors.append(f"{a['product']}: Błąd sprawdzania aukcji {a['id']}: {e}")

    if alerts:
        print(f"Znaleziono {len(alerts)} zaniżonych aukcji – wysyłam e-mail…")
        send_alert(alerts)
    else:
        print("Brak zaniżonych cen.")

    if errors:
        print("[BŁĘDY]\n" + "\n".join(errors))

if __name__ == "__main__":
    main()
