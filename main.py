print("Zawartość katalogu roboczego:")
print(os.listdir("."))
print("Zawartość folderu aukcje:")
print(os.listdir("aukcje"))

import os
from get_price import get_price
from email_alert import send_alert


def load_auctions_from_files(folder="."):
    auctions = []
    for filename in os.listdir(folder):
        if filename.endswith(".txt"):
            filepath = os.path.join(folder, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split(";")
                    if len(parts) == 2:
                        auction_id, min_price = parts
                        auctions.append({
                            "id": auction_id.strip(),
                            "min_price": float(min_price.strip()),
                            "product": filename.replace(".txt", "")
                        })
    return auctions

def main():
    auctions = load_auctions_from_files()
    alerts = []

    for auction in auctions:
        try:
            price = get_price(auction["id"])
            if price < auction["min_price"]:
                alerts.append(f'{auction["product"]}: Aukcja {auction["id"]} ma cenę {price:.2f} zł (min: {auction["min_price"]:.2f} zł)')
        except Exception as e:
            alerts.append(f'{auction["product"]}: Błąd sprawdzania aukcji {auction["id"]}: {str(e)}')

    if alerts:
        send_alert(alerts)

if __name__ == "__main__":
    main()




