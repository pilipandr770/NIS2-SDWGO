# NIS2Audit — Automated Security Audit & Compliance Platform

**Andrii-IT** · IT-Sicherheitsdienstleistungen · Frankfurt am Main

Automatisierte Plattform für NIS2/DSGVO-Compliance-Prüfungen mit
KI-gestützter Schwachstellenanalyse, passivem Kassensystem-Check,
Stripe-Zahlungsabwicklung und automatisiertem PDF-Reporting.

---

## Inhaltsverzeichnis

- [Funktionsübersicht](#funktionsübersicht)
- [Architektur / Tech-Stack](#architektur--tech-stack)
- [Der komplette Ablauf (Sales-to-Report Pipeline)](#der-komplette-ablauf-sales-to-report-pipeline)
- [Rechtliche Leitplanken](#rechtliche-leitplanken-wichtig)
- [Installation](#installation)
- [Environment-Variablen](#environment-variablen)
- [Projektstruktur](#projektstruktur)
- [Datenbankschema (orders-Pipeline)](#datenbankschema-orders-pipeline)
- [Sicherheit der Plattform selbst](#sicherheit-der-plattform-selbst)
- [Betrieb / Wartung](#betrieb--wartung)

---

## Funktionsübersicht

| Bereich | Beschreibung |
|---|---|
| **Web-/NIS2-Audit** | KI-Agent (Claude) orchestriert Nmap, Nuclei, httpx, subfinder, testssl.sh, Nikto gegen die vom Kunden autorisierte Domain |
| **Kassensystem-Check** | Rein **passive** Prüfung: Shodan-Indexabfrage + CVE-Abgleich (NVD/CIRCL), keine aktive Verbindung zum Zielsystem |
| **Angebot & Vertrag** | PDF-Generierung (WeasyPrint), individuelle Angebotsnummer, Leistungsbeschreibung |
| **Kunden-Self-Service** | Personalisierte Bestätigungsseite (`/confirm/<token>`) — Kunde bestätigt Berechtigung und bezahlt |
| **Zahlungsabwicklung** | Stripe Checkout — Kartendaten werden ausschließlich von Stripe verarbeitet, nie vom eigenen Server gesehen |
| **Automatischer Start** | Nach Zahlungseingang (Stripe-Webhook) startet die vereinbarte Prüfung automatisch im Hintergrund |
| **Manuelle Freigabe** | Der fertige Bericht wird **niemals automatisch versendet** — er wartet im Dashboard auf manuelle Prüfung und Freigabe |
| **E-Mail-Versand** | Gmail SMTP mit App-Passwort (16-stellig, kein Kontopasswort) für Angebots- und Berichtsversand |
| **Dashboard mit Pipeline** | Trichter-Ansicht (Angebot → Bezahlt → Läuft → Review nötig → Versendet) mit klickbaren Status-Filtern |
| **Compliance-Checkliste** | 26 NIS2/DSGVO-Aufgaben pro Kunde mit Fortschrittsverfolgung |

---

## Architektur / Tech-Stack

**Backend**
- Python 3.12 / Flask 3.x
- SQLite (Datei-DB, ein File pro Deployment)
- Flask-WTF (CSRF-Schutz), Flask-Limiter (Rate-Limiting)

**KI / Automatisierung**
- Anthropic Claude API (`app/agent.py`) — orchestriert die aktiven Web-Sicherheitstools und formuliert Findings in deutscher Sprache
- Modell konfigurierbar über `ANTHROPIC_MODEL` (Standard: `claude-sonnet-4-5`)

**Aktive Sicherheitstools** (nur gegen vertraglich autorisierte Web-Ziele, `app/agent.py`)
- Nmap (Portscan)
- Nuclei (CVE/Template-Scan)
- httpx (HTTP-Probing, Tech-Stack-Erkennung)
- subfinder (Subdomain-Enumeration)
- testssl.sh (TLS/SSL-Konfiguration)
- Nikto (Web-Server-Schwachstellenscan)
- eigene DNS-/Cookie-Checks (SPF, DMARC, DKIM, DNSSEC)

**Passiver Kassensystem-Check** (`app/kassen_check.py`) — sendet **keine** Anfrage an das Zielsystem
- Shodan API (`shodan.io`) — liest bereits indexierte, öffentlich bekannte Hostdaten
- NVD API 2.0 (`nvd.nist.gov`) — offizielle CVE-Datenbank, primäre Quelle
- CIRCL CVE-Search (`cve.circl.lu`) — Fallback ohne API-Key

**Zahlungen** (`app/payments.py`)
- Stripe Checkout (dynamische Preise pro Angebot, `stripe` Python-SDK)
- Stripe Webhooks (`checkout.session.completed`) mit Signaturverifikation

**E-Mail** (`app/mailer.py`)
- Gmail SMTP (STARTTLS, Port 587) mit App-Passwort
- PDF-Anhänge (Angebot/Bericht) direkt aus `reports/`

**PDF-Generierung** (`app/pdf_generator.py`)
- WeasyPrint (echtes PDF), HTML-Fallback falls WeasyPrint nicht verfügbar
- CVSS-Scoring, DSGVO-/NIS2-Referenzmapping

**Frontend**
- Server-seitig gerenderte Jinja2-Templates, kein SPA-Framework
- Eigenes CSS-Designsystem (`static/css/style.css`), Dark-UI

**Infrastruktur**
- Docker Multi-Stage-Build (Python-Base + kompilierte Go-Security-Tools)
- nginx als Reverse-Proxy mit TLS-Terminierung und Security-Headers
- docker-compose für Orchestrierung

---

## Der komplette Ablauf (Sales-to-Report Pipeline)

Der Kundenfund selbst (Recherche, Ansprache) erfolgt **manuell** außerhalb
dieses Systems. Ab dem Punkt "Kunde ist interessiert" übernimmt die
Plattform:

```
1. Kunde manuell anlegen           → /clients/new
2. Angebot erstellen               → /angebot/new
                                      - Art der Prüfung wählen (Web-Audit / Kassen-Check)
                                      - Zielobjekt (Domain/IP), Betrag (Standard: 100 EUR)
                                      - Angebot-PDF wird generiert
                                      - eindeutiger confirm_token wird erzeugt
3. Angebot per E-Mail senden       → Button "✉ Angebot senden"
                                      - E-Mail enthält Link zu /confirm/<token>
4. Kunde bestätigt + bezahlt       → öffentliche Seite /confirm/<token> (kein Login)
                                      - Kunde sieht NUR sein eigenes Angebot
                                      - Checkbox: "Ich bin zur Beauftragung berechtigt"
                                      - Weiterleitung zu Stripe Checkout
5. Zahlung eingegangen             → Stripe-Webhook /webhook/stripe
                                      - Signatur wird verifiziert
                                      - Order-Status → 'paid'
                                      - passende Prüfung startet AUTOMATISCH im Hintergrund
6. Prüfung läuft                   → Order-Status → 'running'
                                      - Web-Audit: KI-Agent mit Sicherheitstools (aktiv, nur autorisierte Domain)
                                      - Kassen-Check: Shodan + CVE-Abgleich (passiv)
7. Prüfung abgeschlossen           → Order-Status → 'review'
                                      - erscheint im Dashboard unter "⏳ Wartet auf deine Freigabe"
                                      - Bericht wird NICHT automatisch versendet
8. Manuelle Prüfung durch Admin    → /orders/<id> — Findings durchsehen, ggf. anpassen
9. Bericht generieren              → Button "📄 Compliance-Bericht generieren"
10. Bericht versenden              → Button "✉ Bericht senden" (manuell, nach Sichtprüfung)
                                      - Order-Status → 'completed'
```

**Wichtigstes Prinzip:** Schritte 1–7 sind automatisierbar. Schritt 8–10
sind bewusst **niemals automatisch** — jeder Bericht wird von einem
Menschen gesehen, bevor er den Kunden erreicht.

---

## Rechtliche Leitplanken (wichtig)

Diese Plattform ist ausschließlich für **vertraglich autorisierte**
Prüfungen konzipiert (§202a-c StGB beachten):

- Der Kunde muss über die Bestätigungsseite explizit erklären, zur
  Beauftragung berechtigt zu sein (Eigentümer/rechtmäßig Verfügungsberechtigter
  der genannten Domain/IP).
- Der **Kassensystem-Check ist rein passiv** — er stellt keine einzige
  Verbindung zum Zielsystem her, sondern liest ausschließlich bereits
  öffentlich indexierte Daten (Shodan) und öffentliche CVE-Datenbanken.
  Details siehe Docstring in `app/kassen_check.py`.
- Der **Web-Audit ist aktiv** (echte Portscans etc.) und darf ausschließlich
  gegen Ziele laufen, die im unterschriebenen Angebot als Prüfungsziel
  genannt sind.
- Vor produktivem Einsatz sollten die Textbausteine für Angebot,
  Leistungsbeschreibung und Haftungsausschluss von einem Rechtsanwalt für
  IT-Recht geprüft werden (siehe `kassen_check_textbausteine.md`, sofern
  im Projektverzeichnis vorhanden).

---

## Installation

### 1. Repository vorbereiten

```bash
cd NIS2-SDWGO-main
```

### 2. Environment konfigurieren

```bash
cp .env.example .env
```

Alle Pflicht- und optionalen Variablen sind in `.env.example`
dokumentiert (siehe auch Tabelle unten).

### 3. TLS-Zertifikat

Für Entwicklung (selbstsigniert):

```bash
chmod +x generate-ssl.sh
./generate-ssl.sh
```

Für Produktion — Let's Encrypt:

```bash
certbot certonly --standalone -d deine-domain.de
cp /etc/letsencrypt/live/deine-domain.de/fullchain.pem ssl/cert.pem
cp /etc/letsencrypt/live/deine-domain.de/privkey.pem ssl/key.pem
```

### 4. Build & Start

```bash
docker-compose up -d --build
```

Erreichbar unter `https://localhost` bzw. der konfigurierten Domain.

### 5. Login

`https://deine-domain/login` mit `ADMIN_EMAIL` / `ADMIN_PASSWORD`.

### 6. Stripe-Webhook registrieren (für automatischen Prüfungsstart)

Im Stripe-Dashboard unter **Developers → Webhooks**:
- Endpoint-URL: `https://deine-domain/webhook/stripe`
- Event: `checkout.session.completed`
- Signing Secret in `.env` als `STRIPE_WEBHOOK_SECRET` eintragen

---

## Environment-Variablen

| Variable | Pflicht | Beschreibung |
|---|---|---|
| `SECRET_KEY` | ✅ | Flask-Session-Secret (`python3 -c "import secrets; print(secrets.token_hex(32))"`) |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | ✅ | Login-Zugangsdaten |
| `ANTHROPIC_API_KEY` | ✅ | Für KI-Audit-Agent — console.anthropic.com |
| `ANTHROPIC_MODEL` | – | Standard: `claude-sonnet-4-5` |
| `DB_PATH` | – | Standard: `/data/nis2audit.db` |
| `HTTPS` | – | `1` aktiviert sichere Session-Cookies |
| `SHODAN_API_KEY` | für Kassen-Check | shodan.io — einmaliger Plan (~$49) reicht für Host-Lookups |
| `NVD_API_KEY` | optional | Erhöht NVD-Rate-Limit — nvd.nist.gov/developers/request-an-api-key |
| `SMTP_HOST` / `SMTP_PORT` | – | Standard: `smtp.gmail.com` / `587` |
| `SMTP_USER` | für E-Mail-Versand | Gmail-Adresse |
| `SMTP_APP_PASSWORD` | für E-Mail-Versand | 16-stelliges App-Passwort — myaccount.google.com/apppasswords (erfordert 2FA) |
| `SMTP_FROM_NAME` | – | Anzeigename im Absender |
| `PUBLIC_BASE_URL` | für Bestätigungslinks | z. B. `https://nis2.andrii-it.de` |
| `STRIPE_SECRET_KEY` | für Zahlungen | dashboard.stripe.com/apikeys |
| `STRIPE_WEBHOOK_SECRET` | für automatischen Start | dashboard.stripe.com/webhooks |

Alle Geheimnisse ausschließlich in `.env` (niemals in `.env.example` oder
Git committen — siehe `.gitignore`). API-Schlüssel, die versehentlich in
Chats, Screenshots oder Tickets geteilt wurden, sollten umgehend neu
ausgestellt werden.

---

## Projektstruktur

```
app/
├── app.py              # Flask-Routen: Auth, Clients, Orders, Pipeline, Webhooks
├── agent.py            # KI-Audit-Agent (aktiv: Nmap/Nuclei/httpx/testssl/Nikto)
├── kassen_check.py      # Passiver Kassensystem-Check (Shodan + CVE, keine Zielverbindung)
├── mailer.py            # Gmail-SMTP-Versand (App-Passwort) mit PDF-Anhang
├── payments.py           # Stripe Checkout + Webhook-Verifikation
├── live_check.py         # Echtzeit-Checks: HTTP-Header, TLS, DNS, Cookies
├── pdf_generator.py       # PDF/HTML-Berichtserstellung (WeasyPrint)
├── models.py              # SQLite-Schema, Migrationen, NIS2-Standardaufgaben
└── requirements.txt        # Python-Abhängigkeiten

templates/
├── dashboard.html          # Pipeline-Trichter, Review-Warteliste, Kurzübersicht
├── orders.html             # Auftragsliste mit klickbaren Status-Filtern
├── order_detail.html        # Einzelauftrag: Aktionen, Findings, Downloads, E-Mail-Versand
├── client_confirm.html      # ÖFFENTLICHE Bestätigungs-/Zahlungsseite (kein Login)
├── angebot_form.html         # Angebot erstellen (inkl. Auswahl Prüfungsart)
├── clients.html / client_form.html / client_detail.html
├── login.html
└── base.html                 # Layout für eingeloggten Bereich

static/css/style.css           # Design-System (Dark-UI, Pipeline, Badges)
nginx.conf                     # Reverse-Proxy, TLS, Security-Headers
Dockerfile                     # Multi-Stage-Build (Python + Go-Security-Tools)
docker-compose.yml              # Service-Orchestrierung
.env.example                    # Alle Umgebungsvariablen dokumentiert
```

---

## Datenbankschema (orders-Pipeline)

Relevante Spalten der Tabelle `orders`:

| Spalte | Bedeutung |
|---|---|
| `check_type` | `'audit'` (aktiver Web-Scan) oder `'kassen'` (passiver Shodan/CVE-Check) |
| `confirm_token` | Eindeutiges, nicht erratbares Token für die öffentliche Bestätigungsseite |
| `paid_at` | Zeitstempel des Zahlungseingangs (gesetzt vom Stripe-Webhook) |
| `status` | Pipeline-Stufe — siehe unten |

**Status-Werte und ihre Bedeutung:**

| Status | Bedeutung |
|---|---|
| `angebot` | Angebot erstellt/gesendet, wartet auf Kundenbestätigung |
| `paid` | Zahlung eingegangen, Prüfung wird gestartet |
| `running` | Prüfung läuft im Hintergrund |
| `review` / `done` / `active` | Prüfung abgeschlossen, wartet auf manuelle Freigabe (im Dashboard zusammengefasst als "Review nötig") |
| `completed` | Bericht manuell geprüft und versendet |
| `failed` | Fehler während der Prüfung — siehe `audit_logs` |

---

## Sicherheit der Plattform selbst

- CSRF-Schutz auf allen Formularen (Flask-WTF) — Ausnahme: `/webhook/stripe`
  (nutzt stattdessen Stripe-Signaturverifikation)
- SSRF-Schutz — private/loopback IPs als Prüfungsziel blockiert (`is_public_target`)
- Rate-Limiting (Login, Zahlungsauslösung)
- Session-Cookies: HttpOnly, SameSite=Lax, Secure (bei `HTTPS=1`)
- nginx Security-Headers: CSP, HSTS, X-Frame-Options, X-Content-Type-Options,
  Referrer-Policy, Permissions-Policy, COOP, CORP
- Admin-Passwort gehasht (Werkzeug pbkdf2:sha256)
- Kundenzugriff auf `/confirm/<token>` ausschließlich über individuelles,
  kryptographisch zufälliges Token — kein Rate-Limit-Bypass auf fremde Aufträge möglich
- Kartendaten werden **nie** vom eigenen Server verarbeitet oder gespeichert (Stripe Checkout)

---

## Betrieb / Wartung

**Code-Update ohne Rebuild** (nur Python-Änderungen):

```bash
docker cp app/app.py nis2audit_v2-nis2audit-1:/app/app/app.py
docker restart nis2audit_v2-nis2audit-1
```

**nginx-Konfiguration aktualisieren:**

```bash
docker cp nginx.conf nis2audit_v2-nginx-1:/etc/nginx/nginx.conf
docker exec nis2audit_v2-nginx-1 nginx -t
docker exec nis2audit_v2-nginx-1 nginx -s reload
```

**API-Schlüssel rotieren** (empfohlen nach jedem versehentlichen Teilen):
- Shodan: account.shodan.io → "Reset API Key"
- NVD: nvd.nist.gov/developers/request-an-api-key (neuer Request)
- Stripe: dashboard.stripe.com/apikeys → Key zurückziehen, neuen erzeugen
- Gmail App-Passwort: myaccount.google.com/apppasswords → altes entfernen, neues erzeugen

---

## Lizenz

Proprietär — Andrii-IT. Alle Rechte vorbehalten.
