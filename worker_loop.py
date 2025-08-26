# worker_loop.py
import os, time
from main import main

LOOP_INTERVAL = int(os.getenv("LOOP_INTERVAL", "900"))  # co 15 min (zmienisz w ENV)
HEARTBEAT_EVERY = int(os.getenv("HEARTBEAT_EVERY", "60"))  # co 60 s

def run_once():
    print("== Uruchamiam pojedyncze sprawdzenie aukcji ==", flush=True)
    t0 = time.time()
    try:
        main()  # w środku dodamy więcej logów
    finally:
        dt = time.time() - t0
        print(f"[INFO] Sprawdzenie zakończone w {dt:.1f}s", flush=True)

def loop_forever():
    print("== Start workera (pętla nieskończona) ==", flush=True)
    next_hb = time.time() + HEARTBEAT_EVERY
    while True:
        run_once()
        t_end = time.time() + LOOP_INTERVAL
        while time.time() < t_end:
            if time.time() >= next_hb:
                left = int(t_end - time.time())
                print(f"[HB] Czekam do następnego cyklu… {left}s", flush=True)
                next_hb += HEARTBEAT_EVERY
            time.sleep(1)

if __name__ == "__main__":
    # jeśli używasz worker-only, odpal pętlę:
    loop_forever()
