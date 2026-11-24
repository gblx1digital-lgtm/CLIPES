#!/bin/sh
# Contêiner único: worker em segundo plano (reinicia se cair) + API servindo o painel.
cd /app/backend
(while true; do python -m app.worker.main; echo "worker saiu; reiniciando em 5s"; sleep 5; done) &
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
