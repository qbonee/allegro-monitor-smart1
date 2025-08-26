import time
from main import main

if __name__ == "__main__":
    while True:
        try:
            print("=== RUN START ===")
            main()
            print("=== RUN DONE ===")
        except Exception as e:
            print("[FATAL] run failed:", e)
        time.sleep(3 * 60 * 60)  # co 3 godziny
