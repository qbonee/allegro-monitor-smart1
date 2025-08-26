import os
import time
import traceback

# ile minut między kolejnymi uruchomieniami
INTERVAL_MINUTES = float(os.getenv("CHECK_INTERVAL_MIN", "30"))  # domyślnie co 30 min

# opcjonalnie: ile razy powtórzyć bez spania zaraz po starcie (na ciepły start)
WARMUP_RUNS = int(os.getenv("WARMUP_RUNS", "1"))

def run_once():
    from main import main  # import tu, żeby ładować aktualny kod po redeployu
    print("=== RUN START ===")
    try:
        main()
        print("=== RUN OK ===")
    except Exception:
        print("=== RUN ERROR ===")
        traceback.print_exc()

def loop():
    # szybkie uruchomienia po starcie (np. 1 raz)
    for _ in range(max(WARMUP_RUNS, 0)):
        run_once()

    # stała pętla co INTERVAL_MINUTES
    while True:
        time.sleep(int(INTERVAL_MINUTES * 60))
        run_once()

if __name__ == "__main__":
    print(f"[worker] start; interval={INTERVAL_MINUTES} min, warmup={WARMUP_RUNS}")
    loop()
