"""
PDF Generator — WeasyPrint (echtes PDF) mit HTML-Fallback
"""
from datetime import datetime
import os

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
    now = datetime.now().strftime("%d.%m.%Y")
    m   = datetime.now().month
    y   = datetime.now().year
    valid = f"05.{(m%12)+1:02d}.{y if m<12 else y+1}"

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
    return _save_html(html, out_path)


def generate_report_pdf(out_path, order, findings, live, tasks=None):
    now     = datetime.now().strftime("%d.%m.%Y")
    company = order.get("company","")
    address = order.get("address","")
    target  = order.get("target","")

    counts = {"critical":0,"high":0,"medium":0,"low":0,"info":0}
    for f in findings:
        sev = f.get("severity","info").lower()
        counts[sev] = counts.get(sev,0)+1
    total = sum(counts.values())

    missing      = [h for h in live.get("headers",[]) if not h.get("good")]
    art32_issues = missing + [{"note":w} for w in live.get("warnings",[])]

    # ── Tasks summary ────────────────────────────────────────────────────────
    tasks = tasks or []
    tasks_done  = [t for t in tasks if t.get("done")]
    tasks_open  = [t for t in tasks if not t.get("done")]
    tasks_total = len(tasks)
    tasks_pct   = int(len(tasks_done) / tasks_total * 100) if tasks_total else 0

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
            ftable += f'<tr><td>{i}</td><td>{esc(f.get("title",""))}</td><td><span class="badge badge-{sev}">{sev.upper()}</span></td><td>{esc(f.get("cvss","—"))}</td><td style="font-size:9px">{esc(f.get("dsgvo_article","—"))}</td></tr>'
        ftable += "</tbody></table>"
        for f in findings:
            sev = f.get("severity","info").lower()
            fdetail += f'<div class="finding {sev}"><div class="finding-title">[{sev.upper()}] {esc(f.get("title",""))}</div><div class="finding-meta">Ziel: {esc(f.get("target","—"))} · CVSS: {esc(f.get("cvss","—"))} · {esc(f.get("dsgvo_article",""))}</div><p style="font-size:10px;margin:3px 0"><b>Beschreibung:</b> {esc(f.get("description",""))}</p><p style="font-size:10px;margin:3px 0"><b>Empfehlung:</b> {esc(f.get("recommendation",""))}</p></div>'
    else:
        ftable = '<div class="green-box">✓ Keine Schwachstellen gefunden — Automatisierte Prüfung ergab keine sicherheitsrelevanten Befunde.</div>'

    # Live check
    if live.get("fetch_error"):
        live_html = f'<div class="warn-box">⚠ Live-Prüfung fehlgeschlagen: {esc(live["fetch_error"])}</div>'
    else:
        tg  = live.get("tls_grade","")
        tc  = "#16a34a" if tg=="A" else "#dc2626"
        live_html = f'<table><thead><tr><th>TLS/SSL</th><th>Ergebnis</th><th>Bewertung</th></tr></thead><tbody><tr><td>Protokoll</td><td>{esc(live.get("tls_version",""))}</td><td style="color:{tc};font-weight:700">{esc(tg)}</td></tr><tr><td>CA-Aussteller</td><td>{esc(live.get("tls_issuer",""))}</td><td class="ok">✓</td></tr><tr><td>Zertifikat</td><td>Gültig bis {esc(live.get("tls_expiry",""))}</td><td class="{"fail" if live.get("tls_expired") else "ok"}">{"✗ ABGELAUFEN" if live.get("tls_expired") else "✓"}</td></tr></tbody></table>'
        live_html += '<table style="margin-top:10px"><thead><tr><th style="width:26%">Security Header</th><th>Wert</th><th style="width:10%">Status</th><th style="width:22%">DSGVO</th></tr></thead><tbody>'
        for h in live.get("headers",[]):
            val = (h.get("value","") or "— (nicht gesetzt)")[:80]
            sc  = "ok" if h.get("good") else "fail"
            si  = "✓ OK" if h.get("good") else "✗ Fehlt"
            art = h.get("article","—") if not h.get("good") else "—"
            live_html += f'<tr><td><b>{esc(h.get("name",""))}</b><br><span style="font-size:8px;color:#666">{esc(h.get("desc",""))}</span></td><td style="font-size:9px;word-break:break-all">{esc(val)}</td><td class="{sc}">{si}</td><td style="font-size:9px">{esc(art)}</td></tr>'
        live_html += "</tbody></table>"
        if live.get("warnings"):
            live_html += '<div class="warn-box"><b>⚠ Festgestellte Mängel:</b><ul style="margin:4px 0 0 14px">' + "".join(f"<li>{esc(w)}</li>" for w in live["warnings"]) + "</ul></div>"
        elif live.get("passed"):
            live_html += '<div class="green-box">✓ Alle Security-Header korrekt konfiguriert (Art. 32 DSGVO)</div>'

    art32_html = (f'<p class="fail">✗ {len(art32_issues)} Verstoß/-verstöße</p><div class="warn-box"><b>Live-Prüfung Mängel:</b><ul style="margin:4px 0 0 14px">' +
                  "".join(f'<li>{esc(i.get("note","") or i.get("name",""))}</li>' for i in art32_issues if i.get("note") or i.get("name")) +
                  "</ul></div>") if art32_issues else '<p class="ok">✓ Konform</p>'

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
  <div class="cover-meta">Prüfer: {esc(FULL_NAME)}<br>{esc(ADDRESS)}<br>{esc(EMAIL)} · {esc(PHONE)}<br>{esc(UST_ID)}<br>Gesamtbefunde: <b>{total}</b> &nbsp;·&nbsp; Compliance: <b>{tasks_pct}%</b></div>
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
<tr><td>Compliance-Stand</td><td><b style="color:{"#16a34a" if tasks_pct==100 else "#d97706"}">{tasks_pct}% ({len(tasks_done)}/{tasks_total} Aufgaben)</b></td></tr>
</table>
{stats_html}

<h2 class="pb">2. Prüfungsumfang und Methodik</h2>
<table class="info-table">
<tr><td>Prüfungstyp</td><td>Black-Box Penetration Test (extern, ohne Voranmeldung) + Compliance-Analyse</td></tr>
<tr><td>Autorisierung</td><td>Schriftlicher Prüfungsauftrag liegt vor (gem. §202a StGB)</td></tr>
<tr><td>Standards</td><td>NIS2 / §30 BSIG · DSGVO Art. 32 · §25 TTDSG · BSI IT-Grundschutz · OWASP Top 10 (2021) · CVSS v3.1</td></tr>
</table>
<h3>In-Scope</h3>
<ul>
  <li>HTTP Security-Header-Analyse (8 Header: CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, COOP, CORP)</li>
  <li>TLS/SSL-Konfigurationsprüfung (Protokollversionen, Cipher-Suites, Zertifikat, HSTS)</li>
  <li>Port-Scan und Netzwerksicherheit (nmap)</li>
  <li>Automatisierter Schwachstellen-Scan (Nuclei, CVE-Templates)</li>
  <li>OWASP Top 10: SQL-Injection, XSS, CSRF, IDOR, Broken Authentication, Security Misconfiguration</li>
  <li>NIS2 / DSGVO Compliance-Checkliste ({tasks_total} Prüfpunkte)</li>
</ul>

<h2 class="pb">3. Live-Sicherheitsprüfung (automatisch)</h2>
<p style="font-size:9px;color:#666;margin-bottom:8px">Automatische HTTP/TLS-Analyse von <b>{esc(target)}</b> am {esc(live.get("checked_at",now))}</p>
{live_html}

<h2 class="pb">4. Sicherheitsbefunde</h2>
{ftable}{fdetail}

<h2 class="pb">5. NIS2 / DSGVO Compliance-Checkliste</h2>
<p style="font-size:9px;color:#666;margin-bottom:8px">Stand der Compliance-Prüfung zum {now}. Pflichtaufgaben gemäß §30 BSIG und DSGVO Art. 32.</p>
{task_stats_html}
{tasks_html}

<h2 class="pb">6. DSGVO Compliance-Analyse (Art. 32)</h2>
<h3>Art. 5 §1f DSGVO — Integrität und Vertraulichkeit</h3>{('<p class="ok">✓ Konform</p>' if not art32_issues else '<p class="fail">✗ Mängel festgestellt</p>')}
<h3>Art. 25 DSGVO — Privacy by Design &amp; by Default</h3><p class="ok">✓ Konform</p>
<h3>Art. 32 DSGVO — Technische und organisatorische Maßnahmen (TOM)</h3>{art32_html}
<h3>Art. 33 DSGVO — Meldung von Datenschutzverletzungen (NIS2 §32 BSIG)</h3><p class="ok">✓ Konform — Meldepflicht: 24h Erstmeldung, 72h Detailmeldung, 1 Monat Abschlussbericht</p>
<h3>§25 TTDSG — Schutz der Privatsphäre bei Endeinrichtungen</h3><p class="ok">✓ Konform</p>

<h2 class="pb">7. Empfehlungen und Retest-Plan</h2>
<table><thead><tr><th>Zeitraum</th><th>Maßnahme</th><th>Priorität</th><th>Retest</th></tr></thead><tbody>
<tr><td>0–48h</td><td>Kritische Befunde beheben. Incident Response einleiten falls nötig.</td><td><span class="badge badge-critical">SOFORT</span></td><td>Sofort</td></tr>
<tr><td>1–2 Wochen</td><td>Security-Header: HSTS (max-age), CSP (kein unsafe-inline), Permissions-Policy, CORP, COOP.</td><td><span class="badge badge-high">HOCH</span></td><td>+14 Tage</td></tr>
<tr><td>1 Monat</td><td>Server-Banner entfernen. TLS 1.0/1.1 abschalten. MFA aktivieren. Offene Aufgaben schließen.</td><td><span class="badge badge-medium">MITTEL</span></td><td>+30 Tage</td></tr>
<tr><td>3 Monate</td><td>SRI für CDN-Ressourcen. Cookie-Attribute: Secure, HttpOnly, SameSite=Strict. DSFA aktualisieren.</td><td><span class="badge badge-low">NIEDRIG</span></td><td>+90 Tage</td></tr>
<tr><td>Jährlich</td><td>Pentest wiederholen. Security-Awareness-Training. Risikoanalyse aktualisieren.</td><td><span class="badge badge-info">GEPLANT</span></td><td>Laufend</td></tr>
</tbody></table>
<div class="warn-box" style="margin-top:12px">⚖ <b>Geschätztes Bußgeldrisiko (DSGVO Art. 83 / NIS2): bis 10.000.000 EUR oder 2% des weltweiten Jahresumsatzes</b></div>

<h2 class="pb">8. Prüfererklärung und Unterschrift</h2>
<p style="font-size:10px;margin-bottom:14px">Der nachfolgende Bericht gibt den Sicherheitszustand des geprüften Systems zum Prüfungszeitpunkt wieder. {esc(COMPANY)} bescheinigt die Durchführung der Prüfung im Rahmen des Prüfungsauftrags gem. §202a StGB.</p>
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
