"""Processo worker: consome a fila e agenda o monitoramento automático.

Uso:  python -m app.worker.main
Para mais paralelismo, rode mais de um processo (o claim da fila é atômico).
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import traceback

from ..config import get_settings
from ..db import SessionLocal, init_db
from ..logging_setup import setup_logging
from ..queue import jobs as q
from sqlalchemy import update

from ..models import Job, utcnow
from ..services import activity
from ..services.settings_store import set_value
from .handlers import HANDLERS, NON_RETRYABLE, due_monitors, on_requeue, reconcile_orphans

log = logging.getLogger("clipes.worker")

_stop = False


def _handle_signal(signum, _frame):  # noqa: ANN001
    global _stop
    log.info("Sinal %s recebido; encerrando após o job atual.", signum)
    _stop = True


def run_one(worker_id: str) -> bool:
    """Processa um job (se houver). Retorna True se processou algo."""
    db = SessionLocal()
    try:
        job = q.claim_next(db, worker_id)
        if job is None:
            return False
        handler = HANDLERS.get(job.type)
        log.info("Job #%s %s iniciado (tentativa %s)", job.id, job.type, job.attempts)
        try:
            if handler is None:
                raise RuntimeError(f"Sem handler para {job.type}")
            message = handler(db, job)
            db.refresh(job)
            if job.status == "cancelled":
                return True
            q.succeed(db, job, message or "Concluído")
            log.info("Job #%s concluído: %s", job.id, message)
        except NON_RETRYABLE as e:
            db.rollback()
            if q.is_cancelled(db, job):
                return True
            log.warning("Job #%s falhou (definitivo): %s", job.id, e)
            q.fail(db, job, str(e), retryable=False)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            if q.is_cancelled(db, job):
                return True
            log.exception("Job #%s falhou", job.id)
            requeued = q.fail(db, job, f"{e}\n\n{traceback.format_exc()[-2500:]}", retryable=True)
            if requeued:
                on_requeue(db, job)
            else:
                activity.record(db, "job", f"Job {job.type} #{job.id} falhou: {str(e)[:200]}", level="error",
                                ref_type="job", ref_id=job.id)
        return True
    finally:
        db.close()


def _heartbeat_loop(worker_id: str) -> None:
    """Sinal de vida em thread separada: continua mesmo durante jobs longos."""
    while not _stop:
        db = SessionLocal()
        try:
            set_value(db, "worker_heartbeat", {"at": utcnow().isoformat(), "worker_id": worker_id})
            db.execute(update(Job).where(Job.worker_id == worker_id, Job.status == "running")
                       .values(heartbeat_at=utcnow()))
            db.commit()
        except Exception:  # noqa: BLE001
            log.warning("Falha ao registrar heartbeat", exc_info=True)
        finally:
            db.close()
        for _ in range(20):
            if _stop:
                break
            time.sleep(1)


def main() -> None:
    setup_logging("worker")
    s = get_settings()
    init_db()
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    log.info("Worker %s iniciado (ffmpeg=%s, IA=%s)", worker_id, bool(s.ffmpeg_path), s.ai_configured)

    threading.Thread(target=_heartbeat_loop, args=(worker_id,), daemon=True).start()
    last_schedule = 0.0
    last_recover = 0.0
    while not _stop:
        now = time.monotonic()
        if now - last_schedule > 20:
            last_schedule = now
            db = SessionLocal()
            try:
                n = due_monitors(db)
                if n:
                    log.info("%s verificações de criadores agendadas", n)
                if now - last_recover > 300:
                    last_recover = now
                    rec = q.recover_stale(db, s.job_stale_minutes)
                    if rec:
                        log.warning("%s jobs recuperados de workers parados", rec)
                    fixed = reconcile_orphans(db)
                    if fixed:
                        log.warning("%s itens destravados (sem job ativo)", fixed)
            except Exception:  # noqa: BLE001
                log.exception("Falha no agendador")
            finally:
                db.close()
        try:
            worked = run_one(worker_id)
        except Exception:  # noqa: BLE001
            log.exception("Falha inesperada no loop do worker")
            worked = False
        if not worked:
            time.sleep(s.worker_poll_seconds)
    log.info("Worker encerrado.")


if __name__ == "__main__":
    main()
