import smtplib
from email.mime.text import MIMEText

def send_alert(alerts):
    sender = "kuba.karbowski455@gmail.com"
    password = "omzn oguj kgeu zfvf"

    recipients = [
        "zamowienia@biobakt.pl",
        "kuba.karbowski455@gmail.com"
    ]

    subject = "ALERT: Zaniżona cena na Allegro"
    body = "\n".join(alerts)

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipients, msg.as_string())
    except Exception as e:
        print("Błąd wysyłania e-maila:", str(e))
