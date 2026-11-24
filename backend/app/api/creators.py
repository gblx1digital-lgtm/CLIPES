from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Clip, Creator, SourceVideo
from ..queue import jobs as q
from ..services import activity
from ..services.layout import normalize_layout
from ..services.sources.drive import parse_folder_id
from .serializers import creator_out, job_out

router = APIRouter(prefix="/api/creators", tags=["criadores"])


class CreatorIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    youtube_handle: str | None = None
    youtube_channel_id: str | None = None
    twitch_login: str | None = None
    drive_folder: str | None = None
    active: bool = True
    media_authorized: bool = False
    authorization_note: str | None = None
    notes: str | None = None


class CreatorPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    youtube_handle: str | None = None
    youtube_channel_id: str | None = None
    twitch_login: str | None = None
    drive_folder: str | None = None
    active: bool | None = None
    media_authorized: bool | None = None
    authorization_note: str | None = None
    notes: str | None = None
    default_layout: dict[str, Any] | None = None


def _clean(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


def _stats(db: Session) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for cid, n in db.execute(select(SourceVideo.creator_id, func.count(SourceVideo.id)).group_by(SourceVideo.creator_id)):
        out.setdefault(cid, {})["videos"] = n
    for cid, n, avg, best in db.execute(
        select(Clip.creator_id, func.count(Clip.id), func.avg(Clip.viral_score), func.max(Clip.viral_score)).group_by(Clip.creator_id)
    ):
        out.setdefault(cid, {}).update({"clips": n, "avg_score": round(float(avg or 0), 1), "best_score": best})
    for cid, n in db.execute(select(Clip.creator_id, func.count(Clip.id)).where(Clip.status == "approved").group_by(Clip.creator_id)):
        out.setdefault(cid, {})["approved"] = n
    return out


@router.get("")
def list_creators(db: Session = Depends(get_db)):
    stats = _stats(db)
    creators = db.scalars(select(Creator).order_by(Creator.name)).all()
    return [creator_out(c, {"videos": 0, "clips": 0, "approved": 0, "avg_score": 0, "best_score": None, **stats.get(c.id, {})})
            for c in creators]


@router.post("", status_code=201)
def create_creator(body: CreatorIn, db: Session = Depends(get_db)):
    if db.scalar(select(Creator).where(func.lower(Creator.name) == body.name.strip().lower())):
        raise HTTPException(409, "Já existe um criador com esse nome.")
    try:
        folder = parse_folder_id(body.drive_folder)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    c = Creator(name=body.name.strip(), youtube_handle=_clean(body.youtube_handle), drive_folder_id=folder,
                youtube_channel_id=_clean(body.youtube_channel_id), twitch_login=_clean(body.twitch_login),
                active=body.active, media_authorized=body.media_authorized,
                authorization_note=_clean(body.authorization_note), notes=_clean(body.notes))
    db.add(c)
    db.commit()
    activity.record(db, "creator", f"Criador adicionado: {c.name}", ref_type="creator", ref_id=c.id)
    return creator_out(c)


@router.patch("/{creator_id}")
def update_creator(creator_id: int, body: CreatorPatch, db: Session = Depends(get_db)):
    c = db.get(Creator, creator_id)
    if not c:
        raise HTTPException(404, "Criador não encontrado.")
    data = body.model_dump(exclude_unset=True)
    for key in ("youtube_handle", "youtube_channel_id", "twitch_login", "authorization_note", "notes"):
        if key in data:
            data[key] = _clean(data[key])
    if "youtube_handle" in data and data["youtube_handle"] != c.youtube_handle and "youtube_channel_id" not in data:
        c.youtube_channel_id = None  # força nova resolução do canal
    if "twitch_login" in data and data["twitch_login"] != c.twitch_login:
        c.twitch_user_id = None
    if "drive_folder" in data:
        try:
            c.drive_folder_id = parse_folder_id(data.pop("drive_folder"))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    if "default_layout" in data and data["default_layout"] is not None:
        data["default_layout"] = normalize_layout(data["default_layout"])
    for k, v in data.items():
        setattr(c, k, v.strip() if k == "name" and isinstance(v, str) else v)
    db.commit()
    return creator_out(c)


@router.delete("/{creator_id}", status_code=204)
def delete_creator(creator_id: int, db: Session = Depends(get_db)):
    c = db.get(Creator, creator_id)
    if not c:
        raise HTTPException(404, "Criador não encontrado.")
    if db.scalar(select(func.count(SourceVideo.id)).where(SourceVideo.creator_id == creator_id)):
        raise HTTPException(409, "Este criador tem vídeos cadastrados. Desative-o em vez de excluir.")
    db.delete(c)
    db.commit()


@router.post("/{creator_id}/check")
def check_creator(creator_id: int, db: Session = Depends(get_db)):
    c = db.get(Creator, creator_id)
    if not c:
        raise HTTPException(404, "Criador não encontrado.")
    if not (c.youtube_handle or c.youtube_channel_id or c.twitch_login or c.drive_folder_id):
        raise HTTPException(400, "Cadastre um canal do YouTube, da Twitch ou uma pasta do Google Drive para este criador.")
    job = q.enqueue(db, "monitor_creator", {"creator_id": c.id}, ref_type="creator", ref_id=c.id, priority=40)
    return job_out(job)
