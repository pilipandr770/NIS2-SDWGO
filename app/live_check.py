"""
Live Check — HTTP Security Headers, TLS/SSL, Cookie Flags, DNS (SPF/DMARC/DKIM)
"""
import ssl
import socket
import urllib.request
import urllib.error
import subprocess
import shutil
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
        "tls_san": [],
    }
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.create_connection((hostname, 443), timeout=10),
                             server_hostname=hostname) as s:
            cert = s.getpeercert()
            info["tls_version"] = s.version() or ""

            # Issuer
            issuer_dict = dict(x[0] for x in cert.get("issuer", []))
            info["tls_issuer"] = issuer_dict.get("organizationName",
                                  issuer_dict.get("commonName", ""))

            # Expiry
            expiry_str = cert.get("notAfter", "")
            if expiry_str:
                try:
                    expiry_dt = datetime.strptime(expiry_str, "%b %d %H:%M:%S %Y %Z")
                    info["tls_expiry"]  = expiry_dt.strftime("%d.%m.%Y")
                    info["tls_expired"] = expiry_dt < datetime.now()
                except Exception:
                    info["tls_expiry"] = expiry_str

            # SAN (Subject Alternative Names)
            raw_san = cert.get("subjectAltName") or ()
            san_list = [v for t, v in raw_san if t == "DNS"]
            # Fallback to CN if SAN is genuinely absent
            if not san_list:
                subject_dict = dict(x[0] for x in cert.get("subject", []))
                cn = subject_dict.get("commonName", "")
                if cn:
                    san_list = [cn]
            info["tls_san"] = san_list[:10]

            # Grade
            ver = info["tls_version"]
            if "TLSv1.3" in ver or "TLSv1.2" in ver:
                info["tls_grade"] = "A" if not info["tls_expired"] else "C"
            elif "TLSv1.1" in ver or "TLSv1.0" in ver:
                info["tls_grade"] = "D"
            else:
                info["tls_grade"] = "B"
    except ssl.SSLCertVerificationError as e:
        info["tls_grade"] = "F"
        info["tls_version"] = f"Zertifikatsfehler: {str(e)[:80]}"
    except (socket.timeout, ConnectionRefusedError, OSError):
        info["tls_grade"] = "?"
        info["tls_version"] = "Nicht erreichbar oder kein HTTPS"
    except Exception as e:
        info["tls_grade"] = "?"
        info["tls_version"] = f"Fehler: {str(e)[:60]}"
    return info


def _check_cookies(resp_headers: dict) -> list:
    """Parse Set-Cookie headers and check security flags."""
    results = []
    raw_cookies = resp_headers.get("set-cookie", "")
    if not raw_cookies:
        return results
    # Multiple cookies can appear; urllib merges them with comma — split by pattern
    for raw in raw_cookies.split("\n") if "\n" in raw_cookies else [raw_cookies]:
        if not raw.strip():
            continue
        name = raw.split("=")[0].strip()
        low  = raw.lower()
        issues = []
        if "secure" not in low:
            issues.append("kein Secure-Flag")
        if "httponly" not in low:
            issues.append("kein HttpOnly-Flag")
        if "samesite" not in low:
            issues.append("kein SameSite-Flag")
        elif "samesite=none" in low and "secure" not in low:
            issues.append("SameSite=None ohne Secure")
        results.append({
            "name":   name,
            "good":   len(issues) == 0,
            "issues": issues,
            "raw":    raw[:120],
        })
    return results


def _dig(qtype: str, name: str, server: str = "8.8.8.8") -> str:
    if not shutil.which("dig"):
        return ""
    try:
        result = subprocess.run(
            ["dig", "+short", qtype, name, f"@{server}"],
            capture_output=True, text=True, timeout=10
        )
        return (result.stdout + result.stderr).strip()
    except Exception:
        return ""


def _check_dns(hostname: str) -> dict:
    """Check SPF, DMARC, DKIM records and DNSSEC."""
    parts = hostname.split(".")
    domain = ".".join(parts[-2:]) if len(parts) >= 2 else hostname

    spf_raw   = _dig("TXT", domain)
    dmarc_raw = _dig("TXT", f"_dmarc.{domain}")
    dnskey    = _dig("DNSKEY", domain)

    spf_ok    = "v=spf1" in spf_raw
    dmarc_ok  = "v=DMARC1" in dmarc_raw
    dnssec_ok = bool(dnskey)

    dmarc_policy = ""
    if dmarc_ok:
        if "p=reject" in dmarc_raw:
            dmarc_policy = "reject"
        elif "p=quarantine" in dmarc_raw:
            dmarc_policy = "quarantine"
        else:
            dmarc_policy = "none"

    # DKIM (common selectors)
    dkim_ok  = False
    dkim_sel = ""
    for sel in ["default", "google", "mail", "k1", "dkim", "selector1", "selector2"]:
        out = _dig("TXT", f"{sel}._domainkey.{domain}")
        if "v=DKIM1" in out:
            dkim_ok  = True
            dkim_sel = sel
            break

    return {
        "domain":        domain,
        "spf_ok":        spf_ok,
        "spf_value":     spf_raw[:120] if spf_ok else "",
        "dmarc_ok":      dmarc_ok,
        "dmarc_policy":  dmarc_policy,
        "dkim_ok":       dkim_ok,
        "dkim_selector": dkim_sel,
        "dnssec_ok":     dnssec_ok,
    }


def fetch_live_check(target: str) -> dict:
    url = _normalize_url(target)
    result = {
        "url":           url,
        "checked_at":    datetime.now().strftime("%d.%m.%Y %H:%M"),
        "headers":       [],
        "cookies":       [],
        "dns":           {},
        "warnings":      [],
        "passed":        False,
        "fetch_error":   None,
        "tls_grade":     "",
        "tls_version":   "",
        "tls_issuer":    "",
        "tls_expiry":    "",
        "tls_expired":   False,
        "tls_san":       [],
    }

    # TLS check
    try:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or target.split("/")[0]
        tls = _get_tls_info(hostname)
        result.update(tls)
        if tls["tls_grade"] == "D":
            result["warnings"].append(
                f"Veraltetes TLS-Protokoll: {tls['tls_version']} — "
                "TLS 1.0/1.1 sind unsicher (Art. 32 DSGVO / §30 BSIG)"
            )
        if tls["tls_expired"]:
            result["warnings"].append(
                f"SSL-Zertifikat abgelaufen (seit {tls['tls_expiry']}) — kritisch!"
            )
    except Exception as e:
        result["warnings"].append(f"TLS-Prüfung fehlgeschlagen: {e}")

    # DNS / SPF / DMARC / DKIM check
    try:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or target.split("/")[0]
        dns = _check_dns(hostname)
        result["dns"] = dns
        if not dns["spf_ok"]:
            result["warnings"].append(
                f"SPF-Record fehlt für {dns['domain']} — E-Mail-Spoofing möglich"
            )
        if not dns["dmarc_ok"]:
            result["warnings"].append(
                f"DMARC-Record fehlt für {dns['domain']} — Phishing-Risiko"
            )
        elif dns["dmarc_policy"] == "none":
            result["warnings"].append(
                f"DMARC policy=none für {dns['domain']} — kein aktiver Schutz"
            )
        if not dns["dkim_ok"]:
            result["warnings"].append(
                f"DKIM nicht gefunden für {dns['domain']} — E-Mail-Authentifizierung fehlt"
            )
        if not dns["dnssec_ok"]:
            result["warnings"].append(
                f"DNSSEC nicht aktiviert für {dns['domain']}"
            )
    except Exception as e:
        result["warnings"].append(f"DNS-Prüfung fehlgeschlagen: {e}")

    # HTTP headers + cookie check
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (NIS2-Audit-Bot/2.0; +https://andrii-it.de)"}
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            resp_headers = {k.lower(): v for k, v in resp.getheaders()}

        # Evaluate security headers
        issues = []
        header_results = []
        for hdef in SECURITY_HEADERS:
            val  = resp_headers.get(hdef["key"], "")
            good = bool(val)

            if hdef["key"] == "strict-transport-security" and val:
                if "max-age=" not in val.lower():
                    good = False
                else:
                    # Check max-age value >= 15768000 (6 months)
                    try:
                        ma = int(val.lower().split("max-age=")[1].split(";")[0].strip())
                        if ma < 15768000:
                            good = False
                    except Exception:
                        pass

            if hdef["key"] == "content-security-policy" and val:
                if "unsafe-inline" in val.lower() or "unsafe-eval" in val.lower():
                    good = False  # CSP exists but is weak

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

        # Cookie security
        result["cookies"] = _check_cookies(resp_headers)
        bad_cookies = [c for c in result["cookies"] if not c["good"]]
        if bad_cookies:
            result["warnings"].append(
                f"{len(bad_cookies)} Cookie(s) ohne Sicherheits-Flags: "
                + ", ".join(c["name"] for c in bad_cookies)
            )

        # Server banner leak
        server = resp_headers.get("server", "")
        if server and any(x in server.lower() for x in ["apache/", "nginx/", "iis/", "php/", "tomcat/"]):
            result["warnings"].append(
                f"Server-Banner gibt Version preis: {server} — Informationsleck (§30 BSIG)"
            )

        # X-Powered-By leak
        xpb = resp_headers.get("x-powered-by", "")
        if xpb:
            result["warnings"].append(
                f"X-Powered-By Header: {xpb} — Technologie-Fingerprinting möglich"
            )

        # HSTS without HTTPS warning
        if url.startswith("https://") and not resp_headers.get("strict-transport-security"):
            result["warnings"].append(
                "HSTS fehlt — Browser kann HTTP-Verbindungen fallback (Art. 32 DSGVO)"
            )

        result["passed"] = len(issues) == 0
        if issues:
            result["warnings"].append(f"Fehlende/schwache Security-Header: {', '.join(issues)}")

    except urllib.error.URLError as e:
        result["fetch_error"] = str(e.reason)
    except Exception as e:
        result["fetch_error"] = str(e)

    return result


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
