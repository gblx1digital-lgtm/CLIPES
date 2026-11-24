"""Fila de processamento persistida no banco.

Por que no banco e não Redis: a fila sobrevive a reinícios, é auditável pelo painel
(progresso/erro por job) e funciona igual em SQLite (dev) e Postgres (produção).
O "claim" é atômico: UPDATE ... WHERE status='queued' só tem sucesso para um worker.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Job, utcnow

JOB_TYPES = {"monitor_creator", "ingest_media", "analyze_video", "render_export"}

ACTIVE_STATUSES = ("queued", "running")


def enqueue(
    db: Session,
    type: str,
    payload: dict[str, Any] | None = None,
    *,
    priority: int = 100,
    ref_type: str | None = None,
    ref_id: int | None = None,
    max_attempts: int = 2,
    dedupe: bool = True,
    commit: bool = True,
) -> Job:
    if type not in JOB_TYPES:
        raise ValueError(f"Tipo de job desconhecido: {type}")
    if dedupe and ref_type and ref_id is not None:
        existing = db.scalar(
            select(Job).where(
                Job.type == type, Job.ref_type == ref_type, Job.ref_id == ref_id, Job.status.in_(ACTIVE_STATUSES)
            )
        )
        if existing:
            return existing
    job = Job(
        type=type,
        payload=payload or {},
        priority=priority,
        ref_type=ref_type,
        ref_id=ref_id,
        max_attempts=max_attempts,
        message="Na fila",
    )
    db.add(job)
    if commit:
        db.commit()
    else:
        db.flush()
    return job


def claim_next(db: Session, worker_id: str, types: set[str] | None = None) -> Job | None:
    now = utcnow()
    q = (
        select(Job.id)
        .where(Job.status == "queued", Job.run_after <= now)
        .order_by(Job.priority, Job.id)
        .limit(5)
    )
    if types:
        q = q.where(Job.type.in_(types))
    for job_id in db.scalars(q).all():
        res = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="running", worker_id=worker_id, started_at=now, heartbeat_at=now,
                    attempts=Job.attempts + 1, message="Iniciando", error=None)
        )
        db.commit()
        if res.rowcount == 1:
            return db.get(Job, job_id, populate_existing=True)
    return None


def progress(db: Session, job: Job, pct: float, message: str | None = None) -> None:
    job.progress = max(0.0, min(100.0, pct))
    if message:
        job.message = message[:500]
    job.heartbeat_at = utcnow()
    db.commit()


def is_cancelled(db: Session, job: Job) -> bool:
    db.refresh(job, attribute_names=["status"])
    return job.status == "cancelled"


def succeed(db: Session, job: Job, message: str = "Concluído") -> None:
    job.status = "succeeded"
    job.progress = 100.0
    job.message = message[:500]
    job.finished_at = utcnow()
    db.commit()


def fail(db: Session, job: Job, error: str, *, retryable: bool = True) -> bool:
    """Marca falha. Retorna True se o job voltou para a fila (nova tentativa)."""
    job.error = error[-4000:]
    job.finished_at = utcnow()
    if retryable and job.attempts < job.max_attempts:
        job.status = "queued"
        job.message = f"Falhou (tentativa {job.attempts}/{job.max_attempts}); nova tentativa agendada"
        job.run_after = utcnow() + timedelta(seconds=30 * job.attempts)
        job.progress = 0.0
        db.commit()
        return True
    job.status = "failed"
    job.message = "Falhou"
    db.commit()
    return False


def recover_stale(db: Session, timeout_minutes: int) -> int:
    """Jobs 'running' sem heartbeat (worker morreu) voltam para a fila."""
    limit = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
    stale = db.scalars(select(Job).where(Job.status == "running", Job.heartbeat_at < limit)).all()
    for job in stale:
        job.status = "queued" if job.attempts < job.max_attempts else "failed"
        job.message = "Recuperado após worker parar de responder"
        job.error = (job.error or "") + "\nWorker sem heartbeat; job recuperado."
    db.commit()
    return len(stale)
