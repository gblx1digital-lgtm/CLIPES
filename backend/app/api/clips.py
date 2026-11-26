from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..logging_setup import redact_secrets
from ..models import CATEGORY_KEYS, Clip, Export, utcnow
from ..queue import jobs as q
from ..services import activity, ai_analysis, render, storage
from ..services.layout import normalize_layout
from ..services.settings_store import get_automation
from .serializers import CATEGORY_LABELS, clip_out, export_out

router = APIRouter(prefix="/api/clips", tags=["cortes"])

SORTS = {
    "score": (Clip.viral_score.desc(), Clip.id.desc()),
    "recent": (Clip.discovered_at.desc(), Clip.id.desc()),
    "duration": ((Clip.end_s - Clip.start_s).asc(), Clip.id.desc()),
}


@router.get("")
def list_clips(
    creator_id: int | None = None,
    category: str | None = None,
    status: str | None = None,
    tier: str | None = None,
    render_status: str | None = None,
    min_score: int | None = None,
    max_score: int | None = None,
    min_duration: float | None = None,
    max_duration: float | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    q_: str | None = Query(None, alias="q"),
    sort: Literal["score", "recent", "duration"] = "score",
    page: int = 1,
    page_size: int = 24,
    db: Session = Depends(get_db),
):
    filters = []
    if creator_id:
        filters.append(Clip.creator_id == creator_id)
    if category:
        filters.append(Clip.category == category)
    if status:
        filters.append(Clip.status.in_(status.split(",")))
    if tier:
        filters.append(Clip.tier.in_(tier.split(",")))
    if render_status:
        filters.append(Clip.render_status.in_(render_status.split(",")))
    if min_score is not None:
        filters.append(Clip.viral_score >= min_score)
    if max_score is not None:
        filters.append(Clip.viral_score <= max_score)
    if min_duration is not None:
        filters.append((Clip.end_s - Clip.start_s) >= min_duration)
    if max_duration is not None:
        filters.append((Clip.end_s - Clip.start_s) <= max_duration)
    if date_from:
        filters.append(Clip.discovered_at >= date_from)
    if date_to:
        filters.append(Clip.discovered_at <= date_to)
    if q_:
        like = f"%{q_.strip()}%"
        filters.append(or_(Clip.title.ilike(like), Clip.summary.ilike(like)))
    page_size = max(1, min(page_size, 100))
    total = db.scalar(select(func.count(Clip.id)).where(*filters)) or 0
    items = db.scalars(select(Clip).where(*filters).order_by(*SORTS[sort]).offset((max(page, 1) - 1) * page_size).limit(page_size)).all()
    return {"items": [clip_out(c) for c in items], "total": total, "page": page, "page_size": page_size}


@router.get("/{clip_id}")
def get_clip(clip_id: int, db: Session = Depends(get_db)):
    c = db.get(Clip, clip_id)
    if not c:
        raise HTTPException(404, "Corte não encontrado.")
    return clip_out(c, detail=True)


class ClipPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    category: str | None = None
    start_s: float | None = Field(None, ge=0)
    end_s: float | None = Field(None, gt=0)
    layout: dict[str, Any] | None = None
    status: Literal["pending_review", "approved", "rejected"] | None = None
    review_note: str | None = None


def _regen_thumbnail(clip_id: int) -> None:
    db = SessionLocal()
    try:
        c = db.get(Clip, clip_id)
        if not c:
            return
        v = c.source_video
        src = storage.abs_path(v.media_path)
        if not src or not src.exists():
            return
        t = storage.thumb_path(c.id)
        render.render_thumbnail(src, t, t=min(c.start_s + 1.0, c.end_s), layout=c.layout, src_w=v.width, src_h=v.height)
        c.thumbnail_path = storage.rel_path(t)
        c.updated_at = utcnow()
        db.commit()
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger("clipes.api").exception("Falha ao regenerar miniatura do corte %s", clip_id)
    finally:
        db.close()


@router.patch("/{clip_id}")
def update_clip(clip_id: int, body: ClipPatch, background: BackgroundTasks, db: Session = Depends(get_db)):
    c = db.get(Clip, clip_id)
    if not c:
        raise HTTPException(404, "Corte não encontrado.")
    data = body.model_dump(exclude_unset=True)
    visual_change = False
    if "category" in data:
        if data["category"] not in CATEGORY_KEYS:
            raise HTTPException(400, "Categoria inválida.")
        c.category = data["category"]
    if "title" in data:
        c.title = data["title"].strip()
    if "start_s" in data or "end_s" in data:
        start = data.get("start_s", c.start_s)
        end = data.get("end_s", c.end_s)
        dur = c.source_video.duration_s or end
        if not (0 <= start < end <= dur + 0.05):
            raise HTTPException(400, "Início e fim inválidos para a duração do vídeo.")
        if end - start < 1:
            raise HTTPException(400, "O corte precisa ter pelo menos 1 segundo.")
        if end - start > 180:
            raise HTTPException(400, "O corte deve ter no máximo 180 segundos.")
        c.start_s, c.end_s = round(start, 3), round(end, 3)
        visual_change = True
    if "layout" in data and data["layout"] is not None:
        lay = normalize_layout({**data["layout"], "cam_source": data["layout"].get("cam_source") or "manual"})
        if data["layout"].get("mode") == "split" and not lay["cam"]:
            raise HTTPException(400, "Para tela dividida, defina a área da webcam.")
        c.layout = lay
        visual_change = True
    if "status" in data and data["status"] != c.status:
        c.status = data["status"]
        c.reviewed_at = utcnow() if c.status != "pending_review" else None
        c.auto_approved = False
        label = {"approved": "aprovado", "rejected": "rejeitado", "pending_review": "voltou para revisão"}[c.status]
        activity.record(db, "review", f"Corte {label}: {c.title[:100]}",
                        level="success" if c.status == "approved" else "info", ref_type="clip", ref_id=c.id, commit=False)
    if "review_note" in data:
        c.review_note = (data["review_note"] or "").strip() or None
    c.updated_at = utcnow()
    db.commit()
    if visual_change:
        background.add_task(_regen_thumbnail, c.id)
    return clip_out(c, detail=True)


class ExportIn(BaseModel):
    quality: Literal["standard", "high", "max"] | None = None


class TitleOptionsBody(BaseModel):
    keep_titles: bool = False  # True: só gera as hashtags e mantém as opções de título atuais


@router.post("/{clip_id}/title-options")
def generate_title_options(clip_id: int, body: TitleOptionsBody | None = None, db: Session = Depends(get_db)):
    """Gera (ou troca por novas) 5 opções de título e as hashtags do segmento para postar o corte."""
    c = db.get(Clip, clip_id)
    if not c:
        raise HTTPException(404, "Corte não encontrado.")
    ctx = {
        "creator": c.creator.name if c.creator else None,
        "source_title": c.source_video.title if c.source_video else None,
        "duration_s": c.end_s - c.start_s, "category": CATEGORY_LABELS.get(c.category, c.category),
        "title": c.title, "summary": c.summary, "hook": c.hook, "rationale": c.rationale,
    }
    keep = bool(body and body.keep_titles and c.title_options)
    try:
        titles, tags = ai_analysis.suggest_post(ctx, avoid=None if keep else (c.title_options or None))
    except ai_analysis.AIUnavailable as e:
        raise HTTPException(400, redact_secrets(str(e))) from e
    except ai_analysis.AIError as e:
        raise HTTPException(502, redact_secrets(str(e))) from e
    if not keep:
        c.title_options = titles
    c.hashtags = tags or c.hashtags
    db.commit()
    db.refresh(c)
    return clip_out(c, detail=True)


@router.post("/{clip_id}/export", status_code=201)
def export_clip(clip_id: int, body: ExportIn | None = None, db: Session = Depends(get_db)):
    c = db.get(Clip, clip_id)
    if not c:
        raise HTTPException(404, "Corte não encontrado.")
    if c.status != "approved":
        raise HTTPException(400, "Aprove o corte antes de exportar.")
    if c.source_video.media_status != "ready":
        raise HTTPException(400, "A mídia original não está disponível.")
    quality = (body.quality if body and body.quality else None) or get_automation(db).export_quality
    exp = Export(clip_id=c.id, quality=quality, layout=c.layout, start_s=c.start_s, end_s=c.end_s, status="queued")
    db.add(exp)
    db.flush()
    job = q.enqueue(db, "render_export", {"export_id": exp.id}, ref_type="export", ref_id=exp.id, priority=20, commit=False)
    exp.job_id = job.id
    c.render_status = "queued"
    db.commit()
    return export_out(exp)


@router.get("/{clip_id}/thumbnail")
def clip_thumbnail(clip_id: int, db: Session = Depends(get_db)):
    c = db.get(Clip, clip_id)
    path = storage.abs_path(c.thumbnail_path) if c else None
    if not path or not path.exists():
        raise HTTPException(404, "Miniatura indisponível.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
