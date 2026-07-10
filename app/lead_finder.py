"""
lead_finder.py — Passive Lead-Discovery für die Zielgruppe "Kassensystem-Betreiber"
========================================================================================

Ablauf:
  1. discover_leads(branche, limit) — findet Unternehmen (Gastronomie/Einzelhandel)
     über die OpenStreetMap Overpass API (kostenlos, kein API-Key, öffentliche Daten).
     Nur Betriebe mit bereits hinterlegter Website werden zurückgegeben.
  2. enrich_lead(lead) — besucht passiv die Startseite + Impressum der Website,
     um E-Mail/Ansprechpartner/Adresse zu vervollständigen (kein aktiver Scan,
     keine Verbindung zu einem Kassensystem — nur was jeder Browser auch sieht).
  3. save_leads(leads) — speichert neue Leads in der DB (Tabelle `leads`).
  4. build_outreach_email(...) — baut eine personalisierte Einladungs-Mail mit
     Link zu /lead/<token>. Der eigentliche Kassensystem-Check (Shodan/CVE, siehe
     kassen_check.py) läuft ERST nachdem der Lead über diesen Link zugestimmt hat —
     vorher gibt es keine technische Prüfung, nur passive OSINT-Anreicherung.
"""

import re
import json
import socket
import ssl
import threading
import time
from datetime import datetime

import requests

from models import db_query, db_execute
from payments import PUBLIC_BASE_URL

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AndriiIT-LeadFinder/1.0; +https://andrii-it.de)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "de-DE,de;q=0.9",
}

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

BRANCHE_TAG_FILTER = {
    "gastronomie": '["amenity"~"^(restaurant|cafe|fast_food|bar|pub|biergarten)$"]',
    "einzelhandel": '["shop"]',
}

BRANCHE_LABELS = {
    "gastronomie": "Gastronomie",
    "einzelhandel": "Einzelhandel",
}

# Radius-Suche (around:) statt Länder-Polygon/BBox — eine Deutschland-weite
# Flächenabfrage ist bei Overpass zu langsam (Timeout). Städte nacheinander
# abfragen, bis genug Leads gefunden sind. Frankfurt zuerst (Standort).
CITIES = [
    ("Frankfurt am Main", 50.1109, 8.6821),
    ("Wiesbaden", 50.0782, 8.2398),
    ("Mainz", 49.9929, 8.2473),
    ("Darmstadt", 49.8728, 8.6512),
    ("Offenbach", 50.1055, 8.7761),
    ("Köln", 50.9375, 6.9603),
    ("Düsseldorf", 51.2277, 6.7735),
    ("Stuttgart", 48.7758, 9.1829),
    ("München", 48.1351, 11.5820),
    ("Berlin", 52.5200, 13.4050),
    ("Hamburg", 53.5511, 9.9937),
    ("Leipzig", 51.3397, 12.3731),
    ("Hannover", 52.3759, 9.7320),
    ("Nürnberg", 49.4521, 11.0767),
    ("Bremen", 53.0793, 8.8017),
    ("Dresden", 51.0504, 13.7373),
    ("Dortmund", 51.5136, 7.4653),
    ("Essen", 51.4556, 7.0116),
    ("Bonn", 50.7374, 7.0982),
    ("Mannheim", 49.4875, 8.4660),
    ("Karlsruhe", 49.0069, 8.4037),
    ("Freiburg", 47.9990, 7.8421),
    ("Münster", 51.9607, 7.6261),
    ("Augsburg", 48.3705, 10.8978),
    ("Kassel", 51.3127, 9.4797),
    ("Regensburg", 49.0134, 12.1016),
    ("Erfurt", 50.9848, 11.0299),
    ("Rostock", 54.0924, 12.0991),
    ("Saarbrücken", 49.2402, 6.9969),
]
CITY_RADIUS_M = 15000


def _overpass_query_city(branche: str, lat: float, lon: float, fetch_n: int) -> list[dict]:
    tag_filter = BRANCHE_TAG_FILTER.get(branche)
    if not tag_filter:
        raise ValueError(f"Unbekannte Branche: {branche}")

    ql = f"""
    [out:json][timeout:25];
    (
      node{tag_filter}["website"](around:{CITY_RADIUS_M},{lat},{lon});
    );
    out body {fetch_n};
    """
    resp = requests.post(OVERPASS_URL, data={"data": ql},
                          headers={"User-Agent": "AndriiIT-LeadFinder/1.0"}, timeout=35)
    resp.raise_for_status()
    data = resp.json()
    if data.get("remark"):
        raise RuntimeError(data["remark"])
    return data.get("elements", [])


def _normalize_domain(url: str) -> str | None:
    url = url.strip().lower()
    url = re.sub(r"^https?://", "", url)
    url = url.split("/")[0]
    url = url.replace("www.", "")
    if "." not in url or " " in url:
        return None
    return url


def _osm_address(tags: dict) -> str | None:
    street = " ".join(p for p in [tags.get("addr:street", ""), tags.get("addr:housenumber", "")] if p).strip()
    city = " ".join(p for p in [tags.get("addr:postcode", ""), tags.get("addr:city", "")] if p).strip()
    full = ", ".join(p for p in [street, city] if p)
    return full or None


def discover_leads(branche: str, limit: int = 20, known_domains: set | None = None) -> list[dict]:
    """Findet Unternehmen mit Website-Eintrag via OpenStreetMap Overpass API.
    Fragt Städte nacheinander ab (Radius-Suche), bis `limit` neue Leads
    gefunden wurden. Gibt eine Liste von Lead-Dicts zurück (noch NICHT in
    der DB gespeichert)."""
    known_domains = known_domains or set()
    leads = []
    seen = set()
    fetch_n = max(limit * 2, 30)

    for city_name, lat, lon in CITIES:
        if len(leads) >= limit:
            break
        try:
            elements = _overpass_query_city(branche, lat, lon, fetch_n)
        except Exception:
            continue

        for el in elements:
            tags = el.get("tags", {})
            website = tags.get("website") or tags.get("contact:website")
            if not website:
                continue
            domain = _normalize_domain(website)
            if not domain or domain in seen or domain in known_domains:
                continue
            seen.add(domain)

            leads.append({
                "company": tags.get("name") or domain,
                "domain": domain,
                "branche": BRANCHE_LABELS.get(branche, branche),
                "city": city_name,
                "contact": None,
                "salutation": None,
                "email": (tags.get("contact:email") or tags.get("email") or "").lower() or None,
                "phone": tags.get("contact:phone") or tags.get("phone"),
                "address": _osm_address(tags),
            })
            if len(leads) >= limit:
                break
    return leads


def _find_email(domain: str, base_url: str, html: str) -> str | None:
    """Passive E-Mail-Suche: mailto-Links, dann Impressum/Kontakt-Seite."""
    domain_root = domain.replace("www.", "")
    mailto = re.findall(r"mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})", html)
    domain_mails = [e for e in mailto if domain_root in e.lower()]
    if domain_mails:
        return domain_mails[0].lower()

    emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", html)
    domain_emails = [e for e in emails if domain_root in e.lower()]
    if domain_emails:
        return domain_emails[0].lower()

    for path in ("/impressum", "/impressum.html", "/impressum.php", "/kontakt", "/kontakt.html"):
        try:
            resp = requests.get(f"{base_url}{path}", headers=HEADERS, timeout=6, allow_redirects=True)
            if resp.status_code != 200 or len(resp.text) < 100:
                continue
            mailto = re.findall(r"mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})", resp.text)
            if mailto:
                return mailto[0].lower()
            emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", resp.text)
            domain_emails = [e for e in emails if domain_root in e.lower()]
            if domain_emails:
                return domain_emails[0].lower()
        except Exception:
            continue
    return None


def _clean_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_impressum(base_url: str) -> dict:
    """Extrahiert Ansprechpartner/Anrede/Telefon/Adresse aus der Impressum-Seite."""
    info = {"owner_name": None, "salutation": None, "phone": None, "street": None,
            "zip_code": None, "city": None}

    for path in ("/impressum", "/impressum.html", "/impressum.php", "/impressum/", "/de/impressum"):
        try:
            resp = requests.get(f"{base_url}{path}", headers=HEADERS, timeout=6, allow_redirects=True)
            if resp.status_code != 200 or len(resp.text) < 100:
                continue
        except Exception:
            continue

        text = _clean_html(resp.text)

        RESPONSIBLE_TITLES = (r"Inhaber(?:in)?|Geschäftsführer(?:in)?|Herausgeber(?:in)?|"
                              r"Vorstand(?:svorsitzende[rn]?)?|Vorsitzende[rn]?|Leitung|"
                              r"Ansprechpartner(?:in)?|Verantwortlich(?:er|e)? (?:im Sinne des )?"
                              r"(?:§\s?5\s?TMG|Presserechts?)?|Betreiber(?:in)?")
        for pattern, salutation, group in [
            (rf"(?:{RESPONSIBLE_TITLES}):?\s+"
             r"((?:Herr|Frau)\s+[A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+){0,3})", "detected", 1),
            (r"\b(Herr)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+){1,3})", "Herr", 2),
            (r"\b(Frau)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+){1,3})", "Frau", 2),
            # Fallback: Titel gefolgt von Name ohne Anrede (z.B. "Vorstand: Max Mustermann")
            (rf"(?:{RESPONSIBLE_TITLES}):?\s+"
             r"([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+){1,2})", "unbekannt", 1),
        ]:
            m = re.search(pattern, text)
            if m:
                if salutation in ("detected", "unbekannt"):
                    full = m.group(group).strip()
                    if full.startswith("Herr"):
                        info["salutation"], info["owner_name"] = "Herr", full[4:].strip()
                    elif full.startswith("Frau"):
                        info["salutation"], info["owner_name"] = "Frau", full[4:].strip()
                    else:
                        info["owner_name"] = full
                else:
                    info["salutation"], info["owner_name"] = salutation, m.group(2).strip()
                break

        phone_m = re.search(
            r"(?:Tel(?:efon)?\.?|Fon|Phone):?\s*((?:\+49|0)[0-9\s\-\/\(\)]{6,20})", text, re.IGNORECASE)
        if phone_m:
            info["phone"] = re.sub(r"\s+", " ", phone_m.group(1)).strip()

        zip_m = re.search(r"\b(?:D-)?(\d{5})\s+([A-ZÄÖÜ][a-zäöüß]+(?:[\s\-][A-ZÄÖÜ][a-zäöüß]+){0,2})", text)
        if zip_m:
            info["zip_code"] = zip_m.group(1)
            junk = {"vertreten", "gmbh", "ag", "home", "kontakt", "impressum"}
            city_clean = []
            for part in zip_m.group(2).strip().split():
                if part.lower() in junk:
                    break
                city_clean.append(part)
            if city_clean:
                info["city"] = " ".join(city_clean)[:30]

        street_m = re.search(
            r"([A-ZÄÖÜ][a-zäöüßA-ZÄÖÜ\s]{3,30}(?:straße|strasse|str\.|weg|gasse|allee|platz|ring|damm)"
            r"\.?\s*\d+[a-z]?)", text, re.IGNORECASE)
        if street_m:
            info["street"] = street_m.group(1).strip()

        return info

    return info


def enrich_lead(lead: dict) -> dict:
    """Ergänzt fehlende Felder durch einen passiven Besuch der Website (Startseite +
    Impressum). Ändert `lead` in-place und gibt es zurück."""
    domain = lead["domain"]
    html, base_url = "", None
    for scheme in ("https://", "http://"):
        try:
            resp = requests.get(f"{scheme}{domain}", headers=HEADERS, timeout=8, allow_redirects=True)
            html, base_url = resp.text, f"{scheme}{domain}"
            break
        except Exception:
            continue

    if base_url is None:
        return lead

    if not lead.get("email"):
        lead["email"] = _find_email(domain, base_url, html)

    if not lead.get("contact") or not lead.get("address") or not lead.get("phone"):
        info = _parse_impressum(base_url)
        if info.get("owner_name") and not lead.get("contact"):
            lead["contact"] = info["owner_name"]
            lead["salutation"] = info.get("salutation")
        if not lead.get("phone") and info.get("phone"):
            lead["phone"] = info["phone"]
        if not lead.get("address") and (info.get("street") or info.get("city")):
            city_line = f"{info.get('zip_code', '')} {info.get('city', '')}".strip()
            lead["address"] = ", ".join(p for p in [info.get("street"), city_line] if p)

    return lead


def save_leads(leads: list[dict]) -> int:
    """Speichert neue Leads (Domains, die noch nicht existieren). Gibt die Anzahl
    neu gespeicherter Leads zurück."""
    saved = 0
    for lead in leads:
        existing = db_query("SELECT id FROM leads WHERE domain=?", (lead["domain"],))
        if existing:
            continue
        db_execute(
            """INSERT INTO leads (company,contact,salutation,email,phone,address,domain,
                                   branche,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,'found',?)""",
            (lead["company"], lead.get("contact"), lead.get("salutation"), lead.get("email"),
             lead.get("phone"), lead.get("address"), lead["domain"], lead.get("branche"),
             datetime.now().isoformat()),
        )
        saved += 1
    return saved


FINDING_TEMPLATES = {
    "missing_headers": {
        "title": "Ihre Website versendet keine modernen Sicherheits-Header (z.B. Content-Security-Policy)",
        "hacker": "Ohne diese Header sind Angriffe wie Clickjacking oder das Einschleusen "
                  "fremden Codes (Cross-Site-Scripting) deutlich leichter umzusetzen.",
        "legal": "Nach Art. 32 DSGVO sind angemessene technische Schutzmaßnahmen Pflicht — "
                 "bei einem Datenvorfall kann das Fehlen solcher Basics als Versäumnis gewertet werden.",
    },
    "exposed_version": {
        "title": "Ihre Website verrät die genaue Software-Version im Klartext ({detail})",
        "hacker": "Angreifer suchen gezielt nach bekannten Sicherheitslücken für exakt diese "
                  "Version — das verkürzt die Vorbereitung eines Angriffs erheblich.",
        "legal": "Ein unnötig offengelegter Software-Stand erleichtert gezielte Angriffe und "
                 "gilt als vermeidbares Risiko im Sinne von Art. 32 DSGVO.",
    },
    "exposed_git": {
        "title": "Ein Git-Repository (.git) ist öffentlich über Ihre Website erreichbar",
        "hacker": "Darüber lässt sich häufig der komplette Quellcode inklusive alter "
                  "Zugangsdaten oder interner Kommentare herunterladen.",
        "legal": "Ein offenes Repository kann personenbezogene Daten oder Zugangsdaten "
                 "enthalten — ein klassischer Fall für ein meldepflichtiges Datenleck (Art. 33 DSGVO).",
    },
    "exposed_env": {
        "title": "Eine Konfigurationsdatei (.env) mit möglichen Zugangsdaten ist öffentlich abrufbar",
        "hacker": "Solche Dateien enthalten oft Datenbank-Passwörter oder API-Schlüssel — "
                  "damit lässt sich direkt auf interne Systeme zugreifen.",
        "legal": "Der Verlust von Zugangsdaten ist ein melde­pflichtiger Sicherheitsvorfall "
                 "nach Art. 33/34 DSGVO — Bußgelder bis 20 Mio. € bzw. 4 % des Jahresumsatzes sind möglich.",
    },
    "weak_ssl": {
        "title": "Die Verschlüsselung Ihrer Website (TLS/SSL) ist veraltet oder das Zertifikat läuft bald ab",
        "hacker": "Veraltete Verschlüsselung lässt sich mit heutiger Rechenleistung leichter "
                  "kompromittieren — Angreifer könnten Daten Ihrer Kunden mitlesen.",
        "legal": "Eine unsichere Übertragung personenbezogener Daten verstößt gegen die in "
                 "Art. 32 DSGVO geforderte Verschlüsselung.",
    },
    "outdated_copyright": {
        "title": "Ihre Website wirkt seit mehreren Jahren nicht mehr aktualisiert",
        "hacker": "Länger nicht gepflegte Websites laufen häufig auf veralteter, ungepatchter "
                  "Software — ein bevorzugtes Ziel für automatisierte Angriffs-Scans.",
        "legal": "Fehlende Pflege ist zwar kein eigener Verstoß, korreliert in der Praxis aber "
                 "stark mit ungepatchten Sicherheitslücken.",
    },
    "missing_legal": {
        "title": "Impressum bzw. Datenschutzerklärung waren auf den üblichen Pfaden nicht auffindbar",
        "hacker": None,
        "legal": "Ein fehlendes oder schwer auffindbares Impressum verstößt gegen § 5 TMG, eine "
                 "fehlende Datenschutzerklärung gegen Art. 13 DSGVO — beides ist bußgeldbewehrt "
                 "und wird von Wettbewerbern/Verbänden regelmäßig abgemahnt.",
    },
}


def extract_business_context(html: str) -> str | None:
    """Extrahiert eine kurze Beschreibung der Geschäftstätigkeit aus Meta-Description,
    Open-Graph-Description oder Titel — für eine kontextbezogene Anrede im Anschreiben."""
    for pattern in (
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{20,200})["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']{20,200})["\']',
    ):
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            text = _clean_html(m.group(1)).strip()
            if len(text) > 15:
                return text[:180]

    title_m = re.search(r"<title[^>]*>([^<]{5,120})</title>", html, re.IGNORECASE)
    if title_m:
        text = _clean_html(title_m.group(1)).strip()
        if len(text) > 5:
            return text[:120]
    return None


def _check_ssl(domain: str) -> dict | None:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=6) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                version = ssock.version()
        not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
        days_left = (not_after - datetime.now()).days
        return {"version": version, "days_left": days_left}
    except Exception:
        return None


def light_scan(domain: str) -> dict:
    """Passiver Website-Check (kein Kassensystem!) — liest nur, was jeder Browser auch
    sieht: HTTP-Header, öffentlich abrufbare Pfade, SSL-Zertifikat, Impressum-Erreichbarkeit.
    Rechtliche Grundlage identisch zur bestehenden OSINT-Anreicherung (passiv, §202a StGB-konform)."""
    findings = []
    html, base_url, headers = "", None, {}
    for scheme in ("https://", "http://"):
        try:
            resp = requests.get(f"{scheme}{domain}", headers=HEADERS, timeout=8, allow_redirects=True)
            html, base_url, headers = resp.text, f"{scheme}{domain}", resp.headers
            break
        except Exception:
            continue

    if base_url is None:
        return {"findings": [], "checked_at": datetime.now().isoformat()}

    missing = [h for h in ("Content-Security-Policy", "X-Content-Type-Options",
                            "X-Frame-Options", "Strict-Transport-Security") if h not in headers]
    if len(missing) >= 2:
        findings.append({"id": "missing_headers", **FINDING_TEMPLATES["missing_headers"]})

    for hdr in ("Server", "X-Powered-By"):
        val = headers.get(hdr, "")
        if re.search(r"/[\d.]+", val):
            f = dict(FINDING_TEMPLATES["exposed_version"])
            f["title"] = f["title"].format(detail=val)
            findings.append({"id": "exposed_version", **f})
            break

    try:
        r = requests.get(f"{base_url}/.git/HEAD", headers=HEADERS, timeout=5)
        if r.status_code == 200 and "ref:" in r.text.lower():
            findings.append({"id": "exposed_git", **FINDING_TEMPLATES["exposed_git"]})
    except Exception:
        pass

    try:
        r = requests.get(f"{base_url}/.env", headers=HEADERS, timeout=5)
        if r.status_code == 200 and re.search(r"^[A-Z_]+=", r.text, re.MULTILINE):
            findings.append({"id": "exposed_env", **FINDING_TEMPLATES["exposed_env"]})
    except Exception:
        pass

    if base_url.startswith("https://"):
        ssl_info = _check_ssl(domain)
        if ssl_info and (ssl_info["days_left"] < 30 or ssl_info["version"] in ("TLSv1", "TLSv1.1")):
            findings.append({"id": "weak_ssl", **FINDING_TEMPLATES["weak_ssl"]})

    year_m = re.search(r"(?:©|Copyright)\s*(\d{4})", html)
    if year_m and datetime.now().year - int(year_m.group(1)) >= 3:
        findings.append({"id": "outdated_copyright", **FINDING_TEMPLATES["outdated_copyright"]})

    legal_found = False
    for path in ("/impressum", "/datenschutz", "/impressum.html", "/datenschutzerklaerung"):
        try:
            r = requests.get(f"{base_url}{path}", headers=HEADERS, timeout=5)
            if r.status_code == 200 and len(r.text) > 100:
                legal_found = True
                break
        except Exception:
            continue
    if not legal_found:
        findings.append({"id": "missing_legal", **FINDING_TEMPLATES["missing_legal"]})

    return {"findings": findings, "checked_at": datetime.now().isoformat()}


def analyze_lead(lead_id: int) -> dict:
    """Führt den leichten Website-Check + Kontext-Extraktion für einen Lead aus und
    speichert das Ergebnis persistent (für Vorschau/Bearbeitung vor dem Versand)."""
    lead = db_query("SELECT * FROM leads WHERE id=?", (lead_id,))
    if not lead:
        raise ValueError("Lead nicht gefunden")
    lead = dict(lead[0])

    scan = light_scan(lead["domain"])
    business_context = None
    for scheme in ("https://", "http://"):
        try:
            resp = requests.get(f"{scheme}{lead['domain']}", headers=HEADERS, timeout=8)
            business_context = extract_business_context(resp.text)
            break
        except Exception:
            continue

    db_execute(
        "UPDATE leads SET scan_result=?,business_context=? WHERE id=?",
        (json.dumps(scan, ensure_ascii=False), business_context, lead_id),
    )
    lead["scan_result"] = json.dumps(scan, ensure_ascii=False)
    lead["business_context"] = business_context

    subject, body = build_outreach_email(lead, "PREVIEW", PUBLIC_BASE_URL)
    db_execute("UPDATE leads SET draft_subject=?,draft_body=? WHERE id=?", (subject, body, lead_id))
    return {"scan": scan, "business_context": business_context, "subject": subject, "body": body}


def build_outreach_email(lead: dict, lead_token: str, base_url: str) -> tuple[str, str]:
    """Baut Betreff + Text der Einladungs-Mail. Nutzt vorhandene Scan-Befunde und
    Geschäftskontext für ein persönliches, konkretes Anschreiben statt einer generischen
    Massen-Mail-Vorlage. Fällt auf einen knappen generischen Text zurück, falls noch kein
    Scan durchgeführt wurde (siehe analyze_lead)."""
    salutation, contact = lead.get("salutation"), lead.get("contact")
    if contact and salutation == "Herr":
        greeting = f"Sehr geehrter Herr {contact},"
    elif contact and salutation == "Frau":
        greeting = f"Sehr geehrte Frau {contact},"
    elif contact:
        greeting = f"Sehr geehrte(r) {contact},"
    else:
        greeting = "Sehr geehrte Damen und Herren,"

    link = f"{base_url}/lead/{lead_token}"
    subject = f"Sicherheitshinweis zu {lead['company']} — kostenlose Prüfung möglich"

    scan_raw = lead.get("scan_result")
    findings = json.loads(scan_raw)["findings"] if scan_raw else []
    business_context = lead.get("business_context")

    context_line = ""
    if business_context:
        context_line = f"Ich bin auf {lead['company']} aufmerksam geworden ({business_context}).\n\n"

    if findings:
        top = findings[:2]
        findings_lines = "\n".join(f"  • {f['title']}" for f in top)
        consequence = next((f["legal"] for f in top if f.get("legal")), None)
        hacker = next((f["hacker"] for f in top if f.get("hacker")), None)

        findings_block = f"""Bei einer rein passiven Prüfung Ihrer öffentlich erreichbaren Website
(keine Anmeldung, keine Verbindung zu internen Systemen) ist mir aufgefallen:

{findings_lines}
"""
        if hacker:
            findings_block += f"\nKonkret bedeutet das: {hacker}\n"
        if consequence:
            findings_block += f"\nRechtlich relevant: {consequence}\n"
    else:
        findings_block = ("Betriebe in Gastronomie und Einzelhandel setzen häufig Kassensysteme "
                           "(POS) ein, die über Fernwartung oder Cloud-Anbindung versehentlich im "
                           "Internet sichtbar sind — oft ohne dass der Betreiber davon weiß.\n")

    body = f"""{greeting}

mein Name ist Andrii Pylypchuk, ich bin IT-Sicherheitsberater aus Frankfurt am Main
(andrii-it.de) und beschäftige mich mit der Absicherung von Kassensystemen und
Webauftritten im Rahmen der NIS2-Richtlinie.

{context_line}{findings_block}
Ich biete Ihnen dazu eine kostenlose, unverbindliche Ersteinschätzung an — rein passiv,
ohne jede Beeinträchtigung Ihres Betriebs:

  {link}

Dort sehen Sie die Details und können bei Interesse eine vollständige Sicherheitsprüfung
mit schriftlichem Bericht beauftragen.

Falls Sie keine weiteren Nachrichten dieser Art erhalten möchten, teilen Sie mir das
einfach per Antwort-E-Mail mit — ich entferne Sie dann aus meiner Liste.

Mit freundlichen Grüßen
Andrii Pylypchuk
IT-Sicherheitsberater, Frankfurt am Main
{base_url}
"""
    return subject, body


# ── Hintergrund-Suche (Start/Stop über Admin-UI) ───────────────────────────────
# Läuft in einem Thread über alle Branchen x Städte, bis gestoppt oder eine
# volle Runde ohne neue Treffer durchlaufen wurde. Nur Discovery + passive
# Anreicherung — der Versand der Einladungs-Mail bleibt bewusst ein separater,
# manueller Klick pro Lead (siehe /leads/<id>/send).

_state_lock = threading.Lock()
_stop_event = threading.Event()
_state = {
    "running": False,
    "branches": [],
    "found_total": 0,
    "current_branche": None,
    "current_city": None,
    "started_at": None,
    "last_error": None,
}


def get_status() -> dict:
    with _state_lock:
        return dict(_state)


def is_running() -> bool:
    with _state_lock:
        return _state["running"]


def start_background_search(branches: list[str]) -> bool:
    """Startet die Hintergrund-Suche. Gibt False zurück, wenn bereits eine läuft."""
    with _state_lock:
        if _state["running"]:
            return False
        _stop_event.clear()
        _state.update(running=True, branches=branches, found_total=0,
                       current_branche=None, current_city=None,
                       started_at=datetime.now().isoformat(), last_error=None)
    thread = threading.Thread(target=_background_loop, args=(branches,), daemon=True)
    thread.start()
    return True


def stop_background_search() -> None:
    _stop_event.set()


def _background_loop(branches: list[str]) -> None:
    try:
        while not _stop_event.is_set():
            found_this_round = 0
            for branche in branches:
                if _stop_event.is_set():
                    break
                for city_name, lat, lon in CITIES:
                    if _stop_event.is_set():
                        break
                    with _state_lock:
                        _state["current_branche"] = branche
                        _state["current_city"] = city_name

                    try:
                        known = {r["domain"] for r in db_query("SELECT domain FROM leads")}
                        elements = _overpass_query_city(branche, lat, lon, 60)
                    except Exception as e:
                        with _state_lock:
                            _state["last_error"] = str(e)
                        time.sleep(3)
                        continue

                    for el in elements:
                        if _stop_event.is_set():
                            break
                        tags = el.get("tags", {})
                        website = tags.get("website") or tags.get("contact:website")
                        if not website:
                            continue
                        domain = _normalize_domain(website)
                        if not domain or domain in known:
                            continue
                        known.add(domain)

                        lead = {
                            "company": tags.get("name") or domain,
                            "domain": domain,
                            "branche": BRANCHE_LABELS.get(branche, branche),
                            "contact": None,
                            "salutation": None,
                            "email": (tags.get("contact:email") or tags.get("email") or "").lower() or None,
                            "phone": tags.get("contact:phone") or tags.get("phone"),
                            "address": _osm_address(tags),
                        }
                        enrich_lead(lead)
                        if save_leads([lead]):
                            found_this_round += 1
                            with _state_lock:
                                _state["found_total"] += 1

                    time.sleep(2)  # Rücksicht auf die kostenlose Overpass-API
            if found_this_round == 0:
                break  # eine volle Runde ohne neue Treffer — automatisch anhalten
    finally:
        with _state_lock:
            _state.update(running=False, current_branche=None, current_city=None)
