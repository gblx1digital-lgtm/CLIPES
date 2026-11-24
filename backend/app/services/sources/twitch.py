"""Twitch Helix API (oficial). Só metadados de VODs/destaques.

Configuração: TWITCH_CLIENT_ID e TWITCH_CLIENT_SECRET (dev.twitch.tv/console > Register Your Application).
Usa token de aplicativo (client credentials), renovado automaticamente.
"""
from __future__ import annotations

import time
from datetime import datetime

import httpx

from ...config import get_settings
from .base import DiscoveredVideo, SourceError, SourceNotConfigured, parse_twitch_duration

_token: tuple[str, float] | None = None


def _auth_headers(client: httpx.Client) -> dict[str, str]:
    global _token
    s = get_settings()
    if not (s.twitch_client_id and s.twitch_client_secret):
        raise SourceNotConfigured("TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET não configurados.")
    if _token is None or _token[1] < time.time() + 60:
        r = client.post("https://id.twitch.tv/oauth2/token", data={
            "client_id": s.twitch_client_id, "client_secret": s.twitch_client_secret,
            "grant_type": "client_credentials"}, timeout=20)
        if r.status_code >= 400:
            raise SourceError(f"Falha ao autenticar na Twitch ({r.status_code}): {r.text[:200]}")
        data = r.json()
        _token = (data["access_token"], time.time() + float(data.get("expires_in", 3600)))
    return {"Client-Id": s.twitch_client_id, "Authorization": f"Bearer {_token[0]}"}


def _get(client: httpx.Client, path: str, params: dict) -> dict:
    r = client.get(f"https://api.twitch.tv/helix/{path}", params=params, headers=_auth_headers(client), timeout=20)
    if r.status_code >= 400:
        raise SourceError(f"Twitch API erro {r.status_code}: {r.text[:300]}")
    return r.json()


def resolve_user(login: str) -> dict:
    with httpx.Client() as client:
        data = _get(client, "users", {"login": login.strip().lstrip("@").lower()})
    if not data.get("data"):
        raise SourceError(f"Usuário da Twitch não encontrado: {login}")
    u = data["data"][0]
    return {"user_id": u["id"], "login": u["login"], "display_name": u["display_name"]}


def list_recent(user_id: str, first: int = 20) -> list[DiscoveredVideo]:
    with httpx.Client() as client:
        data = _get(client, "videos", {"user_id": user_id, "first": first, "type": "all"})
    out = []
    for v in data.get("data", []):
        thumb = (v.get("thumbnail_url") or "").replace("%{width}", "640").replace("%{height}", "360") or None
        out.append(DiscoveredVideo(
            platform="twitch",
            external_id=v["id"],
            title=v.get("title", ""),
            url=v.get("url", f"https://www.twitch.tv/videos/{v['id']}"),
            published_at=datetime.fromisoformat(v["created_at"].replace("Z", "+00:00")) if v.get("created_at") else None,
            duration_s=parse_twitch_duration(v.get("duration")),
            thumbnail_url=thumb,
            is_live_vod=v.get("type") == "archive",
        ))
    return out


def live_stream(user_id: str) -> dict | None:
    """Transmissão em andamento do canal (ou None)."""
    with httpx.Client() as client:
        data = _get(client, "streams", {"user_id": user_id})
    items = data.get("data") or []
    if not items:
        return None
    st = items[0]
    return {
        "title": st.get("title", ""),
        "game": st.get("game_name", ""),
        "started_at": datetime.fromisoformat(st["started_at"].replace("Z", "+00:00")) if st.get("started_at") else None,
        "url": f"https://www.twitch.tv/{st.get('user_login', '')}",
    }
