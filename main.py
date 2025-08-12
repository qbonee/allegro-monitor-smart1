import os
from get_price import get_price
from email_alert import send_alert

print("== Start programu ==")
print("Zawartość katalogu roboczego:", os.listdir("."))

if os.path.isdir("aukcje"):
    print("Zawartość folderu aukcje:", os.listdir("aukcje"))
else:
    print("Brak folderu 'aukcje' – czytam pliki z bieżącego katalogu.")


def parse_price(text: str) -> float:
    """Zamienia '40zł', '40 zł', '40,00' -> 40.0"""
    t = text.lower().replace("zł", "").replace(" ", "").replace(",", ".")
    return float(t)

def load_auctions_from_files(folder="."):
    """
    Czyta wszystkie .txt w folderze i obsługuje dwa formaty:
    A) nagłówek 'cena minimalna: 40zł' + ID w kolejnych liniach
    B) linie 'ID;MIN_CENA'
    Zwraca listę słowników: {id, min_price, product}
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

            # Format B: ID;MIN_CENA
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

    print(f"Wczytano {len(auctions)} aukcji.")
    return auctions

def main():
    auctions = load_auctions_from_files(".")
    alerts = []

    for auction in auctions:
        try:
            print(f"Sprawdzam {auction['product']} ({auction['id']}) ...")
            price = get_price(auction["id"])
            if price < auction["min_price"]:
                alerts.append(
                    f"{auction['product']}: Aukcja {auction['id']} ma cenę {price:.2f} zł "
                    f"(min: {auction['min_price']:.2f} zł)"
                )
        except Exception as e:
            alerts.append(
                f"{auction['product']}: Błąd sprawdzania aukcji {auction['id']}: {str(e)}"
            )

    if alerts:
        print(f"Wysyłam e-mail (liczba alertów: {len(alerts)})")
        send_alert(alerts)
    else:
        print("Brak alertów – wszystkie ceny >= minimalnych.")

if __name__ == "__main__":
    main()

