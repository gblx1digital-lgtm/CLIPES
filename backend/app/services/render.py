"""Renderização final: MP4 H.264 + AAC, 1080x1920, áudio sincronizado."""
from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .layout import OUT_H, OUT_W, build_filter
from .media import MediaError, _bin

log = logging.getLogger("clipes.render")

QUALITY_PRESETS = {
    "standard": {"crf": "23", "preset": "medium", "audio": "160k"},
    "high": {"crf": "19", "preset": "slow", "audio": "192k"},
    "max": {"crf": "16", "preset": "slow", "audio": "256k"},
}


def render_vertical(
    src: str | Path,
    dst: str | Path,
    *,
    start: float,
    end: float,
    layout: dict[str, Any],
    src_w: int,
    src_h: int,
    has_audio: bool,
    src_fps: float | None = None,
    quality: str = "high",
    on_progress: Callable[[float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Path:
    q = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["high"])
    duration = max(0.1, end - start)
    dst = Path(dst)
    tmp = dst.with_suffix(".part.mp4")
    cmd = [
        _bin("ffmpeg"), "-y", "-v", "error", "-nostdin",
        # -ss antes do -i + reencode = corte preciso no quadro e áudio/vídeo alinhados
        "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}",
        "-filter_complex", build_filter(layout, src_w, src_h, OUT_W, OUT_H),
        "-map", "[v]",
    ]
    if has_audio:
        cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", q["audio"], "-ar", "48000", "-ac", "2"]
    if src_fps and src_fps > 60.5:
        cmd += ["-r", "60"]
    cmd += [
        "-c:v", "libx264", "-preset", q["preset"], "-crf", q["crf"], "-profile:v", "high", "-level", "4.2",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(tmp),
    ]
    log.info("Renderizando %s (%.1fs a %.1fs)", dst.name, start, end)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    us = int(line.split("=", 1)[1].strip())
                except ValueError:
                    continue
                if on_progress:
                    on_progress(min(99.0, us / 1_000_000 / duration * 100))
                if should_cancel and should_cancel():
                    proc.kill()
                    raise MediaError("Renderização cancelada.")
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        err = proc.stderr.read() if proc.stderr else ""
        tmp.unlink(missing_ok=True)
        raise MediaError("Falha ao renderizar:\n" + "\n".join(err.strip().splitlines()[-12:]))
    tmp.replace(dst)
    return dst


def render_thumbnail(src: str | Path, dst: str | Path, *, t: float, layout: dict[str, Any], src_w: int, src_h: int) -> Path:
    """Miniatura já no enquadramento 9:16 final (360x640)."""
    graph = build_filter(layout, src_w, src_h, OUT_W, OUT_H) + ";[v]scale=360:640:flags=lanczos[t]"
    proc = subprocess.run(
        [_bin("ffmpeg"), "-y", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(src),
         "-filter_complex", graph, "-map", "[t]", "-frames:v", "1", "-q:v", "3", str(dst)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise MediaError("Falha ao gerar miniatura: " + proc.stderr.strip()[-500:])
    return Path(dst)
