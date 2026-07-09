"""
kassen_check.py — Passiver Kassensystem-Expositions-Check (Shodan + CVE)
==========================================================================

WICHTIG — Scope-Grenzen dieses Moduls (bewusst so gehalten):

1. NUR PASSIV. Dieses Modul sendet KEINE Pakete an das Zielsystem
   (keine Ports werden verbunden, keine Requests an die Kasse selbst).
   Es liest ausschließlich bereits öffentlich indexierte Daten von Shodan
   (shodan.io) und öffentliche CVE-Datenbanken (NVD / CIRCL).

2. NUR EIGENE, VERTRAGLICH FREIGEGEBENE ZIELE. Das aufrufende Programm
   (agent.py / app.py) darf diese Funktion ausschließlich für Domains/IPs
   aufrufen, die (a) durch OSINT dem Kunden eindeutig zugeordnet wurden
   (Impressum / Handelsregister) UND (b) Teil eines unterschriebenen
   Auftrags (orders.scope) sind. Dieses Modul selbst nimmt keine
   Nutzereingabe von IP/Domain entgegen — der Zielwert kommt ausschließlich
   aus der Order-Datenbank.

3. KEINE EXPLOITATION. Es wird nichts ausgenutzt, nichts verändert,
   nichts "bewiesen". Ergebnis ist ausschließlich eine Liste:
   "gefundener Dienst/Version -> bekannte CVE -> Empfehlung: updaten/schließen".

4. MENSCHLICHE FREIGABE PFLICHT. Ergebnisse landen in der bestehenden
   `findings`-Tabelle wie jeder andere Fund auch und durchlaufen denselben
   manuellen Review vor Versand (siehe app.py / order_detail.html).

Benötigte Umgebungsvariable:
    SHODAN_API_KEY   — Shodan API Key (einmalig ca. $49 Plan reicht für Host-Lookups)
    NVD_API_KEY      — optional, erhöht NVD-Rate-Limit (kostenlos auf nvd.nist.gov)
"""

import os
import re
import time
import json
import ipaddress
import socket
from datetime import datetime

import requests

from models import db_execute

SHODAN_API_KEY = os.environ.get("SHODAN_API_KEY", "")
NVD_API_KEY = os.environ.get("NVD_API_KEY", "")

SHODAN_HOST_URL = "https://api.shodan.io/shodan/host/{ip}"
SHODAN_DNS_RESOLVE_URL = "https://api.shodan.io/dns/resolve"
NVD_CVE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
CIRCL_CVE_SEARCH_URL = "https://cve.circl.lu/api/search/{vendor}/{product}"

RANK = {"critical": 1, "high": 2, "medium": 3, "low": 4, "info": 5}


def _log(order_id: int, level: str, message: str):
    db_execute(
        "INSERT INTO audit_logs (order_id,level,message,created_at) VALUES (?,?,?,?)",
        (order_id, level, message, datetime.now().isoformat())
    )


def _add_finding(order_id: int, title: str, description: str, severity: str,
                  recommendation: str = "", cvss: str = "", dsgvo_article: str = "",
                  target: str = "", tool: str = "kassen_check"):
    rank = RANK.get(severity.lower(), 5)
    db_execute(
        """INSERT INTO findings
           (order_id,title,description,severity,severity_rank,target,recommendation,cvss,dsgvo_article,tool,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (order_id, title, description, severity, rank, target,
         recommendation, cvss, dsgvo_article, tool, datetime.now().isoformat())
    )


def _resolve_to_ip(target: str) -> str | None:
    """Domain -> IP über Shodan DNS-Resolve-Endpoint (kein direkter Kontakt zum Zielhost)."""
    try:
        ipaddress.ip_address(target)
        return target
    except ValueError:
        pass
    try:
        r = requests.get(SHODAN_DNS_RESOLVE_URL,
                          params={"hostnames": target, "key": SHODAN_API_KEY},
                          timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get(target)
    except Exception:
        try:
            return socket.gethostbyname(target)
        except Exception:
            return None


def shodan_lookup(ip: str) -> dict:
    """Liest den bereits von Shodan indexierten Datensatz für eine IP.
    Sendet KEINE Anfrage an die Ziel-IP selbst — nur an die Shodan-API."""
    if not SHODAN_API_KEY:
        return {"error": "SHODAN_API_KEY nicht konfiguriert"}
    try:
        r = requests.get(SHODAN_HOST_URL.format(ip=ip),
                          params={"key": SHODAN_API_KEY}, timeout=20)
        if r.status_code == 404:
            return {"not_indexed": True}
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _extract_services(shodan_data: dict) -> list:
    """Extrahiert Dienst/Produkt/Version-Tripel aus Shodan-Antwort."""
    services = []
    for item in shodan_data.get("data", []):
        product = item.get("product", "")
        version = item.get("version", "")
        port = item.get("port", "")
        transport = item.get("transport", "tcp")
        cpe = item.get("cpe", []) or item.get("cpe23", [])
        if product:
            services.append({
                "port": port, "transport": transport,
                "product": product, "version": version, "cpe": cpe,
            })
    return services


def match_cve_nvd(product: str, version: str) -> list:
    """CVE-Lookup über NVD API 2.0 (offiziell, reiner Datenbank-Read)."""
    if not product:
        return []
    keyword = f"{product} {version}".strip()
    headers = {"apiKey": NVD_API_KEY} if NVD_API_KEY else {}
    try:
        r = requests.get(NVD_CVE_URL,
                          params={"keywordSearch": keyword, "resultsPerPage": 10},
                          headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
        out = []
        for v in data.get("vulnerabilities", []):
            cve = v.get("cve", {})
            cve_id = cve.get("id")
            metrics = cve.get("metrics", {})
            score, severity = "", "medium"
            for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
                if key in metrics:
                    m = metrics[key][0]["cvssData"]
                    score = m.get("baseScore", "")
                    severity = metrics[key][0].get("baseSeverity", "medium").lower()
                    break
            descs = cve.get("descriptions", [])
            desc_text = next((d["value"] for d in descs if d.get("lang") == "en"), "")
            out.append({"id": cve_id, "score": score, "severity": severity, "desc": desc_text})
        return out
    except Exception:
        return []


def match_cve_circl(product: str, version: str) -> list:
    """Fallback: CIRCL CVE-Search (frei, ohne API-Key)."""
    if not product:
        return []
    vendor_guess = product.split()[0].lower()
    product_guess = product.lower().replace(" ", "_")
    try:
        r = requests.get(CIRCL_CVE_SEARCH_URL.format(vendor=vendor_guess, product=product_guess),
                          timeout=20)
        if r.status_code != 200:
            return []
        data = r.json()
        results = data.get("data", []) if isinstance(data, dict) else data
        out = []
        for item in results[:10]:
            out.append({
                "id": item.get("id"),
                "score": item.get("cvss", ""),
                "severity": "medium",
                "desc": item.get("summary", ""),
            })
        return out
    except Exception:
        return []


def match_cve(product: str, version: str) -> list:
    results = match_cve_nvd(product, version)
    if not results:
        time.sleep(1)
        results = match_cve_circl(product, version)
    return results


def run_kassen_check(order_id: int, target: str):
    """
    Orchestrierung: Zielwert kommt AUSSCHLIESSLICH aus der Order (nicht aus
    Nutzereingabe). Ablauf: Shodan-Host-Lookup (passiv) -> CVE-Abgleich ->
    Findings in DB schreiben. Kein einziger Request geht an den Zielhost.
    """
    _log(order_id, "INFO", f"Kassensystem-Check gestartet (passiv, Ziel aus Order: {target})")

    ip = _resolve_to_ip(target)
    if not ip:
        _log(order_id, "ERROR", "Konnte Ziel nicht auflösen — Check abgebrochen")
        _add_finding(
            order_id, "Kassensystem-Check nicht möglich",
            "Die hinterlegte Domain/IP konnte nicht aufgelöst werden.",
            "info", target=target,
        )
        return

    shodan_data = shodan_lookup(ip)

    if shodan_data.get("error"):
        _log(order_id, "ERROR", f"Shodan-Fehler: {shodan_data['error']}")
        return

    if shodan_data.get("not_indexed"):
        _add_finding(
            order_id,
            "Kassensystem-Netzwerk: keine öffentliche Exposition gefunden",
            "In der Shodan-Datenbank sind für diese IP aktuell keine offenen "
            "Dienste indexiert. Das bedeutet nicht automatisch vollständige "
            "Sicherheit — Shodan-Daten können veraltet sein und interne "
            "Netzwerke werden hierdurch nicht erfasst.",
            "info", target=target,
            recommendation="Regelmäßige Wiederholung dieser Prüfung empfohlen "
                            "sowie ergänzende interne Netzwerksegmentierungsprüfung vor Ort.",
        )
        _log(order_id, "INFO", "Keine Shodan-Exposition gefunden — Check abgeschlossen")
        return

    services = _extract_services(shodan_data)
    org = shodan_data.get("org", "")
    last_update = shodan_data.get("last_update", "")

    if not services:
        _add_finding(
            order_id,
            "Kassensystem-Netzwerk: offene Ports ohne erkennbares Produkt",
            f"Shodan listet offene Ports für {ip}, konnte aber keine "
            f"Produkt-/Versionsinformation extrahieren (Org: {org or 'unbekannt'}, "
            f"Stand: {last_update or 'unbekannt'}).",
            "low", target=target,
            recommendation="Manuelle Überprüfung der offenen Ports empfohlen.",
        )

    for svc in services:
        cves = match_cve(svc["product"], svc["version"])
        label = f"{svc['product']} {svc['version']}".strip()

        if not cves:
            _add_finding(
                order_id,
                f"Offener Dienst erkannt: {label} (Port {svc['port']}/{svc['transport']})",
                f"Shodan hat einen öffentlich erreichbaren Dienst indexiert: "
                f"{label} auf Port {svc['port']}. Keine bekannten CVEs für diese "
                f"Version in den geprüften Datenbanken gefunden.",
                "low", target=target,
                recommendation="Prüfen, ob dieser Dienst öffentlich erreichbar "
                                "sein muss. Falls nicht erforderlich: Port schließen "
                                "oder hinter VPN/Firewall legen.",
            )
            continue

        for cve in cves:
            severity = cve.get("severity", "medium")
            _add_finding(
                order_id,
                f"{cve['id']}: {label} (Port {svc['port']})",
                cve.get("desc", "")[:800],
                severity,
                target=target,
                cvss=str(cve.get("score", "")),
                recommendation=f"Software '{label}' auf die neueste Version aktualisieren "
                                f"oder Port {svc['port']} nicht öffentlich exponieren. "
                                f"Herstellerangaben zu {cve['id']} prüfen.",
            )

    _log(order_id, "INFO", f"Kassensystem-Check abgeschlossen: {len(services)} Dienst(e) geprüft")
