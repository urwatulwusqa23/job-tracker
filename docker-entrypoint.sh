#!/bin/sh
set -e

alembic upgrade head

exec gunicorn \
  --bind 0.0.0.0:"${PORT:-8080}" \
  --workers 2 \
  --worker-class uvicorn.workers.UvicornWorker \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  main:app
