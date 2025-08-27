import os
import time
import importlib
import traceback
import random

INTERVAL_SEC = int(os.getenv("WORKER_INTERVAL_SEC", "10800"))  # domyślnie 3h
JITTER_SEC = int(os.getenv("WORKER_JITTER_SEC", "15"))

def run_once():
    try:
        main_mod = importlib.import_module("main")
        importlib.reload(main_mod)
        main_mod.main()
        return True
    except Exception:
        traceback.print_exc()
        return False

if __name__ == "__main__":
    if JITTER_SEC > 0:
        d = random.randint(0, JITTER_SEC)
        print(f"[worker] jitter start: {d}s")
        time.sleep(d)

    print("== Start workera (pętla nieskończona) ==")
    while True:
        print("== Uruchamiam pojedyncze sprawdzenie aukcji ==")
        ok = run_once()
        print("== Sprawdzenie zakończone ==")
        time.sleep(INTERVAL_SEC)
