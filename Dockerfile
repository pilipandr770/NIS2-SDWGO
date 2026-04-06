FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/data/nis2audit.db

# System packages (nmap for port scan, openssl/curl for live checks, WeasyPrint PDF libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap curl openssl ca-certificates \
    libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 \
    libcairo2 libffi8 \
    fonts-liberation fontconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/

# Create data and reports dirs
RUN mkdir -p /data /app/reports

EXPOSE 5000

CMD ["python3", "app/app.py"]
