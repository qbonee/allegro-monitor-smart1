# get_price.py (fragmenty)
from typing import List, Dict, Tuple

def get_price_batch(auctions: List[Dict], progress_every: int = 20) -> Tuple[List[Dict], List[str]]:
    """
    Zwraca (alerts, errors).
    Alerts: list(dict(product, id, price, min))
    """
    alerts: List[Dict] = []
    errors: List[str] = []

    # …inicjalizacja Playwright (browser = p.chromium.launch(...))…

    for i, a in enumerate(auctions, 1):
        try:
            price = get_price_single_with_page(page, a["id"])  # albo Twoja funkcja
            if price < a["min_price"]:
                alerts.append({
                    "product": a["product"],
                    "id": a["id"],
                    "price": price,
                    "min": a["min_price"],
                })
        except Exception as e:
            errors.append(f'{a["product"]} {a["id"]}: {e}')

        if i % progress_every == 0 or i == len(auctions):
            print(f"[PROGRESS] {i}/{len(auctions)} gotowe (alerts: {len(alerts)}, errors: {len(errors)})", flush=True)

    # …zamykanie Playwright…
    return alerts, errors
