"""Pontuação de potencial viral (0-100) — ESTIMATIVA, não promessa.

A IA dá notas 0-10 para cada critério; a nota final combina esses critérios
(85%) com a intensidade objetiva medida nos sinais (15%).
"""
from __future__ import annotations

CRITERIA: dict[str, tuple[str, float]] = {
    "hook": ("Força dos primeiros segundos", 0.20),
    "retention": ("Potencial de retenção", 0.18),
    "reaction": ("Reação do streamer", 0.12),
    "humor": ("Humor e entretenimento", 0.12),
    "surprise": ("Surpresa", 0.10),
    "context_clarity": ("Clareza do contexto", 0.10),
    "shareability": ("Potencial de compartilhamento", 0.10),
    "gta6_interest": ("Interesse do público de GTA 6", 0.08),
}
AI_WEIGHT = 0.85
SIGNAL_WEIGHT = 0.15

TIERS = [("alto", 75), ("medio", 50), ("baixo", 0)]
TIER_LABELS = {"alto": "Alto potencial viral", "medio": "Potencial médio", "baixo": "Baixo potencial"}


def ai_score(scores: dict[str, float]) -> float:
    total = 0.0
    for key, (_label, weight) in CRITERIA.items():
        v = float(scores.get(key, 0))
        total += weight * max(0.0, min(10.0, v))
    return total * 10.0


def final_score(scores: dict[str, float], signal_score: float) -> int:
    value = AI_WEIGHT * ai_score(scores) + SIGNAL_WEIGHT * max(0.0, min(100.0, signal_score))
    return int(round(max(0.0, min(100.0, value))))


def tier_for(score: int) -> str:
    for name, threshold in TIERS:
        if score >= threshold:
            return name
    return "baixo"


def breakdown(scores: dict[str, float], signal_score: float) -> dict:
    return {
        "criteria": {k: {"label": CRITERIA[k][0], "weight": CRITERIA[k][1], "value": float(scores.get(k, 0))}
                     for k in CRITERIA},
        "ai_score": round(ai_score(scores), 1),
        "signal_score": round(signal_score, 1),
        "weights": {"ai": AI_WEIGHT, "signals": SIGNAL_WEIGHT},
    }
