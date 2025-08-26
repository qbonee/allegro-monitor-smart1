# main.py (fragmenty istotne)
from get_price import get_price_batch  # jeśli masz wersję batchową; jeśli nie, zostaw pojedyncze

def main():
    auctions = load_auctions_from_files(".")
    n = len(auctions)
    print(f"[INFO] Wczytano {n} wpisów .txt", flush=True)
    if n == 0:
        return

    print("[INFO] Start batch…", flush=True)
    t0 = time.time()
    results, errors = get_price_batch(auctions, progress_every=20)  # patrz niżej
    dt = time.time() - t0
    print(f"[INFO] Batch zakończony w {dt:.1f}s", flush=True)

    alerts = results  # jeśli get_price_batch zwraca gotowe alerty
    if alerts:
        print(f"[INFO] Znaleziono alerty: {len(alerts)} – wysyłam email…", flush=True)
        ok = send_alert(alerts)
        print(f"[MAIL] status wysyłki: {'OK' if ok else 'FAIL'}", flush=True)
    else:
        print("[INFO] Brak zaniżonych cen.", flush=True)

    if errors:
        print(f"[WARN] Błędów: {len(errors)}", flush=True)
        for e in errors[:10]:
            print(f"[ERR] {e}", flush=True)
        if len(errors) > 10:
            print(f"[WARN] (+{len(errors)-10} dalszych…)", flush=True)
