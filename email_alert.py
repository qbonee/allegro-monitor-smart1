import os
import smtplib
from email.mime.text import MIMEText
from typing import List, Dict

def _env(key: str, default: str = "") -> str:
    v = os.getenv(key)
    return v if v is not None else default

def send_alert(alerts: List[Dict]):
    """
    alerts: [{product, id, price, min, url}]
    """
    smtp_host = _env("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(_env("SMTP_PORT", "465"))
    smtp_user = _env("SMTP_USER")               # np. Gmail
    smtp_pass = _env("SMTP_PASS")               # App Password (Gmail)
    mail_from = _env("MAIL_FROM", smtp_user)    # nadawca
    mail_to = [e.strip() for e in _env("MAIL_TO", "").split(",") if e.strip()]
    if not mail_to:
        print("[WARN] MAIL_TO nie ustawione – pomijam wysyłkę.")
        return

    subject = f"ALERT: Zaniżone ceny ({len(alerts)})"
    lines = []
    for a in alerts:
        line = (f"- {a['product']} | {a['id']} | "
                f"{a['price']:.2f} zł (min: {a['min']:.2f} zł)")
        if a.get("url"):
            line += f"\n  {a['url']}"
        lines.append(line)
    body = "Wykryto zaniżone ceny na Allegro:\n\n" + "\n".join(lines)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(mail_to)

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.sendmail(mail_from, mail_to, msg.as_string())

    print(f"[MAIL] Wysłano do: {', '.join(mail_to)}")
