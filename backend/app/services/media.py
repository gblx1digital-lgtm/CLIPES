"""Wrappers de ffmpeg/ffprobe. Tudo roda em subprocessos no worker (nunca na API)."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings

log = logging.getLogger("clipes.media")


class MediaError(RuntimeError):
    pass


@dataclass
class ProbeResult:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    video_codec: str | None
    audio_codec: str | None


def _bin(name: str) -> str:
    s = get_settings()
    path = s.ffmpeg_path if name == "ffmpeg" else s.ffprobe_path
    if not path:
        raise MediaError(f"{name} não encontrado no PATH. Instale o FFmpeg.")
    return path


def run(cmd: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    log.debug("exec: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise MediaError(f"Comando falhou ({proc.returncode}): {Path(cmd[0]).name}\n{tail}")
    return proc


def _parse_rate(rate: str | None) -> float:
    if not rate or rate == "0/0":
        return 0.0
    if "/" in rate:
        n, d = rate.split("/", 1)
        return float(n) / float(d) if float(d) else 0.0
    return float(rate)


def probe(path: str | Path) -> ProbeResult:
    proc = run([_bin("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
               timeout=120)
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None:
        raise MediaError("Arquivo sem trilha de vídeo.")
    duration = float(data.get("format", {}).get("duration") or v.get("duration") or 0)
    if duration <= 0:
        raise MediaError("Não foi possível determinar a duração do vídeo.")
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = abs(int(sd["rotation"]))
    if rot in (90, 270):
        w, h = h, w
    return ProbeResult(
        duration=duration,
        width=w,
        height=h,
        fps=_parse_rate(v.get("avg_frame_rate")) or _parse_rate(v.get("r_frame_rate")),
        has_audio=a is not None,
        video_codec=v.get("codec_name"),
        audio_codec=a.get("codec_name") if a else None,
    )


def extract_audio_wav(src: str | Path, dst: str | Path, sample_rate: int = 16000) -> Path:
    """Áudio mono PCM 16 bits — base para análise de energia e transcrição."""
    run([_bin("ffmpeg"), "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sample_rate),
         "-c:a", "pcm_s16le", str(dst)])
    return Path(dst)


def detect_scene_changes(
    src: str | Path,
    threshold: float = 0.35,
    analysis_height: int = 180,
    *,
    start: float = 0.0,
    duration: float | None = None,
    on_progress=None,  # noqa: ANN001  callable(fração 0-1)
) -> list[float]:
    """Timestamps absolutos (s) de mudanças bruscas de cena, no vídeo todo ou só em [start, start+duration].

    Para ser rápido: decodifica só os quadros-chave (15-20x mais rápido, mesmas cenas detectadas) em baixa resolução.
    """
    cmd = [_bin("ffmpeg"), "-v", "info", "-nostdin", "-skip_frame", "nokey"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-an", "-vf", f"scale=-2:{analysis_height},select='gt(scene,{threshold})',showinfo",
            "-progress", "pipe:2", "-nostats", "-f", "null", "-"]
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
    assert proc.stderr is not None
    times: list[float] = []
    tail: list[str] = []
    last = -1.0
    for line in proc.stderr:
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            times.append(start + float(m.group(1)))
        elif line.startswith("out_time_us=") and on_progress and duration:
            try:
                frac = min(1.0, int(line.split("=", 1)[1]) / 1e6 / duration)
            except ValueError:
                continue
            if frac - last >= 0.02:
                last = frac
                on_progress(frac)
        tail = (tail + [line])[-10:]
    proc.wait()
    if proc.returncode != 0:
        raise MediaError("Falha na detecção de cenas:\n" + "".join(tail))
    return times


def merge_windows(windows: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(windows):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def extract_frame(src: str | Path, t: float, dst: str | Path, width: int | None = None) -> Path:
    vf = ["-vf", f"scale={width}:-2"] if width else []
    run([_bin("ffmpeg"), "-y", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(src), "-frames:v", "1",
         *vf, "-q:v", "3", str(dst)])
    return Path(dst)


def extract_frames_gray(src: str | Path, times: list[float], width: int = 640) -> list:
    """Frames em memória (numpy BGR) para visão computacional local."""
    import cv2  # import tardio: só o worker precisa
    import numpy as np

    frames = []
    for t in times:
        proc = subprocess.run(
            [_bin("ffmpeg"), "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(src), "-frames:v", "1",
             "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True,
        )
        if proc.returncode == 0 and proc.stdout:
            img = cv2.imdecode(np.frombuffer(proc.stdout, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                frames.append(img)
    return frames


PLAYABLE_VIDEO = {"h264", "vp9", "av1"}
PLAYABLE_AUDIO = {None, "aac", "mp3", "opus", "vorbis"}


def browser_playable(path: str | Path, info: ProbeResult) -> bool:
    return (Path(path).suffix.lower() in (".mp4", ".m4v", ".webm") and info.video_codec in PLAYABLE_VIDEO
            and info.audio_codec in PLAYABLE_AUDIO)


def make_playable_mp4(path: str | Path, info: ProbeResult) -> Path:
    """Remuxa (sem perda) quando os codecs já são compatíveis; senão reencoda em alta qualidade."""
    src = Path(path)
    dst = src.with_name("source_playable.mp4")
    v = ["-c:v", "copy"] if info.video_codec == "h264" else ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p"]
    a = ["-c:a", "copy"] if info.audio_codec in ("aac", "mp3") else ["-c:a", "aac", "-b:a", "256k"]
    run([_bin("ffmpeg"), "-y", "-v", "error", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", *v, *a,
         "-movflags", "+faststart", str(dst)])
    src.unlink(missing_ok=True)
    return dst
