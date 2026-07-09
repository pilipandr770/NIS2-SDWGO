"""
payments.py — Stripe Checkout für Angebots-Bestätigung durch den Kunden
==========================================================================

Ablauf:
  1. Kunde erhält per E-Mail einen personalisierten Link: /confirm/<token>
  2. Kunde sieht dort NUR sein eigenes Angebot (Zielobjekt, Betrag, Scope)
     und bestätigt per Checkbox, dass er Eigentümer/Berechtigter der
     genannten Domain ist.
  3. Klick auf "Jetzt bezahlen" erzeugt eine Stripe-Checkout-Session
     (Kreditkartendaten werden NUR von Stripe verarbeitet, nie von diesem
     Server gesehen oder gespeichert).
  4. Nach erfolgreicher Zahlung sendet Stripe einen Webhook -> Order wird
     als 'paid' markiert -> die passende Prüfung (Audit oder
     Kassensystem-Check) wird automatisch gestartet.
  5. Der fertige Bericht wird NICHT automatisch versendet — er wartet auf
     manuelle Freigabe/Versand durch den Admin (siehe app.py send_report).

Umgebungsvariablen (.env):
  STRIPE_SECRET_KEY      = sk_live_... oder sk_test_...
  STRIPE_WEBHOOK_SECRET  = whsec_...
  PUBLIC_BASE_URL        = https://deine-domain.de
"""

import os

try:
    import stripe
    HAS_STRIPE = True
except ImportError:
    HAS_STRIPE = False

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:5000")

if HAS_STRIPE and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


class PaymentsNotConfigured(Exception):
    pass


def create_checkout_session(order: dict) -> str:
    """Erstellt eine Stripe-Checkout-Session für den Auftrag und gibt die
    Checkout-URL zurück, zu der der Kunde weitergeleitet wird."""
    if not HAS_STRIPE or not STRIPE_SECRET_KEY:
        raise PaymentsNotConfigured(
            "STRIPE_SECRET_KEY nicht konfiguriert oder 'stripe' Paket fehlt "
            "(pip install stripe)."
        )

    amount_eur = float(str(order["amount"]).replace(",", "."))
    amount_cents = int(round(amount_eur * 100))

    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "eur",
                "unit_amount": amount_cents,
                "product_data": {
                    "name": f"Sicherheitsprüfung — {order['company']}",
                    "description": (order.get("scope") or "")[:500],
                },
            },
            "quantity": 1,
        }],
        customer_email=order["email"],
        client_reference_id=str(order["id"]),
        metadata={"order_id": str(order["id"])},
        success_url=f"{PUBLIC_BASE_URL}/confirm/{order['confirm_token']}?paid=1",
        cancel_url=f"{PUBLIC_BASE_URL}/confirm/{order['confirm_token']}?paid=0",
    )
    return session.url


def verify_webhook(payload: bytes, sig_header: str) -> dict:
    """Verifiziert die Stripe-Webhook-Signatur. Wirft bei Fehler eine Exception."""
    if not STRIPE_WEBHOOK_SECRET:
        raise PaymentsNotConfigured("STRIPE_WEBHOOK_SECRET nicht konfiguriert.")
    return stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)


def is_configured() -> bool:
    return bool(HAS_STRIPE and STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET)
