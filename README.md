# NIS2Audit — Automated Security Audit Platform

**Andrii-IT** · IT-Sicherheitsdienstleistungen

Automated NIS2/DSGVO compliance audit platform with AI-powered vulnerability analysis, live security checks, and professional PDF report generation.

## Features

- **AI-Powered Audit Agent** — Claude-based agent runs security tools (Nmap, Nuclei, httpx, Nikto, testssl.sh, subfinder) and produces structured findings
- **Live Security Check** — Real-time HTTP headers, TLS/SSL, Cookie flags, DNS (SPF/DMARC/DKIM/DNSSEC) analysis
- **PDF Reports** — Professional German-language audit reports with CVSS scoring, DSGVO/NIS2 mapping, and remediation recommendations (WeasyPrint)
- **Compliance Checklist** — 26 NIS2/DSGVO tasks per client with progress tracking
- **Client & Order Management** — Full CRM workflow: Angebot → Audit → Bericht

## Tech Stack

- **Backend:** Python 3.12 / Flask + SQLite
- **PDF:** WeasyPrint (real PDF) with HTML fallback
- **AI:** Anthropic Claude API (configurable model)
- **Security Tools:** Nmap, Nuclei, httpx, subfinder, Nikto, testssl.sh (compiled in Docker multi-stage build)
- **Reverse Proxy:** nginx with TLS, security headers (CSP, HSTS, COOP, CORP, etc.)
- **Containerized:** Docker Compose

## Quick Start

### 1. Clone

```bash
git clone https://github.com/pilipandr770/NIS2-SDWGO.git
cd NIS2-SDWGO
```

### 2. Configure Environment

Copy and edit the `.env` file:

```bash
cp .env.example .env   # or edit .env directly
```

**Required variables:**

| Variable | Description | Example |
|----------|-------------|---------|
| `SECRET_KEY` | Flask session secret (min 32 chars) | `openssl rand -hex 32` |
| `ADMIN_PASSWORD` | Login password | strong password |
| `ANTHROPIC_API_KEY` | Claude API key for AI agent | `sk-ant-api03-...` |

**Optional variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_EMAIL` | `admin@andrii-it.de` | Login email |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5` | AI model name |
| `DB_PATH` | `/data/nis2audit.db` | SQLite database path |
| `HTTPS` | `1` | Enable secure session cookies |

### 3. Generate TLS Certificate

For development (self-signed):

```bash
chmod +x generate-ssl.sh
./generate-ssl.sh
```

For production, use Let's Encrypt:

```bash
# Option A: certbot standalone (stop nginx first)
certbot certonly --standalone -d your-domain.de
cp /etc/letsencrypt/live/your-domain.de/fullchain.pem ssl/cert.pem
cp /etc/letsencrypt/live/your-domain.de/privkey.pem ssl/key.pem

# Option B: Use Cloudflare Origin Certificate
# Download from Cloudflare Dashboard → SSL/TLS → Origin Server
```

### 4. Build & Run

```bash
docker-compose up -d --build
```

The platform will be available at:
- **HTTPS:** https://localhost (or your domain)
- **HTTP:** redirects to HTTPS

### 5. Login

Navigate to `https://your-domain/login` and use:
- **Email:** value of `ADMIN_EMAIL`
- **Password:** value of `ADMIN_PASSWORD`

## Usage Workflow

1. **Add Client** — Create client with company name, address, contact
2. **Create Angebot** — Generate offer PDF with target URL and price
3. **Start Audit** — AI agent runs all security tools against the target
4. **Review Findings** — Check/edit findings, mark compliance tasks
5. **Generate Bericht** — Create final audit report PDF

## Project Structure

```
app/
├── app.py              # Flask application, routes, API
├── agent.py            # AI audit agent (Anthropic Claude)
├── live_check.py       # Real-time security checks
├── pdf_generator.py    # PDF/HTML report generation
├── models.py           # SQLite database models
└── requirements.txt    # Python dependencies
templates/              # Jinja2 HTML templates
static/                 # CSS, JS
nginx.conf              # Reverse proxy config
Dockerfile              # Multi-stage build
docker-compose.yml      # Service orchestration
```

## Security

- CSRF protection on all endpoints (Flask-WTF)
- SSRF protection — private/loopback IPs blocked
- Rate limiting (10/min login, 30/min API)
- Session cookies: HttpOnly, SameSite=Lax, Secure
- nginx security headers: CSP, HSTS, X-Frame-Options, XCTO, Referrer-Policy, Permissions-Policy, COOP, CORP
- Password hashed with Werkzeug (pbkdf2:sha256)

## Updating (without rebuild)

For Python code changes only:

```bash
docker cp app/app.py nis2audit_v2-nis2audit-1:/app/app/app.py
# Restart Flask (container auto-restarts)
docker restart nis2audit_v2-nis2audit-1
```

For nginx config changes:

```bash
docker cp nginx.conf nis2audit_v2-nginx-1:/etc/nginx/nginx.conf
docker exec nis2audit_v2-nginx-1 nginx -t
docker exec nis2audit_v2-nginx-1 nginx -s reload
```

## License

Proprietary — Andrii-IT. All rights reserved.
