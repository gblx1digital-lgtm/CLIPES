"""Configurações de automação editáveis no painel (persistidas no banco)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from ..models import CATEGORY_KEYS, Setting

AUTOMATION_KEY = "automation"


class AutomationSettings(BaseModel):
    monitoring_enabled: bool = False
    monitor_interval_minutes: int = Field(60, ge=15, le=24 * 60)
    # Analisar automaticamente vídeos cuja mídia ficou disponível
    auto_analyze: bool = True
    max_clips_per_day: int = Field(30, ge=1, le=500)
    max_clips_per_video: int = Field(8, ge=1, le=50)
    min_clip_seconds: int = Field(15, ge=5, le=180)
    max_clip_seconds: int = Field(60, ge=10, le=180)
    priority_categories: list[str] = Field(default_factory=lambda: ["engracados", "reacoes", "bugs"])
    min_viral_score: int = Field(40, ge=0, le=100)
    approval_mode: Literal["manual", "automatic"] = "manual"
    auto_approve_min_score: int = Field(80, ge=0, le=100)
    export_quality: Literal["standard", "high", "max"] = "high"
    # Palavras que identificam conteúdo de GTA 6 nos títulos das fontes monitoradas
    title_keywords: list[str] = Field(default_factory=lambda: ["gta 6", "gta vi", "gta6", "gtavi", "grand theft auto vi"])

    @model_validator(mode="after")
    def _check(self) -> AutomationSettings:
        if self.min_clip_seconds >= self.max_clip_seconds:
            raise ValueError("A duração mínima deve ser menor que a máxima.")
        bad = [c for c in self.priority_categories if c not in CATEGORY_KEYS]
        if bad:
            raise ValueError(f"Categorias inválidas: {', '.join(bad)}")
        self.title_keywords = [k.strip().lower() for k in self.title_keywords if k.strip()]
        return self


def get_automation(db: Session) -> AutomationSettings:
    row = db.get(Setting, AUTOMATION_KEY)
    if row is None or not isinstance(row.value, dict):
        return AutomationSettings()
    return AutomationSettings.model_validate({**AutomationSettings().model_dump(), **row.value})


def save_automation(db: Session, data: dict[str, Any]) -> AutomationSettings:
    merged = {**get_automation(db).model_dump(), **data}
    settings = AutomationSettings.model_validate(merged)
    row = db.get(Setting, AUTOMATION_KEY)
    if row is None:
        db.add(Setting(key=AUTOMATION_KEY, value=settings.model_dump()))
    else:
        row.value = settings.model_dump()
    db.commit()
    return settings


def get_value(db: Session, key: str, default: Any = None) -> Any:
    row = db.get(Setting, key)
    return default if row is None else row.value


def set_value(db: Session, key: str, value: Any) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.commit()
