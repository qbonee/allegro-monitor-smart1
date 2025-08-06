import smtplib
from email.mime.text import MIMEText
from get_price import get_price

# Funkcja do wysyłki maila
def send_email(body: str):
    recipients = ["zamowienia@biobakt.pl", "kuba.karbowski455@gmail.com"]
    sender = "kuba.karbowski455@gmail.com"  # <- Ustaw adres nadawcy (Gmail najlepiej)
    password = "vfnv resn xqrb fuac"  # <- Hasło aplikacji (nie zwykłe hasło do Gmaila!)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "📉 Alert cenowy Allegro – wykryto zaniżoną cenę!"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())

# Główna logika
if __name__ == "__main__":
    print("🔍 Sprawdzam ceny...")
    underpriced_auctions = get_price()

    if underpriced_auctions:
        email_body = "Wykryto oferty z ceną poniżej ustalonego minimum:\n\n"
        email_body += "\n".join(underpriced_auctions)
        print("📬 Wysyłam e-mail...")
        send_email(email_body)
        print("✅ E-mail został wysłany!")
    else:
        print("✅ Wszystkie ceny są poprawne.")
