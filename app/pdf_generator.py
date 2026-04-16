"""
PDF Generator — WeasyPrint (echtes PDF) mit HTML-Fallback
"""
from datetime import datetime
import os
import json

try:
    from weasyprint import HTML as _WP_HTML
    HAS_WEASYPRINT = True
except Exception:
    HAS_WEASYPRINT = False

COMPANY   = "AndriiIT"
WEBSITE   = "https://www.andrii-it.de"
FULL_NAME = "AndriiIT | IT-Sicherheitsdienstleistungen"
ADDRESS   = "Bergmannweg 16, 65934 Frankfurt am Main, Deutschland"
EMAIL     = "info@andrii-it.de"
PHONE     = "+49 160 95030120"
UST_ID    = "USt-IdNr.: DE456902445"

def esc(s):
    if not s: return ""
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def _save_html(html, out_path):
    path = out_path.replace(".pdf", ".html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def _save_pdf(html, out_path):
    """Generate real PDF via WeasyPrint; fall back to HTML if unavailable."""
    if HAS_WEASYPRINT:
        pdf_path = out_path if out_path.endswith(".pdf") else out_path.replace(".html", ".pdf")
        try:
            _WP_HTML(string=html).write_pdf(pdf_path)
            return pdf_path
        except Exception:
            pass
    return _save_html(html, out_path)

PRINT_CSS = """
<style>
@page { size: A4; margin: 2cm 2.5cm; margin-top: 2cm; margin-bottom: 2cm; }
@media print {
  @page { margin-top: 2cm; margin-bottom: 2cm; }
  html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .no-print { display:none!important; }
  body { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  .pb { page-break-before:always; }
  * { -webkit-margin-before: 0; }
}
* { box-sizing:border-box; margin:0; padding:0; }
body { font-family:Arial,Helvetica,sans-serif; color:#1a1a2e; font-size:11px; line-height:1.6; }
.print-bar { background:#1a1a2e; color:#fff; padding:10px 24px; display:flex; justify-content:space-between; align-items:center; position:sticky; top:0; z-index:99; }
.print-bar h2 { font-size:13px; font-weight:600; }
.btn-print { background:#e94560; color:#fff; border:none; padding:8px 20px; border-radius:6px; font-size:13px; font-weight:700; cursor:pointer; }
.cover { background:#1a1a2e; color:#fff; min-height:26cm; text-align:center; padding:50px 40px; page-break-after:always; }
.cover-logo { font-size:26px; font-weight:700; color:#e94560; margin-bottom:4px; }
.cover-sub  { font-size:12px; color:#a8b2d8; margin-bottom:44px; }
.cover h1   { font-size:28px; font-weight:700; margin-bottom:10px; }
.cover-box  { display:inline-block; border:1px solid rgba(255,255,255,.22); border-radius:10px; padding:16px 32px; margin:10px 4px; }
.cover-box .lbl { font-size:9px; color:#a8b2d8; text-transform:uppercase; letter-spacing:2px; }
.cover-box .val { font-size:15px; font-weight:600; color:#e2e8f0; margin-top:4px; }
.cover-meta { font-size:11px; color:#a8b2d8; margin-top:22px; line-height:2.1; }
.cover-seal { display:inline-block; margin-top:32px; padding:5px 18px; border:1px solid #e94560; border-radius:20px; font-size:10px; color:#e94560; font-weight:700; letter-spacing:1px; }
.cover-amount { font-size:24px; font-weight:700; color:#e94560; margin-top:22px; }
.cbadge { background:rgba(255,255,255,.1); padding:4px 10px; border-radius:10px; font-size:10px; margin:2px; display:inline-block; }
h2 { font-size:14px; font-weight:700; color:#1a1a2e; border-bottom:2px solid #e94560; padding-bottom:5px; margin:22px 0 12px; }
h3 { font-size:12px; font-weight:700; margin:13px 0 6px; color:#2d3a4a; }
table { width:100%; border-collapse:collapse; margin:10px 0; font-size:10px; }
table th { background:#1a1a2e; color:#fff; padding:6px 8px; text-align:left; }
table td { padding:5px 8px; border-bottom:1px solid #e8e8e8; vertical-align:top; }
table tr:nth-child(even) td { background:#f8f9fa; }
.info-table td:first-child { font-weight:700; width:35%; color:#555; }
.ok   { color:#16a34a; font-weight:700; }
.fail { color:#dc2626; font-weight:700; }
.warn { color:#d97706; }
.badge { display:inline-block; padding:2px 8px; border-radius:10px; font-size:9px; font-weight:700; color:#fff; }
.badge-critical { background:#dc2626; }
.badge-high     { background:#e67e22; }
.badge-medium   { background:#d4a017; color:#333; }
.badge-low      { background:#16a34a; }
.badge-info     { background:#2980b9; }
.stats-row { display:flex; gap:8px; margin:14px 0; }
.stat-cell { flex:1; text-align:center; padding:12px 8px; background:#f8f9fa; border-radius:6px; border:1px solid #e8e8e8; }
.stat-num  { font-size:22px; font-weight:700; display:block; }
.finding { margin:10px 0; padding:10px 12px; border-left:4px solid #ddd; background:#fafafa; }
.finding.critical { border-color:#dc2626; background:#fff5f5; }
.finding.high     { border-color:#e67e22; background:#fffaf0; }
.finding.medium   { border-color:#d4a017; background:#fffdf0; }
.finding.low      { border-color:#16a34a; background:#f0fff4; }
.finding.info     { border-color:#2980b9; background:#f0f8ff; }
.finding-title { font-weight:700; font-size:12px; margin-bottom:4px; }
.finding-meta  { font-size:9px; color:#666; margin-bottom:5px; }
.warn-box  { background:#fff8f0; border:1px solid #e67e22; border-radius:4px; padding:8px 12px; margin:8px 0; font-size:10px; }
.green-box { background:#f0fdf4; border:1px solid #16a34a; border-radius:4px; padding:8px 12px; margin:8px 0; font-size:10px; font-weight:700; color:#16a34a; }
.sig-table td { padding:12px; border:1px solid #ddd; vertical-align:top; width:50%; }
.sig-line { border-top:1px solid #333; margin-top:50px; padding-top:4px; font-size:9px; color:#999; }
.footer { margin-top:28px; padding-top:10px; border-top:1px solid #eee; font-size:9px; color:#999; text-align:center; }
ul { margin-left:16px; font-size:10px; line-height:1.9; }
</style>"""

def generate_angebot_pdf(out_path, client, target, amount, scope, angebot_num):
    """Generate Angebot as real PDF (WeasyPrint) with HTML fallback."""
    from datetime import timedelta
    today  = datetime.now()
    now    = today.strftime("%d.%m.%Y")
    valid  = (today + timedelta(days=30)).strftime("%d.%m.%Y")

    services = [
        ("Penetrationstest (Blackbox)","OWASP Top 10, SQL-Injection, XSS, CSRF, Directory Traversal, Broken Authentication","3–5 Werktage"),
        ("TLS/SSL-Sicherheitsanalyse","Protokollversionen, Cipher-Suites, Zertifikatsvalidierung, HSTS","Nach Auftrag"),
        ("HTTP Security-Header-Audit","CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, CORP/COOP","Nach Auftrag"),
        ("DSGVO & NIS2 Compliance","Art. 5/25/32/33 DSGVO · §25 TTDSG · NIS2/§30 BSIG · Bußgeldrisiko-Bewertung","Nach Auftrag"),
        ("Schwachstellen-Scanning (Nuclei)","CVE-Templates, Fehlkonfigurationen, sensible Endpunkte","Nach Auftrag"),
        ("Subdomain-Enumeration & DNS","Subdomains, DNS-Zonenübertragungen, Dangling DNS, Shadow-IT","Nach Auftrag"),
        ("Prüfungsbericht (PDF, Deutsch)","CVSS-Bewertung, DSGVO/NIS2-Mapping, Empfehlungen, Retest-Plan. Behördenkonform.","7 Werktage"),
        ("Retest nach Behebung","Erneute Prüfung und Bestätigung","Nach Behebung"),
    ]
    rows = "".join(f"<tr><td>{i}</td><td><b>{esc(t)}</b><br><span style='font-size:9px;color:#666'>{esc(d)}</span></td><td style='white-space:nowrap'>{esc(dl)}</td></tr>"
                   for i,(t,d,dl) in enumerate(services,1))

    html = f"""<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8"><title>Angebot {esc(angebot_num)}</title>{PRINT_CSS}</head><body>
<div class="print-bar no-print">
  <h2>Angebot {esc(angebot_num)} · {esc(client.get('company',''))}</h2>
  <button class="btn-print" onclick="window.print()">🖨 Als PDF drucken</button>
</div>
<div class="cover">
  <div class="cover-logo">{esc(COMPANY)}</div>
  <div class="cover-sub">IT-Sicherheitsdienstleistungen · Penetration Testing · DSGVO / NIS2 Compliance</div>
  <h1>Angebot</h1>
  <p style="font-size:13px;color:#a8b2d8;margin-bottom:22px">Cybersicherheitsdienstleistungen &amp; Penetrationstest</p>
  <div class="cover-box"><div class="lbl">Angebotsnummer</div><div class="val">{esc(angebot_num)}</div></div>
  <div class="cover-box"><div class="lbl">Datum</div><div class="val">{now}</div></div>
  <div class="cover-box"><div class="lbl">Gültig bis</div><div class="val">{valid}</div></div>
  <div class="cover-meta"><b>Auftraggeber:</b> {esc(client.get('company',''))}<br>
  {esc(client.get('address',''))} · {esc(client.get('email',''))}<br>
  <b>Prüfungsziel:</b> {esc(target)}<br><br>
  <b>Anbieter:</b> {esc(COMPANY)} · {esc(ADDRESS)}<br>
  {esc(EMAIL)} · {esc(PHONE)} · {esc(UST_ID)}</div>
  <div class="cover-amount">AUFTRAGSSUMME: {esc(amount)} EUR</div>
  <div style="margin-top:12px">
    <span class="cbadge">✓ NIS2 / §30 BSIG</span>
    <span class="cbadge">✓ DSGVO Art. 32</span>
    <span class="cbadge">✓ BSI IT-Grundschutz</span>
    <span class="cbadge">✓ OWASP Top 10</span>
  </div>
  <div class="cover-seal">⚠ VERTRAULICHES ANGEBOT</div>
</div>
<div style="padding:0 0 20px">
<div style="background:#f0f4ff;border:1px solid #a8b2d8;border-radius:6px;padding:10px 14px;margin-bottom:14px;font-size:9px;color:#1a1a2e">
ℹ <b>Hinweis zur Leistungserbringung:</b> Die Sicherheitsprüfung wird mit KI-gestützten Analyse- und Security-Tools durchgeführt und durch einen Experten geprüft und freigegeben. Es handelt sich um einen <em>automatisierten Web-Security-Check mit manueller Expertenprüfung</em>, keinen vollumfänglichen manuellen Penetrationstest durch zertifizierte BSI-Prüfer.</div>
<h2>Leistungsumfang</h2>
<table><thead><tr><th style="width:4%">#</th><th>Leistung</th><th style="width:14%">Liefertermin</th></tr></thead>
<tbody>{rows}</tbody></table>
<table style="margin-top:6px"><tr>
<td style="text-align:right;font-weight:700;font-size:13px;border:none">Gesamtbetrag (inkl. MwSt.):</td>
<td style="font-weight:700;font-size:15px;color:#e94560;width:160px;border:none">{esc(amount)} EUR</td>
</tr></table>
<h2>Bedingungen</h2>
<table class="info-table">
<tr><td>Zahlungsbedingungen</td><td>50% Anzahlung bei Auftragserteilung, 50% nach Berichtsübergabe</td></tr>
<tr><td>Vertragslaufzeit</td><td>Einmalauftrag. Verlängerung auf Wunsch möglich.</td></tr>
<tr><td>Testumgebung</td><td>Ausschließlich auf schriftlich freigegebenen Systemen (§202a StGB)</td></tr>
<tr><td>Vertraulichkeit</td><td>Alle Informationen streng vertraulich. NDA auf Wunsch möglich.</td></tr>
<tr><td>Haftung</td><td>Nur bei grober Fahrlässigkeit oder Vorsatz, begrenzt auf Auftragssumme</td></tr>
</table>
<h2>Auftragserteilung und Unterschrift</h2>
<p style="font-size:10px;margin-bottom:18px">Mit Unterzeichnung erteilt der Auftraggeber {esc(COMPANY)} den Auftrag und bestätigt die Autorisierung (§202a StGB).</p>
<table class="sig-table"><tr>
<td><b>AUFTRAGGEBER</b><br><br>{esc(client.get('company',''))}<br>{esc(client.get('address',''))}<br><br>
Datum: ______________________<br><div class="sig-line">Unterschrift / Stempel des Auftraggebers</div></td>
<td><b>AUFTRAGNEHMER</b><br><br><b>{esc(COMPANY)}</b><br>{esc(ADDRESS)}<br>
E-Mail: {esc(EMAIL)}<br>Tel.: {esc(PHONE)}<br>{esc(UST_ID)}<br>{esc(WEBSITE)}<br><br>
Datum: {now}<br><div class="sig-line">Unterschrift / Stempel {esc(COMPANY)}</div></td>
</tr></table>
<div class="footer">{esc(FULL_NAME)} · {esc(WEBSITE)} · {esc(EMAIL)} · {esc(PHONE)}<br>
{esc(UST_ID)} · {esc(ADDRESS)}<br>
Angebot Nr. {esc(angebot_num)} · Erstellt am {now} · Gültig bis {valid}<br>
NIS2/§30 BSIG · DSGVO Art. 32 · BSI IT-Grundschutz · OWASP Top 10 (2021) · CVSS v3.1</div>
</div></body></html>"""
    return _save_pdf(html, out_path)


def _build_protocol_rows(tools_used: dict, logs: list, target: str) -> str:
    """Build HTML rows for the Prüfungsprotokoll table."""
    TOOL_INFO = {
        "httpx":        ("httpx (ProjectDiscovery)",     "HTTP-Status, Server-Banner, Tech-Stack, Weiterleitungen"),
        "nmap":         ("Nmap 7.x",                     "Port-Scan (21 Ports), Dienst-Erkennung, Banner-Grabbing"),
        "testssl":      ("testssl.sh 3.x",               "TLS-Protokolle, Cipher-Suites, Zertifikat, TLS-CVEs"),
        "subfinder":    ("Subfinder (ProjectDiscovery)", "Passive Subdomain-Enumeration, Shadow-IT"),
        "dns_audit":    ("DNS Audit (dig)",              "SPF, DMARC, DKIM, DNSSEC, Zone-Transfer, MX"),
        "cookie_check": ("Cookie-Check (intern)",         "Secure/HttpOnly/SameSite-Flags"),
        "nuclei":       ("Nuclei (ProjectDiscovery)",    "CVE-Templates, Fehlkonfigurationen, sensible Endpunkte"),
        "nikto":        ("Nikto 2.x",                    "OWASP Top 10, gefährliche Dateien, Web-Misconfigs"),
    }
    rows = ""
    idx = 1

    # 1. Rows from tools_used dict (logged by agent)
    for tool_name, info in tools_used.items():
        label, desc = TOOL_INFO.get(tool_name, (tool_name.replace("_"," ").title(), "Security-Analyse"))
        start = (info.get("start","") or "")[:16].replace("T"," ")
        end   = (info.get("end","")   or "")[:16].replace("T"," ")
        n_findings = info.get("findings", 0)
        rows += (f'<tr><td>{idx}</td><td><b>{esc(label)}</b></td>'
                 f'<td style="font-size:9px">{esc(start) or "—"}</td>'
                 f'<td style="font-size:9px">{esc(end) or "—"}</td>'
                 f'<td style="font-size:9px">{esc(desc)}</td>'
                 f'<td style="text-align:center;font-weight:700">{n_findings if n_findings else "—"}</td></tr>')
        idx += 1

    # 2. Reconstruct from CMD logs if tools_used is empty
    if not tools_used:
        seen = {}
        for lg in logs:
            msg   = lg.get("message","")
            ts    = (lg.get("created_at","") or "")[:16].replace("T"," ")
            level = lg.get("level","")
            if level == "CMD" and msg.startswith("▶ "):
                t = msg[2:].split(" ")[0]
                if t not in seen:
                    seen[t] = {"start": ts, "end": "", "findings": 0}
            if level == "CMD" and msg.startswith("✓ "):
                t = msg[2:].split(" ")[0]
                if t in seen:
                    seen[t]["end"] = ts
            if level == "FINDING":
                last_t = list(seen.keys())[-1] if seen else ""
                if last_t:
                    seen[last_t]["findings"] += 1
        for tool_name, info in seen.items():
            label, desc = TOOL_INFO.get(tool_name, (tool_name, "Security-Analyse"))
            rows += (f'<tr><td>{idx}</td><td><b>{esc(label)}</b></td>'
                     f'<td style="font-size:9px">{esc(info["start"]) or "—"}</td>'
                     f'<td style="font-size:9px">{esc(info["end"]) or "—"}</td>'
                     f'<td style="font-size:9px">{esc(desc)}</td>'
                     f'<td style="text-align:center;font-weight:700">{info["findings"] or "—"}</td></tr>')
            idx += 1

    # Always add Live-Check row
    rows += (f'<tr><td>{idx}</td><td><b>Live-Check (HTTP/TLS/DNS/Cookie)*</b></td>'
             f'<td style="font-size:9px" colspan="2">Bei Berichtsgenerierung</td>'
             f'<td style="font-size:9px">HTTP-Header, TLS-Zertifikat, DNS (SPF/DMARC/DKIM/DNSSEC), Cookies</td>'
             f'<td style="text-align:center;font-weight:700">—</td></tr>')
    idx += 1
    rows += (f'<tr><td>{idx}</td><td><b>NIS2/DSGVO Compliance-Checkliste (KI-Analyse)</b></td>'
             f'<td style="font-size:9px" colspan="2">Bei Berichtsgenerierung</td>'
             f'<td style="font-size:9px">§30 BSIG / DSGVO Art. 32/25/28/30/33/35 — {len(logs) and "automatisch" or "automatisch"}</td>'
             f'<td style="text-align:center;font-weight:700">—</td></tr>')
    return rows or '<tr><td colspan="6" style="text-align:center;color:#888">Keine Tool-Protokolldaten verfügbar — Bericht ohne KI-Audit generiert</td></tr>'


def generate_report_pdf(out_path, order, findings, live, tasks=None, logs=None):
    now     = datetime.now().strftime("%d.%m.%Y")
    company = order.get("company","")
    address = order.get("address","")
    target  = order.get("target","")

    # ── Parse tools_used from audit_logs ─────────────────────────────────────
    logs = logs or []
    tools_used = {}   # {tool_name: {"start", "end", "findings", "dur_s"}}
    audit_start = ""
    audit_end   = ""
    for lg in logs:
        msg   = lg.get("message","")
        ts    = lg.get("created_at","")[:16]
        level = lg.get("level","")
        if level == "TOOLS_USED":
            try:
                tools_used = json.loads(msg)
            except Exception:
                pass
        if not audit_start and level in ("INFO","AGENT"):
            audit_start = ts
        audit_end = ts  # keep updating to get last timestamp

    # Build per-tool timing from TOOLS_USED log or reconstruct from CMD logs
    if not tools_used:
        for lg in logs:
            msg = lg.get("message","")
            ts  = lg.get("created_at","")
            if lg.get("level") == "CMD" and msg.startswith("▶ "):
                tool_name = msg[2:].split(" ")[0]
                tools_used.setdefault(tool_name, {"start": ts, "end": "", "findings": 0})
            if lg.get("level") == "CMD" and msg.startswith("✓ "):
                tool_name = msg[2:].split(" ")[0]
                if tool_name in tools_used:
                    tools_used[tool_name]["end"] = ts

    # ── Tasks summary (must come before findings sync and counts) ─────────────
    tasks = tasks or []
    tasks_done  = [t for t in tasks if t.get("done")]
    tasks_open  = [t for t in tasks if not t.get("done")]
    tasks_total = len(tasks)
    tasks_pct   = int(len(tasks_done) / tasks_total * 100) if tasks_total else 0

    # ── Sync findings with checklist: if client marked area ✓ → downgrade to INFO ──
    # Build lowercase joined text of all done-task titles for keyword matching
    done_task_text = " ".join(t.get("title","").lower() for t in tasks_done)
    COMPLIANCE_AREAS = {
        "incident":           ["incident response", "irp", "incident-response"],
        "supply chain":       ["supply chain", "lieferkette", "drittanbieter"],
        "training":           ["training", "schulung", "awareness"],
        "dpia":               ["dpia", "dsfa", "folgenabschätzung", "art. 35"],
        "business continuity":["business continuity", "bcp", "bcm", "notfallplan"],
        "isms":               ["isms", "managementsystem", "governance"],
    }
    findings = list(findings)   # mutable copy
    for i, f in enumerate(findings):
        sev = f.get("severity","info").lower()
        if sev not in ("medium", "low"):
            continue
        f_text = (f.get("title","") + " " + f.get("description","")).lower()
        for area, kws in COMPLIANCE_AREAS.items():
            if any(kw in f_text for kw in kws) and any(kw in done_task_text for kw in kws):
                f = dict(f)
                f["severity"] = "info"
                f["cvss"] = ""
                orig_rec = f.get("recommendation","")
                f["recommendation"] = (
                    (orig_rec + " " if orig_rec else "") +
                    "Hinweis: Laut Auftraggeber-Checkliste als erledigt markiert — "
                    "externe Verifizierung der Dokumentation ist im Rahmen des "
                    "Black-Box-Audits nicht möglich."
                )
                findings[i] = f
                break

    # ── Count findings (after sync) ───────────────────────────────────────────
    counts = {"critical":0,"high":0,"medium":0,"low":0,"info":0}
    for f in findings:
        sev = f.get("severity","info").lower()
        counts[sev] = counts.get(sev,0)+1
    total = sum(counts.values())

    missing      = [h for h in live.get("headers",[]) if not h.get("good")]
    art32_issues = missing + [{"note":w} for w in live.get("warnings",[])]

    # ── Auto-inject SPF/DMARC finding EARLY (before Sec.6 computation) ───────
    dns = live.get("dns", {})
    if dns:
        existing_titles = " ".join(f.get("title","").lower() for f in findings)
        if (not dns.get("spf_ok") or not dns.get("dmarc_ok") or not dns.get("dkim_ok")) \
                and "spf" not in existing_titles and "dmarc" not in existing_titles \
                and "e-mail" not in existing_titles:
            missing_email = []
            if not dns.get("spf_ok"):   missing_email.append("SPF")
            if not dns.get("dmarc_ok"): missing_email.append("DMARC")
            if not dns.get("dkim_ok"):  missing_email.append("DKIM")
            findings = list(findings) + [{
                "title":         f"E-Mail-Authentifizierung fehlt ({', '.join(missing_email)})",
                "description":   (f"Für die Domain {dns.get('domain','')} fehlen folgende DNS-Sicherheitseinträge: "
                                  f"{', '.join(missing_email)}. Ohne SPF kann die Absenderadresse gefälscht werden "
                                  f"(E-Mail-Spoofing). Ohne DMARC gibt es keine Richtlinie für nicht autorisierte E-Mails. "
                                  f"Ohne DKIM fehlt die kryptografische Signierung ausgehender E-Mails."),
                "severity":      "low",
                "cvss":          "3.7",
                "dsgvo_article": "Art. 25 DSGVO / Art. 32 DSGVO / §30 Abs. 2 Nr. 1 BSIG",
                "target":        dns.get("domain",""),
                "tool":          "dns_audit",
                "recommendation": (f"SPF-TXT-Record setzen (z. B. \"v=spf1 include:_spf.example.com -all\"), "
                                   f"DMARC-Record mit policy=reject konfigurieren "
                                   f"(\"v=DMARC1; p=reject; rua=mailto:dmarc@{dns.get('domain','')}\"), "
                                   f"DKIM-Schlüsselpaar beim E-Mail-Provider aktivieren."),
            }]
            counts["low"] = counts.get("low", 0) + 1
            total = sum(counts.values())

    # Build tasks HTML by category
    tasks_html = ""
    if tasks:
        cats = []
        seen = set()
        for t in tasks:
            c = t.get("category","")
            if c not in seen:
                cats.append(c)
                seen.add(c)
        tasks_html = '<table><thead><tr><th style="width:4%">#</th><th>Aufgabe</th><th style="width:12%">NIS2-Referenz</th><th style="width:16%">DSGVO-Referenz</th><th style="width:8%">Status</th></tr></thead><tbody>'
        idx = 0
        for cat in cats:
            cat_tasks = [t for t in tasks if t.get("category") == cat]
            tasks_html += f'<tr><td colspan="5" style="background:#f0f4ff;font-weight:700;font-size:10px;color:#1a1a2e;padding:5px 8px">{esc(cat)}</td></tr>'
            for t in cat_tasks:
                idx += 1
                done = t.get("done")
                st_cls = "ok" if done else "fail"
                st_txt = "✓ Erledigt" if done else "✗ Offen"
                done_at = f'<br><span style="font-size:8px;color:#888">{esc(str(t.get("done_at",""))[:16])}</span>' if done and t.get("done_at") else ""
                notes_row = f'<br><span style="font-size:8px;color:#555">📝 {esc(t["notes"])}</span>' if t.get("notes") else ""
                req = '<span style="font-size:8px;color:#dc2626;font-weight:700"> *</span>' if t.get("required") else ""
                tasks_html += (f'<tr><td>{idx}</td>'
                               f'<td><b>{esc(t.get("title",""))}</b>{req}<br>'
                               f'<span style="font-size:8px;color:#666">{esc(t.get("description","")[:100])}</span>'
                               f'{notes_row}</td>'
                               f'<td style="font-size:8px">{esc(t.get("nis2_ref","") or "—")}</td>'
                               f'<td style="font-size:8px">{esc(t.get("dsgvo_ref","") or "—")}</td>'
                               f'<td class="{st_cls}">{st_txt}{done_at}</td></tr>')
        tasks_html += "</tbody></table>"
        if tasks_open:
            tasks_html += f'<div class="warn-box">⚠ <b>{len(tasks_open)} Aufgabe(n) noch offen</b> — vor Vorlage beim Regulator abschließen!</div>'
        else:
            tasks_html += '<div class="green-box">✓ Alle Compliance-Aufgaben abgeschlossen — bereit für behördliche Prüfung.</div>'
    else:
        tasks_html = '<div class="warn-box">Keine Aufgaben erfasst.</div>'

    task_stats_html = (
        f'<div class="stats-row">'
        f'<div class="stat-cell"><span class="stat-num" style="color:#16a34a">{len(tasks_done)}</span>Erledigt</div>'
        f'<div class="stat-cell"><span class="stat-num" style="color:#dc2626">{len(tasks_open)}</span>Offen</div>'
        f'<div class="stat-cell"><span class="stat-num" style="color:#2980b9">{tasks_total}</span>Gesamt</div>'
        f'<div class="stat-cell"><span class="stat-num" style="color:{"#16a34a" if tasks_pct==100 else "#d97706"}">{tasks_pct}%</span>Fortschritt</div>'
        f'</div>'
    )

    # Stats
    cols = {"critical":"#dc2626","high":"#e67e22","medium":"#d4a017","low":"#16a34a","info":"#2980b9"}
    stats_html = '<div class="stats-row">' + "".join(
        f'<div class="stat-cell"><span class="stat-num" style="color:{c}">{counts[s]}</span>{s.upper()}</div>'
        for s,c in cols.items()) + "</div>"

    # Findings
    ftable = fdetail = ""
    if findings:
        ftable = '<table><thead><tr><th>#</th><th>Bezeichnung</th><th>Schweregrad</th><th>CVSS</th><th>DSGVO</th></tr></thead><tbody>'
        for i,f in enumerate(findings,1):
            sev = f.get("severity","info")
            cvss_disp = f.get("cvss","") or ("" if sev == "info" else "N/A (Compliance-Befund)")
            ftable += f'<tr><td>{i}</td><td>{esc(f.get("title",""))}</td><td><span class="badge badge-{sev}">{sev.upper()}</span></td><td>{esc(cvss_disp) or "—"}</td><td style="font-size:9px">{esc(f.get("dsgvo_article","—"))}</td></tr>'
        ftable += "</tbody></table>"
        for f in findings:
            sev = f.get("severity","info").lower()
            cvss_disp = f.get("cvss","") or ("" if sev == "info" else "N/A (Compliance-Befund)")
            tool_src  = f.get("tool","")
            TOOL_LABELS = {
                "nmap": "Nmap (Port-Scan)", "nuclei": "Nuclei (CVE-Scan)",
                "httpx": "httpx (HTTP-Probe)", "testssl": "testssl.sh (TLS-Analyse)",
                "nikto": "Nikto (Web-Scan)", "dns_audit": "DNS Audit (dig)",
                "subfinder": "Subfinder (Subdomain-Enum)", "cookie_check": "Cookie-Check",
                "live_check": "Live-Check (intern)",
            }
            tool_label = TOOL_LABELS.get(tool_src, tool_src.replace("_"," ").title()) if tool_src else "KI-Analyse / Live-Check"
            fdetail += (f'<div class="finding {sev}">'
                        f'<div class="finding-title">[{sev.upper()}] {esc(f.get("title",""))}</div>'
                        f'<div class="finding-meta">Ziel: {esc(f.get("target","—"))} · CVSS: {esc(cvss_disp) or "—"} · {esc(f.get("dsgvo_article",""))} · <b>Erkannt durch:</b> {esc(tool_label)}</div>'
                        f'<p style="font-size:10px;margin:3px 0"><b>Beschreibung:</b> {esc(f.get("description",""))}</p>'
                        f'<p style="font-size:10px;margin:3px 0"><b>Empfehlung:</b> {esc(f.get("recommendation",""))}</p>'
                        f'</div>')
    else:
        ftable = '<div class="green-box">✓ Keine Schwachstellen gefunden — Automatisierte Prüfung ergab keine sicherheitsrelevanten Befunde.</div>'

    # Live check — TLS, Security Headers, Cookie, DNS sections
    if live.get("fetch_error"):
        live_html = f'<div class="warn-box">⚠ Live-Prüfung fehlgeschlagen: {esc(live["fetch_error"])}</div>'
    else:
        tg  = live.get("tls_grade","")
        tc  = "#16a34a" if tg=="A" else ("#d97706" if tg in ("B","C") else "#dc2626")
        san_str = ", ".join(live.get("tls_san",[])[:5]) or "—"
        live_html = (
            f'<table><thead><tr><th>TLS/SSL</th><th>Ergebnis</th><th>Bewertung</th></tr></thead><tbody>'
            f'<tr><td>Protokoll</td><td>{esc(live.get("tls_version",""))}</td>'
            f'<td style="color:{tc};font-weight:700">{esc(tg)}</td></tr>'
            f'<tr><td>CA-Aussteller</td><td>{esc(live.get("tls_issuer",""))}</td><td class="ok">✓</td></tr>'
            f'<tr><td>Zertifikat gültig bis</td><td>{esc(live.get("tls_expiry",""))}</td>'
            f'<td class="{"fail" if live.get("tls_expired") else "ok"}">{"✗ ABGELAUFEN" if live.get("tls_expired") else "✓"}</td></tr>'
            f'<tr><td>Subject Alt Names</td><td style="font-size:8px">{esc(san_str)}</td><td>—</td></tr>'
            f'</tbody></table>'
        )
        # Security Headers table
        live_html += '<table style="margin-top:10px"><thead><tr><th style="width:26%">Security Header</th><th>Wert</th><th style="width:10%">Status</th><th style="width:22%">DSGVO</th></tr></thead><tbody>'
        for h in live.get("headers",[]):
            val = (h.get("value","") or "— (nicht gesetzt)")[:160]
            sc  = "ok" if h.get("good") else "fail"
            si  = "✓ OK" if h.get("good") else "✗ Fehlt/Schwach"
            art = h.get("article","—") if not h.get("good") else "—"
            live_html += f'<tr><td><b>{esc(h.get("name",""))}</b><br><span style="font-size:8px;color:#666">{esc(h.get("desc",""))}</span></td><td style="font-size:9px;word-break:break-all">{esc(val)}</td><td class="{sc}">{si}</td><td style="font-size:9px">{esc(art)}</td></tr>'
        live_html += "</tbody></table>"

        # Cookie security table
        cookies = live.get("cookies", [])
        if cookies:
            live_html += '<h3 style="margin-top:12px">Cookie-Sicherheits-Flags</h3>'
            live_html += '<table><thead><tr><th style="width:28%">Cookie</th><th>Secure</th><th>HttpOnly</th><th>SameSite</th><th>Status</th></tr></thead><tbody>'
            for c in cookies:
                raw  = (c.get("raw") or "").lower()
                s_ok = "secure"   in raw
                h_ok = "httponly" in raw
                ss   = "none" if "samesite=none" in raw else ("lax" if "samesite=lax" in raw else ("strict" if "samesite=strict" in raw else "—"))
                all_ok = c.get("good", False)
                st_cls = "ok" if all_ok else "fail"
                st_txt = "✓ OK" if all_ok else f'✗ {"; ".join(c.get("issues",[]))}'
                live_html += (
                    f'<tr><td style="font-size:9px"><b>{esc(c.get("name",""))}</b></td>'
                    f'<td class="{"ok" if s_ok else "fail"}">{("✓" if s_ok else "✗")}</td>'
                    f'<td class="{"ok" if h_ok else "fail"}">{("✓" if h_ok else "✗")}</td>'
                    f'<td style="font-size:9px">{esc(ss)}</td>'
                    f'<td class="{st_cls}" style="font-size:9px">{esc(st_txt[:80])}</td></tr>'
                )
            live_html += "</tbody></table>"

        # DNS table
        dns = live.get("dns", {})
        if dns:
            live_html += '<h3 style="margin-top:12px">DNS-Sicherheit</h3>'
            live_html += '<table><thead><tr><th>Prüfung</th><th>Status</th><th>Detail</th></tr></thead><tbody>'
            dns_checks = [
                ("SPF",    dns.get("spf_ok"),    dns.get("spf_value","") or "Nicht vorhanden — E-Mail-Spoofing möglich"),
                ("DMARC",  dns.get("dmarc_ok"),  (f"Policy: {dns.get('dmarc_policy','')}" if dns.get("dmarc_ok") else "Nicht vorhanden")),
                ("DKIM",   dns.get("dkim_ok"),    (f"Selector: {dns.get('dkim_selector','')}" if dns.get("dkim_ok") else "Nicht gefunden")),
                ("DNSSEC", dns.get("dnssec_ok"),  "Aktiviert" if dns.get("dnssec_ok") else "Nicht aktiviert"),
            ]
            for name, ok, detail in dns_checks:
                cls = "ok" if ok else "fail"
                ico = "✓" if ok else "✗"
                live_html += f'<tr><td><b>{esc(name)}</b></td><td class="{cls}">{ico}</td><td style="font-size:9px">{esc(str(detail)[:120])}</td></tr>'
            live_html += "</tbody></table>"

        if live.get("warnings"):
            live_html += '<div class="warn-box"><b>⚠ Festgestellte Mängel:</b><ul style="margin:4px 0 0 14px">' + "".join(f"<li>{esc(w)}</li>" for w in live["warnings"]) + "</ul></div>"
        elif live.get("passed"):
            live_html += '<div class="green-box">✓ Alle Security-Header korrekt konfiguriert (Art. 32 DSGVO)</div>'

    art32_html = (f'<p class="fail">✗ {len(art32_issues)} Verstoß/-verstöße</p><div class="warn-box"><b>Live-Prüfung Mängel:</b><ul style="margin:4px 0 0 14px">' +
                  "".join(f'<li>{esc(i.get("note","") or i.get("name",""))}</li>' for i in art32_issues if i.get("note") or i.get("name")) +
                  "</ul></div>") if art32_issues else '<p class="ok">✓ Konform</p>'

    # ── Section 6: DSGVO analysis driven by final findings list ─────────────
    # Helper: collect non-info findings mentioning a DSGVO article keyword
    def _findings_for(art_keywords: list) -> list:
        kws = [k.lower() for k in art_keywords]
        return [f for f in findings
                if f.get("severity","info").lower() != "info"
                and any(kw in (f.get("dsgvo_article","") or "").lower() for kw in kws)]

    cookie_issues = [c for c in live.get("cookies",[]) if not c.get("good")]

    # Art. 5 §1f — Integrity & Confidentiality: header failures, TLS issues, general
    art5_findings = _findings_for(["art. 5", "art.5", "§30"])
    if not art5_findings:
        art5_html = '<p class="ok">✓ Konform — keine technischen Verstöße festgestellt</p>'
    else:
        art5_html = (f'<p class="fail">✗ {len(art5_findings)} Verstoß/-verstöße festgestellt</p>'
                     f'<ul style="margin:4px 0 0 14px;font-size:10px">'
                     + "".join(f'<li>[{f.get("severity","").upper()}] {esc(f.get("title",""))}</li>' for f in art5_findings)
                     + '</ul>')

    # Art. 25 — Privacy by Design: SPF/DMARC/DKIM, Permissions-Policy, Cookies
    art25_findings = _findings_for(["art. 25", "art.25"])
    permissions_ok = any(h.get("key") == "permissions-policy" and h.get("good")
                         for h in live.get("headers", []))
    if not art25_findings and permissions_ok and not cookie_issues:
        art25_html = '<p class="ok">✓ Konform</p>'
    else:
        items_25 = [f'[{f.get("severity","").upper()}] {esc(f.get("title",""))}' for f in art25_findings]
        if not permissions_ok:
            items_25.append("Permissions-Policy fehlt (Browser-Feature-Kontrolle)")
        if cookie_issues:
            items_25.append(f"{len(cookie_issues)} Cookie(s) ohne Sicherheits-Flags")
        art25_html = (f'<p class="fail">✗ {len(items_25)} Mängel</p>'
                      f'<ul style="margin:4px 0 0 14px;font-size:10px">'
                      + "".join(f'<li>{esc(i)}</li>' for i in items_25)
                      + '</ul>')

    # Art. 32 — Technical & Organisational Measures: security headers, TLS, everything
    art32_findings = _findings_for(["art. 32", "art.32"])
    if not art32_findings:
        art32_html = '<p class="ok">✓ Konform — keine technischen TOMs-Verstöße festgestellt</p>'
    else:
        art32_html = (f'<p class="fail">✗ {len(art32_findings)} Verstoß/-verstöße</p>'
                      f'<ul style="margin:4px 0 0 14px;font-size:10px">'
                      + "".join(f'<li>[{f.get("severity","").upper()}] {esc(f.get("title",""))}'
                                f'<span style="color:#888;font-size:9px"> — CVSS: {esc(f.get("cvss","") or "N/A")}</span></li>'
                                for f in art32_findings)
                      + '</ul>')

    # §25 TTDSG — Cookie Consent
    ttdsg_html = ('<p class="ok">✓ Keine Cookie-Probleme festgestellt</p>'
                  if not cookie_issues
                  else f'<p class="warn">⚠ {len(cookie_issues)} Cookie(s) ohne korrekte Flags — '
                       f'Cookie-Consent-Banner prüfen (§25 TTDSG)</p>')

    # ── Dynamic recommendations from actual findings ───────────────────────────
    crit_findings = [f for f in findings if f.get("severity") == "critical"]
    high_findings = [f for f in findings if f.get("severity") == "high"]
    med_findings  = [f for f in findings if f.get("severity") == "medium"]

    rec_rows = ""
    if crit_findings:
        titles = "; ".join(f.get("title","") for f in crit_findings[:3])
        rec_rows += f'<tr><td>0–48h</td><td><b>KRITISCH:</b> {esc(titles[:200])}. Sofortiger Incident-Response-Prozess einleiten.</td><td><span class="badge badge-critical">SOFORT</span></td><td>Sofort nach Behebung</td></tr>'
    if high_findings:
        titles = "; ".join(f.get("title","") for f in high_findings[:3])
        rec_rows += f'<tr><td>1–2 Wochen</td><td>{esc(titles[:200])}. Behebung und Verifikation.</td><td><span class="badge badge-high">HOCH</span></td><td>+14 Tage</td></tr>'
    # Standard recommendations based on live-check results
    missing_headers = [h.get("name") for h in live.get("headers",[]) if not h.get("good")]
    if missing_headers:
        rec_rows += f'<tr><td>1–2 Wochen</td><td>Security-Header setzen: {esc(", ".join(missing_headers[:5]))}.</td><td><span class="badge badge-high">HOCH</span></td><td>+14 Tage</td></tr>'
    if cookie_issues:
        rec_rows += f'<tr><td>1 Monat</td><td>Cookie-Flags setzen (Secure, HttpOnly, SameSite=Strict) für {len(cookie_issues)} Cookie(s).</td><td><span class="badge badge-medium">MITTEL</span></td><td>+30 Tage</td></tr>'
    if not dns.get("spf_ok") or not dns.get("dmarc_ok"):
        rec_rows += f'<tr><td>1 Monat</td><td>E-Mail-Sicherheit: SPF, DMARC (policy=reject) und DKIM konfigurieren.</td><td><span class="badge badge-medium">MITTEL</span></td><td>+30 Tage</td></tr>'
    if med_findings:
        tech_med = [f for f in med_findings if f.get("cvss","") and f.get("cvss","") != "N/A (Compliance-Befund)"]
        comp_med = [f for f in med_findings if not f.get("cvss","") or f.get("cvss","") == "N/A (Compliance-Befund)"]
        if tech_med:
            rec_rows += f'<tr><td>1 Monat</td><td>{len(tech_med)} technische Schwachstelle(n) beheben: {esc("; ".join(f.get("title","") for f in tech_med[:2]))}. Patch-Management überprüfen.</td><td><span class="badge badge-medium">MITTEL</span></td><td>+30 Tage</td></tr>'
        if comp_med:
            rec_rows += f'<tr><td>1 Monat</td><td>{len(comp_med)} Compliance-Lücke(n) dokumentieren: {esc("; ".join(f.get("title","") for f in comp_med[:2]))}. Interne Dokumentation erstellen und dem Prüfer vorlegen.</td><td><span class="badge badge-medium">MITTEL</span></td><td>+30 Tage</td></tr>'
    rec_rows += '<tr><td>3 Monate</td><td>SRI für CDN. MFA auf allen Zugängen. DSFA aktualisieren. Offene Compliance-Aufgaben schließen.</td><td><span class="badge badge-low">NIEDRIG</span></td><td>+90 Tage</td></tr>'
    rec_rows += '<tr><td>Jährlich</td><td>Pentest wiederholen. Security-Awareness-Training (§30 Abs.2 Nr.9 BSIG). Risikoanalyse aktualisieren.</td><td><span class="badge badge-info">GEPLANT</span></td><td>Laufend</td></tr>'

    html = f"""<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8"><title>Sicherheitsprüfungsbericht — {esc(company)}</title>{PRINT_CSS}</head><body>
<div class="print-bar no-print">
  <h2>Sicherheitsprüfungsbericht · {esc(company)}</h2>
  <button class="btn-print" onclick="window.print()">🖨 Als PDF drucken / speichern</button>
</div>
<div class="cover">
  <div class="cover-logo">{esc(COMPANY)}</div>
  <div class="cover-sub">IT-Sicherheitsdienstleistungen · {esc(WEBSITE)}</div>
  <h1>NIS2 / DSGVO Compliance-Bericht</h1>
  <p style="font-size:13px;color:#a8b2d8;margin-bottom:10px">Penetration Testing &amp; Compliance-Analyse</p>
  <div class="cover-box"><div class="lbl">PRÜFUNGSZIEL</div><div class="val">{esc(target)}</div></div>
  <div class="cover-box"><div class="lbl">KUNDE</div><div class="val">{esc(company)}</div></div>
  <div class="cover-box"><div class="lbl">DATUM</div><div class="val">{now}</div></div>
  <div class="cover-meta">Prüfer: {esc(FULL_NAME)}<br>{esc(ADDRESS)}<br>{esc(EMAIL)} · {esc(PHONE)}<br>{esc(UST_ID)}<br>Gesamtbefunde: <b>{total}</b> &nbsp;·&nbsp; Prüffortschritt: <b>{tasks_pct}%</b></div>
  <div style="margin-top:14px">
    <span class="cbadge">✓ NIS2 / §30 BSIG</span>
    <span class="cbadge">✓ DSGVO Art. 32</span>
    <span class="cbadge">✓ BSI IT-Grundschutz</span>
    <span class="cbadge">✓ OWASP Top 10</span>
  </div>
  <div class="cover-seal">⚠ VERTRAULICH – NUR FÜR AUFTRAGGEBER</div>
</div>
<div>
<h2>1. Zusammenfassung (Executive Summary)</h2>
<table class="info-table">
<tr><td>Auftraggeber</td><td><b>{esc(company)}</b></td></tr>
<tr><td>Adresse</td><td>{esc(address)}</td></tr>
<tr><td>Prüfungsziel</td><td>{esc(target)}</td></tr>
<tr><td>Prüfer</td><td>{esc(FULL_NAME)} · {esc(WEBSITE)}</td></tr>
<tr><td>Prüfungsdatum</td><td>{now}</td></tr>
<tr><td>Prüffortschritt</td><td><b style="color:{"#16a34a" if tasks_pct==100 else "#d97706"}">{tasks_pct}% ({len(tasks_done)}/{tasks_total} Aufgaben abgeschlossen)</b></td></tr>
<tr><td>Offene Befunde</td><td><b style="color:{"#dc2626" if (counts["critical"]+counts["high"]) > 0 else ("#d97706" if counts["medium"] > 0 else "#16a34a")}">{counts["critical"]+counts["high"]+counts["medium"]+counts["low"]} Befunde ({counts["critical"]} kritisch / {counts["high"]} hoch / {counts["medium"]} mittel / {counts["low"]} niedrig) · {counts["info"]} informativ</b></td></tr>
</table>
{stats_html}

<h2 class="pb">2. Prüfungsumfang und Methodik</h2>
<table class="info-table">
<tr><td>Prüfungstyp</td><td>KI-gestützter Web-Security-Check mit manueller Expertenprüfung (Black-Box, extern)</td></tr>
<tr><td>Methodik</td><td>Die Prüfung erfolgt durch Kombination aus etablierten Security-Tools, KI-gestützter Analyse und manueller Validierung der Ergebnisse. Kritische Befunde werden durch einen Security-Experten geprüft und freigegeben.</td></tr>
<tr><td>Autorisierung</td><td>Schriftlicher Prüfungsauftrag liegt vor (gem. §202a StGB)</td></tr>
<tr><td>Standards</td><td>NIS2 / §30 BSIG · DSGVO Art. 32 · §25 TTDSG · BSI IT-Grundschutz · OWASP Top 10 (2021) · CVSS v3.1</td></tr>
<tr><td>Hinweis</td><td>Kein vollumfänglicher manueller Penetrationstest durch zertifizierte Prüfer (BSI IT-Grundschutz-Zertifizierung). Geeignet als DSGVO/NIS2-Nachweis für regelmäßige Sicherheitsüberprüfung gem. Art. 32 DSGVO / §30 BSIG.</td></tr>
</table>
<h3>Eingesetzte Prüfwerkzeuge</h3>
<table><thead><tr><th style="width:4%">#</th><th style="width:28%">Prüfkategorie</th><th style="width:24%">Tool / Methode</th><th>Prüfinhalt</th><th style="width:12%">Status</th></tr></thead><tbody>
<tr><td>1</td><td>HTTP-Fingerprinting / Tech-Stack</td><td>httpx (ProjectDiscovery)</td><td>HTTP-Status, Server-Banner, eingesetzte Technologien, Weiterleitungen</td><td class="ok">✓ Durchgeführt</td></tr>
<tr><td>2</td><td>Port-Scan / Netzwerksicherheit</td><td>Nmap 7.x</td><td>Offene Ports (21 Ports), Dienste, Banner-Grabbing, nicht autorisierte Dienste</td><td class="{"ok" if any("nmap" in (lg.get("message","") or "").lower() for lg in logs) else "warn"}">{"✓ Durchgeführt" if any("nmap" in (lg.get("message","") or "").lower() and lg.get("level")=="CMD" for lg in logs) else "— Kein Ergebnis"}</td></tr>
<tr><td>3</td><td>TLS/SSL-Konfiguration</td><td>testssl.sh 3.x</td><td>TLS-Protokolle (1.0–1.3), Cipher-Suites, Zertifikat, bekannte TLS-CVEs (POODLE/BEAST/Heartbleed)</td><td class="{"ok" if any("testssl" in (lg.get("message","") or "").lower() and lg.get("level")=="CMD" for lg in logs) else "warn"}">{"✓ Durchgeführt" if any("testssl" in (lg.get("message","") or "").lower() and lg.get("level")=="CMD" for lg in logs) else "— Kein Ergebnis"}</td></tr>
<tr><td>4</td><td>Subdomain-Enumeration / DNS</td><td>Subfinder (ProjectDiscovery)</td><td>Subdomains, Shadow-IT, Dangling DNS, DNS-Zonenübertragung</td><td class="{"ok" if any("subfinder" in (lg.get("message","") or "").lower() and lg.get("level")=="CMD" for lg in logs) else "warn"}">{"✓ Durchgeführt" if any("subfinder" in (lg.get("message","") or "").lower() and lg.get("level")=="CMD" for lg in logs) else "— Kein Ergebnis"}</td></tr>
<tr><td>5</td><td>DNS-Sicherheit (SPF/DMARC/DKIM)</td><td>dns_audit (dig)</td><td>SPF, DMARC, DKIM, DNSSEC, DNS-Zonenübertragung, MX-Records</td><td class="{"ok" if any("dns_audit" in (lg.get("message","") or "").lower() and lg.get("level")=="CMD" for lg in logs) else "warn"}">{"✓ Durchgeführt" if any("dns_audit" in (lg.get("message","") or "").lower() and lg.get("level")=="CMD" for lg in logs) else "— Kein Ergebnis"}</td></tr>
<tr><td>6</td><td>Cookie-Sicherheit</td><td>cookie_check (intern)</td><td>Secure-, HttpOnly-, SameSite-Flags; Cookie-Consent-Prüfung (§25 TTDSG)</td><td class="{"ok" if any("cookie_check" in (lg.get("message","") or "").lower() and lg.get("level")=="CMD" for lg in logs) else "warn"}">{"✓ Durchgeführt" if any("cookie_check" in (lg.get("message","") or "").lower() and lg.get("level")=="CMD" for lg in logs) else "— Kein Ergebnis"}</td></tr>
<tr><td>7</td><td>CVE / Schwachstellen-Scan</td><td>Nuclei (ProjectDiscovery)</td><td>CVE-Templates, Fehlkonfigurationen, sensible Endpunkte, bekannte Exploits</td><td class="{"ok" if any("nuclei" in (lg.get("message","") or "").lower() and lg.get("level")=="CMD" for lg in logs) else "warn"}">{"✓ Durchgeführt" if any("nuclei" in (lg.get("message","") or "").lower() and lg.get("level")=="CMD" for lg in logs) else "— Kein Ergebnis"}</td></tr>
<tr><td>8</td><td>OWASP-Check / Web-Schwachstellen</td><td>Nikto 2.x</td><td>OWASP Top 10: SQL-Injection, XSS, CSRF, gefährliche Dateien/Verzeichnisse, Fehlkonfigurationen</td><td class="{"ok" if any("nikto" in (lg.get("message","") or "").lower() and lg.get("level")=="CMD" for lg in logs) else "warn"}">{"✓ Durchgeführt" if any("nikto" in (lg.get("message","") or "").lower() and lg.get("level")=="CMD" for lg in logs) else "— Kein Ergebnis"}</td></tr>
<tr><td>9</td><td>HTTP Security-Header-Analyse</td><td>Live-Check (intern)</td><td>CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, COOP, CORP</td><td class="ok">✓ Durchgeführt</td></tr>
<tr><td>10</td><td>NIS2 / DSGVO Compliance-Checkliste</td><td>KI-Analyse (Claude AI)</td><td>{tasks_total} Prüfpunkte: §30 BSIG, DSGVO Art. 32/25/28/30/33/35, §25 TTDSG — Organisatorisch, Technisch, DSGVO</td><td class="ok">✓ Durchgeführt</td></tr>
</tbody></table>
<h3>In-Scope (Prüfumfang)</h3>
<ul>
  <li>Öffentlich erreichbare Web-Applikation und HTTP/HTTPS-Dienste: <b>{esc(target)}</b></li>
  <li>TLS/SSL-Konfiguration (Protokollversionen, Cipher-Suites, Zertifikat, HSTS)</li>
  <li>HTTP Security-Header (8 Header: CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, COOP, CORP)</li>
  <li>DNS-Sicherheit (SPF, DMARC, DKIM, DNSSEC, Zone Transfer)</li>
  <li>Port-Scan: 21 ausgewählte Ports (FTP, SSH, SMTP, DNS, HTTP, MSSQL, MySQL, RDP, MongoDB, Redis u.a.)</li>
  <li>Automatisierter CVE-Scan (Nuclei-Templates: critical/high/medium)</li>
  <li>OWASP Top 10: SQL-Injection, XSS, CSRF, IDOR, Broken Authentication, Security Misconfiguration</li>
  <li>Cookie-Sicherheit: Secure/HttpOnly/SameSite-Flags</li>
  <li>Subdomain-Enumeration (passive Erkennung)</li>
  <li>NIS2 / DSGVO Compliance-Checkliste ({tasks_total} Prüfpunkte)</li>
</ul>
<div class="warn-box" style="font-size:9px"><b>Nicht im Scope:</b> Authentifizierte Tests (Login erforderlich), interne Netzwerke / VPN, physische Sicherheit, Social Engineering, manuelle Code-Analyse, Datenbank-Interna.</div>

<h2 class="pb">3. Live-Sicherheitsprüfung (automatisch)</h2>
<p style="font-size:9px;color:#666;margin-bottom:8px">Automatische HTTP/TLS/DNS-Analyse von <b>{esc(target)}</b> · Prüfungszeitpunkt: {esc(live.get("checked_at",now))} · Prüfer: {esc(COMPANY)}</p>
{live_html}

<h2 class="pb">4. Sicherheitsbefunde</h2>
{ftable}{fdetail}

<h2 class="pb">5. NIS2 / DSGVO Compliance-Checkliste</h2>
<p style="font-size:9px;color:#666;margin-bottom:8px">Stand der Compliance-Prüfung zum {now}. Pflichtaufgaben gemäß §30 BSIG und DSGVO Art. 32.</p>
{task_stats_html}
{tasks_html}

<h2 class="pb">6. DSGVO Compliance-Analyse</h2>
<p style="font-size:9px;color:#666;margin-bottom:8px">Die nachfolgende Analyse basiert ausschließlich auf den in Abschnitt 4 dokumentierten Sicherheitsbefunden und ist damit vollständig konsistent mit den Prüfergebnissen.</p>
<h3>Art. 5 Abs. 1f DSGVO — Integrität und Vertraulichkeit</h3>{art5_html}
<h3>Art. 25 DSGVO — Privacy by Design &amp; by Default</h3>{art25_html}
<h3>Art. 32 DSGVO — Technische und organisatorische Maßnahmen (TOM)</h3>{art32_html}
<h3>Art. 33 DSGVO — Meldung von Datenschutzverletzungen (NIS2 §32 BSIG)</h3><p class="ok">✓ Konform — Meldepflicht: 24h Erstmeldung, 72h Detailmeldung, 1 Monat Abschlussbericht</p>
<h3>§25 TTDSG — Schutz der Privatsphäre bei Endeinrichtungen</h3>{ttdsg_html}

<h2 class="pb">7. Empfehlungen und Retest-Plan</h2>
<table><thead><tr><th>Zeitraum</th><th>Maßnahme</th><th>Priorität</th><th>Retest</th></tr></thead><tbody>
{rec_rows}
</tbody></table>
<div class="warn-box" style="margin-top:12px">⚖ <b>Geschätztes Bußgeldrisiko:</b><br>NIS2 §30 BSIG: bis 10.000.000 EUR oder 2% des weltweiten Jahresumsatzes<br>DSGVO Art. 83 Abs. 4: bis 10.000.000 EUR oder 2% (technische Verstöße)<br>DSGVO Art. 83 Abs. 5 (Art. 32): bis 20.000.000 EUR oder 4% des weltweiten Jahresumsatzes</div>

<h2 class="pb">8. Prüfungsprotokoll (Nachweis durchgeführter Prüfschritte)</h2>
<p style="font-size:9px;color:#666;margin-bottom:8px">Dieses Protokoll dokumentiert den Ablauf der Sicherheitsprüfung als Nachweis der erbrachten Leistung gem. DSGVO Art. 32 / §30 BSIG.</p>
<table class="info-table">
<tr><td>Auftraggeber</td><td>{esc(company)} · {esc(address)}</td></tr>
<tr><td>Prüfungsziel</td><td><b>{esc(target)}</b></td></tr>
<tr><td>Prüfer</td><td>{esc(COMPANY)} · {esc(ADDRESS)}</td></tr>
<tr><td>Prüfungsbeginn</td><td>{esc(audit_start or live.get("checked_at", now))}</td></tr>
<tr><td>Prüfungsende</td><td>{esc(audit_end or now)}</td></tr>
<tr><td>Berichtsdatum</td><td>{now}</td></tr>
</table>
<h3>Protokoll der durchgeführten Prüfschritte</h3>
<table><thead><tr><th style="width:4%">#</th><th style="width:26%">Tool / Prüfschritt</th><th style="width:18%">Startzeitpunkt</th><th style="width:18%">Endzeitpunkt</th><th>Prüfinhalt</th><th style="width:8%">Befunde</th></tr></thead><tbody>
{_build_protocol_rows(tools_used, logs, target)}
</tbody></table>
<p style="font-size:9px;color:#666;margin-top:8px">* Live-Check (HTTP/TLS/DNS) wird automatisch bei Berichtsgenerierung durchgeführt und ist unabhängig vom KI-gestützten Audit-Lauf.</p>

<h2 class="pb">9. Prüfererklärung und Unterschrift</h2>
<p style="font-size:10px;margin-bottom:14px">Der vorliegende Bericht dokumentiert den Sicherheitszustand des geprüften Systems zum Prüfungszeitpunkt. {esc(COMPANY)} bescheinigt die Durchführung der Prüfung im Rahmen des Prüfungsauftrags gem. §202a StGB. Die Prüfung erfolgte durch Einsatz KI-gestützter Analyse- und Security-Tools unter manueller Expertenprüfung und Freigabe.</p>
<table class="sig-table"><tr>
<td><b>PRÜFER / AUFTRAGNEHMER</b><br><br><b>{esc(COMPANY)}</b><br>{esc(ADDRESS)}<br>
E-Mail: {esc(EMAIL)}<br>Tel.: {esc(PHONE)}<br>{esc(UST_ID)}<br>{esc(WEBSITE)}<br><br>
Datum: {now}<br><div class="sig-line">Unterschrift / Stempel {esc(COMPANY)}</div></td>
<td><b>AUFTRAGGEBER / KUNDE</b><br><br>{esc(company)}<br>{esc(address)}<br><br>
Datum: ______________________<br><div class="sig-line">Unterschrift / Stempel des Auftraggebers</div></td>
</tr></table>
<div class="footer">{esc(FULL_NAME)} · {esc(WEBSITE)} · {esc(EMAIL)} · {esc(PHONE)}<br>
{esc(UST_ID)} · {esc(ADDRESS)}<br>
Bericht erstellt am {now} · NIS2 §30 BSIG · DSGVO Art. 32 · BSI IT-Grundschutz · OWASP Top 10 (2021) · CVSS v3.1<br>
* = Pflichtmaßnahme gemäß §30 BSIG / DSGVO</div>
</div></body></html>"""
    return _save_pdf(html, out_path)
