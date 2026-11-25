#!/bin/sh
# Contêiner único: worker em segundo plano (reinicia se cair) + API servindo o painel.
cd /app/backend
# Uploads grandes passam por arquivos temporários: usar o volume (/data), não o disco pequeno do contêiner
mkdir -p /data/tmp && export TMPDIR=/data/tmp
find /data/tmp -type f -mmin +120 -delete 2>/dev/null || true
(while true; do python -m app.worker.main; echo "worker saiu; reiniciando em 5s"; sleep 5; done) &
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
