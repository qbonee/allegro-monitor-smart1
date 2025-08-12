import os
import smtplib
from email.mime.text import MIMEText

def send_alert(alerts):
    """
    alerts: lista dictów:
      {"product": "...", "id": "...", "price": 123.45, "min": 150.00}
    Wysyłamy e-mail TYLKO, jeśli lista nie jest pusta.
    """

    # --- KONFIGURACJA MAILA (Gmail) -----------------------------------------
    sender = "kuba.karbowski455@gmail.com"               # Twój adres Gmail
    # UŻYJ hasła do aplikacji (Gmail 2FA) lub ustaw w Render → Environment:
    password = os.getenv("GMAIL_APP_PASSWORD", "WPISZ_TUTAJ_HASLO_DO_APLIKACJI")
    recipients = [
        "zamowienia@biobakt.pl",
        "kuba.karbowski455@gmail.com",
    ]
    # ------------------------------------------------------------------------

    if len(alerts) == 1:
        a = alerts[0]
        subject = f"ALERT: cena poniżej minimum – {a['product']} ({a['id']})"
        body = (
            "Wykryto zaniżoną cenę na Allegro:\n\n"
            f"Produkt: {a['product']}\n"
            f"Aukcja:  {a['id']}\n"
            f"Cena:    {a['price']:.2f} zł\n"
            f"Minimum: {a['min']:.2f} zł\n"
        )
    else:
        subject = f"ALERT: {len(alerts)} aukcji poniżej minimum"
        lines = []
        for a in alerts:
            lines.append(
                f"- {a['product']} (aukcja {a['id']}): "
                f"{a['price']:.2f} zł < {a['min']:.2f} zł"
            )
        body = "Wykryto zaniżone ceny na Allegro:\n\n" + "\n".join(lines)

    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipients, msg.as_string())
        print("[MAIL] Wysłano powiadomienie.")
    except Exception as e:
        print("[MAIL] Błąd wysyłania:", e)
