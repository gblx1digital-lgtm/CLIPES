from __future__ import annotations

from typing import Any

from ..models import CATEGORIES, Clip, Creator, Export, Job, SourceVideo
from ..services.scoring import TIER_LABELS

CATEGORY_LABELS = dict(CATEGORIES)


def _dt(v):  # noqa: ANN001
    return v.isoformat() if v else None


def creator_out(c: Creator, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": c.id, "name": c.name, "youtube_handle": c.youtube_handle, "youtube_channel_id": c.youtube_channel_id,
        "twitch_login": c.twitch_login, "twitch_user_id": c.twitch_user_id, "active": c.active,
        "media_authorized": c.media_authorized, "authorization_note": c.authorization_note,
        "default_layout": c.default_layout, "notes": c.notes,
        "drive_folder_id": c.drive_folder_id,
        "drive_folder_url": f"https://drive.google.com/drive/folders/{c.drive_folder_id}" if c.drive_folder_id else None,
        "live_now": bool(c.live_now), "live_title": c.live_title, "live_url": c.live_url,
        "live_since": _dt(c.live_since), "last_checked_at": _dt(c.last_checked_at),
        "last_check_error": c.last_check_error, "created_at": _dt(c.created_at),
        "stats": stats or {},
    }


def video_out(v: SourceVideo, clip_count: int | None = None) -> dict[str, Any]:
    return {
        "id": v.id, "creator_id": v.creator_id, "creator_name": v.creator.name if v.creator else None,
        "platform": v.platform, "external_id": v.external_id, "title": v.title, "url": v.url,
        "thumbnail_url": v.thumbnail_url, "published_at": _dt(v.published_at), "discovered_at": _dt(v.discovered_at),
        "is_live_vod": v.is_live_vod, "rights_basis": v.rights_basis, "rights_note": v.rights_note,
        "media_status": v.media_status, "media_error": v.media_error, "has_media": v.media_status == "ready",
        "duration_s": v.duration_s, "width": v.width, "height": v.height, "fps": v.fps, "has_audio": v.has_audio,
        "analysis_status": v.analysis_status, "analysis_error": v.analysis_error, "analyzed_at": _dt(v.analyzed_at),
        "layout_hint": v.layout_hint, "analysis_meta": v.analysis_meta,
        "clip_count": clip_count if clip_count is not None else len(v.clips),
    }


def clip_out(c: Clip, *, detail: bool = False) -> dict[str, Any]:
    v = c.source_video
    out = {
        "id": c.id, "source_video_id": c.source_video_id, "creator_id": c.creator_id,
        "creator_name": c.creator.name if c.creator else None,
        "title": c.title, "summary": c.summary, "hook": c.hook,
        "category": c.category, "category_label": CATEGORY_LABELS.get(c.category, c.category),
        "start_s": c.start_s, "end_s": c.end_s, "duration_s": round(c.end_s - c.start_s, 2),
        "viral_score": c.viral_score, "tier": c.tier, "tier_label": TIER_LABELS.get(c.tier, c.tier),
        "status": c.status, "render_status": c.render_status, "auto_approved": c.auto_approved,
        "discovered_at": _dt(c.discovered_at), "reviewed_at": _dt(c.reviewed_at),
        "thumbnail_url": f"/api/clips/{c.id}/thumbnail?v={int(c.updated_at.timestamp()) if c.updated_at else 0}" if c.thumbnail_path else None,
        "source_title": v.title if v else None, "source_url": v.url if v else None,
        "source_platform": v.platform if v else None,
        "layout": c.layout,
    }
    if detail:
        out.update({
            "score_breakdown": c.score_breakdown, "rationale": c.rationale, "signals": c.signals,
            "analysis_source": c.analysis_source, "review_note": c.review_note,
            "title_options": c.title_options or [],
            "source": {
                "id": v.id, "width": v.width, "height": v.height, "duration_s": v.duration_s, "fps": v.fps,
                "has_audio": v.has_audio, "media_ready": v.media_status == "ready",
                "stream_url": f"/api/videos/{v.id}/stream" if v.media_status == "ready" else None,
                "rights_basis": v.rights_basis, "layout_hint": v.layout_hint,
            } if v else None,
            "exports": [export_out(e) for e in sorted(c.exports, key=lambda e: e.id, reverse=True)],
        })
    return out


def export_out(e: Export) -> dict[str, Any]:
    return {
        "id": e.id, "clip_id": e.clip_id, "clip_title": e.clip.title if e.clip else None,
        "creator_name": e.clip.creator.name if e.clip and e.clip.creator else None,
        "status": e.status, "quality": e.quality, "width": e.width, "height": e.height,
        "start_s": e.start_s, "end_s": e.end_s, "duration_s": round(e.end_s - e.start_s, 2),
        "size_bytes": e.size_bytes, "error": e.error, "job_id": e.job_id,
        "created_at": _dt(e.created_at), "finished_at": _dt(e.finished_at),
        "download_url": f"/api/exports/{e.id}/download" if e.status == "done" else None,
        "file_url": f"/api/exports/{e.id}/file" if e.status == "done" else None,
    }


def job_out(j: Job) -> dict[str, Any]:
    return {
        "id": j.id, "type": j.type, "status": j.status, "progress": round(j.progress, 1), "message": j.message,
        "error": j.error, "attempts": j.attempts, "max_attempts": j.max_attempts, "ref_type": j.ref_type,
        "ref_id": j.ref_id, "payload": j.payload, "created_at": _dt(j.created_at), "started_at": _dt(j.started_at),
        "finished_at": _dt(j.finished_at),
    }
