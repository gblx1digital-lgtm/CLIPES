"""Configuração central lida de variáveis de ambiente (arquivo .env suportado).

Segredos (chaves de API) ficam SOMENTE no ambiente — nunca no banco nem no frontend.
Parâmetros operacionais editáveis pelo painel (automação) ficam no banco: ver services/settings_store.py.
"""
from __future__ import annotations

import re
import shutil
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Infra
    database_url: str = f"sqlite:///{(REPO_DIR / 'data' / 'clipes.db').as_posix()}"
    storage_dir: Path = REPO_DIR / "data" / "storage"
    frontend_dist: Path = REPO_DIR / "frontend" / "dist"
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"

    # Acesso ao painel quando publicado na internet (vazio = sem senha, só para uso local)
    app_user: str = "admin"
    app_password: str | None = None

    # Upload
    max_upload_mb: int = 8192

    # IA — Claude (Anthropic)
    anthropic_api_key: str | None = None
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"  # low | medium | high | xhigh | max
    ai_max_candidates_per_request: int = 6
    ai_frames_per_candidate: int = 4

    # Transcrição local (opcional, requer requirements-transcription.txt)
    transcription_provider: str = "none"  # none | faster_whisper
    whisper_model: str = "small"
    whisper_device: str = "auto"  # auto | cpu | cuda
    whisper_language: str = "pt"

    # Fontes oficiais
    youtube_api_key: str | None = None
    # Chave Google para o Drive (se vazia, usa a mesma do YouTube; ative a "Google Drive API" nela)
    google_api_key: str | None = None
    twitch_client_id: str | None = None
    twitch_client_secret: str | None = None

    # Worker
    worker_poll_seconds: float = 2.0
    # Job 'running' sem heartbeat por N minutos (worker morreu) volta para a fila
    job_stale_minutes: int = 10

    @field_validator("anthropic_api_key", "youtube_api_key", "google_api_key", "twitch_client_id",
                     "twitch_client_secret", "app_password", "ai_model", "ai_effort", mode="before")
    @classmethod
    def _strip(cls, v):  # noqa: ANN001
        """Remove espaços, quebras de linha e aspas que costumam vir junto ao colar chaves no painel."""
        if isinstance(v, str):
            v = v.strip().strip('"').strip("'").strip()
            return v or None if v == "" else v
        return v

    @field_validator("anthropic_api_key", mode="after")
    @classmethod
    def _only_the_key(cls, v):  # noqa: ANN001
        """Aceita a chave colada junto com outro texto (ex.: o comando curl de exemplo do console da Anthropic,
        que traz a chave no meio): usa só o trecho sk-ant-... Um texto assim no cabeçalho derruba a conexão."""
        if v:
            m = re.search(r"sk-ant-[A-Za-z0-9_\-]+", v)
            if m:
                return m.group(0)
        return v

    @property
    def ffmpeg_path(self) -> str | None:
        return shutil.which("ffmpeg")

    @property
    def ffprobe_path(self) -> str | None:
        return shutil.which("ffprobe")

    @property
    def ai_configured(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def youtube_configured(self) -> bool:
        return bool(self.youtube_api_key)

    @property
    def drive_key(self) -> str | None:
        return self.google_api_key or self.youtube_api_key

    @property
    def twitch_configured(self) -> bool:
        return bool(self.twitch_client_id and self.twitch_client_secret)

    def ensure_dirs(self) -> None:
        for sub in ("sources", "work", "exports", "thumbnails", "uploads_tmp"):
            (self.storage_dir / sub).mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            Path(self.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
