from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime


class SourceError(RuntimeError):
    pass


class SourceNotConfigured(SourceError):
    pass


@dataclass
class DiscoveredVideo:
    platform: str
    external_id: str
    title: str
    url: str
    published_at: datetime | None
    duration_s: float | None
    thumbnail_url: str | None
    is_live_vod: bool = False
    live_now: bool = False  # transmissão acontecendo agora (não é VOD ainda)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def matches_keywords(title: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    t = re.sub(r"\s+", " ", _fold(title))
    compact = t.replace(" ", "")
    for kw in keywords:
        k = _fold(kw).strip()
        if k and (k in t or k.replace(" ", "") in compact):
            return True
    return False


def parse_iso8601_duration(value: str | None) -> float | None:
    if not value:
        return None
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", value)
    if not m:
        return None
    d, h, mi, s = m.groups()
    return int(d or 0) * 86400 + int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)


def parse_twitch_duration(value: str | None) -> float | None:
    if not value:
        return None
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", value)
    if not m or not any(m.groups()):
        return None
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi or 0) * 60 + int(s or 0)
