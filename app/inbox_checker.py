"""
inbox_checker.py — Passive Postfach-Prüfung (IMAP) für die Lead-Kaltakquise
==============================================================================

Prüft NUR das eigene Postfach (SMTP_USER via IMAP, gleiches Gmail-App-Passwort
wie für den Versand) auf:
  1. Bounce-Benachrichtigungen (Zustellung fehlgeschlagen) — automatischer
     Abgleich der enthaltenen E-Mail-Adressen gegen versendete Leads.
  2. Echte Antworten von Leads — Absender-Adresse entspricht einem Lead, der
     bereits angeschrieben wurde (kein Bounce-Absender). Enthält die Antwort
     ein Opt-out ("bitte keine weiteren Mails"), wird der Lead nur markiert
     und NICHT konvertiert. Jede andere Antwort gilt als Interesse und wird
     automatisch zum Kunden + Standard-Angebot konvertiert (Zahlungslink per
     Mail) — volle Automatisierung, siehe _auto_convert_lead().

Kein Zugriff auf fremde Postfächer, keine aktive Interaktion mit Absendern —
rein lesend/reagierend auf tatsächlich eingegangene Antworten.
"""

import email
import imaplib
import os
import re
import secrets
from datetime import datetime, timedelta
from email.header import decode_header

from models import db_query, db_execute, create_order_tasks
from payments import PUBLIC_BASE_URL
import mailer

IMAP_HOST = os.environ.get("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@andrii-it.de")

# Standard-Angebot für automatisch konvertierte Leads (Kassensystem-Zielgruppe)
STANDARD_AMOUNT = "100"
STANDARD_SCOPE = ("Vollständige Sicherheitsprüfung (Blackbox-Pentest) — automatisch "
                   "nach Antwort des Leads angelegt, Ziel = eigene Website des Leads")

BOUNCE_SENDER_HINTS = ("mailer-daemon", "postmaster", "mail delivery")
BOUNCE_SUBJECT_HINTS = (
    "delivery status notification", "undelivered mail", "returned to sender",
    "mail delivery failed", "delivery failure", "nicht zustellbar", "unzustellbar",
)
OPT_OUT_HINTS = (
    "abmelden", "keine weiteren", "aus ihrer liste", "aus der liste", "nicht kontaktieren",
    "keine mails mehr", "keine e-mails mehr", "entfernen sie mich", "unsubscribe",
    "remove me", "no longer contact", "stop contacting", "bitte nicht mehr",
)
# Automatische Antworten (Autoresponder, Abwesenheitsnotiz, Ticketsystem-Bestätigung) sind
# KEIN echtes Interesse eines Menschen — dürfen NICHT automatisch konvertiert werden.
AUTOREPLY_HEADER_HINTS = ("auto-replied", "auto-generated", "auto-submitted")
AUTOREPLY_BODY_HINTS = (
    "automatische antwort", "automatisch generiert", "automatisch erstellt",
    "out of office", "out-of-office", "abwesenheitsnotiz", "abwesend bis",
    "derzeit nicht im büro", "currently out of the office", "wir werden uns zeitnah",
    "wir werden uns in kürze", "wir melden uns in kürze", "ihre anfrage wurde erfasst",
    "ticket wurde erstellt", "ticket-nummer", "diese nachricht wurde automatisch",
    "this is an automated", "auto-reply", "autoresponder",
)
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


class InboxNotConfigured(Exception):
    pass


_QUOTE_HEADER_RE = re.compile(
    r"^(On .+ wrote:|Am .+ schrieb .+:|-{2,}\s*Original Message\s*-{2,}|Von:.+Gesendet:)",
    re.IGNORECASE,
)


def _strip_quoted(body: str) -> str:
    """Entfernt zitierten Text (Antwort-Zitat der eigenen Ausgangsmail) — sonst würde
    z.B. der Opt-out-Hinweistext aus unserer eigenen Vorlage, den Mail-Clients beim
    Antworten automatisch zitieren, jede normale Antwort fälschlich als Opt-out
    erkennen. Gibt nur den NEUEN, oben stehenden Text vor dem ersten Zitat zurück."""
    lines = body.splitlines()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(">"):
            break
        if _QUOTE_HEADER_RE.match(stripped):
            break
        new_lines.append(line)
    result = "\n".join(new_lines).strip()
    return result if result else body  # Fallback: falls alles herausgefiltert wurde


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

    result = {"bounces_found": 0, "replies_found": 0, "checked": 0, "converted": 0,
               "opted_out": 0, "autoreplies_found": 0}
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
            auto_submitted_header = (msg.get("Auto-Submitted", "") + msg.get("X-Autoreply", "") +
                                      msg.get("X-Autorespond", "") + msg.get("Precedence", "")).lower()

            is_bounce = any(h in from_header for h in BOUNCE_SENDER_HINTS) or \
                        any(h in subject for h in BOUNCE_SUBJECT_HINTS)

            if is_bounce:
                # Bounce-Bodies zitieren oft die komplette Original-Nachricht (inkl.
                # "From: <eigene Adresse>") — die eigene Adresse ist nie der fehlgeschlagene
                # Empfänger und muss ausgeschlossen werden, sonst False-Positive-Bounce.
                candidates = (set(EMAIL_RE.findall(body)) | set(EMAIL_RE.findall(subject))) \
                             - {SMTP_USER.lower()}
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
                    new_text = _strip_quoted(body)
                    snippet = " ".join(new_text.split())[:300]
                    is_opt_out = any(h in new_text.lower() or h in subject for h in OPT_OUT_HINTS)
                    is_autoreply = (
                        any(h in auto_submitted_header for h in AUTOREPLY_HEADER_HINTS)
                        or any(h in new_text.lower() or h in subject for h in AUTOREPLY_BODY_HINTS)
                    )
                    for lead in by_email[addr_l]:
                        db_execute(
                            "UPDATE leads SET replied_at=?,reply_snippet=? WHERE id=? AND replied_at IS NULL",
                            (datetime.now().isoformat(), snippet, lead["id"]),
                        )
                        result["replies_found"] += 1
                        if is_opt_out:
                            db_execute("UPDATE leads SET status='opted_out' WHERE id=?", (lead["id"],))
                            result["opted_out"] += 1
                        elif is_autoreply:
                            # Kein Mensch hat das gelesen — NICHT konvertieren, nur zur
                            # manuellen Sichtung markiert lassen (bleibt status='emailed').
                            result["autoreplies_found"] = result.get("autoreplies_found", 0) + 1
                        else:
                            try:
                                if _auto_convert_lead(lead["id"], snippet):
                                    result["converted"] += 1
                            except Exception as e:
                                result["conversion_errors"] = result.get("conversion_errors", 0) + 1
                    del by_email[addr_l]

            if not by_email:
                break
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    return result


def _auto_convert_lead(lead_id: int, reply_snippet: str) -> int | None:
    """Legt aus einem interessierten Lead automatisch einen Kunden + Standard-Angebot
    an (Standardpreis/-scope) und sendet sofort den Bestätigungs-/Zahlungslink an den
    Lead. Erst nach Zahlung (bestehender Stripe-Webhook) startet die tatsächliche
    technische Prüfung — hier wird nur der Datensatz angelegt, nichts aktiv getestet.
    Meldet den neuen heißen Lead sofort per Mail an ADMIN_EMAIL (nicht erst im
    Tagesreport). Idempotent: bereits konvertierte Leads werden übersprungen."""
    rows = db_query("SELECT * FROM leads WHERE id=?", (lead_id,))
    if not rows:
        return None
    lead = dict(rows[0])
    if lead.get("client_id") or lead.get("order_id"):
        return lead.get("order_id")

    email_addr = lead["email"]
    client_row = db_query("SELECT id FROM clients WHERE email=?", (email_addr,))
    if client_row:
        client_id = client_row[0]["id"]
    else:
        client_id = db_execute(
            "INSERT INTO clients (company,contact,email,phone,address,notes,created_at) VALUES (?,?,?,?,?,?,?)",
            (lead["company"], lead.get("contact"), email_addr, lead.get("phone"), lead.get("address"),
             "Automatisch angelegt — Lead hat auf Kaltakquise-Mail geantwortet", datetime.now().isoformat()),
        )

    confirm_token = secrets.token_urlsafe(24)
    order_id = db_execute(
        """INSERT INTO orders (client_id,target,amount,scope,notes,status,check_type,confirm_token,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (client_id, lead["domain"], STANDARD_AMOUNT, STANDARD_SCOPE,
         f"Automatisch aus Lead #{lead_id} (Antwort erkannt) — Branche: {lead.get('branche')}",
         "angebot", "audit", confirm_token, datetime.now().isoformat(), datetime.now().isoformat()),
    )
    create_order_tasks(order_id)

    db_execute("UPDATE leads SET status='confirmed',client_id=?,order_id=? WHERE id=?",
               (client_id, order_id, lead_id))

    confirm_url = f"{PUBLIC_BASE_URL}/confirm/{confirm_token}"
    try:
        mailer.send_email(
            to_addr=email_addr,
            subject=f"Ihr Angebot — {lead['company']}",
            body_text=(
                "Sehr geehrte Damen und Herren,\n\n"
                "vielen Dank für Ihre Rückmeldung. Wie angeboten, hier der Link zur "
                f"Bestätigung und Beauftragung der vollständigen Sicherheitsprüfung "
                f"({STANDARD_AMOUNT} EUR):\n\n"
                f"{confirm_url}\n\n"
                f"Mit freundlichen Grüßen\nAndrii Pylypchuk\nAndrii-IT\n{PUBLIC_BASE_URL}"
            ),
        )
    except Exception:
        pass

    try:
        mailer.send_email(
            to_addr=ADMIN_EMAIL,
            subject=f"Heisser Lead: {lead['company']} hat geantwortet",
            body_text=(
                f"{lead['company']} ({email_addr}) hat auf die Kaltakquise-Mail geantwortet:\n\n"
                f"\"{reply_snippet}\"\n\n"
                f"Wurde automatisch als Kunde angelegt und hat einen Bestätigungs-/Zahlungslink "
                f"erhalten (Standard-Angebot {STANDARD_AMOUNT} EUR).\n"
                f"Auftrag ansehen (Login nötig): {PUBLIC_BASE_URL}/orders/{order_id}"
            ),
        )
    except Exception:
        pass

    return order_id
