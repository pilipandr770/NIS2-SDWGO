"""
Live Check — HTTP Security Headers + TLS/SSL analysis
"""
import ssl
import socket
import urllib.request
import urllib.error
from datetime import datetime

SECURITY_HEADERS = [
    {
        "name": "Strict-Transport-Security",
        "key": "strict-transport-security",
        "desc": "HSTS — erzwingt HTTPS, verhindert SSL-Stripping",
        "article": "Art. 32 DSGVO / §30 BSIG",
    },
    {
        "name": "Content-Security-Policy",
        "key": "content-security-policy",
        "desc": "CSP — verhindert XSS und Datenlecks",
        "article": "Art. 32 DSGVO",
    },
    {
        "name": "X-Frame-Options",
        "key": "x-frame-options",
        "desc": "Click-Jacking-Schutz",
        "article": "Art. 32 DSGVO",
    },
    {
        "name": "X-Content-Type-Options",
        "key": "x-content-type-options",
        "desc": "Verhindert MIME-Sniffing",
        "article": "Art. 32 DSGVO",
    },
    {
        "name": "Referrer-Policy",
        "key": "referrer-policy",
        "desc": "Kontrolliert Referrer-Informationen",
        "article": "Art. 5 Abs. 1f DSGVO",
    },
    {
        "name": "Permissions-Policy",
        "key": "permissions-policy",
        "desc": "Steuert Browser-Features (Kamera, Mikrofon, etc.)",
        "article": "Art. 25 DSGVO",
    },
    {
        "name": "Cross-Origin-Opener-Policy",
        "key": "cross-origin-opener-policy",
        "desc": "COOP — isoliert Cross-Origin-Dokumente",
        "article": "Art. 32 DSGVO",
    },
    {
        "name": "Cross-Origin-Resource-Policy",
        "key": "cross-origin-resource-policy",
        "desc": "CORP — verhindert Cross-Origin-Einbindung",
        "article": "Art. 32 DSGVO",
    },
]


def _normalize_url(target: str) -> str:
    target = target.strip()
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    return target


def _get_tls_info(hostname: str) -> dict:
    info = {
        "tls_version": "",
        "tls_issuer": "",
        "tls_expiry": "",
        "tls_expired": False,
        "tls_grade": "F",
    }
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.create_connection((hostname, 443), timeout=10), server_hostname=hostname) as s:
            cert = s.getpeercert()
            info["tls_version"] = s.version() or ""

            # Issuer
            issuer_dict = dict(x[0] for x in cert.get("issuer", []))
            info["tls_issuer"] = issuer_dict.get("organizationName", issuer_dict.get("commonName", ""))

            # Expiry
            expiry_str = cert.get("notAfter", "")
            if expiry_str:
                try:
                    expiry_dt = datetime.strptime(expiry_str, "%b %d %H:%M:%S %Y %Z")
                    info["tls_expiry"] = expiry_dt.strftime("%d.%m.%Y")
                    info["tls_expired"] = expiry_dt < datetime.now()
                except Exception:
                    info["tls_expiry"] = expiry_str

            # Grade
            ver = info["tls_version"]
            if "TLSv1.3" in ver or "TLSv1.2" in ver:
                info["tls_grade"] = "A" if not info["tls_expired"] else "C"
            elif "TLSv1.1" in ver or "TLSv1.0" in ver:
                info["tls_grade"] = "D"
            else:
                info["tls_grade"] = "B"
    except ssl.SSLCertVerificationError:
        info["tls_grade"] = "F"
        info["tls_version"] = "Zertifikatsfehler"
    except Exception:
        info["tls_grade"] = "?"
        info["tls_version"] = "Nicht erreichbar"
    return info


def fetch_live_check(target: str) -> dict:
    url = _normalize_url(target)
    result = {
        "url": url,
        "checked_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "headers": [],
        "warnings": [],
        "passed": False,
        "fetch_error": None,
        "tls_grade": "",
        "tls_version": "",
        "tls_issuer": "",
        "tls_expiry": "",
        "tls_expired": False,
    }

    # TLS check
    try:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or target
        tls = _get_tls_info(hostname)
        result.update(tls)
    except Exception as e:
        result["warnings"].append(f"TLS-Prüfung fehlgeschlagen: {e}")

    # HTTP headers check
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (NIS2-Audit-Bot/1.0; +https://andrii-it.de)"}
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            resp_headers = {k.lower(): v for k, v in resp.getheaders()}

        # Evaluate each security header
        issues = []
        header_results = []
        for hdef in SECURITY_HEADERS:
            val = resp_headers.get(hdef["key"], "")
            good = bool(val)

            # Extra quality checks
            if hdef["key"] == "strict-transport-security" and val:
                if "max-age=" not in val.lower():
                    good = False

            header_results.append({
                "name":    hdef["name"],
                "key":     hdef["key"],
                "desc":    hdef["desc"],
                "article": hdef["article"],
                "value":   val,
                "good":    good,
            })
            if not good:
                issues.append(hdef["name"])

        result["headers"] = header_results

        # Server banner leak
        server = resp_headers.get("server", "")
        if server and any(x in server.lower() for x in ["apache/", "nginx/", "iis/", "php/"]):
            result["warnings"].append(f"Server-Banner enthüllt Version: {server} (§30 BSIG — Informationsleck)")

        # Check for mixed content hints
        if url.startswith("https://"):
            if not resp_headers.get("strict-transport-security"):
                result["warnings"].append("HSTS fehlt — Browser könnte HTTP-Verbindungen zulassen (Art. 32 DSGVO)")

        result["passed"] = len(issues) == 0
        if issues:
            result["warnings"].append(f"Fehlende Security-Header: {', '.join(issues)}")

    except urllib.error.URLError as e:
        result["fetch_error"] = str(e.reason)
    except Exception as e:
        result["fetch_error"] = str(e)

    return result
