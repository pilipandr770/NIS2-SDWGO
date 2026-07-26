"""
NIS2 Audit Agent — Claude-powered automated security audit
Supported tools: nmap, nuclei, httpx, subfinder, testssl, nikto, dns_audit, cookie_check,
                 dnsx, gau, katana, ffuf, arjun
"""
import os
import re
import json
import subprocess
import shutil
import time
from datetime import datetime

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

from models import db_execute, db_query

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MAX_ITERATIONS    = 40
# Modell-Routing (angelehnt an BB_Assist): Standard bewusst Sonnet für den Haupt-Loop —
# im Test produzierte Haiku deutlich mehr Findings (Duplikate, teils ohne die
# Pflicht-Kennzeichnung "[Compliance-Hinweis]"). Bei $100/Audit ist die Ersparnis durch
# ein billigeres Modell marginal, Berichtsqualität beim Kunden wiegt schwerer.
# Kann per .env auf claude-haiku-4-5 umgestellt werden, wenn Kosten wichtiger sind.
MODEL             = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
MODEL_VERIFY      = os.environ.get("ANTHROPIC_MODEL_VERIFY", "claude-sonnet-4-5")

# Geschätzte Kosten pro Mio. Token (USD) — für die Kosten-Anzeige im Audit-Log.
# Nur eine Schätzung zur Kostenkontrolle, keine Rechnungsgrundlage; bei Bedarf per
# .env anpassen, falls sich die Anthropic-Preise ändern.
_COST_PER_MTOK = {
    "haiku":  (float(os.environ.get("ANTHROPIC_COST_HAIKU_IN",  "1.0")),
               float(os.environ.get("ANTHROPIC_COST_HAIKU_OUT", "5.0"))),
    "sonnet": (float(os.environ.get("ANTHROPIC_COST_SONNET_IN",  "3.0")),
               float(os.environ.get("ANTHROPIC_COST_SONNET_OUT", "15.0"))),
    "opus":   (float(os.environ.get("ANTHROPIC_COST_OPUS_IN",  "15.0")),
               float(os.environ.get("ANTHROPIC_COST_OPUS_OUT", "75.0"))),
}


def _price_for(model: str) -> tuple:
    m = (model or "").lower()
    key = "haiku" if "haiku" in m else ("opus" if "opus" in m else "sonnet")
    return _COST_PER_MTOK[key]


def _compress_messages(messages: list, keep_recent: int = 6, max_len: int = 400) -> list:
    """Leichte, abhängigkeitsfreie Kontext-Kompression (ähnliches Ziel wie BB_Assists
    headroom-Kompression, hier ohne zusätzliche Abhängigkeit, da unsere Tool-Ausgaben
    ohnehin bereits auf 5000 Zeichen gekappt sind — kein 50k-URL-Problem wie dort).
    Kürzt Tool-Ausgaben in ÄLTEREN Nachrichten weiter auf eine kurze Zusammenfassung;
    die letzten `keep_recent` Nachrichten bleiben unverändert (aktiver Kontext).
    Gibt eine NEUE Liste zurück — die vom Aufrufer gehaltene Original-Historie bleibt
    unverändert (so behält jede Iteration Zugriff auf die volle Historie)."""
    if len(messages) <= keep_recent:
        return messages
    cutoff = len(messages) - keep_recent
    compressed = []
    for i, msg in enumerate(messages):
        if i >= cutoff or msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            compressed.append(msg)
            continue
        new_content = []
        for block in msg["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_result" and isinstance(block.get("content"), str):
                text = block["content"]
                if len(text) > max_len:
                    block = {**block, "content": text[:max_len] + f"\n… [gekürzt, {len(text)} Zeichen gesamt]"}
            new_content.append(block)
        compressed.append({**msg, "content": new_content})
    return compressed


def _log(order_id: int, level: str, message: str):
    db_execute(
        "INSERT INTO audit_logs (order_id,level,message,created_at) VALUES (?,?,?,?)",
        (order_id, level, message, datetime.now().isoformat())
    )


def _add_finding(order_id: int, title: str, description: str, severity: str,
                 recommendation: str = "", cvss: str = "", dsgvo_article: str = "",
                 target: str = "", tool: str = ""):
    RANK = {"critical": 1, "high": 2, "medium": 3, "low": 4, "info": 5}
    rank = RANK.get(severity.lower(), 5)
    db_execute(
        """INSERT INTO findings
           (order_id,title,description,severity,severity_rank,target,recommendation,cvss,dsgvo_article,tool,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (order_id, title, description, severity, rank, target,
         recommendation, cvss, dsgvo_article, tool, datetime.now().isoformat())
    )


_EN_RE = re.compile(
    r'\b(the |this |these |should |has been |was found|there is |it is |'
    r'in order to |to ensure |the following |make sure |recommend that |'
    r'we recommend |you should |please |vulnerability was|attack can)\b',
    re.IGNORECASE,
)

def _is_english(text: str) -> bool:
    """Return True if text contains more than 2 English indicator phrases."""
    return len(_EN_RE.findall(text or "")) > 2


_CONTINUATION_RE = re.compile(
    r'\s*[\(\[]\s*(fortsetzung|continued?|teil\s*\d+|part\s*\d+)\b.*?[\)\]]\s*$',
    re.IGNORECASE,
)

def _normalize_finding_title(title: str) -> str:
    """Strip continuation markers like '(Fortsetzung)' so a truncated finding
    that gets re-submitted under a slightly different title is still caught
    as a duplicate of the original."""
    return _CONTINUATION_RE.sub("", (title or "").strip()).strip().lower()


def _run_cmd(cmd: list, timeout: int = 90) -> str:
    """Run a command; return stdout+stderr, cap at 5000 chars."""
    exe = shutil.which(cmd[0]) if cmd else None
    if not exe:
        return f"(tool not found: {cmd[0]} — install in Dockerfile)"
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        out = (result.stdout + result.stderr).strip()
        return out[:5000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return f"(timeout after {timeout}s — partial results may have been logged)"
    except Exception as e:
        return f"(error: {e})"


# ── Individual tool functions ─────────────────────────────────────────────────

def _tool_nmap(target: str) -> str:
    host = target.replace("https://", "").replace("http://", "").split("/")[0]
    return _run_cmd([
        "nmap", "-sV", "--open", "-T4",
        "-p", "21,22,23,25,53,80,110,143,443,445,993,995,3306,3389,5432,6379,8080,8443,8888,27017",
        "--script", "banner,http-title",
        host
    ], timeout=90)


def _tool_nuclei(target: str) -> str:
    if not shutil.which("nuclei"):
        return "(nuclei not installed — ensure Dockerfile used multi-stage build)"
    return _run_cmd([
        "nuclei", "-u", target,
        "-severity", "critical,high,medium",
        "-silent", "-no-color",
        "-timeout", "10",
        "-rl", "20"
    ], timeout=180)


def _tool_httpx(target: str) -> str:
    if not shutil.which("httpx"):
        return "(httpx not installed)"
    host = target.replace("https://", "").replace("http://", "").split("/")[0]
    return _run_cmd([
        "httpx", "-u", host,
        "-title", "-status-code", "-tech-detect",
        "-content-length", "-follow-redirects", "-silent",
        "-no-color"
    ], timeout=30)


def _tool_subfinder(target: str) -> str:
    if not shutil.which("subfinder"):
        return "(subfinder not installed)"
    host = target.replace("https://", "").replace("http://", "").split("/")[0]
    parts = host.split(".")
    domain = ".".join(parts[-2:]) if len(parts) >= 2 else host
    return _run_cmd(["subfinder", "-d", domain, "-silent", "-t", "20"], timeout=90)


def _tool_testssl(target: str) -> str:
    """Deep TLS/SSL analysis: protocols, cipher suites, known vulnerabilities."""
    if not shutil.which("testssl.sh"):
        return "(testssl.sh not installed)"
    host = target.replace("https://", "").replace("http://", "").split("/")[0]
    return _run_cmd([
        "testssl.sh",
        "--quiet", "--no-color",
        "--severity", "MEDIUM",
        "--fast",
        host
    ], timeout=180)


def _tool_nikto(target: str) -> str:
    """Web vulnerability scan: OWASP misconfigs, outdated software, dangerous files."""
    if not shutil.which("nikto"):
        return "(nikto not installed)"
    url = target if target.startswith("http") else f"https://{target}"
    return _run_cmd([
        "nikto",
        "-h", url,
        "-nointeractive",
        "-maxtime", "120s",
        "-Tuning", "1234578"   # file upload, auth bypass, injections, info, command exe, XSS+SQL
    ], timeout=150)


def _tool_dns_audit(target: str) -> str:
    """DNS security: SPF, DMARC, DKIM, zone transfer, DNSSEC."""
    host = target.replace("https://", "").replace("http://", "").split("/")[0]
    parts = host.split(".")
    domain = ".".join(parts[-2:]) if len(parts) >= 2 else host
    results = []

    def dig(qtype: str, name: str, server: str = "8.8.8.8") -> str:
        out = _run_cmd(["dig", "+short", qtype, name, f"@{server}"], timeout=15)
        return out

    # SPF
    spf = dig("TXT", domain)
    if "v=spf1" in spf:
        results.append(f"SPF: FOUND — {spf[:300]}")
    else:
        results.append("SPF: NOT FOUND — E-Mail-Spoofing möglich (Art. 32 DSGVO)")

    # DMARC
    dmarc = dig("TXT", f"_dmarc.{domain}")
    if "v=DMARC1" in dmarc:
        policy = "none" if "p=none" in dmarc else ("quarantine" if "p=quarantine" in dmarc else "reject")
        results.append(f"DMARC: FOUND (policy={policy}) — {dmarc[:200]}")
        if policy == "none":
            results.append("DMARC policy=none — kein Schutz, nur Monitoring (schwach)")
    else:
        results.append("DMARC: NOT FOUND — Phishing-Risiko, keine E-Mail-Authentifizierung")

    # DKIM (common selectors)
    dkim_found = False
    for sel in ["default", "google", "mail", "k1", "dkim", "selector1", "selector2", "s1", "s2"]:
        out = dig("TXT", f"{sel}._domainkey.{domain}")
        if "v=DKIM1" in out:
            results.append(f"DKIM: FOUND (selector={sel})")
            dkim_found = True
            break
    if not dkim_found:
        results.append("DKIM: NOT FOUND (gängige Selektoren geprüft) — E-Mail-Signierung fehlt")

    # DNSSEC
    ds = dig("DS", domain)
    dnskey = dig("DNSKEY", domain)
    if ds or dnskey:
        results.append("DNSSEC: ENABLED")
    else:
        results.append("DNSSEC: NOT ENABLED — DNS-Spoofing möglich")

    # Zone transfer (AXFR)
    ns_raw = dig("NS", domain)
    ns_list = [n.strip().rstrip(".") for n in ns_raw.splitlines() if n.strip()]
    zt_possible = False
    for ns in ns_list[:3]:
        axfr = _run_cmd(["dig", "AXFR", domain, f"@{ns}"], timeout=15)
        if axfr and "Transfer failed" not in axfr and "REFUSED" not in axfr and len(axfr) > 200:
            results.append(f"DNS ZONE TRANSFER POSSIBLE via {ns} — kritisches Sicherheitsproblem!")
            zt_possible = True
            break
    if not zt_possible:
        results.append("DNS Zone Transfer: gesperrt (OK)")

    # MX records
    mx = dig("MX", domain)
    if mx:
        results.append(f"MX: {mx[:200]}")

    return "\n".join(results)


def _tool_cookie_check(target: str) -> str:
    """Check cookie security flags: Secure, HttpOnly, SameSite."""
    import urllib.request, ssl
    url = target if target.startswith("http") else f"https://{target}"
    results = []
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (NIS2-Audit/2.0)"})
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            set_cookies = resp.headers.get_all("Set-Cookie") or []
            if not set_cookies:
                return "No Set-Cookie headers found"
            for raw in set_cookies:
                name = raw.split("=")[0].strip()
                low  = raw.lower()
                issues = []
                if "secure" not in low:
                    issues.append("MISSING Secure flag — Cookie über HTTP übertragbar")
                if "httponly" not in low:
                    issues.append("MISSING HttpOnly — JavaScript kann Cookie lesen (XSS-Risiko)")
                if "samesite" not in low:
                    issues.append("MISSING SameSite — CSRF-Risiko")
                elif "samesite=none" in low:
                    issues.append("SameSite=None — Cross-Site-Zugriff explizit erlaubt")
                if issues:
                    results.append(f"Cookie '{name}': " + "; ".join(issues))
                else:
                    results.append(f"Cookie '{name}': OK (Secure, HttpOnly, SameSite gesetzt)")
    except Exception as e:
        return f"Cookie-Check fehlgeschlagen: {e}"
    return "\n".join(results) if results else "Keine Set-Cookie-Header gefunden"


def _tool_dnsx(target: str) -> str:
    """Validiert DNS-Auflösung für eine Domain + gängige Subdomains (schnell, passiv)."""
    if not shutil.which("dnsx"):
        return "(dnsx not installed)"
    host = target.replace("https://", "").replace("http://", "").split("/")[0]
    parts = host.split(".")
    domain = ".".join(parts[-2:]) if len(parts) >= 2 else host
    candidates = [host] + [f"{sub}.{domain}" for sub in
                            ("www", "api", "admin", "mail", "vpn", "dev", "staging", "test", "portal")]
    input_data = "\n".join(dict.fromkeys(candidates))
    try:
        result = subprocess.run(
            ["dnsx", "-silent", "-resp", "-t", "50"],
            input=input_data, capture_output=True, text=True, timeout=30
        )
        out = (result.stdout + result.stderr).strip()
        return out[:5000] if out else "(keine DNS-Einträge gefunden)"
    except Exception as e:
        return f"(error: {e})"


def _tool_gau(target: str) -> str:
    """Historische/archivierte URLs (Wayback, Common Crawl, OTX) — findet vergessene Endpunkte."""
    if not shutil.which("gau"):
        return "(gau not installed)"
    host = target.replace("https://", "").replace("http://", "").split("/")[0]
    parts = host.split(".")
    domain = ".".join(parts[-2:]) if len(parts) >= 2 else host
    out = _run_cmd([
        "gau", domain,
        "--blacklist", "png,jpg,gif,jpeg,svg,ico,css,woff,woff2,ttf,mp4,mp3",
        "--threads", "5", "--timeout", "20"
    ], timeout=60)
    lines = out.splitlines()
    if len(lines) > 150:
        out = "\n".join(lines[:150]) + f"\n… ({len(lines)} URLs gesamt, gekürzt auf 150)"
    return out


def _tool_katana(target: str) -> str:
    """Web-Crawler für Endpunkt-Entdeckung (inkl. JS-Crawling), begrenzte Tiefe/Zeit."""
    if not shutil.which("katana"):
        return "(katana not installed)"
    url = target if target.startswith("http") else f"https://{target}"
    out = _run_cmd([
        "katana", "-u", url, "-silent", "-jc",
        "-depth", "2", "-concurrency", "10", "-rate-limit", "50",
        "-timeout", "10", "-crawl-duration", "60s"
    ], timeout=90)
    lines = out.splitlines()
    if len(lines) > 150:
        out = "\n".join(lines[:150]) + f"\n… ({len(lines)} URLs gesamt, gekürzt auf 150)"
    return out


def _tool_ffuf(target: str) -> str:
    """Content-Discovery: sucht nach nicht verlinkten Verzeichnissen/Dateien (kleine Wordlist)."""
    if not shutil.which("ffuf"):
        return "(ffuf not installed)"
    wordlist = "/wordlists/common.txt" if os.path.isfile("/wordlists/common.txt") else None
    if not wordlist:
        return "(kein Wordlist verfügbar)"
    url = target if target.startswith("http") else f"https://{target}"
    return _run_cmd([
        "ffuf", "-u", f"{url.rstrip('/')}/FUZZ", "-w", wordlist,
        "-mc", "200,201,301,302,403", "-t", "20", "-rate", "20",
        "-timeout", "8", "-silent"
    ], timeout=90)


def _tool_arjun(target: str) -> str:
    """Entdeckt versteckte HTTP-GET/POST-Parameter eines Endpunkts (potenzielle Angriffsfläche)."""
    if not shutil.which("arjun"):
        return "(arjun not installed)"
    url = target if target.startswith("http") else f"https://{target}"
    return _run_cmd(["arjun", "-u", url, "--stable", "-q", "-t", "10"], timeout=60)


TOOLS = {
    "nmap":         {"fn": _tool_nmap,        "desc": "Port scan + service detection (21 ports)"},
    "nuclei":       {"fn": _tool_nuclei,      "desc": "CVE & misconfiguration vulnerability scan"},
    "httpx":        {"fn": _tool_httpx,       "desc": "HTTP probe: status, title, tech stack"},
    "subfinder":    {"fn": _tool_subfinder,   "desc": "Subdomain enumeration"},
    "testssl":      {"fn": _tool_testssl,     "desc": "Deep TLS/SSL analysis: ciphers, protocols, CVEs"},
    "nikto":        {"fn": _tool_nikto,       "desc": "Web vulnerability scan (OWASP, dangerous files)"},
    "dns_audit":    {"fn": _tool_dns_audit,   "desc": "DNS: SPF, DMARC, DKIM, DNSSEC, zone transfer"},
    "cookie_check": {"fn": _tool_cookie_check,"desc": "Cookie security: Secure/HttpOnly/SameSite flags"},
    "dnsx":         {"fn": _tool_dnsx,        "desc": "DNS-Validierung für Domain + gängige Subdomains"},
    "gau":          {"fn": _tool_gau,         "desc": "Archivierte/historische URLs (Wayback, Common Crawl)"},
    "katana":       {"fn": _tool_katana,      "desc": "Web-Crawler: entdeckt Endpunkte inkl. JS-Routen"},
    "ffuf":         {"fn": _tool_ffuf,        "desc": "Content-Discovery: unverlinkte Verzeichnisse/Dateien"},
    "arjun":        {"fn": _tool_arjun,       "desc": "Findet versteckte HTTP-Parameter eines Endpunkts"},
}

SYSTEM_PROMPT = """You are an expert cybersecurity auditor specializing in NIS2 (§30 BSIG) and DSGVO compliance for German businesses.
Conduct a thorough, professional security audit of the target and produce findings suitable for regulatory submission.

LANGUAGE REQUIREMENT: ALL finding titles, descriptions, and recommendations MUST be written in German.
Do NOT use English in any finding field. Use professional German IT-security terminology.

AUDIT WORKFLOW (follow this order):
1. httpx — identify tech stack, server, redirects
2. nmap — discover open ports, running services, banners
3. testssl — deep TLS/SSL analysis (ciphers, protocols, certificate, CVEs like POODLE/BEAST/Heartbleed)
4. subfinder — enumerate subdomains, find shadow IT
5. dnsx — validate which of the discovered subdomains actually resolve (avoid chasing dead hosts)
6. dns_audit — check SPF, DMARC, DKIM, DNSSEC, zone transfer
7. cookie_check — validate cookie security flags
8. gau + katana — discover additional URLs/endpoints (archived + crawled) beyond the homepage
9. ffuf — content discovery for unlinked directories/files on the main host
10. arjun — on 1-2 of the most interesting discovered endpoints (e.g. with query params or forms),
    check for hidden HTTP parameters
11. nuclei — scan for CVEs and misconfigurations (use additional URLs from gau/katana as targets too
    if they look distinct/interesting, not just the homepage)
12. nikto — web vulnerability scan (OWASP Top 10, dangerous files)
13. Analyze all results comprehensively
14. Add findings for EVERY discovered issue
15. finish_audit with a professional summary in German

Note: gau/katana/ffuf/arjun are recon/discovery tools, not vulnerability scanners — they rarely
produce findings by themselves. Only add a finding from their output if something CONCRETE and
security-relevant is visible (e.g. an exposed /admin/backup.zip, a leaked API key in an archived
URL, an endpoint with obvious debug/staging parameters). Do not create findings just because a
URL exists — that is normal recon noise, not a vulnerability.

FINDING REQUIREMENTS:
- title: short descriptive title IN GERMAN (max 80 chars)
- description: detailed technical description IN GERMAN
- recommendation: remediation steps IN GERMAN
- severity: critical/high/medium/low/info
- ALWAYS set cvss score for critical/high/medium/low findings (e.g. "7.5 (AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N)")
  - critical: 9.0–10.0, high: 7.0–8.9, medium: 4.0–6.9, low: 2.0–3.9
  - info findings: cvss may be empty
- Always map to DSGVO article (Art. 32, Art. 25, Art. 33, Art. 28, etc.) and NIS2 (§30 BSIG Abs. 2 Nr. X)
- Add the target URL/hostname as the target field

SEVERITY GUIDELINES:
- critical: Remote code execution, SQL injection, exposed credentials, zone transfer possible
- high: Missing HSTS, weak TLS (<1.2), XSS, open sensitive ports (3306, 5432 public)
- medium: Missing security headers (CSP, X-Frame-Options), server banner leakage, cookie issues
- low: Missing DKIM/DMARC, DNSSEC not enabled, minor misconfigs
- info: Service enumeration results, general observations

EVIDENCE-BASED FINDING RULES (MANDATORY — violations undermine report credibility):
CVSS scores MUST ONLY be assigned for findings DIRECTLY CONFIRMED by tool output.
The following topics are NOT verifiable via black-box scan — for ALL of them you MUST use
severity=low, cvss="" (EMPTY string), and prefix the title with "[Compliance-Hinweis]":
  - AVV / Auftragsverarbeitungsvertrag — internal contract, not externally visible
  - DSFA / DPIA (Art. 35 DSGVO) — INTERNAL document, NOT required to be public
  - SIEM / Log-Management — internal infrastructure, completely invisible from outside
  - Backup-Strategie / Notfallplan — internal process, not externally verifiable
  - MFA / Multi-Faktor-Authentifizierung — only verifiable with authenticated login (out-of-scope here)
  - Verschlüsselung ruhender Daten / Data-at-Rest — not externally visible
  - API-Sicherheit / API-Dokumentation — requires authenticated API access (out-of-scope)
  - Authentifizierungsmechanismen / Zugriffsrechte — requires authenticated test (out-of-scope)
  - Incident Response Prozesse / IRP — internal document
  - Datenresidenz / Data-Residency — not externally verifiable
Example correct title: "[Compliance-Hinweis] DSFA-Dokumentation nicht nachgewiesen"
Example correct description: "Im Rahmen des Black-Box-Audits nicht verifizierbar — erfordert Einsicht in interne Dokumentation / Interview mit Auftraggeber."
Do NOT assign CVSS 4.0+ to any of the above. "Fehlende DSFA" cannot have CVSS 7.1 —
you have zero black-box evidence of actual vulnerability impact.

Additional rules:
- WAF: If Cloudflare or CDN/reverse-proxy detected (httpx output) → severity=info, cvss="",
  title: "[Compliance-Hinweis] WAF-Ruleset nicht extern verifizierbar"
  (Cloudflare itself is a WAF — rule-set just cannot be confirmed from outside)
- MX Records: Absence of MX is often intentional (domain may not send mail) → severity=info, cvss="" only
- DNSSEC: ONLY create a positive DNSSEC finding if `dig DNSKEY <domain>` returns an ACTUAL DNSKEY record
  in the tool output. If the output is empty, shows NXDOMAIN, or shows no DNSKEY record, do NOT create
  a positive finding. Do NOT write titles like "DNSSEC erfolgreich implementiert" unless you can quote
  the exact DNSKEY record from the tool output. When DNSSEC is absent, create a LOW finding instead.
- HSTS: Only write "HSTS erfolgreich implementiert" if max-age >= 31536000 (1 year). If max-age is
  present but less than 1 year (e.g. 15552000 = 180 days), create a LOW finding
  "HSTS max-age zu kurz (<1 Jahr)" instead of a positive finding.

Complete within {max_iter} iterations. Be thorough — regulatory-grade report required.
"""

TOOLS_SPEC = [
    {
        "name": "run_tool",
        "description": "Run a security scanning tool against the target",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool": {
                    "type": "string",
                    "enum": list(TOOLS.keys()),
                    "description": "Tool name to run"
                },
                "target": {
                    "type": "string",
                    "description": "Target URL or domain (include https:// for web tools)"
                }
            },
            "required": ["tool", "target"]
        }
    },
    {
        "name": "add_finding",
        "description": "Add a security finding to the audit report",
        "input_schema": {
            "type": "object",
            "properties": {
                "title":          {"type": "string", "description": "Short, descriptive title IN GERMAN (max 80 chars)"},
                "description":    {"type": "string", "description": "Detailed description of the vulnerability/finding"},
                "severity":       {"type": "string", "enum": ["critical","high","medium","low","info"]},
                "recommendation": {"type": "string", "description": "How to fix this (in German)"},
                "cvss":           {"type": "string", "description": "CVSS v3.1 score, e.g. 7.5"},
                "dsgvo_article":  {"type": "string", "description": "Applicable DSGVO article and NIS2 reference"},
                "target":         {"type": "string", "description": "Affected target (URL, hostname, or subdomain)"},
                "tool":           {"type": "string", "description": "Tool that detected this finding (e.g. nmap, nuclei, testssl, nikto, dns_audit, httpx, subfinder, cookie_check, live_check)"}
            },
            "required": ["title", "description", "severity", "recommendation"]
        }
    },
    {
        "name": "log_message",
        "description": "Log a status or progress message",
        "input_schema": {
            "type": "object",
            "properties": {
                "level":   {"type": "string", "enum": ["INFO","CMD","FINDING","AGENT","ERROR"]},
                "message": {"type": "string"}
            },
            "required": ["level", "message"]
        }
    },
    {
        "name": "finish_audit",
        "description": "Mark the audit as complete with a professional summary",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Professional executive summary in German (2-4 sentences)"
                }
            },
            "required": ["summary"]
        }
    }
]


def _auto_mark_tasks(order_id: int):
    """
    Auto-mark compliance tasks as done/open based on what was actually checked.
    A task is only marked as done (= compliant) if the tool ran AND no related
    negative finding was recorded for that area.
    Called after the agent completes.
    """
    findings = db_query("SELECT title, severity, description FROM findings WHERE order_id=?", (order_id,))
    logs     = db_query("SELECT message FROM audit_logs WHERE order_id=? AND level='CMD'", (order_id,))

    tools_run = set()
    for log in logs:
        for t in TOOLS:
            if t in (log.get("message") or "").lower():
                tools_run.add(t)

    # Build a set of "problem areas" from findings with medium+ severity
    problem_areas = set()
    for f in findings:
        sev = f.get("severity","info").lower()
        if sev in ("critical","high","medium"):
            txt = (f.get("title","") + " " + f.get("description","")).lower()
            if any(k in txt for k in ["tls","ssl","protokoll","cipher","zertifikat"]):
                problem_areas.add("tls")
            if any(k in txt for k in ["header","csp","hsts","x-frame","x-content",
                                       "referrer","permissions","clickjacking",
                                       "mime-sniff","content-security","corp","coop"]):
                problem_areas.add("headers")
            if any(k in txt for k in ["cookie","secure-flag","httponly","samesite"]):
                problem_areas.add("cookie")
            if any(k in txt for k in ["port","dienst","service","offen"]):
                problem_areas.add("nmap")
            if any(k in txt for k in ["schwachstelle","cve","nuclei","exploit"]):
                problem_areas.add("nuclei")
            if any(k in txt for k in ["mfa","zwei-faktor","2fa","multi-factor","authentifizierung","zugriffsrecht"]):
                problem_areas.add("mfa")
            if any(k in txt for k in ["verschlüssel","encryption","aes","tls-verschl"]):
                problem_areas.add("encryption")
            if any(k in txt for k in ["backup","datensicher","wiederherstellung","rto","rpo"]):
                problem_areas.add("backup")

    tasks = db_query("SELECT id, title, category FROM order_tasks WHERE order_id=? AND done=0", (order_id,))
    now = datetime.now().isoformat()

    for task in tasks:
        ttl = task.get("title","").lower()
        mark_done = False

        # Map tasks to tools/findings — only mark done if tool ran AND no related problem found
        if "http security header" in ttl and "httpx" in tools_run and "headers" not in problem_areas:
            mark_done = True
        if "tls/ssl" in ttl and ("testssl" in tools_run or "nmap" in tools_run) and "tls" not in problem_areas:
            mark_done = True
        if ("penetrationstest" in ttl or "web-security-check" in ttl) and ("nikto" in tools_run or "nuclei" in tools_run) and "nuclei" not in problem_areas:
            mark_done = True
        if "schwachstellen-scan" in ttl and "nuclei" in tools_run and "nuclei" not in problem_areas:
            mark_done = True
        if "port-scan" in ttl and "nmap" in tools_run and "nmap" not in problem_areas:
            mark_done = True
        if "subdomain" in ttl and "subfinder" in tools_run:
            mark_done = True
        if "dns" in ttl and "dns_audit" in tools_run:
            mark_done = True
        if "cookie" in ttl and "cookie_check" in tools_run and "cookie" not in problem_areas:
            mark_done = True

        if mark_done:
            db_execute(
                "UPDATE order_tasks SET done=1, done_at=?, notes=? WHERE id=?",
                (now, "Automatisch durch KI-Audit verifiziert — keine kritischen Befunde", task["id"])
            )


def run_audit_agent(order_id: int, target: str, company: str):
    """Main entry point — runs the Claude-powered audit agent."""
    _log(order_id, "INFO", f"Audit gestartet: {target} ({company})")
    _log(order_id, "INFO", f"Verfügbare Tools: {', '.join(TOOLS.keys())}")

    if not HAS_ANTHROPIC:
        _log(order_id, "ERROR", "anthropic library nicht installiert — pip install anthropic")
        db_execute("UPDATE orders SET status='failed',updated_at=? WHERE id=?",
                   (datetime.now().isoformat(), order_id))
        return

    if not ANTHROPIC_API_KEY:
        _log(order_id, "ERROR", "ANTHROPIC_API_KEY nicht gesetzt — KI-Audit nicht möglich")
        db_execute("UPDATE orders SET status='failed',updated_at=? WHERE id=?",
                   (datetime.now().isoformat(), order_id))
        return

    # Verify tool availability — only check tools that are actual OS binaries
    _BINARY_TOOLS = {"nmap", "nuclei", "httpx", "subfinder", "nikto",
                      "dnsx", "gau", "katana", "ffuf", "arjun"}
    _SCRIPT_TOOLS  = {"dns_audit", "cookie_check", "testssl"}  # Python functions or sh wrappers
    missing_tools = [t for t in _BINARY_TOOLS if not shutil.which(t)]
    if missing_tools:
        _log(order_id, "INFO", f"Hinweis — folgende Tools nicht im PATH: {', '.join(missing_tools)}")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    messages = [
        {
            "role": "user",
            "content": (
                f"Führe einen vollständigen NIS2/DSGVO Sicherheits-Audit durch:\n"
                f"Unternehmen: {company}\n"
                f"Prüfungsziel: {target}\n\n"
                f"Folge dem Audit-Workflow aus deinen Anweisungen. "
                f"Verwende ALLE verfügbaren Tools. "
                f"Erstelle für JEDES gefundene Problem einen separaten Befund (finding). "
                f"Der Bericht muss NIS2 §30 BSIG und DSGVO Art. 32 Standards genügen."
            )
        }
    ]

    finished = False
    api_errors = 0
    last_tool_run = ""          # tracks the most-recently executed tool for finding attribution
    tools_used    = {}          # {tool_name: {"start": iso, "end": iso, "findings": count}}
    added_finding_titles = set()  # normalized titles already saved — blocks truncated/duplicate re-submits
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    for iteration in range(MAX_ITERATIONS):
        _log(order_id, "AGENT", f"Iteration {iteration + 1}/{MAX_ITERATIONS}")

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=8192,
                system=SYSTEM_PROMPT.format(max_iter=MAX_ITERATIONS),
                tools=TOOLS_SPEC,
                messages=_compress_messages(messages),
            )
            api_errors = 0  # reset on success
            in_tok  = getattr(response.usage, "input_tokens", 0) or 0
            out_tok = getattr(response.usage, "output_tokens", 0) or 0
            price_in, price_out = _price_for(MODEL)
            usage["calls"] += 1
            usage["input_tokens"]  += in_tok
            usage["output_tokens"] += out_tok
            usage["cost_usd"] += in_tok / 1_000_000 * price_in + out_tok / 1_000_000 * price_out
        except anthropic.RateLimitError:
            _log(order_id, "INFO", "API Rate Limit — warte 30s...")
            time.sleep(30)
            continue
        except anthropic.APIStatusError as e:
            api_errors += 1
            _log(order_id, "ERROR", f"Claude API Fehler ({e.status_code}): {str(e)[:200]}")
            if api_errors >= 3:
                break
            time.sleep(5)
            continue
        except Exception as e:
            api_errors += 1
            _log(order_id, "ERROR", f"Unbekannter Fehler: {str(e)[:300]}")
            if api_errors >= 3:
                break
            continue

        assistant_content = []
        tool_results = []

        for block in response.content:
            assistant_content.append(block)

            if block.type == "text":
                if block.text.strip():
                    _log(order_id, "AGENT", block.text[:600])

            elif block.type == "tool_use":
                tool_name   = block.name
                tool_input  = block.input
                tool_use_id = block.id

                _log(order_id, "CMD", f"[{tool_name}] {json.dumps(tool_input)[:250]}")

                # ── Execute tool ──────────────────────────────────────────────
                if tool_name == "run_tool":
                    t   = tool_input.get("tool")
                    tgt = tool_input.get("target", target)
                    if t in TOOLS:
                        t_start = datetime.now()
                        last_tool_run = t
                        tools_used.setdefault(t, {"start": t_start.isoformat(), "end": "", "findings": 0})
                        _log(order_id, "CMD", f"▶ {t} gestartet ({tgt})")
                        output = TOOLS[t]["fn"](tgt)
                        t_dur = int((datetime.now() - t_start).total_seconds())
                        tools_used[t]["end"] = datetime.now().isoformat()
                        _log(order_id, "OUT", output[:400])
                        _log(order_id, "CMD", f"✓ {t} abgeschlossen ({t_dur}s)")
                    else:
                        output = f"Unbekanntes Tool: {t}"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": output
                    })

                elif tool_name == "add_finding":
                    finding_tool = tool_input.get("tool", "") or last_tool_run
                    title = tool_input.get("title", "")
                    desc = tool_input.get("description", "")
                    rec  = tool_input.get("recommendation", "")
                    norm_title = _normalize_finding_title(title)

                    if _is_english(desc) or _is_english(rec):
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": (
                                "FEHLER: Beschreibung oder Empfehlung ist auf Englisch. "
                                "Bitte das Finding VOLLSTÄNDIG auf Deutsch neu erstellen. "
                                "Kein englischer Text erlaubt."
                            ),
                        })
                        _log(order_id, "WARN",
                             f"Englisches Finding abgelehnt: {title[:60]}")
                    elif len(rec.strip()) < 10:
                        # Meist Folge einer bei max_tokens abgeschnittenen Tool-Antwort:
                        # description kam noch durch, recommendation fehlt/ist ein Stub.
                        # Lieber ablehnen und den Agenten zur vollständigen Neuerstellung
                        # zwingen, als ein halbfertiges Finding im Kundenbericht landen zu lassen.
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": (
                                "FEHLER: Feld 'recommendation' fehlt oder ist zu kurz. "
                                "Erstelle dieses Finding NEU in EINEM Tool-Call mit vollständiger, "
                                "konkreter Empfehlung (recommendation). Keine Platzhalter, keine "
                                "Aufteilung in mehrere Findings."
                            ),
                        })
                        _log(order_id, "WARN",
                             f"Finding ohne Empfehlung abgelehnt: {title[:60]}")
                    elif norm_title and norm_title in added_finding_titles:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": (
                                "FEHLER: Ein Finding mit diesem (oder sehr ähnlichem) Titel wurde "
                                "bereits gespeichert. Kein Duplikat/Fortsetzung anlegen — falls das "
                                "vorherige Finding unvollständig war, wurde es bereits abgelehnt und "
                                "muss stattdessen unter demselben Titel VOLLSTÄNDIG neu erstellt werden."
                            ),
                        })
                        _log(order_id, "WARN",
                             f"Doppeltes Finding abgelehnt: {title[:60]}")
                    else:
                        added_finding_titles.add(norm_title)
                        _add_finding(
                            order_id,
                            title          = tool_input.get("title",""),
                            description    = desc,
                            severity       = tool_input.get("severity","info"),
                            recommendation = rec,
                            cvss           = tool_input.get("cvss",""),
                            dsgvo_article  = tool_input.get("dsgvo_article",""),
                            target         = tool_input.get("target", target),
                            tool           = finding_tool,
                        )
                        if finding_tool in tools_used:
                            tools_used[finding_tool]["findings"] = tools_used[finding_tool].get("findings", 0) + 1
                        _log(order_id, "FINDING",
                             f"[{tool_input.get('severity','info').upper()}] {tool_input.get('title','')}"
                             + (f" ({finding_tool})" if finding_tool else ""))
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": "Finding gespeichert"
                        })

                elif tool_name == "log_message":
                    _log(order_id,
                         tool_input.get("level","INFO"),
                         tool_input.get("message",""))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": "Logged"
                    })

                elif tool_name == "finish_audit":
                    summary = tool_input.get("summary","")
                    _log(order_id, "INFO", f"AUDIT ABGESCHLOSSEN: {summary[:400]}")
                    _log(order_id, "TOOLS_USED", json.dumps(tools_used))
                    # Auto-mark tasks that were covered by tools
                    _auto_mark_tasks(order_id)
                    db_execute("UPDATE orders SET status='done',updated_at=? WHERE id=?",
                               (datetime.now().isoformat(), order_id))
                    finished = True
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": "Audit abgeschlossen und gespeichert"
                    })

        messages.append({"role": "assistant", "content": assistant_content})
        if tool_results:
            messages.append({"role": "user", "content": tool_results})

        if finished or response.stop_reason == "end_turn":
            break

    if not finished:
        _log(order_id, "INFO", "Audit abgeschlossen (Iterationslimit erreicht)")
        _log(order_id, "TOOLS_USED", json.dumps(tools_used))
        _auto_mark_tasks(order_id)
        db_execute("UPDATE orders SET status='done',updated_at=? WHERE id=?",
                   (datetime.now().isoformat(), order_id))

    _log(order_id, "INFO",
         f"LLM-Nutzung Hauptlauf ({MODEL}): {usage['calls']} Calls, "
         f"{usage['input_tokens']} Input-/{usage['output_tokens']} Output-Tokens, "
         f"geschätzte Kosten: ${usage['cost_usd']:.4f}")

    verify_usage = _verify_high_severity_findings(order_id, messages, client)

    total_cost = usage["cost_usd"] + verify_usage["cost_usd"]
    total_calls = usage["calls"] + verify_usage["calls"]
    _log(order_id, "INFO",
         f"LLM-Nutzung gesamt: {total_calls} Calls, geschätzte Kosten: ${total_cost:.4f}")
    db_execute("UPDATE orders SET llm_cost_usd=? WHERE id=?", (round(total_cost, 6), order_id))


def _verify_high_severity_findings(order_id: int, messages: list, client) -> dict:
    """Verifikations-/Filter-Schritt für alle critical/high Findings: prüft jeden Befund
    noch einmal GEGEN die im Konversationsverlauf bereits sichtbaren Roh-Ausgaben der Tools
    und stuft unbelegte Befunde herab statt sie unkommentiert im Bericht zu lassen. Keine
    aktive Nachprüfung/Exploitation — reine Re-Analyse der bereits erhobenen (passiven)
    Tool-Ausgaben, angelehnt an ein PoC-/Plausibilitäts-Review vor dem Kundenbericht."""
    verify_usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    findings = db_query(
        "SELECT id,title,description,severity,tool,target FROM findings "
        "WHERE order_id=? AND severity IN ('critical','high')", (order_id,)
    )
    if not findings:
        _log(order_id, "INFO", "Verifikation: keine kritischen/hohen Befunde vorhanden")
        return verify_usage

    _log(order_id, "INFO",
         f"Verifikation von {len(findings)} kritischen/hohen Befunden gestartet (Modell: {MODEL_VERIFY})")

    findings_block = "\n".join(
        f"- ID {f['id']} [{f['severity'].upper()}] {f['title']} (Tool: {f['tool']}, Ziel: {f['target']})\n"
        f"  Beschreibung: {(f['description'] or '')[:300]}"
        for f in findings
    )
    verify_prompt = (
        "Du hast oben einen Sicherheitsaudit durchgeführt. Bevor der Bericht an den Kunden geht, "
        "prüfe JEDEN der folgenden kritischen/hohen Befunde noch einmal GEGEN die bereits "
        "angezeigten Roh-Ausgaben der Tools in diesem Verlauf. Ist der Befund direkt und "
        "eindeutig durch die Tool-Ausgabe belegt? Wenn ja: confirmed. Wenn die Ausgabe die "
        "Schwere nicht eindeutig rechtfertigt, du sie nicht mehr im Verlauf findest, oder es sich "
        "eigentlich nur um eine informative Beobachtung ohne konkreten Nachweis handelt: "
        "downgrade (mit kurzer Begründung auf Deutsch).\n\n"
        f"{findings_block}\n\n"
        "Rufe submit_verification GENAU EINMAL für ALLE oben aufgelisteten IDs auf."
    )
    verify_tool = {
        "name": "submit_verification",
        "description": "Reicht die Verifikationsergebnisse für alle geprüften Findings ein",
        "input_schema": {
            "type": "object",
            "properties": {
                "verdicts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "finding_id": {"type": "integer"},
                            "verdict":    {"type": "string", "enum": ["confirmed", "downgrade"]},
                            "reason":     {"type": "string", "description": "Nur bei downgrade, auf Deutsch"}
                        },
                        "required": ["finding_id", "verdict"]
                    }
                }
            },
            "required": ["verdicts"]
        }
    }

    try:
        response = client.messages.create(
            model=MODEL_VERIFY,
            max_tokens=2048,
            messages=_compress_messages(messages) + [{"role": "user", "content": verify_prompt}],
            tools=[verify_tool],
            tool_choice={"type": "tool", "name": "submit_verification"},
        )
        in_tok  = getattr(response.usage, "input_tokens", 0) or 0
        out_tok = getattr(response.usage, "output_tokens", 0) or 0
        price_in, price_out = _price_for(MODEL_VERIFY)
        verify_usage.update(
            calls=1, input_tokens=in_tok, output_tokens=out_tok,
            cost_usd=in_tok / 1_000_000 * price_in + out_tok / 1_000_000 * price_out,
        )
    except Exception as e:
        _log(order_id, "ERROR", f"Verifikation fehlgeschlagen (übersprungen): {e}")
        return verify_usage

    verdicts = []
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_verification":
            verdicts = block.input.get("verdicts", [])

    confirmed, downgraded = 0, 0
    for v in verdicts:
        fid = v.get("finding_id")
        if not isinstance(fid, int):
            continue
        if v.get("verdict") == "downgrade":
            reason = v.get("reason", "")
            db_execute(
                "UPDATE findings SET severity='low',severity_rank=4,cvss='',"
                "title='[Unbestätigt] ' || title WHERE id=? AND severity IN ('critical','high')",
                (fid,)
            )
            _log(order_id, "WARN", f"Finding #{fid} bei Verifikation herabgestuft: {reason[:200]}")
            downgraded += 1
        else:
            confirmed += 1

    _log(order_id, "INFO", f"Verifikation abgeschlossen: {confirmed} bestätigt, {downgraded} herabgestuft")
    return verify_usage
