import time
import sys
from main import main

SLEEP_SECS = 600  # 10 minut

def run_once():
    print("== Uruchamiam pojedyncze sprawdzenie aukcji ==", flush=True)
    main()
    print("== Zakończono pojedynczy przebieg ==", flush=True)

if __name__ == "__main__":
    print("== Start workera (pętla nieskończona) ==", flush=True)
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"[BŁĄD WORKERA] {e}", flush=True)
        print(f"== Pauza {SLEEP_SECS//60} minut ==", flush=True)
        sys.stdout.flush()
        time.sleep(SLEEP_SECS)
