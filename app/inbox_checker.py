"""
inbox_checker.py — Passive Postfach-Prüfung (IMAP) für die Lead-Kaltakquise
==============================================================================

Prüft NUR das eigene Postfach (SMTP_USER via IMAP, gleiches Gmail-App-Passwort
wie für den Versand) auf:
  1. Bounce-Benachrichtigungen (Zustellung fehlgeschlagen) — automatischer
     Abgleich der enthaltenen E-Mail-Adressen gegen versendete Leads.
  2. Echte Antworten von Leads — Absender-Adresse entspricht einem Lead, der
     bereits angeschrieben wurde (kein Bounce-Absender).

Kein Zugriff auf fremde Postfächer, keine aktive Interaktion mit Absendern —
rein lesend, zur Status-Pflege der eigenen Lead-Liste.
"""

import email
import imaplib
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header

from models import db_query, db_execute

IMAP_HOST = os.environ.get("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")

BOUNCE_SENDER_HINTS = ("mailer-daemon", "postmaster", "mail delivery")
BOUNCE_SUBJECT_HINTS = (
    "delivery status notification", "undelivered mail", "returned to sender",
    "mail delivery failed", "delivery failure", "nicht zustellbar", "unzustellbar",
)
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


class InboxNotConfigured(Exception):
    pass


def _decode(value: str) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _extract_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    continue
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                    return re.sub(r"<[^>]+>", " ", html)
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return ""


def check_inbox(lookback_days: int = 2) -> dict:
    """Prüft die letzten `lookback_days` Tage im Posteingang auf Bounces/Antworten
    zu bereits versendeten Leads. Gibt {"bounces_found", "replies_found", "checked"}
    zurück. Idempotent — bereits erkannte Leads (bounced_at/replied_at gesetzt)
    werden nicht erneut verarbeitet."""
    if not SMTP_USER or not SMTP_APP_PASSWORD:
        raise InboxNotConfigured("SMTP_USER / SMTP_APP_PASSWORD nicht gesetzt")

    sent_leads = db_query(
        "SELECT id,company,email FROM leads WHERE status='emailed' "
        "AND bounced_at IS NULL AND replied_at IS NULL AND email IS NOT NULL"
    )
    by_email = {}
    for l in sent_leads:
        by_email.setdefault(l["email"].lower(), []).append(l)

    result = {"bounces_found": 0, "replies_found": 0, "checked": 0}
    if not by_email:
        return result

    since = (datetime.now() - timedelta(days=max(1, lookback_days))).strftime("%d-%b-%Y")
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    try:
        conn.login(SMTP_USER, SMTP_APP_PASSWORD)
        conn.select("INBOX")
        _typ, data = conn.search(None, f'(SINCE "{since}")')
        ids = data[0].split()
        # Zusätzliche Obergrenze als Sicherheitsnetz, auch bei sehr vielen Mails im Zeitraum
        ids = ids[-300:]

        for msg_id in ids:
            _typ, msg_data = conn.fetch(msg_id, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            result["checked"] += 1

            from_header = _decode(msg.get("From", "")).lower()
            subject = _decode(msg.get("Subject", "")).lower()
            body = _extract_body(msg)

            is_bounce = any(h in from_header for h in BOUNCE_SENDER_HINTS) or \
                        any(h in subject for h in BOUNCE_SUBJECT_HINTS)

            if is_bounce:
                candidates = set(EMAIL_RE.findall(body)) | set(EMAIL_RE.findall(subject))
                for addr in candidates:
                    addr_l = addr.lower()
                    if addr_l in by_email:
                        for lead in by_email[addr_l]:
                            db_execute("UPDATE leads SET status='bounced',bounced_at=? WHERE id=? AND bounced_at IS NULL",
                                       (datetime.now().isoformat(), lead["id"]))
                            result["bounces_found"] += 1
                        del by_email[addr_l]
                continue

            from_addr_m = EMAIL_RE.search(from_header)
            if from_addr_m:
                addr_l = from_addr_m.group(0).lower()
                if addr_l in by_email:
                    snippet = " ".join(body.split())[:300]
                    for lead in by_email[addr_l]:
                        db_execute(
                            "UPDATE leads SET replied_at=?,reply_snippet=? WHERE id=? AND replied_at IS NULL",
                            (datetime.now().isoformat(), snippet, lead["id"]),
                        )
                        result["replies_found"] += 1
                    del by_email[addr_l]

            if not by_email:
                break
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    return result
