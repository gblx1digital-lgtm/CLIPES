from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import RIGHTS_BASIS, Clip, Creator, SourceVideo
from ..queue import jobs as q
from ..services import activity, storage
from .serializers import job_out, video_out

router = APIRouter(prefix="/api/videos", tags=["vídeos"])

ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".ts", ".flv"}


def _clip_counts(db: Session) -> dict[int, int]:
    return dict(db.execute(select(Clip.source_video_id, func.count(Clip.id)).group_by(Clip.source_video_id)).all())


@router.get("")
def list_videos(
    creator_id: int | None = None,
    media_status: str | None = None,
    analysis_status: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    stmt = select(SourceVideo).order_by(SourceVideo.discovered_at.desc()).limit(min(limit, 500))
    if creator_id:
        stmt = stmt.where(SourceVideo.creator_id == creator_id)
    if media_status:
        stmt = stmt.where(SourceVideo.media_status == media_status)
    if analysis_status:
        stmt = stmt.where(SourceVideo.analysis_status == analysis_status)
    counts = _clip_counts(db)
    return [video_out(v, counts.get(v.id, 0)) for v in db.scalars(stmt).all()]


@router.get("/{video_id}")
def get_video(video_id: int, db: Session = Depends(get_db)):
    v = db.get(SourceVideo, video_id)
    if not v:
        raise HTTPException(404, "Vídeo não encontrado.")
    return video_out(v)


def _check_rights(rights_basis: str, confirm: bool) -> None:
    if rights_basis not in RIGHTS_BASIS:
        raise HTTPException(400, "Informe a base de direitos: own (próprio), authorized (autorizado) ou licensed (licenciado).")
    if not confirm:
        raise HTTPException(400, "Confirme que você tem direito de usar esta mídia.")


async def _save_upload(file: UploadFile, dst_dir: Path) -> Path:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Formato não suportado ({ext or 'sem extensão'}). Use: {', '.join(sorted(ALLOWED_EXT))}")
    limit = get_settings().max_upload_mb * 1024 * 1024
    tmp = storage.root() / "uploads_tmp" / f"{uuid.uuid4().hex}{ext}"
    size = 0
    try:
        with open(tmp, "wb") as f:
            while chunk := await file.read(4 * 1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Arquivo maior que o limite de {get_settings().max_upload_mb} MB.")
                f.write(chunk)
        dst = dst_dir / f"source{ext}"
        shutil.move(str(tmp), dst)
    except BaseException:
        tmp.unlink(missing_ok=True)  # envio interrompido ou disco cheio: não deixa lixo ocupando o volume
        raise
    finally:
        await file.close()
    return dst


@router.post("/upload", status_code=201)
async def upload_video(
    file: UploadFile = File(...),
    creator_id: int = Form(...),
    title: str = Form(""),
    rights_basis: str = Form(...),
    rights_note: str = Form(""),
    confirm_rights: bool = Form(False),
    video_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    """Envia a mídia de um vídeo. Com video_id, anexa a mídia a um vídeo descoberto pelo monitoramento."""
    _check_rights(rights_basis, confirm_rights)
    creator = db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(404, "Criador não encontrado.")
    if rights_basis == "authorized" and not creator.media_authorized:
        raise HTTPException(400, "Este criador não está marcado como autorizado. Registre a autorização em Criadores.")
    if video_id:
        video = db.get(SourceVideo, video_id)
        if not video:
            raise HTTPException(404, "Vídeo não encontrado.")
        if video.media_status == "ingesting":
            raise HTTPException(409, "A mídia deste vídeo já está sendo processada.")
    else:
        video = SourceVideo(creator_id=creator.id, platform="upload", external_id=uuid.uuid4().hex,
                            title=(title or Path(file.filename or "video").stem)[:500])
        db.add(video)
        db.flush()
    path = await _save_upload(file, storage.source_dir(video.id))
    video.rights_basis = rights_basis
    video.rights_note = rights_note.strip() or None
    video.media_path = storage.rel_path(path)
    video.media_status = "ingesting"
    job = q.enqueue(db, "ingest_media", {"video_id": video.id}, ref_type="video", ref_id=video.id, priority=30, commit=False)
    db.commit()  # status e job na mesma transação
    activity.record(db, "ingest", f"Mídia enviada para “{video.title[:100]}” ({rights_basis})", ref_type="video", ref_id=video.id)
    return {"video": video_out(video), "job": job_out(job)}


class FromUrlIn(BaseModel):
    creator_id: int
    url: HttpUrl
    title: str = Field("", max_length=500)
    rights_basis: str
    rights_note: str = ""
    confirm_rights: bool = False
    video_id: int | None = None


@router.post("/from-url", status_code=201)
def video_from_url(body: FromUrlIn, db: Session = Depends(get_db)):
    """Link DIRETO para um arquivo de vídeo autorizado (ex.: link de download enviado pelo criador)."""
    _check_rights(body.rights_basis, body.confirm_rights)
    creator = db.get(Creator, body.creator_id)
    if not creator:
        raise HTTPException(404, "Criador não encontrado.")
    if body.rights_basis == "authorized" and not creator.media_authorized:
        raise HTTPException(400, "Este criador não está marcado como autorizado. Registre a autorização em Criadores.")
    url = str(body.url)
    if body.video_id:
        video = db.get(SourceVideo, body.video_id)
        if not video:
            raise HTTPException(404, "Vídeo não encontrado.")
    else:
        video = SourceVideo(creator_id=creator.id, platform="url", external_id=uuid.uuid4().hex,
                            title=(body.title or url.rsplit("/", 1)[-1] or "Vídeo")[:500], url=url)
        db.add(video)
        db.flush()
    video.rights_basis = body.rights_basis
    video.rights_note = body.rights_note.strip() or None
    video.media_status = "ingesting"
    job = q.enqueue(db, "ingest_media", {"video_id": video.id, "url": url}, ref_type="video", ref_id=video.id, priority=30,
                    commit=False)
    db.commit()
    return {"video": video_out(video), "job": job_out(job)}


@router.post("/{video_id}/analyze")
def analyze(video_id: int, db: Session = Depends(get_db)):
    v = db.get(SourceVideo, video_id)
    if not v:
        raise HTTPException(404, "Vídeo não encontrado.")
    if v.media_status != "ready":
        raise HTTPException(400, "A mídia deste vídeo ainda não está disponível. Envie o arquivo autorizado primeiro.")
    v.analysis_status = "queued"
    v.analysis_error = None
    job = q.enqueue(db, "analyze_video", {"video_id": v.id}, ref_type="video", ref_id=v.id, priority=50, commit=False)
    db.commit()
    return job_out(job)


@router.delete("/{video_id}", status_code=204)
def delete_video(video_id: int, db: Session = Depends(get_db)):
    v = db.get(SourceVideo, video_id)
    if not v:
        raise HTTPException(404, "Vídeo não encontrado.")
    if any(c.status == "approved" for c in v.clips):
        raise HTTPException(409, "Há cortes aprovados deste vídeo. Remova-os antes de excluir a fonte.")
    for c in v.clips:
        for p in [storage.abs_path(c.thumbnail_path), *[storage.abs_path(e.path) for e in c.exports]]:
            if p:
                p.unlink(missing_ok=True)
    storage.video_thumb_path(v.id).unlink(missing_ok=True)
    shutil.rmtree(storage.root() / "sources" / str(v.id), ignore_errors=True)
    shutil.rmtree(storage.root() / "work" / str(v.id), ignore_errors=True)
    title = v.title
    db.delete(v)
    db.commit()
    activity.record(db, "video", f"Vídeo removido: {title[:100]}")


@router.get("/{video_id}/thumbnail")
def video_thumbnail(video_id: int):
    path = storage.video_thumb_path(video_id)
    if not path.exists():
        raise HTTPException(404, "Miniatura indisponível.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/{video_id}/stream")
def stream_video(video_id: int, db: Session = Depends(get_db)):
    v = db.get(SourceVideo, video_id)
    if not v or v.media_status != "ready":
        raise HTTPException(404, "Mídia indisponível.")
    path = storage.abs_path(v.media_path)
    if not path or not path.exists():
        raise HTTPException(404, "Arquivo não encontrado.")
    media_type = {".webm": "video/webm", ".mkv": "video/x-matroska", ".mov": "video/quicktime"}.get(path.suffix, "video/mp4")
    return FileResponse(path, media_type=media_type)  # suporta Range (seek no player)
