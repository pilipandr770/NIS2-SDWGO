import sqlite3, os
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "/data/nis2audit.db")

# ── Стандартные NIS2 / DSGVO задачи (одинаковые для каждого клиента) ─────────
# (category, title, description, nis2_ref, dsgvo_ref, required)
NIS2_STANDARD_TASKS = [
    # --- Technisch ---
    ("Technisch", "HTTP Security Headers",
     "CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, COOP, CORP prüfen",
     "§30 Abs. 2 Nr. 3 BSIG", "Art. 32 DSGVO", 1),
    ("Technisch", "TLS/SSL Konfiguration",
     "TLS 1.2/1.3, keine veralteten Protokolle (SSLv3/TLS1.0/1.1), starke Cipher-Suites, gültiges Zertifikat, HSTS",
     "§30 Abs. 2 Nr. 3 BSIG", "Art. 32 Abs. 1 DSGVO", 1),
    ("Technisch", "Penetrationstest (OWASP Top 10)",
     "SQL-Injection, XSS, CSRF, IDOR, Broken Authentication, Security Misconfiguration, Sensitive Data Exposure",
     "§30 Abs. 2 Nr. 3 BSIG", "Art. 32 DSGVO", 1),
    ("Technisch", "Schwachstellen-Scan (CVE / Nuclei)",
     "Automatisierter Scan auf bekannte CVEs, Fehlkonfigurationen, veraltete Software-Komponenten",
     "§30 Abs. 2 Nr. 5 BSIG", "Art. 32 DSGVO", 1),
    ("Technisch", "Port-Scan und Netzwerksicherheit",
     "Offene Ports, unnötige Dienste, Firewall-Konfiguration, Netzwerksegmentierung",
     "§30 Abs. 2 Nr. 3 BSIG", "", 1),
    ("Technisch", "MFA und Zugriffsrechte (IAM)",
     "Zwei-Faktor-Authentifizierung aktiv, Least-Privilege-Prinzip, privilegierte Konten gesichert, Offboarding-Prozess",
     "§30 Abs. 2 Nr. 6 BSIG", "Art. 32 Abs. 1 DSGVO", 1),
    ("Technisch", "Verschlüsselung (Data at Rest & Transit)",
     "Datenverschlüsselung im Ruhezustand (AES-256) und beim Transport (TLS). Schlüsselverwaltung dokumentiert.",
     "§30 Abs. 2 Nr. 4 BSIG", "Art. 32 Abs. 1 lit. a DSGVO", 1),
    ("Technisch", "Backup und Wiederherstellung",
     "Datensicherungskonzept vorhanden, regelmäßige Backups getestet, RTO/RPO-Ziele definiert, Offline-Kopie",
     "§30 Abs. 2 Nr. 2 BSIG", "Art. 32 Abs. 1 lit. c DSGVO", 1),
    ("Technisch", "Logging und Monitoring (SIEM)",
     "Zentrales Log-Management, Audit-Trail, Anomalieerkennung, Aufbewahrung min. 12 Monate",
     "§30 Abs. 2 Nr. 7 BSIG", "Art. 25 DSGVO", 1),
    ("Technisch", "Patch-Management",
     "Software-Updates zeitnah eingespielt (<30 Tage kritisch), CVE-Monitoring aktiv, Patch-Prozess dokumentiert",
     "§30 Abs. 2 Nr. 5 BSIG", "Art. 32 DSGVO", 1),
    ("Technisch", "Subdomain-Enumeration und DNS-Sicherheit",
     "Subdomains auf exponierte Dienste geprüft, DNS-Zonenübertragung gesperrt, Dangling-DNS bereinigt",
     "§30 Abs. 2 Nr. 3 BSIG", "", 1),
    # --- Organisatorisch ---
    ("Organisatorisch", "Risikoanalyse und -bewertung",
     "Dokumentierte IT-Risikoanalyse, Schutzbedarfsfeststellung, Risikoregister, jährliche Aktualisierung",
     "§30 Abs. 2 Nr. 1 BSIG", "Art. 32 Abs. 2 DSGVO", 1),
    ("Organisatorisch", "Informationssicherheits-Richtlinie (ISMS)",
     "Schriftliche IS-Richtlinien vorhanden, Verantwortlichkeiten definiert, Freigabeprozess dokumentiert",
     "§30 Abs. 2 BSIG", "", 1),
    ("Organisatorisch", "Incident Response Plan (IRP)",
     "Vorfallsmanagement-Plan dokumentiert, Eskalationspfad definiert, NIS2-Meldepflicht §32 BSIG bekannt (24h/72h/1Monat)",
     "§30 Abs. 2 Nr. 7 / §32 BSIG", "Art. 33 DSGVO", 1),
    ("Organisatorisch", "Business Continuity / Notfallmanagement",
     "BCP/DRP-Dokumentation vorhanden, Notfallplan getestet (min. jährlich), Wiederanlaufplanung",
     "§30 Abs. 2 Nr. 2 BSIG", "Art. 32 Abs. 1 lit. c DSGVO", 1),
    ("Organisatorisch", "Lieferkettensicherheit (Supply Chain)",
     "Dienstleister-Sicherheitsassessment, Sicherheitsanforderungen in Verträgen, Monitoring kritischer Anbieter",
     "§30 Abs. 2 Nr. 8 BSIG", "Art. 28 DSGVO", 1),
    ("Organisatorisch", "Mitarbeiterschulung und Security-Awareness",
     "Security-Awareness-Training (min. jährlich), Phishing-Simulation, Nachweise vorhanden",
     "§30 Abs. 2 Nr. 9 BSIG", "Art. 32 Abs. 4 DSGVO", 1),
    ("Organisatorisch", "Asset-Management (IT-Inventar)",
     "Aktuelles IT-Asset-Inventar (Hard- und Software), Verantwortliche zugewiesen, Lifecycle-Management",
     "§30 Abs. 2 BSIG", "", 1),
    ("Organisatorisch", "Physische Sicherheit und Zutrittskontrollen",
     "Serverräume/Rechenzentren gesichert, Zutrittskontrolle, Risiko durch physischen Zugriff bewertet",
     "§30 Abs. 2 Nr. 3 BSIG", "Art. 32 Abs. 1 DSGVO", 1),
    # --- DSGVO ---
    ("DSGVO", "Datenschutzerklärung (Art. 13 / 14 DSGVO)",
     "Vollständige, aktuelle DSE auf der Website — alle Pflichtangaben, Zweck, Rechtsgrundlage, Betroffenenrechte",
     "", "Art. 13 / 14 DSGVO", 1),
    ("DSGVO", "Verarbeitungsverzeichnis (Art. 30 DSGVO — VVT)",
     "Aktuelles Verzeichnis aller Verarbeitungstätigkeiten mit Zweck, Rechtsgrundlage, Empfänger, Löschfristen",
     "", "Art. 30 DSGVO", 1),
    ("DSGVO", "Auftragsverarbeitungsverträge (AVV / Art. 28)",
     "Gültige AVV mit allen Auftragsverarbeitern und Cloud-Anbietern, TOM-Nachweis",
     "", "Art. 28 DSGVO", 1),
    ("DSGVO", "Cookie-Consent und §25 TTDSG",
     "Rechtskonformer Cookie-Banner, Opt-in für nicht-essenzielle Cookies, Ablehnoption gleichwertig",
     "", "§25 TTDSG / Art. 6 DSGVO", 1),
    ("DSGVO", "Datenschutz-Folgenabschätzung (DSFA / Art. 35)",
     "DSFA für risikoreiche Verarbeitungen durchgeführt und dokumentiert (falls anwendbar)",
     "", "Art. 35 DSGVO", 0),
    ("DSGVO", "Datenschutzbeauftragter (DSB / Art. 37–39)",
     "DSB benannt falls erforderlich, erreichbar, Kontakt auf Website veröffentlicht",
     "", "Art. 37–39 DSGVO", 0),
    ("DSGVO", "Betroffenenrechte (Art. 15–22 DSGVO)",
     "Prozess für Auskunft, Löschung, Berichtigung, Portabilität vorhanden. Fristenkontrolle (30 Tage).",
     "", "Art. 15–22 DSGVO", 1),
]

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def db_query(sql, params=()):
    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def db_execute(sql, params=()):
    conn = get_db()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS clients (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            company    TEXT NOT NULL,
            contact    TEXT,
            email      TEXT NOT NULL UNIQUE,
            phone      TEXT,
            address    TEXT,
            ustid      TEXT,
            notes      TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id   INTEGER NOT NULL REFERENCES clients(id),
            target      TEXT NOT NULL,
            amount      TEXT DEFAULT '1000',
            scope       TEXT,
            notes       TEXT,
            status      TEXT NOT NULL DEFAULT 'angebot',
            job_id      TEXT,
            angebot_pdf TEXT,
            angebot_num TEXT,
            report_pdf  TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS findings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id        INTEGER NOT NULL REFERENCES orders(id),
            title           TEXT NOT NULL,
            description     TEXT,
            severity        TEXT NOT NULL DEFAULT 'info',
            severity_rank   INTEGER DEFAULT 5,
            target          TEXT,
            proof           TEXT,
            impact          TEXT,
            recommendation  TEXT,
            cvss            TEXT,
            dsgvo_article   TEXT,
            tool            TEXT,
            created_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            level    TEXT NOT NULL DEFAULT 'INFO',
            message  TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id    INTEGER NOT NULL REFERENCES orders(id),
            category    TEXT NOT NULL,
            title       TEXT NOT NULL,
            description TEXT,
            nis2_ref    TEXT,
            dsgvo_ref   TEXT,
            required    INTEGER DEFAULT 1,
            done        INTEGER DEFAULT 0,
            notes       TEXT,
            done_at     TEXT
        );
    """)
    conn.commit()
    conn.close()
    print("DB initialized:", DB_PATH)


def migrate_db():
    """Safe incremental migrations — add columns that may not exist in older DBs."""
    conn = get_db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(findings)").fetchall()}
    if "tool" not in cols:
        conn.execute("ALTER TABLE findings ADD COLUMN tool TEXT")
        conn.commit()
    conn.close()


def create_order_tasks(order_id: int):
    """Pre-populate standard NIS2/DSGVO tasks for a new order."""
    for (cat, title, desc, nis2, dsgvo, req) in NIS2_STANDARD_TASKS:
        db_execute(
            """INSERT INTO order_tasks
               (order_id, category, title, description, nis2_ref, dsgvo_ref, required, done)
               VALUES (?,?,?,?,?,?,?,0)""",
            (order_id, cat, title, desc, nis2, dsgvo, req),
        )
