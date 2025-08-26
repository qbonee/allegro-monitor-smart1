import time
from main import main

def run_once():
    print("== Uruchamiam pojedyncze sprawdzenie aukcji ==")
    main()
    print("== Sprawdzenie zakończone ==")

def loop_forever():
    while True:
        run_once()
        time.sleep(10800)  # co 3 godziny

if __name__ == "__main__":
    print("== Start workera (pętla nieskończona) ==")
    loop_forever()
