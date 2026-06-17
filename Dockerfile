# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

# System deps for pdfplumber (needs pdfminer which needs no extra system libs on slim)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache — only rebuilds when requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for SQLite
RUN mkdir -p /data

# ── Runtime config ────────────────────────────────────────────────────────────
ENV DB_PATH=/data/jobtracker.db
ENV PORT=8080

EXPOSE 8080

# Gunicorn: 2 workers, 120s timeout (AI calls can take ~25s)
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
