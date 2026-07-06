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
RUN chmod +x docker-entrypoint.sh

# Create data directory for SQLite
RUN mkdir -p /data

# ── Runtime config ────────────────────────────────────────────────────────────
ENV DB_PATH=/data/jobtracker.db
ENV PORT=8080

EXPOSE 8080

# Runs pending Alembic migrations, then starts gunicorn with uvicorn workers
# (2 workers, 120s timeout — AI calls can take ~25s)
ENTRYPOINT ["./docker-entrypoint.sh"]
