import os
import time
import importlib
from typing import List, Dict, Callable


# ===== Helpers ===============================================================

def parse_price(text: str) -> float:
    """'40zł' / '40 zł' / '40,00' -> 40.0"""
    t = (text or "").lower().replace("zł", "").replace(" ", "").replace(",", ".")
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
    seen = set()
    uniq: List[Dict] = []
    for a in auctions:
        key = (a["product"], a["id"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(a)

    return uniq


def _resolve_get_price() -> Callable[[str], float]:
    """
    Bezpiecznie ładujemy moduł get_price.
    - Jeśli jest funkcja get_price(auction_id) -> float, używamy jej.
    - Jeśli jest tylko get_price_batch(auctions) -> (results, errors),
      tworzymy lekki adapter.
    """
    try:
        mod = importlib.import_module("get_price")
    except Exception as e:
        raise ImportError(f"[FATAL] Nie mogę zaimportować modułu 'get_price': {e}") from e

    if hasattr(mod, "get_price") and callable(getattr(mod, "get_price")):
        print("[INFO] Używam get_price.get_price()")
        return getattr(mod, "get_price")

    if hasattr(mod, "get_price_batch") and callable(getattr(mod, "get_price_batch")):
        print("[INFO] Używam adaptera do get_price.get_price_batch()")

        def _adapter(auction_id: str) -> float:
            # Tworzymy minimalny obiekt aukcji
            auctions = [{"id": auction_id, "min_price": 0.0, "product": ""}]
            results, errs = mod.get_price_batch(auctions)  # type: ignore[attr-defined]
            if errs:
                # jeśli batch zwróci błąd dla jednej aukcji – sygnalizujemy wyjątek
                raise RuntimeError(errs[0])
            # zakładamy results[0]["price"]
            return float(results[0]["price"])

        return _adapter

    raise ImportError(
        "[FATAL] W 'get_price.py' nie znaleziono ani funkcji 'get_price', ani 'get_price_batch'. "
        "Upewnij się, że plik /app/get_price.py je definiuje i nie ma importów kołowych."
    )


# ===== Main ==================================================================

def main():
    print("== Start programu (main.py) ==")

    # leniwe i odporne ładowanie get_price
    try:
        get_price = _resolve_get_price()
    except Exception as e:
        print(str(e))
        raise

    auctions = load_auctions_from_files(".")
    print(f"[INFO] Wczytano {len(auctions)} wpisów .txt")

    alerts: List[Dict] = []
    errors: List[str] = []

    for idx, a in enumerate(auctions, 1):
        try:
            price = get_price(a["id"])
            if price < a["min_price"]:
                alerts.append({
                    "product": a["product"],
                    "id": a["id"],
                    "price": float(price),
                    "min": float(a["min_price"]),
                })
        except Exception as e:
            errors.append(f"{a['product']}: Błąd sprawdzania aukcji {a['id']}: {e}")

        time.sleep(0.6)  # throttling

    if alerts:
        print(f"[INFO] Znaleziono {len(alerts)} zaniżonych aukcji – wysyłam e-mail…")
        # import lokalny, żeby uniknąć potencjalnych cykli importu na starcie
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
