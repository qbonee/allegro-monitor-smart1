from playwright.sync_api import sync_playwright

def get_price(auction_id):
    url = f"https://allegro.pl/oferta/{auction_id}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)

        # Pobieramy cenę — typowy selektor Allegro
        price_element = page.query_selector("span[data-testid='price']")
        if not price_element:
            raise Exception("Nie znaleziono ceny na stronie")

        price_text = price_element.inner_text().replace("zł", "").replace(",", ".").strip()
        price = float(price_text.split()[0])
        browser.close()
        return price
