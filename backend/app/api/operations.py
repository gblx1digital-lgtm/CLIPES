"""Dashboard, categorias, exportações, fila, atividades, automação e sistema."""
from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import CATEGORIES, ActivityEvent, Clip, Creator, Export, Job, SourceVideo
from ..queue import jobs as q
from ..services import storage, transcription
from ..services.scoring import CRITERIA, TIER_LABELS, TIERS
from ..services.settings_store import get_automation, get_value, save_automation
from .serializers import creator_out, export_out, job_out

router = APIRouter(prefix="/api", tags=["operação"])


def _worker_status(db: Session) -> dict[str, Any]:
    hb = get_value(db, "worker_heartbeat")
    if not hb:
        return {"online": False, "last_seen": None, "worker_id": None}
    seen = datetime.fromisoformat(hb["at"])
    return {"online": datetime.now(timezone.utc) - seen < timedelta(seconds=90), "last_seen": hb["at"],
            "worker_id": hb.get("worker_id")}


def integrations() -> dict[str, Any]:
    s = get_settings()
    return {
        "ai": {"configured": s.ai_configured, "model": s.ai_model, "effort": s.ai_effort,
               "env": ["ANTHROPIC_API_KEY"]},
        "youtube": {"configured": s.youtube_configured, "env": ["YOUTUBE_API_KEY"]},
        "twitch": {"configured": s.twitch_configured, "env": ["TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET"]},
        "ffmpeg": {"configured": bool(s.ffmpeg_path and s.ffprobe_path)},
        "transcription": transcription.provider_status(),
    }


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    count = lambda *w: db.scalar(select(func.count(Clip.id)).where(*w)) or 0  # noqa: E731
    videos_total = db.scalar(select(func.count(SourceVideo.id))) or 0
    videos_analyzed = db.scalar(select(func.count(SourceVideo.id)).where(SourceVideo.analysis_status == "done")) or 0
    exported = db.scalar(select(func.count(func.distinct(Export.clip_id))).where(Export.status == "done")) or 0
    stats = {
        "videos_total": videos_total,
        "videos_analyzed": videos_analyzed,
        "videos_awaiting_media": db.scalar(select(func.count(SourceVideo.id)).where(SourceVideo.media_status == "none")) or 0,
        "clips_total": count(),
        "clips_pending": count(Clip.status == "pending_review"),
        "clips_approved": count(Clip.status == "approved"),
        "clips_rejected": count(Clip.status == "rejected"),
        "clips_exported": exported,
        "clips_high": count(Clip.tier == "alto", Clip.status != "rejected"),
    }
    since = datetime.now(timezone.utc) - timedelta(days=13)
    day_rows = db.execute(select(func.date(Clip.discovered_at), func.count(Clip.id))
                          .where(Clip.discovered_at >= since.replace(hour=0, minute=0, second=0))
                          .group_by(func.date(Clip.discovered_at))).all()
    by_day = {str(d): n for d, n in day_rows}
    days = [(since + timedelta(days=i)).date().isoformat() for i in range(14)]
    jobs_active = db.scalars(select(Job).where(Job.status.in_(("queued", "running")))
                             .order_by(Job.status.desc(), Job.priority, Job.id).limit(10)).all()
    jobs_failed_24h = db.scalar(select(func.count(Job.id)).where(
        Job.status == "failed", Job.finished_at >= datetime.now(timezone.utc) - timedelta(hours=24))) or 0
    creators = db.scalars(select(Creator).order_by(Creator.name)).all()
    activity_rows = db.scalars(select(ActivityEvent).order_by(ActivityEvent.id.desc()).limit(15)).all()
    top = db.scalars(select(Clip).where(Clip.status == "pending_review").order_by(Clip.viral_score.desc()).limit(4)).all()
    from .serializers import clip_out

    return {
        "stats": stats,
        "clips_per_day": [{"date": d, "count": by_day.get(d, 0)} for d in days],
        "processing": {
            "worker": _worker_status(db),
            "queued": db.scalar(select(func.count(Job.id)).where(Job.status == "queued")) or 0,
            "running": db.scalar(select(func.count(Job.id)).where(Job.status == "running")) or 0,
            "failed_24h": jobs_failed_24h,
            "active_jobs": [job_out(j) for j in jobs_active],
        },
        "sources": [creator_out(c) for c in creators],
        "activity": [_activity_out(a) for a in activity_rows],
        "top_pending": [clip_out(c) for c in top],
        "integrations": integrations(),
        "automation": get_automation(db).model_dump(),
    }


def _activity_out(a: ActivityEvent) -> dict[str, Any]:
    return {"id": a.id, "level": a.level, "kind": a.kind, "message": a.message, "ref_type": a.ref_type,
            "ref_id": a.ref_id, "created_at": a.created_at.isoformat()}


@router.get("/activity")
def list_activity(limit: int = 50, before_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(ActivityEvent).order_by(ActivityEvent.id.desc()).limit(min(limit, 200))
    if before_id:
        stmt = stmt.where(ActivityEvent.id < before_id)
    return [_activity_out(a) for a in db.scalars(stmt).all()]


@router.get("/categories")
def categories(db: Session = Depends(get_db)):
    rows = {k: (n, avg, hi) for k, n, avg, hi in db.execute(
        select(Clip.category, func.count(Clip.id), func.avg(Clip.viral_score),
               func.sum(case((Clip.tier == "alto", 1), else_=0)))
        .where(Clip.status != "rejected").group_by(Clip.category))}
    approved = dict(db.execute(select(Clip.category, func.count(Clip.id)).where(Clip.status == "approved")
                               .group_by(Clip.category)).all())
    prio = set(get_automation(db).priority_categories)
    return [{"key": k, "label": label, "count": rows.get(k, (0, 0, 0))[0],
             "avg_score": round(float(rows.get(k, (0, 0, 0))[1] or 0), 1),
             "high_count": int(rows.get(k, (0, 0, 0))[2] or 0), "approved": approved.get(k, 0), "priority": k in prio}
            for k, label in CATEGORIES]


@router.get("/scoring")
def scoring_info():
    return {"criteria": [{"key": k, "label": label, "weight": w} for k, (label, w) in CRITERIA.items()],
            "tiers": [{"key": k, "label": TIER_LABELS[k], "min": m} for k, m in TIERS]}


# ------------------------------------------------------------------ exportações
@router.get("/exports")
def list_exports(status: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    stmt = select(Export).order_by(Export.id.desc()).limit(min(limit, 500))
    if status:
        stmt = stmt.where(Export.status.in_(status.split(",")))
    out = []
    jobs = {}
    rows = db.scalars(stmt).all()
    ids = [e.job_id for e in rows if e.job_id]
    if ids:
        jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_(ids))).all()}
    for e in rows:
        item = export_out(e)
        j = jobs.get(e.job_id)
        item["progress"] = round(j.progress, 1) if j else (100.0 if e.status == "done" else 0.0)
        item["job_message"] = j.message if j else None
        out.append(item)
    return out


def _export_file(export_id: int, db: Session):
    e = db.get(Export, export_id)
    path = storage.abs_path(e.path) if e and e.status == "done" else None
    if not path or not path.exists():
        raise HTTPException(404, "Arquivo exportado indisponível.")
    return e, path


@router.get("/exports/{export_id}/download")
def download_export(export_id: int, db: Session = Depends(get_db)):
    e, path = _export_file(export_id, db)
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in (e.clip.title or "corte"))[:60].strip() or "corte"
    return FileResponse(path, media_type="video/mp4", filename=f"{safe} - {e.width}x{e.height}.mp4")


@router.get("/exports/{export_id}/file")
def export_file(export_id: int, db: Session = Depends(get_db)):
    _e, path = _export_file(export_id, db)
    return FileResponse(path, media_type="video/mp4")


@router.delete("/exports/{export_id}", status_code=204)
def delete_export(export_id: int, db: Session = Depends(get_db)):
    e = db.get(Export, export_id)
    if not e:
        raise HTTPException(404, "Exportação não encontrada.")
    if e.status in ("queued", "rendering"):
        raise HTTPException(409, "Cancele a renderização na fila antes de excluir.")
    p = storage.abs_path(e.path)
    if p:
        p.unlink(missing_ok=True)
    clip = e.clip
    db.delete(e)
    db.flush()
    if clip and not any(x.status == "done" for x in clip.exports if x.id != export_id):
        clip.render_status = "none"
    db.commit()


# ------------------------------------------------------------------ fila
@router.get("/jobs")
def list_jobs(status: str | None = None, type: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    stmt = select(Job).order_by(Job.id.desc()).limit(min(limit, 200))
    if status:
        stmt = stmt.where(Job.status.in_(status.split(",")))
    if type:
        stmt = stmt.where(Job.type == type)
    return [job_out(j) for j in db.scalars(stmt).all()]


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Job não encontrado.")
    if j.status not in ("queued", "running"):
        raise HTTPException(400, "Só é possível cancelar jobs na fila ou em execução.")
    j.status = "cancelled"
    j.message = "Cancelado pelo usuário"
    j.finished_at = datetime.now(timezone.utc)
    _reset_ref_after_stop(db, j)
    db.commit()
    return job_out(j)


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Job não encontrado.")
    if j.status not in ("failed", "cancelled"):
        raise HTTPException(400, "Só é possível repetir jobs que falharam ou foram cancelados.")
    new = q.enqueue(db, j.type, j.payload, priority=j.priority, ref_type=j.ref_type, ref_id=j.ref_id, commit=False)
    if j.type == "analyze_video" and j.ref_id:
        v = db.get(SourceVideo, j.ref_id)
        if v:
            v.analysis_status, v.analysis_error = "queued", None
    if j.type == "render_export" and j.ref_id:
        e = db.get(Export, j.ref_id)
        if e:
            e.status, e.error, e.job_id = "queued", None, new.id
            e.clip.render_status = "queued"
    if j.type == "ingest_media" and j.ref_id:
        v = db.get(SourceVideo, j.ref_id)
        if v:
            v.media_status, v.media_error = "ingesting", None
    db.commit()
    return job_out(new)


def _reset_ref_after_stop(db: Session, j: Job) -> None:
    if j.type == "analyze_video" and j.ref_id:
        v = db.get(SourceVideo, j.ref_id)
        if v and v.analysis_status in ("queued", "running"):
            v.analysis_status, v.analysis_error = "failed", "Cancelado pelo usuário"
    elif j.type == "render_export" and j.ref_id:
        e = db.get(Export, j.ref_id)
        if e and e.status in ("queued", "rendering"):
            e.status, e.error = "failed", "Cancelado pelo usuário"
            e.clip.render_status = "failed"
    elif j.type == "ingest_media" and j.ref_id:
        v = db.get(SourceVideo, j.ref_id)
        if v and v.media_status == "ingesting":
            v.media_status, v.media_error = "failed", "Cancelado pelo usuário"


# ------------------------------------------------------------------ automação e sistema
@router.get("/automation")
def get_automation_settings(db: Session = Depends(get_db)):
    return get_automation(db).model_dump()


@router.put("/automation")
def put_automation_settings(body: dict[str, Any], db: Session = Depends(get_db)):
    try:
        return save_automation(db, body).model_dump()
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/system")
def system(db: Session = Depends(get_db)):
    s = get_settings()
    ffmpeg_version = None
    if s.ffmpeg_path:
        try:
            ffmpeg_version = subprocess.run([s.ffmpeg_path, "-version"], capture_output=True, text=True, timeout=5).stdout.split("\n")[0]
        except Exception:  # noqa: BLE001
            pass
    return {
        "integrations": integrations(),
        "worker": _worker_status(db),
        "ffmpeg_version": ffmpeg_version,
        "storage": {"dir": str(s.storage_dir), "usage_bytes": storage.usage_bytes()},
        "database": "postgresql" if s.database_url.startswith("postgres") else "sqlite",
        "limits": {"max_upload_mb": s.max_upload_mb},
    }
