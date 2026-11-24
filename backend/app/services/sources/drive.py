"""Google Drive (API oficial): pasta compartilhada com os arquivos autorizados pelo criador.

Requisitos: a pasta deve estar compartilhada como "Qualquer pessoa com o link pode ver" e a
chave Google (GOOGLE_API_KEY ou a mesma YOUTUBE_API_KEY) precisa ter a "Google Drive API" ativada.
"""
from __future__ import annotations

import re
from datetime import datetime

import httpx

from ...config import get_settings
from .base import SourceError, SourceNotConfigured

API = "https://www.googleapis.com/drive/v3"


def parse_folder_id(value: str | None) -> str | None:
    """Aceita o link da pasta (drive.google.com/drive/folders/<id>, ...?id=<id>) ou o próprio id."""
    if not value:
        return None
    v = value.strip()
    m = re.search(r"/folders/([A-Za-z0-9_-]{10,})", v) or re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", v)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", v):
        return v
    raise ValueError("Link da pasta do Google Drive inválido. Use o link de compartilhamento da pasta.")


def _key() -> str:
    key = get_settings().drive_key
    if not key:
        raise SourceNotConfigured("Chave Google não configurada (GOOGLE_API_KEY ou YOUTUBE_API_KEY).")
    return key


def list_videos(folder_id: str) -> list[dict]:
    params = {
        "q": f"'{folder_id}' in parents and mimeType contains 'video/' and trashed = false",
        "fields": "nextPageToken, files(id, name, size, mimeType, createdTime, videoMediaMetadata)",
        "pageSize": 100,
        "orderBy": "createdTime desc",
        "key": _key(),
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    out: list[dict] = []
    with httpx.Client(timeout=20) as client:
        while True:
            r = client.get(f"{API}/files", params=params)
            if r.status_code == 403:
                raise SourceError("Google Drive negou acesso. Ative a 'Google Drive API' na chave e confira se a "
                                  "pasta está compartilhada como 'Qualquer pessoa com o link'.")
            if r.status_code == 404:
                raise SourceError("Pasta do Google Drive não encontrada ou não compartilhada publicamente.")
            if r.status_code >= 400:
                raise SourceError(f"Google Drive erro {r.status_code}: {r.text[:200]}")
            data = r.json()
            for f in data.get("files", []):
                meta = f.get("videoMediaMetadata") or {}
                out.append({
                    "id": f["id"],
                    "name": f.get("name", "video"),
                    "size": int(f["size"]) if f.get("size") else None,
                    "created_at": datetime.fromisoformat(f["createdTime"].replace("Z", "+00:00")) if f.get("createdTime") else None,
                    "duration_s": int(meta["durationMillis"]) / 1000 if meta.get("durationMillis") else None,
                })
            if not data.get("nextPageToken"):
                return out
            params["pageToken"] = data["nextPageToken"]


def download_url(file_id: str) -> str:
    """URL de download com a chave. Montada só na hora do download (a chave nunca vai para o banco)."""
    return f"{API}/files/{file_id}?alt=media&supportsAllDrives=true&key={_key()}"


def file_link(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"
