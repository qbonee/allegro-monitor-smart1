# email_alert.py
import os
import smtplib
import socket
from datetime import datetime
from email.message import EmailMessage
from typing import Iterable, Dict, Tuple


def _env(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if val is None or not str(val).strip():
        raise RuntimeError(f"Brak wymaganej zmiennej środowiskowej: {name}")
    return val.strip()


def _fmt_alert_line(a: Dict) -> str:
    # oczekuje słownika: {"product", "id", "price", "min"}
    product = a.get("product", "?")
    aid = a.get("id", "?")
    price = a.get("price", None)
    minp = a.get("min", None)
    price_s = f"{price:.2f} zł" if isinstance(price, (int, float)) else str(price)
    min_s = f"{minp:.2f} zł" if isinstance(minp, (int, float)) else str(minp)
    return f"• {product} | aukcja {aid} | cena: {price_s} (min: {min_s})"


def _dedup(alerts: Iterable[Dict]) -> list[Dict]:
    """Usuń duplikaty po (product, id) na wszelki wypadek."""
    seen: set[Tuple[str, str]] = set()
    out: list[Dict] = []
    for a in alerts:
        key = (str(a.get("product", "")), str(a.get("id", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def send_alert(alerts: Iterable[Dict]) -> bool:
    """
    Wyślij maila z listą zaniżonych aukcji.
    Zwraca True/False i wypisuje czytelne logi do stdout (Render).
    """
    alerts = list(alerts)  # na wypadek generatora
    if not alerts:
        print("[MAIL] Brak alertów – nic nie wysyłam.")
        return False

    alerts = _dedup(alerts)
    count = len(alerts)

    try:
        from_addr = _env("GMAIL_USER")
        app_pass = _env("GMAIL_APP_PASSWORD")
        to_raw = _env("ALERT_TO")
        to_list = [addr.strip() for addr in to_raw.split(",") if addr.strip()]

        host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
        port = int(os.getenv("SMTP_PORT", "587"))

        # Zawartość wiadomości
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        hostname = socket.gethostname()

        subject = f"[ALLEGRO] Zaniżone ceny: {count} aukcje/aukcji ({now})"
        header = (
            f"Znaleziono {count} zaniżonych pozycji.\n"
            f"Host: {hostname}\n"
            f"Czas: {now}\n\n"
        )
        body_lines = [header] + [_fmt_alert_line(a) for a in alerts]
        body = "\n".join(body_lines)

        msg = EmailMessage()
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_list)
        msg["Subject"] = subject
        msg.set_content(body)

        # SMTP STARTTLS (Gmail)
        print(f"[MAIL] Łączenie z SMTP {host}:{port}…")
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            if port == 587:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(from_addr, app_pass)
            smtp.send_message(msg)

        print(f"[MAIL] Wysłano mail do: {', '.join(to_list)} (liczba alertów: {count})")
        return True

    except Exception as e:
        print(f"[MAIL][ERROR] Nie udało się wysłać maila: {e}")
        return False
