import os
import re
from typing import List, Tuple
from playwright.sync_api import sync_playwright

def read_auctions_from_files(folder_path=".") -> List[Tuple[str, float, str]]:
    auctions = []
    for filename in os.listdir(folder_path):
        if filename.endswith(".txt"):
            filepath = os.path.join(folder_path, filename)
            with open(filepath, "r", encoding="utf-8") as file:
                for line in file:
                    parts = line.strip().split(",")
                    if len(parts) >= 2:
                        auction_id = parts[0].strip()
                        try:
                            min_price = float(parts[1].strip())
                            auctions.append((auction_id, min_price, filename))
                        except ValueError:
                            continue
    return auctions

def get_auction_price(page, auction_id: str) -> float:
    url = f"https://allegro.pl/oferta/{auction_id}"
    page.goto(url)
    page.wait_for_timeout(3000)
    
    try:
        price_text = page.locator('[data-testid="offer-price"]').first.text_content()
        if not price_text:
            return None
        price_text = price_text.replace("zł", "").replace(",", ".").strip()
        price_match = re.findall(r"\d+\.\d+", price_text)
        if price_match:
            return float(price_match[0])
    except:
        return None

    return None

def get_price() -> List[str]:
    underpriced = []

    auctions = read_auctions_from_files()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        for auction_id, min_price, filename in auctions:
            price = get_auction_price(page, auction_id)
            if price is not None and price < min_price:
                msg = f"{filename} — {auction_id} za {price} zł (min: {min_price} zł)"
                underpriced.append(msg)

        browser.close()

    return underpriced
