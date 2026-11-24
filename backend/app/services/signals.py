"""Sinais objetivos extraídos do vídeo, usados para achar candidatos a cortes.

- Energia do áudio (RMS em janelas): gritos, risadas, explosões e reações aparecem como picos.
- Mudanças de cena: ação intensa / perseguições geram cortes visuais frequentes.
- Transcrição (opcional): palavras de reação ("kkkk", "mano", "caramba"...).

Esses sinais NÃO decidem sozinhos o que é viral — eles reduzem horas de live para
algumas janelas candidatas, que então são avaliadas pela IA (services/ai_analysis.py).
"""
from __future__ import annotations

import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

WINDOW_S = 0.5


@dataclass
class AudioProfile:
    window_s: float
    rms_db: np.ndarray  # dB por janela
    z: np.ndarray  # z-score robusto (mediana/MAD) por janela

    @property
    def duration(self) -> float:
        return len(self.rms_db) * self.window_s

    def mean_z(self, start: float, end: float) -> float:
        a, b = int(start / self.window_s), max(int(end / self.window_s), int(start / self.window_s) + 1)
        seg = self.z[a:b]
        return float(seg.mean()) if seg.size else 0.0

    def max_z(self, start: float, end: float) -> float:
        a, b = int(start / self.window_s), max(int(end / self.window_s), int(start / self.window_s) + 1)
        seg = self.z[a:b]
        return float(seg.max()) if seg.size else 0.0


def audio_profile(wav_path: str | Path, window_s: float = WINDOW_S) -> AudioProfile:
    with wave.open(str(wav_path), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise ValueError("Esperado PCM 16 bits")
        sr = wf.getframerate()
        ch = wf.getnchannels()
        win = int(sr * window_s)
        values: list[float] = []
        while True:
            chunk = wf.readframes(win * 60)  # 30 s por leitura: memória constante em lives longas
            if not chunk:
                break
            data = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
            if ch > 1:
                data = data.reshape(-1, ch).mean(axis=1)
            n = len(data) // win
            if n:
                blocks = data[: n * win].reshape(n, win)
                values.extend(np.sqrt((blocks**2).mean(axis=1) + 1e-9).tolist())
            rest = len(data) - n * win
            if rest > win // 2:
                tail = data[n * win:]
                values.append(float(np.sqrt((tail**2).mean() + 1e-9)))
    rms = np.asarray(values, dtype=np.float32)
    db = 20 * np.log10(rms / 32768.0 + 1e-9)
    return AudioProfile(window_s=window_s, rms_db=db, z=robust_z(db))


def robust_z(x: np.ndarray) -> np.ndarray:
    if x.size == 0:
        return x
    med = np.median(x)
    mad = np.median(np.abs(x - med)) * 1.4826
    if mad < 1e-6:
        mad = float(x.std()) or 1.0
    return (x - med) / mad


REACTION_TERMS = [
    "kkk", "kkkk", "hahaha", "rsrs", "mano", "meu deus", "caramba", "caraca", "nossa", "não acredito",
    "nao acredito", "que isso", "olha isso", "socorro", "ai meu", "corre", "polícia", "policia", "bugou",
    "bug", "segredo", "easter egg", "que absurdo", "mds", "pqp", "vish", "eita", "uau", "insano",
]


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class SignalSummary:
    audio: AudioProfile | None
    scene_changes: list[float]
    transcript: list[TranscriptSegment] = field(default_factory=list)

    def scene_rate(self, start: float, end: float) -> float:
        """Cortes de cena por minuto na janela."""
        if end <= start:
            return 0.0
        n = sum(1 for t in self.scene_changes if start <= t < end)
        return n * 60.0 / (end - start)

    def reaction_hits(self, start: float, end: float) -> int:
        hits = 0
        for seg in self.transcript:
            if seg.end < start or seg.start > end:
                continue
            low = seg.text.lower()
            hits += sum(low.count(term) for term in REACTION_TERMS)
        return hits

    def transcript_text(self, start: float, end: float) -> str:
        lines = []
        for seg in self.transcript:
            if seg.end < start or seg.start > end:
                continue
            lines.append(f"[{seg.start - start:+06.1f}s] {seg.text.strip()}")
        return "\n".join(lines)
