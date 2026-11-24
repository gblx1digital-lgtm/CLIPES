"""Modelo de dados.

Fluxo principal:
  Creator ──< SourceVideo ──< Clip ──< Export
                 (fonte)      (corte)   (MP4 1080x1920)
  Job: fila de processamento (monitoramento, ingestão, análise, renderização)
  ActivityEvent: trilha de auditoria/atividades exibida no dashboard
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, TypeDecorator, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TZDateTime(TypeDecorator):
    """DateTime sempre em UTC e com timezone (o SQLite perde o fuso ao gravar)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        if isinstance(value, datetime):
            value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):  # noqa: ANN001
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


# ---------------------------------------------------------------- enums (strings)
CATEGORIES: list[tuple[str, str]] = [
    ("engracados", "Momentos Engraçados"),
    ("curiosidades", "Curiosidades"),
    ("missoes", "Missões"),
    ("bugs", "Bugs e Glitches"),
    ("reacoes", "Reações"),
    ("perseguicoes", "Perseguições"),
    ("segredos", "Segredos"),
    ("epicos", "Momentos Épicos"),
    ("noticias", "Notícias e novidades"),
    ("outros", "Outros"),
]
CATEGORY_KEYS = [k for k, _ in CATEGORIES]

CLIP_STATUSES = ["pending_review", "approved", "rejected"]
RENDER_STATUSES = ["none", "queued", "rendering", "done", "failed"]
RIGHTS_BASIS = ["own", "authorized", "licensed"]


class Creator(Base):
    __tablename__ = "creators"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    youtube_handle: Mapped[str | None] = mapped_column(String(120))
    youtube_channel_id: Mapped[str | None] = mapped_column(String(64))
    twitch_login: Mapped[str | None] = mapped_column(String(64))
    twitch_user_id: Mapped[str | None] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Autorização para processar mídia deste criador (cortes de terceiros só com permissão)
    media_authorized: Mapped[bool] = mapped_column(Boolean, default=False)
    authorization_note: Mapped[str | None] = mapped_column(Text)
    # Layout padrão (webcam fixa costuma ficar no mesmo lugar em todas as lives)
    default_layout: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    last_check_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    videos: Mapped[list[SourceVideo]] = relationship(back_populates="creator")


class SourceVideo(Base):
    __tablename__ = "source_videos"
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_source_platform_ext"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(16))  # youtube | twitch | upload | url
    external_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str | None] = mapped_column(String(1000))
    thumbnail_url: Mapped[str | None] = mapped_column(String(1000))
    published_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    discovered_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    is_live_vod: Mapped[bool] = mapped_column(Boolean, default=False)

    # Direitos sobre a mídia (obrigatório para processar)
    rights_basis: Mapped[str | None] = mapped_column(String(16))
    rights_note: Mapped[str | None] = mapped_column(Text)

    media_status: Mapped[str] = mapped_column(String(16), default="none")  # none|ingesting|ready|failed
    media_path: Mapped[str | None] = mapped_column(String(1000))
    media_error: Mapped[str | None] = mapped_column(Text)
    duration_s: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    has_audio: Mapped[bool | None] = mapped_column(Boolean)

    analysis_status: Mapped[str] = mapped_column(String(16), default="not_started")  # not_started|queued|running|done|failed
    analysis_error: Mapped[str | None] = mapped_column(Text)
    analyzed_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    layout_hint: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # webcam detectada
    analysis_meta: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    creator: Mapped[Creator] = relationship(back_populates="videos")
    clips: Mapped[list[Clip]] = relationship(back_populates="source_video", cascade="all, delete-orphan")


class Clip(Base):
    __tablename__ = "clips"
    __table_args__ = (Index("ix_clips_status_score", "status", "viral_score"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_video_id: Mapped[int] = mapped_column(ForeignKey("source_videos.id", ondelete="CASCADE"), index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"), index=True)

    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    # Título interno (organização/legenda do post). NUNCA é gravado no vídeo.
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    hook: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), index=True)
    viral_score: Mapped[int] = mapped_column(Integer, index=True)
    tier: Mapped[str] = mapped_column(String(8))  # alto | medio | baixo
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSON)
    rationale: Mapped[str | None] = mapped_column(Text)
    signals: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    analysis_source: Mapped[str] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(String(16), default="pending_review", index=True)
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    auto_approved: Mapped[bool] = mapped_column(Boolean, default=False)

    layout: Mapped[dict[str, Any]] = mapped_column(JSON)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1000))
    render_status: Mapped[str] = mapped_column(String(16), default="none")

    discovered_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    source_video: Mapped[SourceVideo] = relationship(back_populates="clips")
    creator: Mapped[Creator] = relationship()
    exports: Mapped[list[Export]] = relationship(back_populates="clip", cascade="all, delete-orphan")


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    clip_id: Mapped[int] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|rendering|done|failed
    quality: Mapped[str] = mapped_column(String(16), default="high")
    width: Mapped[int] = mapped_column(Integer, default=1080)
    height: Mapped[int] = mapped_column(Integer, default=1920)
    layout: Mapped[dict[str, Any]] = mapped_column(JSON)
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    path: Mapped[str | None] = mapped_column(String(1000))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime())

    clip: Mapped[Clip] = relationship(back_populates="exports")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_claim", "status", "priority", "run_after"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|succeeded|failed|cancelled
    priority: Mapped[int] = mapped_column(Integer, default=100)  # menor = antes
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    worker_id: Mapped[str | None] = mapped_column(String(64))
    run_after: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    heartbeat_at: Mapped[datetime | None] = mapped_column(TZDateTime())


class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(8), default="info")  # info|success|warning|error
    kind: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)
