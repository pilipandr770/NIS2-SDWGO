"""
mailer.py — E-Mail-Versand über Gmail SMTP mit App-Passwort
=============================================================

Nutzt ein Gmail-App-Passwort (16 Zeichen, kein normales Kontopasswort).

Einrichtung des App-Passworts (einmalig, durch den Kontoinhaber selbst,
NICHT durch dieses Programm):
  1. Google-Konto -> Sicherheit -> 2-Faktor-Authentifizierung aktivieren
     (Pflichtvoraussetzung für App-Passwörter)
  2. https://myaccount.google.com/apppasswords aufrufen
  3. App-Passwort für "Mail" generieren -> 16-stelligen Code kopieren
  4. In .env eintragen (siehe SMTP_* Variablen unten)

Umgebungsvariablen (.env):
  SMTP_HOST     = smtp.gmail.com
  SMTP_PORT     = 587
  SMTP_USER     = deine-adresse@gmail.com
  SMTP_APP_PASSWORD = das 16-stellige App-Passwort (OHNE Leerzeichen)
  SMTP_FROM_NAME = Andrii-IT
"""

import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "Andrii-IT")


class MailerNotConfigured(Exception):
    pass


def send_email(to_addr: str, subject: str, body_text: str,
                attachment_path: str | None = None,
                attachment_name: str | None = None) -> None:
    """Sendet eine E-Mail über Gmail SMTP (STARTTLS, Port 587).
    Wirft MailerNotConfigured, wenn SMTP_USER/SMTP_APP_PASSWORD fehlen."""
    if not SMTP_USER or not SMTP_APP_PASSWORD:
        raise MailerNotConfigured(
            "SMTP_USER / SMTP_APP_PASSWORD nicht in .env gesetzt — "
            "Gmail-App-Passwort unter https://myaccount.google.com/apppasswords erzeugen."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((SMTP_FROM_NAME, SMTP_USER))
    msg["To"] = to_addr
    msg.set_content(body_text)

    if attachment_path and os.path.isfile(attachment_path):
        with open(attachment_path, "rb") as f:
            data = f.read()
        name = attachment_name or os.path.basename(attachment_path)
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=name)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_APP_PASSWORD)
        server.send_message(msg)


def is_configured() -> bool:
    return bool(SMTP_USER and SMTP_APP_PASSWORD)
