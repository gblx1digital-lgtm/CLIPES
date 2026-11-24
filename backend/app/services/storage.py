"""Caminhos no armazenamento. No banco guardamos caminhos RELATIVOS a STORAGE_DIR."""
from __future__ import annotations

from pathlib import Path

from ..config import get_settings


def root() -> Path:
    return get_settings().storage_dir


def abs_path(rel: str | None) -> Path | None:
    if not rel:
        return None
    p = (root() / rel).resolve()
    if root().resolve() not in p.parents and p != root().resolve():
        raise ValueError("Caminho fora do armazenamento")
    return p


def rel_path(p: Path) -> str:
    return p.resolve().relative_to(root().resolve()).as_posix()


def source_dir(video_id: int) -> Path:
    d = root() / "sources" / str(video_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def work_dir(video_id: int) -> Path:
    d = root() / "work" / str(video_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def thumb_path(clip_id: int) -> Path:
    return root() / "thumbnails" / f"clip_{clip_id}.jpg"


def video_thumb_path(video_id: int) -> Path:
    return root() / "thumbnails" / f"video_{video_id}.jpg"


def export_path(clip_id: int, export_id: int) -> Path:
    return root() / "exports" / f"clip_{clip_id}_export_{export_id}.mp4"


def usage_bytes() -> dict[str, int]:
    out: dict[str, int] = {}
    for sub in ("sources", "work", "exports", "thumbnails"):
        d = root() / sub
        out[sub] = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) if d.exists() else 0
    return out
