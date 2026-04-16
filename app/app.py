"""
NIS2Audit — Flask додаток для надання послуг NIS2/DSGVO compliance
Andrii-IT | IT-Sicherheitsdienstleistungen
"""

import os, secrets, json, subprocess, threading, uuid, re
from datetime import datetime, timedelta
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
from live_check import fetch_live_check
from agent import run_audit_agent

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
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
    stats = {
        "clients": db_query("SELECT COUNT(*) as n FROM clients")[0]["n"],
        "orders":  db_query("SELECT COUNT(*) as n FROM orders")[0]["n"],
        "open":    db_query("SELECT COUNT(*) as n FROM orders WHERE status NOT IN ('completed','cancelled')")[0]["n"],
        "done":    db_query("SELECT COUNT(*) as n FROM orders WHERE status='completed'")[0]["n"],
    }
    return render_template("dashboard.html", clients=clients, orders=orders, stats=stats)

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

# ── Angebot ───────────────────────────────────────────────────────────────────
@app.route("/angebot/new", methods=["GET","POST"])
@login_required
def new_angebot():
    clients = db_query("SELECT * FROM clients ORDER BY company")
    if request.method == "POST":
        client_id = int(request.form.get("client_id"))
        target    = request.form.get("target","").strip()
        amount    = request.form.get("amount","1000").strip()
        scope     = request.form.get("scope","").strip()
        notes     = request.form.get("notes","").strip()
        client    = db_query("SELECT * FROM clients WHERE id=?", (client_id,))[0]

        # Генеруємо Angebot PDF
        angebot_num = f"ANG-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        pdf_name    = f"Angebot_{client['company'].replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.html"
        pdf_path    = os.path.join(REPORTS_DIR, pdf_name)
        generate_angebot_pdf(pdf_path, client, target, amount, scope, angebot_num)

        # Зберігаємо заказ
        order_id = db_execute("""INSERT INTO orders
            (client_id,target,amount,scope,notes,status,angebot_pdf,angebot_num,created_at,updated_at)
            VALUES (?,?,?,?,?,'angebot',?,?,?,?)""",
            (client_id, target, amount, scope, notes, pdf_name, angebot_num,
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
    rows = db_query("""
        SELECT o.*, c.company, c.email, c.address FROM orders o
        JOIN clients c ON c.id = o.client_id
        ORDER BY o.created_at DESC
    """)
    return render_template("orders.html", orders=rows)

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

    # Запускаємо аудит в окремому потоці
    job_id = str(uuid.uuid4())[:8]
    db_execute("UPDATE orders SET status='running',job_id=?,updated_at=? WHERE id=?",
               (job_id, datetime.now().isoformat(), oid))

    def run():
        try:
            run_audit_agent(oid, order["target"], order["company"])
        except Exception as e:
            db_execute("UPDATE orders SET status='failed',updated_at=? WHERE id=?",
                       (datetime.now().isoformat(), oid))
            _log(oid, "ERROR", str(e))

    threading.Thread(target=run, daemon=True).start()
    flash("Audit gestartet — läuft im Hintergrund", "success")
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

    pdf_name = f"Bericht_{order['company'].replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    pdf_path = os.path.join(REPORTS_DIR, pdf_name)
    generate_report_pdf(pdf_path, order, findings, live, tasks, logs)

    db_execute("UPDATE orders SET report_pdf=?,status='completed',updated_at=? WHERE id=?",
               (pdf_name, datetime.now().isoformat(), oid))
    _log(oid, "INFO", f"Bericht generiert: {pdf_name}")
    flash("Bericht erfolgreich erstellt", "success")
    return redirect(url_for("order_detail", oid=oid))


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
@csrf.exempt
@limiter.limit("30 per minute")
def api_live_check():
    target = request.args.get("target","")
    if not target:
        return jsonify({"error": "target required"}), 400
    result = fetch_live_check(target)
    return jsonify(result)

# ── API: findings ─────────────────────────────────────────────────────────────
@app.route("/api/findings/<int:oid>", methods=["POST"])
@login_required
@csrf.exempt
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
@csrf.exempt
def delete_finding(fid):
    db_execute("DELETE FROM findings WHERE id=?", (fid,))
    return jsonify({"ok": True})

# ── API: tasks ────────────────────────────────────────────────────────────────
@app.route("/api/tasks/<int:tid>/toggle", methods=["POST"])
@login_required
@csrf.exempt
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
@csrf.exempt
def update_task_notes(tid):
    notes = (request.json or {}).get("notes", "")
    db_execute("UPDATE order_tasks SET notes=? WHERE id=?", (notes[:2000], tid))
    return jsonify({"ok": True})

# ── API: audit log stream ─────────────────────────────────────────────────────
@app.route("/api/logs/<int:oid>")
@login_required
@csrf.exempt
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

# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    migrate_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
