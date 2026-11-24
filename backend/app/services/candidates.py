"""Geração de janelas candidatas a partir dos sinais (sem IA).

Cada candidato tem:
  - peak_s: momento de maior intensidade (o "gancho")
  - context: janela ampla que a IA recebe para escolher o corte exato
  - start/end sugeridos: o gancho perto do início, com contexto suficiente antes
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .signals import SignalSummary


@dataclass
class Candidate:
    peak_s: float
    start_s: float
    end_s: float
    context_start: float
    context_end: float
    signal_score: float  # 0-100
    features: dict


def _smooth(x: np.ndarray, n: int) -> np.ndarray:
    if n <= 1 or x.size == 0:
        return x
    k = np.ones(n, dtype=np.float32) / n
    return np.convolve(x, k, mode="same")


def _scene_series(scene_changes: list[float], length: int, window_s: float) -> np.ndarray:
    arr = np.zeros(length, dtype=np.float32)
    for t in scene_changes:
        i = int(t / window_s)
        if 0 <= i < length:
            arr[i] += 1.0
    return arr


def find_candidates(
    signals: SignalSummary,
    duration: float,
    *,
    min_len: float,
    max_len: float,
    limit: int,
) -> list[Candidate]:
    target = float(np.clip((min_len + max_len) / 2, min_len, max_len))

    if duration <= max_len + 2:
        # Vídeo curto: o próprio vídeo é o candidato
        return [Candidate(peak_s=min(3.0, duration / 3), start_s=0.0, end_s=duration, context_start=0.0,
                          context_end=duration, signal_score=50.0, features={"short_video": True})]

    window_s = signals.audio.window_s if signals.audio is not None else 0.5
    n = int(np.ceil(duration / window_s))

    audio_z = np.zeros(n, dtype=np.float32)
    if signals.audio is not None and signals.audio.z.size:
        m = min(n, signals.audio.z.size)
        audio_z[:m] = signals.audio.z[:m]
    audio_s = _smooth(np.clip(audio_z, -3, 8), max(1, int(2.0 / window_s)))

    scenes = _smooth(_scene_series(signals.scene_changes, n, window_s), max(1, int(10.0 / window_s)))
    scene_z = (scenes - scenes.mean()) / (scenes.std() + 1e-6) if scenes.any() else scenes

    combined = audio_s + 0.5 * np.clip(scene_z, -2, 4)

    # Supressão de não-máximos: picos fortes separados por pelo menos ~ meio corte
    min_gap = int(max(target * 0.75, 12.0) / window_s)
    order = np.argsort(-combined)
    taken = np.zeros(n, dtype=bool)
    peaks: list[int] = []
    for idx in order:
        if len(peaks) >= limit:
            break
        if taken[idx]:
            continue
        peaks.append(int(idx))
        taken[max(0, idx - min_gap): idx + min_gap] = True

    out: list[Candidate] = []
    for idx in peaks:
        peak = idx * window_s
        # Gancho a ~30% do corte: contexto antes, desenrolar depois
        start = max(0.0, peak - target * 0.3)
        end = min(duration, start + target)
        start = max(0.0, end - target)
        ctx_start = max(0.0, peak - max_len * 0.8)
        ctx_end = min(duration, peak + max_len * 0.9)

        peak_z = float(audio_s[idx])
        scene_rate = signals.scene_rate(start, end)
        hits = signals.reaction_hits(start, end)
        score = (
            60 * float(np.clip(peak_z / 5.0, 0, 1))
            + 20 * float(np.clip(scene_rate / 12.0, 0, 1))
            + 20 * float(np.clip(hits / 4.0, 0, 1))
        )
        out.append(Candidate(
            peak_s=round(peak, 2), start_s=round(start, 2), end_s=round(end, 2),
            context_start=round(ctx_start, 2), context_end=round(ctx_end, 2),
            signal_score=round(score, 1),
            features={
                "audio_peak_z": round(peak_z, 2),
                "audio_mean_z": round(float(audio_s[int(start / window_s): max(int(end / window_s), int(start / window_s) + 1)].mean()), 2),
                "scene_changes_per_min": round(scene_rate, 1),
                "reaction_terms": hits,
            },
        ))
    out.sort(key=lambda c: c.peak_s)
    return out
