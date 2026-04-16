# ── Stage 1: Build Go-based security tools ───────────────────────────────────
FROM golang:1.22-alpine AS go-tools
RUN apk add --no-cache git
RUN go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@v3.3.4 \
 && go install github.com/projectdiscovery/httpx/cmd/httpx@v1.6.9 \
 && go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@v2.6.6

# ── Stage 2: testssl.sh ───────────────────────────────────────────────────────
FROM alpine:3.19 AS testssl-stage
RUN apk add --no-cache git
RUN git clone --depth=1 https://github.com/drwetter/testssl.sh.git /opt/testssl

# ── Stage 3: Runtime image ───────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/data/nis2audit.db

# System packages: nmap, dnsutils (dig), perl (for nikto), WeasyPrint libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap curl openssl ca-certificates git \
    dnsutils \
    perl libnet-ssleay-perl libwhisker2-perl libjson-perl libxml-writer-perl \
    bsdmainutils procps \
    libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 \
    libcairo2 libffi8 \
    fonts-liberation fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Install nikto from source (not in Debian Trixie repos)
RUN git clone --depth=1 https://github.com/sullo/nikto.git /opt/nikto \
    && ln -sf /opt/nikto/program/nikto.pl /usr/local/bin/nikto \
    && chmod +x /opt/nikto/program/nikto.pl

# Copy Go binaries from build stage
COPY --from=go-tools /go/bin/nuclei    /usr/local/bin/nuclei
COPY --from=go-tools /go/bin/httpx     /usr/local/bin/httpx
COPY --from=go-tools /go/bin/subfinder /usr/local/bin/subfinder

# Copy testssl.sh
COPY --from=testssl-stage /opt/testssl /opt/testssl
RUN ln -s /opt/testssl/testssl.sh /usr/local/bin/testssl.sh && chmod +x /opt/testssl/testssl.sh

WORKDIR /app

# Pre-download nuclei templates (ignore errors on build)
RUN nuclei -update-templates -silent 2>/dev/null || true

# Install Python dependencies
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Re-copy Go binaries AFTER pip install to prevent Python httpx shim from
# overwriting the ProjectDiscovery httpx Go binary
COPY --from=go-tools /go/bin/httpx /usr/local/bin/httpx

# Copy application
COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/

# Create data and reports dirs
RUN mkdir -p /data /app/reports

EXPOSE 5000

CMD ["python3", "app/app.py"]
