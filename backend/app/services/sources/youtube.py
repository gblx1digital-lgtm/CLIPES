"""YouTube Data API v3 (oficial). Só metadados: título, link, data, duração, miniatura.

Configuração: YOUTUBE_API_KEY (Google Cloud Console > APIs > YouTube Data API v3).
Custo de cota por verificação de canal: ~3 unidades (channels + playlistItems + videos).
"""
from __future__ import annotations

from datetime import datetime

import httpx

from ...config import get_settings
from .base import DiscoveredVideo, SourceError, SourceNotConfigured, parse_iso8601_duration

API = "https://www.googleapis.com/youtube/v3"


def _key() -> str:
    key = get_settings().youtube_api_key
    if not key:
        raise SourceNotConfigured("YOUTUBE_API_KEY não configurada.")
    return key


def _get(client: httpx.Client, path: str, params: dict) -> dict:
    r = client.get(f"{API}/{path}", params={**params, "key": _key()}, timeout=20)
    if r.status_code == 403:
        raise SourceError(f"YouTube API negou acesso (cota ou chave): {r.text[:300]}")
    if r.status_code >= 400:
        raise SourceError(f"YouTube API erro {r.status_code}: {r.text[:300]}")
    return r.json()


def resolve_channel(handle_or_id: str) -> dict:
    """Aceita '@handle', 'handle' ou um channel id 'UC...'. Retorna id, título e playlist de uploads."""
    value = handle_or_id.strip()
    params = {"part": "snippet,contentDetails"}
    if value.startswith("UC") and len(value) == 24:
        params["id"] = value
    else:
        params["forHandle"] = value if value.startswith("@") else f"@{value}"
    with httpx.Client() as client:
        data = _get(client, "channels", params)
    items = data.get("items") or []
    if not items:
        raise SourceError(f"Canal do YouTube não encontrado: {value}")
    ch = items[0]
    return {
        "channel_id": ch["id"],
        "title": ch["snippet"]["title"],
        "uploads_playlist": ch["contentDetails"]["relatedPlaylists"]["uploads"],
    }


def list_recent(channel_id: str, max_results: int = 25) -> list[DiscoveredVideo]:
    with httpx.Client() as client:
        ch = _get(client, "channels", {"part": "contentDetails", "id": channel_id})
        if not ch.get("items"):
            raise SourceError(f"Canal {channel_id} não encontrado.")
        uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl = _get(client, "playlistItems", {"part": "snippet,contentDetails", "playlistId": uploads,
                                            "maxResults": max_results})
        ids = [it["contentDetails"]["videoId"] for it in pl.get("items", [])]
        details: dict[str, dict] = {}
        if ids:
            vd = _get(client, "videos", {"part": "contentDetails,liveStreamingDetails,snippet", "id": ",".join(ids)})
            details = {v["id"]: v for v in vd.get("items", [])}

    out = []
    for vid in ids:
        v = details.get(vid)
        if not v:
            continue
        sn = v["snippet"]
        if sn.get("liveBroadcastContent") == "upcoming":
            continue
        live_now = sn.get("liveBroadcastContent") == "live"
        thumbs = sn.get("thumbnails", {})
        thumb = (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("medium") or {}).get("url")
        out.append(DiscoveredVideo(
            platform="youtube",
            external_id=vid,
            title=sn.get("title", ""),
            url=f"https://www.youtube.com/watch?v={vid}",
            published_at=datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")) if sn.get("publishedAt") else None,
            duration_s=parse_iso8601_duration(v.get("contentDetails", {}).get("duration")),
            thumbnail_url=thumb,
            is_live_vod="liveStreamingDetails" in v and not live_now,
            live_now=live_now,
        ))
    return out
