"""
NIS2Audit — Flask додаток для надання послуг NIS2/DSGVO compliance
Andrii-IT | IT-Sicherheitsdienstleistungen
"""

import os, secrets, json, subprocess, threading, uuid, re, time
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_from_directory, g, abort
)
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from models import init_db, migrate_db, db_query, db_execute, create_order_tasks
from pdf_generator import generate_angebot_pdf, generate_report_pdf
from live_check import fetch_live_check, is_public_target
from agent import run_audit_agent
from kassen_check import run_kassen_check
import lead_finder
import mailer
import payments

app = Flask(__name__, template_folder="../templates", static_folder="../static")

_secret = os.environ.get("SECRET_KEY")
if not _secret:
    raise RuntimeError("SECRET_KEY environment variable is required. Set it in .env or docker-compose.yml")
app.secret_key = _secret
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("HTTPS", "0") == "1"
app.config["WTF_CSRF_TIME_LIMIT"] = 3600
app.config["WTF_CSRF_HEADERS"] = ["X-CSRFToken"]

csrf    = CSRFProtect(app)
limiter = Limiter(app=app, key_func=get_remote_address,
                  default_limits=[], storage_uri="memory://")

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

_ADMIN_PASSWORD_RAW = os.environ.get("ADMIN_PASSWORD", "andrii-it-2026")
_ADMIN_HASH         = generate_password_hash(_ADMIN_PASSWORD_RAW)
del _ADMIN_PASSWORD_RAW          # erase plaintext from memory
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@andrii-it.de")

# Allowed file extensions in reports directory
_ALLOWED_REPORT_EXT = {".pdf", ".html"}

# ── Auth ──────────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.before_request
def load_user():
    g.logged_in = session.get("logged_in", False)

@app.context_processor
def inject_globals():
    return {"now": datetime.now(), "logged_in": g.logged_in}

# ── Login/Logout ──────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pwd   = request.form.get("password", "")
        if email == ADMIN_EMAIL.lower() and check_password_hash(_ADMIN_HASH, pwd):
            session.permanent = True
            session["logged_in"] = True
            session["user_email"] = email
            return redirect(url_for("dashboard"))
        flash("Ungültige Anmeldedaten", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def dashboard():
    clients = db_query("SELECT * FROM clients ORDER BY created_at DESC")
    orders  = db_query("""
        SELECT o.*, c.company, c.email FROM orders o
        JOIN clients c ON c.id = o.client_id
        ORDER BY o.created_at DESC LIMIT 20
    """)
    pipeline = {
        "angebot": db_query("SELECT COUNT(*) as n FROM orders WHERE status='angebot'")[0]["n"],
        "paid":    db_query("SELECT COUNT(*) as n FROM orders WHERE status='paid'")[0]["n"],
        "running": db_query("SELECT COUNT(*) as n FROM orders WHERE status='running'")[0]["n"],
        "review":  db_query("SELECT COUNT(*) as n FROM orders WHERE status IN ('review','done','active')")[0]["n"],
        "completed": db_query("SELECT COUNT(*) as n FROM orders WHERE status='completed'")[0]["n"],
        "failed":  db_query("SELECT COUNT(*) as n FROM orders WHERE status='failed'")[0]["n"],
    }
    revenue = db_query("""
        SELECT COALESCE(SUM(CAST(amount AS REAL)),0) as total
        FROM orders WHERE status IN ('paid','running','review','done','active','completed')
    """)[0]["total"]
    stats = {
        "clients": db_query("SELECT COUNT(*) as n FROM clients")[0]["n"],
        "orders":  db_query("SELECT COUNT(*) as n FROM orders")[0]["n"],
        "open":    db_query("SELECT COUNT(*) as n FROM orders WHERE status NOT IN ('completed','cancelled')")[0]["n"],
        "done":    db_query("SELECT COUNT(*) as n FROM orders WHERE status='completed'")[0]["n"],
        "revenue": revenue,
    }
    review_orders = db_query("""
        SELECT o.*, c.company, c.email FROM orders o
        JOIN clients c ON c.id = o.client_id
        WHERE o.status IN ('review','done','active')
        ORDER BY o.updated_at DESC
    """)
    return render_template("dashboard.html", clients=clients, orders=orders,
                            stats=stats, pipeline=pipeline, review_orders=review_orders)

# ── Clients ───────────────────────────────────────────────────────────────────
@app.route("/clients")
@login_required
def clients():
    rows = db_query("SELECT * FROM clients ORDER BY company")
    return render_template("clients.html", clients=rows)

@app.route("/clients/new", methods=["GET","POST"])
@login_required
def new_client():
    if request.method == "POST":
        company = request.form.get("company","").strip()
        contact = request.form.get("contact","").strip()
        email   = request.form.get("email","").strip()
        phone   = request.form.get("phone","").strip()
        address = request.form.get("address","").strip()
        ustid   = request.form.get("ustid","").strip()
        notes   = request.form.get("notes","").strip()
        if not company or not email:
            flash("Firma und E-Mail sind Pflichtfelder", "error")
            return render_template("client_form.html")
        db_execute(
            "INSERT INTO clients (company,contact,email,phone,address,ustid,notes,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (company, contact, email, phone, address, ustid, notes, datetime.now().isoformat())
        )
        flash(f"Kunde {company} angelegt", "success")
        return redirect(url_for("clients"))
    return render_template("client_form.html")

@app.route("/clients/<int:cid>")
@login_required
def client_detail(cid):
    client = db_query("SELECT * FROM clients WHERE id=?", (cid,))
    if not client:
        flash("Kunde nicht gefunden", "error")
        return redirect(url_for("clients"))
    orders = db_query("SELECT * FROM orders WHERE client_id=? ORDER BY created_at DESC", (cid,))
    return render_template("client_detail.html", client=client[0], orders=orders)

@app.route("/clients/<int:cid>/edit", methods=["GET","POST"])
@login_required
def edit_client(cid):
    client = db_query("SELECT * FROM clients WHERE id=?", (cid,))
    if not client:
        return redirect(url_for("clients"))
    client = client[0]
    if request.method == "POST":
        db_execute("""UPDATE clients SET company=?,contact=?,email=?,phone=?,address=?,ustid=?,notes=?
                      WHERE id=?""",
            (request.form.get("company"), request.form.get("contact"),
             request.form.get("email"), request.form.get("phone"),
             request.form.get("address"), request.form.get("ustid"),
             request.form.get("notes"), cid))
        flash("Kundendaten aktualisiert", "success")
        return redirect(url_for("client_detail", cid=cid))
    return render_template("client_form.html", client=client)

# ── Lead-Finder (Kassensystem-Zielgruppe) ──────────────────────────────────────
@app.route("/leads")
@login_required
def leads():
    rows = db_query("SELECT * FROM leads ORDER BY created_at DESC LIMIT 200")
    counts = {r["status"]: r["n"] for r in db_query("SELECT status, COUNT(*) as n FROM leads GROUP BY status")}
    return render_template("leads.html", leads=rows, counts=counts,
                            search_status=lead_finder.get_status(),
                            send_status=lead_finder.get_send_status())

@app.route("/leads/start", methods=["POST"])
@login_required
def start_leads_search():
    branches = request.form.getlist("branche") or ["gastronomie"]
    started = lead_finder.start_background_search(branches)
    if started:
        flash("Lead-Suche gestartet — läuft im Hintergrund bis zum Stopp", "success")
    else:
        flash("Es läuft bereits eine Suche", "danger")
    return redirect(url_for("leads"))

@app.route("/leads/stop", methods=["POST"])
@login_required
def stop_leads_search():
    lead_finder.stop_background_search()
    flash("Lead-Suche wird gestoppt …", "success")
    return redirect(url_for("leads"))

@app.route("/leads/status")
@login_required
def leads_status():
    return jsonify(lead_finder.get_status())

@app.route("/leads/start-sending", methods=["POST"])
@login_required
def start_leads_sending():
    started = lead_finder.start_send_backlog()
    if started:
        flash(f"Automatischer Versand gestartet — max. {lead_finder.SEND_DAILY_CAP}/24h, "
              f"1 Mail alle {lead_finder.SEND_INTERVAL_SECONDS}s", "success")
    else:
        flash("Versand läuft bereits", "danger")
    return redirect(url_for("leads"))

@app.route("/leads/stop-sending", methods=["POST"])
@login_required
def stop_leads_sending():
    lead_finder.stop_send_backlog()
    flash("Versand wird gestoppt …", "success")
    return redirect(url_for("leads"))

@app.route("/leads/sending-status")
@login_required
def leads_sending_status():
    return jsonify(lead_finder.get_send_status())

@app.route("/leads/<int:lid>/preview", methods=["POST"])
@login_required
def preview_lead_email(lid):
    """Startet die Website-Analyse (mehrere externe HTTP-Requests, kann 10-30s dauern)
    im Hintergrund statt im Request-Handler — sonst blockiert ein langsames Zielsystem
    den gesamten Server (Single-Thread-Risiko), inkl. Healthcheck anderer Nutzer."""
    def run():
        try:
            lead_finder.analyze_lead(lid)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()
    flash("Analyse gestartet (läuft im Hintergrund) — Seite in ein paar Sekunden neu laden", "success")
    return redirect(url_for("leads"))

@app.route("/leads/<int:lid>/send", methods=["POST"])
@login_required
def send_lead_email(lid):
    lead = db_query("SELECT * FROM leads WHERE id=?", (lid,))
    if not lead:
        return redirect(url_for("leads"))
    lead = lead[0]
    if not lead["email"]:
        flash("Kein E-Mail-Kontakt für diesen Lead gefunden", "danger")
        return redirect(url_for("leads"))

    token = secrets.token_urlsafe(24)
    subject = request.form.get("subject", "").strip() or lead["draft_subject"]
    body = request.form.get("body", "").strip() or lead["draft_body"]
    if not subject or not body:
        subject, body = lead_finder.build_outreach_email(dict(lead), token, payments.PUBLIC_BASE_URL)
    else:
        # Link im (ggf. editierten) Text auf den echten Versand-Token umschreiben
        body = re.sub(r"https?://\S+/lead/\S+", f"{payments.PUBLIC_BASE_URL}/lead/{token}", body)

    try:
        mailer.send_email(lead["email"], subject, body)
        db_execute("UPDATE leads SET lead_token=?,status='emailed',emailed_at=? WHERE id=?",
                   (token, datetime.now().isoformat(), lid))
        flash(f"Einladung an {lead['email']} gesendet", "success")
    except mailer.MailerNotConfigured as e:
        flash(str(e), "danger")
    except Exception as e:
        flash(f"Versand fehlgeschlagen: {e}", "danger")
    return redirect(url_for("leads"))

@app.route("/lead/<token>", methods=["GET"])
def lead_landing(token):
    lead = db_query("SELECT * FROM leads WHERE lead_token=?", (token,))
    if not lead:
        abort(404)
    lead = lead[0]
    findings = []
    if lead["scan_result"]:
        try:
            findings = json.loads(lead["scan_result"]).get("findings", [])
        except Exception:
            findings = []
    return render_template("lead_landing.html", lead=lead, findings=findings)

@app.route("/lead/<token>/confirm", methods=["POST"])
def lead_confirm(token):
    lead = db_query("SELECT * FROM leads WHERE lead_token=?", (token,))
    if not lead:
        abort(404)
    lead = lead[0]

    if not request.form.get("owner_confirmed"):
        flash("Bitte bestätigen Sie, dass Sie zur Beauftragung berechtigt sind.", "danger")
        return redirect(url_for("lead_landing", token=token))

    target = request.form.get("target", "").strip() or lead["domain"]
    if not is_public_target(target):
        flash("Bitte geben Sie eine öffentlich erreichbare Domain oder IP an.", "danger")
        return redirect(url_for("lead_landing", token=token))

    email = lead["email"] or f"lead-{lead['id']}@platzhalter.invalid"
    client_row = db_query("SELECT id FROM clients WHERE email=?", (email,))
    if client_row:
        client_id = client_row[0]["id"]
    else:
        client_id = db_execute(
            "INSERT INTO clients (company,contact,email,phone,address,notes,created_at) VALUES (?,?,?,?,?,?,?)",
            (lead["company"], lead["contact"], email, lead["phone"], lead["address"],
             "Angelegt über Lead-Finder (Kassensystem-Zielgruppe)", datetime.now().isoformat()),
        )

    confirm_token = secrets.token_urlsafe(24)
    order_id = db_execute(
        """INSERT INTO orders (client_id,target,amount,scope,notes,status,check_type,confirm_token,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (client_id, target, "100",
         "Vollständige Sicherheitsprüfung (Blackbox-Pentest) — vom Auftraggeber selbst bestätigtes Ziel",
         f"Lead #{lead['id']} — Branche: {lead['branche']}", "angebot", "audit", confirm_token,
         datetime.now().isoformat(), datetime.now().isoformat()),
    )
    create_order_tasks(order_id)

    db_execute("UPDATE leads SET status='confirmed',responded_at=?,client_id=?,order_id=? WHERE id=?",
               (datetime.now().isoformat(), client_id, order_id, lead["id"]))

    order = db_query("""SELECT o.*, c.company, c.email FROM orders o
                         JOIN clients c ON c.id=o.client_id WHERE o.id=?""", (order_id,))[0]
    try:
        checkout_url = payments.create_checkout_session(dict(order))
        return redirect(checkout_url)
    except payments.PaymentsNotConfigured:
        flash("Vielen Dank! Wir haben Ihre Anfrage erhalten und melden uns in Kürze mit den "
              "Zahlungsdetails.", "success")
        return render_template("lead_landing.html", lead=lead, findings=[], confirmed=True)

# ── Angebot ───────────────────────────────────────────────────────────────────
@app.route("/angebot/new", methods=["GET","POST"])
@login_required
def new_angebot():
    clients = db_query("SELECT * FROM clients ORDER BY company")
    if request.method == "POST":
        client_id  = int(request.form.get("client_id"))
        target     = request.form.get("target","").strip()
        amount     = request.form.get("amount","100").strip()
        scope      = request.form.get("scope","").strip()
        notes      = request.form.get("notes","").strip()
        check_type = request.form.get("check_type","audit").strip()
        if check_type not in ("audit", "kassen"):
            check_type = "audit"
        client     = db_query("SELECT * FROM clients WHERE id=?", (client_id,))[0]

        # Генеруємо Angebot PDF
        angebot_num = f"ANG-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        pdf_name    = f"Angebot_{client['company'].replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
        pdf_path    = os.path.join(REPORTS_DIR, pdf_name)
        actual_path = generate_angebot_pdf(pdf_path, client, target, amount, scope, angebot_num)
        pdf_name    = os.path.basename(actual_path)

        confirm_token = secrets.token_urlsafe(32)

        # Зберігаємо заказ
        order_id = db_execute("""INSERT INTO orders
            (client_id,target,amount,scope,notes,status,check_type,confirm_token,
             angebot_pdf,angebot_num,created_at,updated_at)
            VALUES (?,?,?,?,?,'angebot',?,?,?,?,?,?)""",
            (client_id, target, amount, scope, notes, check_type, confirm_token,
             pdf_name, angebot_num,
             datetime.now().isoformat(), datetime.now().isoformat()))

        # Создаём стандартные NIS2/DSGVO задачи для нового заказа
        create_order_tasks(order_id)

        flash(f"Angebot {angebot_num} erstellt", "success")
        return redirect(url_for("dashboard"))
    return render_template("angebot_form.html", clients=clients)

# ── Orders / Audit ────────────────────────────────────────────────────────────
@app.route("/orders")
@login_required
def orders():
    status_filter = request.args.get("status", "").strip()
    if status_filter == "review":
        # "Review nötig" bündelt mehrere interne Status-Werte
        rows = db_query("""
            SELECT o.*, c.company, c.email, c.address FROM orders o
            JOIN clients c ON c.id = o.client_id
            WHERE o.status IN ('review','done','active')
            ORDER BY o.updated_at DESC
        """)
    elif status_filter:
        rows = db_query("""
            SELECT o.*, c.company, c.email, c.address FROM orders o
            JOIN clients c ON c.id = o.client_id
            WHERE o.status = ?
            ORDER BY o.created_at DESC
        """, (status_filter,))
    else:
        rows = db_query("""
            SELECT o.*, c.company, c.email, c.address FROM orders o
            JOIN clients c ON c.id = o.client_id
            ORDER BY o.created_at DESC
        """)
    status_counts = {r["status"]: r["n"] for r in
                      db_query("SELECT status, COUNT(*) as n FROM orders GROUP BY status")}
    return render_template("orders.html", orders=rows, status_filter=status_filter,
                            status_counts=status_counts)

@app.route("/orders/<int:oid>")
@login_required
def order_detail(oid):
    order = db_query("""
        SELECT o.*, c.company, c.email, c.address, c.contact, c.phone, c.ustid
        FROM orders o JOIN clients c ON c.id = o.client_id WHERE o.id=?
    """, (oid,))
    if not order:
        flash("Auftrag nicht gefunden", "error")
        return redirect(url_for("orders"))
    order = order[0]
    findings = db_query("SELECT * FROM findings WHERE order_id=? ORDER BY severity_rank", (oid,))
    logs     = db_query("SELECT * FROM audit_logs WHERE order_id=? ORDER BY created_at DESC LIMIT 50", (oid,))
    tasks    = db_query("SELECT * FROM order_tasks WHERE order_id=? ORDER BY category, id", (oid,))
    return render_template("order_detail.html", order=order, findings=findings, logs=logs, tasks=tasks)

@app.route("/orders/<int:oid>/status", methods=["POST"])
@login_required
def update_status(oid):
    status = request.form.get("status")
    db_execute("UPDATE orders SET status=?,updated_at=? WHERE id=?",
               (status, datetime.now().isoformat(), oid))
    flash("Status aktualisiert", "success")
    return redirect(url_for("order_detail", oid=oid))

@app.route("/orders/<int:oid>/start-audit", methods=["POST"])
@login_required
def start_audit(oid):
    order = db_query("""
        SELECT o.*, c.company, c.email, c.address, c.contact
        FROM orders o JOIN clients c ON c.id=o.client_id WHERE o.id=?
    """, (oid,))
    if not order:
        return jsonify({"error": "not found"}), 404
    order = order[0]

    if not is_public_target(order["target"]):
        flash("Target muss eine öffentliche Internetadresse sein", "danger")
        return redirect(url_for("order_detail", oid=oid))

    job_id = str(uuid.uuid4())[:8]
    db_execute("UPDATE orders SET status='running',job_id=?,updated_at=? WHERE id=?",
               (job_id, datetime.now().isoformat(), oid))
    _launch_check_for_order(oid, "audit", order["target"], order["company"])
    flash("Audit gestartet — läuft im Hintergrund", "success")
    return redirect(url_for("order_detail", oid=oid))

@app.route("/orders/<int:oid>/start-kassen-check", methods=["POST"])
@login_required
def start_kassen_check(oid):
    """Passiver Kassensystem-Check (Shodan + CVE). Zielwert kommt AUSSCHLIESSLICH
    aus order['target'] — keine Nutzereingabe, keine aktive Verbindung zur Kasse."""
    order = db_query("""
        SELECT o.*, c.company, c.email, c.address, c.contact
        FROM orders o JOIN clients c ON c.id=o.client_id WHERE o.id=?
    """, (oid,))
    if not order:
        return jsonify({"error": "not found"}), 404
    order = order[0]

    if not is_public_target(order["target"]):
        flash("Target muss eine öffentliche Internetadresse sein", "danger")
        return redirect(url_for("order_detail", oid=oid))

    job_id = str(uuid.uuid4())[:8]
    db_execute("UPDATE orders SET status='running',job_id=?,updated_at=? WHERE id=?",
               (job_id, datetime.now().isoformat(), oid))
    _launch_check_for_order(oid, "kassen", order["target"], order["company"])
    flash("Kassensystem-Check gestartet (passiv, Shodan + CVE) — läuft im Hintergrund", "success")
    return redirect(url_for("order_detail", oid=oid))

@app.route("/orders/<int:oid>/generate-report", methods=["POST"])
@login_required
def generate_report(oid):
    order = db_query("""
        SELECT o.*, c.company, c.email, c.address, c.contact, c.phone, c.ustid
        FROM orders o JOIN clients c ON c.id=o.client_id WHERE o.id=?
    """, (oid,))
    if not order:
        flash("Auftrag nicht gefunden", "error")
        return redirect(url_for("orders"))
    order    = order[0]
    findings = db_query("SELECT * FROM findings WHERE order_id=? ORDER BY severity_rank", (oid,))
    tasks    = db_query("SELECT * FROM order_tasks WHERE order_id=? ORDER BY category, id", (oid,))
    logs     = db_query("SELECT * FROM audit_logs WHERE order_id=? ORDER BY created_at ASC", (oid,))
    live     = fetch_live_check(order["target"])

    pdf_name = f"Bericht_{order['company'].replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf_path = os.path.join(REPORTS_DIR, pdf_name)
    actual_path = generate_report_pdf(pdf_path, order, findings, live, tasks, logs)
    pdf_name = os.path.basename(actual_path)

    db_execute("UPDATE orders SET report_pdf=?,status='completed',updated_at=? WHERE id=?",
               (pdf_name, datetime.now().isoformat(), oid))
    _log(oid, "INFO", f"Bericht generiert: {pdf_name}")
    flash("Bericht erfolgreich erstellt", "success")
    return redirect(url_for("order_detail", oid=oid))


# ── E-Mail-Versand ────────────────────────────────────────────────────────────

@app.route("/orders/<int:oid>/send-angebot", methods=["POST"])
@login_required
def send_angebot(oid):
    order = db_query("""
        SELECT o.*, c.company, c.email FROM orders o
        JOIN clients c ON c.id=o.client_id WHERE o.id=?
    """, (oid,))
    if not order:
        flash("Auftrag nicht gefunden", "error")
        return redirect(url_for("orders"))
    order = order[0]
    if not order["angebot_pdf"]:
        flash("Kein Angebot-PDF vorhanden — zuerst erstellen", "error")
        return redirect(url_for("order_detail", oid=oid))

    try:
        confirm_url = f"{payments.PUBLIC_BASE_URL}/confirm/{order['confirm_token']}"
        mailer.send_email(
            to_addr=order["email"],
            subject=f"Ihr Angebot — {order['company']}",
            body_text=(
                f"Sehr geehrte Damen und Herren,\n\n"
                f"anbei erhalten Sie unser Angebot ({order['angebot_num']}).\n\n"
                f"Zur Bestätigung und Beauftragung nutzen Sie bitte folgenden Link:\n"
                f"{confirm_url}\n\n"
                f"Mit freundlichen Grüßen\nAndrii Pylypchuk\nAndrii-IT"
            ),
            attachment_path=os.path.join(REPORTS_DIR, order["angebot_pdf"]),
            attachment_name=order["angebot_pdf"],
        )
        flash(f"Angebot an {order['email']} gesendet", "success")
    except mailer.MailerNotConfigured as e:
        flash(str(e), "danger")
    except Exception as e:
        flash(f"Fehler beim Versand: {e}", "danger")
    return redirect(url_for("order_detail", oid=oid))


@app.route("/orders/<int:oid>/send-report", methods=["POST"])
@login_required
def send_report(oid):
    order = db_query("""
        SELECT o.*, c.company, c.email FROM orders o
        JOIN clients c ON c.id=o.client_id WHERE o.id=?
    """, (oid,))
    if not order:
        flash("Auftrag nicht gefunden", "error")
        return redirect(url_for("orders"))
    order = order[0]
    if not order["report_pdf"]:
        flash("Kein Bericht-PDF vorhanden — zuerst erstellen", "error")
        return redirect(url_for("order_detail", oid=oid))

    try:
        mailer.send_email(
            to_addr=order["email"],
            subject=f"Ihr Sicherheitsbericht — {order['company']}",
            body_text=(
                f"Sehr geehrte Damen und Herren,\n\n"
                f"anbei erhalten Sie den vereinbarten Prüfbericht.\n\n"
                f"Bei Fragen stehe ich gerne zur Verfügung.\n\n"
                f"Mit freundlichen Grüßen\nAndrii Pylypchuk\nAndrii-IT"
            ),
            attachment_path=os.path.join(REPORTS_DIR, order["report_pdf"]),
            attachment_name=order["report_pdf"],
        )
        flash(f"Bericht an {order['email']} gesendet", "success")
    except mailer.MailerNotConfigured as e:
        flash(str(e), "danger")
    except Exception as e:
        flash(f"Fehler beim Versand: {e}", "danger")
    return redirect(url_for("order_detail", oid=oid))


# ── Öffentlicher Bestätigungs-/Bezahl-Flow (kein Login) ─────────────────────────

def _launch_check_for_order(order_id: int, check_type: str, target: str, company: str):
    """Startet die passende Prüfung im Hintergrund. Wird sowohl vom Admin-Button
    als auch automatisch nach Zahlungseingang (Webhook) verwendet."""
    def run():
        try:
            if check_type == "kassen":
                run_kassen_check(order_id, target)
            else:
                run_audit_agent(order_id, target, company)
            db_execute("UPDATE orders SET status='review',updated_at=? WHERE id=?",
                       (datetime.now().isoformat(), order_id))
            _log(order_id, "INFO", "Prüfung abgeschlossen — wartet auf manuelle Freigabe/Versand")
        except Exception as e:
            db_execute("UPDATE orders SET status='failed',updated_at=? WHERE id=?",
                       (datetime.now().isoformat(), order_id))
            _log(order_id, "ERROR", str(e))
    threading.Thread(target=run, daemon=True).start()


@app.route("/confirm/<token>", methods=["GET"])
def confirm_order(token):
    """Öffentliche, personalisierte Seite: Kunde sieht NUR sein eigenes Angebot
    und kann es bestätigen + bezahlen. Kein Login, aber Zugriff nur mit dem
    individuellen, nicht erratbaren Token möglich."""
    order = db_query("""
        SELECT o.*, c.company, c.email, c.address FROM orders o
        JOIN clients c ON c.id=o.client_id WHERE o.confirm_token=?
    """, (token,))
    if not order:
        abort(404)
    order = order[0]
    return render_template("client_confirm.html", order=order,
                            stripe_configured=payments.is_configured())


@app.route("/confirm/<token>/pay", methods=["POST"])
@limiter.limit("5 per minute")
def confirm_order_pay(token):
    order = db_query("""
        SELECT o.*, c.company, c.email FROM orders o
        JOIN clients c ON c.id=o.client_id WHERE o.confirm_token=?
    """, (token,))
    if not order:
        abort(404)
    order = order[0]

    if not request.form.get("owner_confirmed"):
        flash("Bitte bestätigen Sie, dass Sie zur Beauftragung berechtigt sind.", "danger")
        return redirect(url_for("confirm_order", token=token))

    try:
        checkout_url = payments.create_checkout_session(dict(order))
        return redirect(checkout_url)
    except payments.PaymentsNotConfigured as e:
        flash(str(e), "danger")
        return redirect(url_for("confirm_order", token=token))


@csrf.exempt
@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    """Stripe-Webhook — verifiziert Signatur, markiert Order als bezahlt und
    startet automatisch die vereinbarte Prüfung. Der fertige Bericht wird
    NICHT automatisch versendet, sondern wartet auf manuelle Freigabe."""
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    try:
        event = payments.verify_webhook(payload, sig_header)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        order_id = session_obj.get("client_reference_id") or session_obj.get("metadata", {}).get("order_id")
        if order_id:
            order = db_query("SELECT * FROM orders WHERE id=?", (order_id,))
            if order:
                order = order[0]
                db_execute("UPDATE orders SET status='paid',paid_at=?,updated_at=? WHERE id=?",
                           (datetime.now().isoformat(), datetime.now().isoformat(), order_id))
                _log(order_id, "INFO", "Zahlung eingegangen (Stripe) — Prüfung wird automatisch gestartet")
                client = db_query("SELECT company FROM clients WHERE id=?", (order["client_id"],))[0]
                _launch_check_for_order(order_id, order["check_type"], order["target"], client["company"])

    return jsonify({"received": True}), 200


# ── Downloads ─────────────────────────────────────────────────────────────────
@app.route("/download/<filename>")
@login_required
def download(filename):
    # Prevent path traversal — only allow safe filenames from REPORTS_DIR
    safe = secure_filename(filename)
    if not safe:
        abort(404)
    ext = os.path.splitext(safe)[1].lower()
    if ext not in _ALLOWED_REPORT_EXT:
        abort(403)
    full = os.path.join(REPORTS_DIR, safe)
    if not os.path.exists(full):
        # Try the alternative extension (pdf <-> html)
        alt_ext = ".html" if ext == ".pdf" else ".pdf"
        alt = os.path.splitext(safe)[0] + alt_ext
        if os.path.exists(os.path.join(REPORTS_DIR, alt)):
            safe = alt
        else:
            abort(404)
    as_attachment = safe.endswith(".pdf")
    return send_from_directory(REPORTS_DIR, safe, as_attachment=as_attachment)

# ── API: live check ───────────────────────────────────────────────────────────
@app.route("/api/live-check")
@login_required
@limiter.limit("30 per minute")
def api_live_check():
    target = request.args.get("target","")
    if not target:
        return jsonify({"error": "target required"}), 400
    if not is_public_target(target):
        return jsonify({"error": "target must be a public internet host"}), 400
    result = fetch_live_check(target)
    return jsonify(result)

# ── API: findings ─────────────────────────────────────────────────────────────
@app.route("/api/findings/<int:oid>", methods=["POST"])
@login_required
def add_finding(oid):
    data = request.json
    RANK = {"critical":1,"high":2,"medium":3,"low":4,"info":5}
    rank = RANK.get(data.get("severity","info").lower(), 5)
    db_execute("""INSERT INTO findings
        (order_id,title,description,severity,severity_rank,target,proof,impact,recommendation,cvss,dsgvo_article,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (oid, data.get("title"), data.get("description"), data.get("severity","info"),
         rank, data.get("target"), data.get("proof"), data.get("impact"),
         data.get("recommendation"), data.get("cvss"), data.get("dsgvo_article"),
         datetime.now().isoformat()))
    return jsonify({"ok": True})

@app.route("/api/findings/<int:fid>", methods=["DELETE"])
@login_required
def delete_finding(fid):
    db_execute("DELETE FROM findings WHERE id=?", (fid,))
    return jsonify({"ok": True})

# ── API: tasks ────────────────────────────────────────────────────────────────
@app.route("/api/tasks/<int:tid>/toggle", methods=["POST"])
@login_required
def toggle_task(tid):
    task = db_query("SELECT * FROM order_tasks WHERE id=?", (tid,))
    if not task:
        return jsonify({"error": "not found"}), 404
    new_done = 0 if task[0]["done"] else 1
    done_at  = datetime.now().isoformat() if new_done else None
    db_execute("UPDATE order_tasks SET done=?, done_at=? WHERE id=?", (new_done, done_at, tid))
    return jsonify({"done": new_done, "done_at": done_at})

@app.route("/api/tasks/<int:tid>/notes", methods=["POST"])
@login_required
def update_task_notes(tid):
    notes = (request.json or {}).get("notes", "")
    db_execute("UPDATE order_tasks SET notes=? WHERE id=?", (notes[:2000], tid))
    return jsonify({"ok": True})

# ── API: audit log stream ─────────────────────────────────────────────────────
@app.route("/api/logs/<int:oid>")
@login_required
def get_logs(oid):
    after = request.args.get("after", "0")
    rows  = db_query(
        "SELECT * FROM audit_logs WHERE order_id=? AND id>? ORDER BY id ASC LIMIT 50",
        (oid, int(after))
    )
    return jsonify(rows)

def _log(order_id, level, message):
    db_execute("INSERT INTO audit_logs (order_id,level,message,created_at) VALUES (?,?,?,?)",
               (order_id, level, message, datetime.now().isoformat()))

# ── Täglicher Lead-Kampagnen-Report ────────────────────────────────────────────
DAILY_SUMMARY_HOUR_UTC = int(os.environ.get("DAILY_SUMMARY_HOUR_UTC", "6"))

def _send_daily_summary():
    try:
        subject, body = lead_finder.build_daily_summary()
        mailer.send_email(ADMIN_EMAIL, subject, body)
    except Exception as e:
        print("Tagesreport fehlgeschlagen:", e)

def _daily_summary_loop():
    while True:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        target = now.replace(hour=DAILY_SUMMARY_HOUR_UTC, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        time.sleep(max(1, (target - now).total_seconds()))
        _send_daily_summary()

@app.route("/leads/send-daily-summary-now", methods=["POST"])
@login_required
def send_daily_summary_now():
    threading.Thread(target=_send_daily_summary, daemon=True).start()
    flash(f"Tagesreport wird erstellt und an {ADMIN_EMAIL} gesendet …", "success")
    return redirect(url_for("leads"))

# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    migrate_db()
    threading.Thread(target=_daily_summary_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
