"""Análise dos candidatos com Claude (Anthropic API).

Para cada candidato a IA recebe: metadados da fonte, sinais medidos, transcrição
(quando houver) e quadros do vídeo com timestamps. Ela decide se vale um corte,
ajusta início/fim, classifica a categoria e dá notas por critério.
Saída em JSON validado por schema (structured outputs).
"""
from __future__ import annotations

import base64
import json
import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..models import CATEGORIES, CATEGORY_KEYS
from .candidates import Candidate
from .scoring import CRITERIA

log = logging.getLogger("clipes.ai")


class AIUnavailable(RuntimeError):
    """IA não configurada (sem chave) — erro definitivo, não adianta tentar de novo."""


class AIError(RuntimeError):
    pass


TITLE_RULES = """Regras das opções de título (title_options):
- exatamente 5 opções, em português do Brasil, com no máximo 90 caracteres cada;
- cada uma num estilo diferente: curiosidade, humor, choque/hype, pergunta para o público, direto ao ponto;
- fiéis ao que acontece no corte: não prometa nada que não aparece no vídeo;
- linguagem natural de quem posta cortes de GTA 6 no Brasil; pode citar o criador ou o GTA 6 quando ajudar;
- no máximo 1 emoji por título e nenhuma hashtag (as hashtags vêm separadas)."""

HASHTAG_RULES = """Regras das hashtags (hashtags):
- de 5 a 7 hashtags do segmento do corte, para postar junto com o título;
- misture: 2 ou 3 do nicho (ex.: #gta6, #gtavi, #gta), 1 do criador e 2 ou 3 sobre o que acontece no corte;
- minúsculas, sem acento e sem espaço, cada uma começando com #;
- nada genérico demais como #fyp, #viral ou #foryou."""


SYSTEM_PROMPT = f"""Você é o editor-chefe de um canal de cortes de GTA 6 para TikTok, Reels e YouTube Shorts.
Seu trabalho é avaliar trechos de lives e vídeos de criadores brasileiros e decidir quais viram cortes.

Um bom corte:
- prende a atenção nos primeiros 1-3 segundos (o gancho aparece logo no início);
- tem contexto suficiente para quem nunca viu a live entender o que está acontecendo;
- mantém o interesse até o fim e termina logo após o desfecho (sem enrolação);
- é engraçado, surpreendente, tenso, curioso ou revela algo interessante do GTA 6.

Rejeite (keep=false) trechos sem sentido isolados, momentos mortos, menus/loading, conversa sem relação
com o que acontece, ou quando os sinais altos são só música/ruído.

Escolha start_s e end_s em segundos ABSOLUTOS do vídeo, dentro da janela de contexto informada,
respeitando a duração mínima e máxima pedidas. Comece o corte o mais perto possível do gancho,
mantendo só o contexto necessário antes dele.

Categorias (use a chave): {", ".join(f"{k} = {label}" for k, label in CATEGORIES)}.

Notas de 0 a 10 por critério: {", ".join(f"{k} ({label})" for k, (label, _w) in CRITERIA.items())}.
Seja exigente e calibrado: 9-10 só para momentos realmente excepcionais. Notas são estimativas.

title: título curto interno em português (para organização e legenda do post; NÃO vai dentro do vídeo).
title_options: 5 opções de título para postar o corte no TikTok, Reels e Shorts. Veja as regras abaixo.
hashtags: hashtags do segmento para postar junto com o título. Veja as regras abaixo.
summary: 1-2 frases do que acontece. hook: o que prende nos primeiros segundos. rationale: por que esse
corte funciona ou não. Responda sempre em português do Brasil.

""" + TITLE_RULES + "\n\n" + HASHTAG_RULES


def _output_schema() -> dict[str, Any]:
    score_props = {k: {"type": "integer"} for k in CRITERIA}
    return {
        "type": "object",
        "properties": {
            "clips": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_index": {"type": "integer"},
                        "keep": {"type": "boolean"},
                        "start_s": {"type": "number"},
                        "end_s": {"type": "number"},
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "hook": {"type": "string"},
                        "category": {"type": "string", "enum": CATEGORY_KEYS},
                        "scores": {
                            "type": "object",
                            "properties": score_props,
                            "required": list(CRITERIA),
                            "additionalProperties": False,
                        },
                        "rationale": {"type": "string"},
                        "title_options": {"type": "array", "items": {"type": "string"}},
                        "hashtags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["candidate_index", "keep", "start_s", "end_s", "title", "summary", "hook",
                                 "category", "scores", "rationale", "title_options", "hashtags"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["clips"],
        "additionalProperties": False,
    }


@dataclass
class CandidateEvidence:
    index: int
    candidate: Candidate
    transcript: str
    frames: list[tuple[float, Path]]  # (timestamp absoluto, jpg)


@dataclass
class AIClipDecision:
    candidate_index: int
    keep: bool
    start_s: float
    end_s: float
    title: str
    summary: str
    hook: str
    category: str
    scores: dict[str, float]
    rationale: str
    title_options: list[str]
    hashtags: list[str]


def build_content(video_meta: dict[str, Any], evidences: list[CandidateEvidence], min_len: float, max_len: float) -> list[dict]:
    content: list[dict] = [{
        "type": "text",
        "text": (
            f"Criador: {video_meta.get('creator')}\nVídeo: {video_meta.get('title')}\n"
            f"Plataforma: {video_meta.get('platform')} | Duração total: {video_meta.get('duration', 0):.0f}s\n"
            f"Duração do corte: mínimo {min_len:.0f}s, máximo {max_len:.0f}s.\n"
            f"Avalie os {len(evidences)} candidatos abaixo e devolva exatamente um item por candidato."
        ),
    }]
    for ev in evidences:
        c = ev.candidate
        feats = ", ".join(f"{k}={v}" for k, v in c.features.items())
        content.append({
            "type": "text",
            "text": (
                f"\n=== Candidato {ev.index} ===\n"
                f"Janela de contexto: {c.context_start:.1f}s a {c.context_end:.1f}s | pico de intensidade em {c.peak_s:.1f}s\n"
                f"Sugestão automática: {c.start_s:.1f}s a {c.end_s:.1f}s\n"
                f"Sinais medidos: {feats}\n"
                + (f"Transcrição (tempo relativo ao início da janela):\n{ev.transcript}\n" if ev.transcript
                   else "Transcrição: indisponível — baseie-se nos quadros e nos sinais.\n")
            ),
        })
        for t, path in ev.frames:
            content.append({"type": "text", "text": f"Quadro em {t:.1f}s:"})
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg",
                           "data": base64.standard_b64encode(path.read_bytes()).decode("ascii")},
            })
    return content


def _call_claude(content: list[dict]) -> dict[str, Any]:
    s = get_settings()
    return _request(SYSTEM_PROMPT, content, _output_schema(), effort=s.ai_effort, max_tokens=16000)


def _request(system: str, content: list[dict], schema: dict[str, Any], *, effort: str, max_tokens: int) -> dict[str, Any]:
    import anthropic

    s = get_settings()
    if not s.anthropic_api_key:
        raise AIUnavailable("ANTHROPIC_API_KEY não configurada. Defina a chave no arquivo .env para ativar a análise com IA.")
    client = anthropic.Anthropic(api_key=s.anthropic_api_key, max_retries=3, timeout=600)
    params = dict(
        model=s.ai_model,
        max_tokens=max_tokens,
        system=system,
        thinking={"type": "adaptive"},
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": content}],
    )
    try:
        if supports_server_fallback(s.ai_model):
            # Se o modelo recusar um trecho, a API tenta de novo em outro modelo na mesma chamada
            response = client.beta.messages.create(**params, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            response = client.messages.create(**params)
    except anthropic.AuthenticationError as e:
        raise AIUnavailable("Chave da Anthropic inválida (401). Verifique ANTHROPIC_API_KEY.") from e
    except anthropic.PermissionDeniedError as e:
        raise AIUnavailable(f"Chave sem permissão para o modelo {s.ai_model}.") from e
    except anthropic.BadRequestError as e:
        raise AIUnavailable(f"Requisição rejeitada pela API (modelo {s.ai_model}): {e.message}") from e
    except anthropic.RateLimitError as e:
        raise AIError("Limite de requisições da API atingido; o job será reprocessado.") from e
    except anthropic.APIStatusError as e:
        raise AIError(f"Erro da API Anthropic ({e.status_code}): {e.message}") from e
    except anthropic.APITimeoutError as e:
        raise AIError("A API Anthropic demorou demais para responder (timeout).") from e
    except anthropic.APIConnectionError as e:
        cause = e.__cause__ or e.__context__
        detail = f"{type(cause).__name__}: {cause}"[:300] if cause else str(e)
        raise AIError(f"Falha de conexão com a API Anthropic ({detail}).") from e

    if response.stop_reason == "refusal":
        raise AIError("A IA recusou analisar este trecho.")
    if response.stop_reason == "max_tokens":
        raise AIError("Resposta da IA truncada (max_tokens).")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise AIError("Resposta da IA sem conteúdo.")
    log.info("Claude respondeu (request_id=%s, in=%s, out=%s)", getattr(response, "_request_id", None),
             response.usage.input_tokens, response.usage.output_tokens)
    return json.loads(text)


def supports_server_fallback(model: str) -> bool:
    """Só os modelos grandes aceitam o parâmetro `fallbacks` (o Haiku, por exemplo, rejeita)."""
    return model.startswith(("claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5-2"))


# Ponto de injeção para testes
ClaudeCaller = Callable[[list[dict]], dict[str, Any]]


def analyze_candidates(
    video_meta: dict[str, Any],
    evidences: list[CandidateEvidence],
    *,
    min_len: float,
    max_len: float,
    duration: float,
    caller: ClaudeCaller | None = None,
) -> list[AIClipDecision]:
    caller = caller or _call_claude
    data = caller(build_content(video_meta, evidences, min_len, max_len))
    by_index = {ev.index: ev for ev in evidences}
    out: list[AIClipDecision] = []
    for item in data.get("clips", []):
        ev = by_index.get(int(item.get("candidate_index", -1)))
        if ev is None:
            continue
        start, end = _clamp_bounds(float(item["start_s"]), float(item["end_s"]), ev.candidate, min_len, max_len, duration)
        category = item.get("category") if item.get("category") in CATEGORY_KEYS else "outros"
        out.append(AIClipDecision(
            candidate_index=ev.index,
            keep=bool(item.get("keep")),
            start_s=start,
            end_s=end,
            title=str(item.get("title", "")).strip()[:300] or "Corte sem título",
            summary=str(item.get("summary", "")).strip(),
            hook=str(item.get("hook", "")).strip(),
            category=category,
            scores={k: float(item.get("scores", {}).get(k, 0)) for k in CRITERIA},
            rationale=str(item.get("rationale", "")).strip(),
            title_options=clean_titles(item.get("title_options")),
            hashtags=clean_hashtags(item.get("hashtags")),
        ))
    return out


def _clamp_bounds(start: float, end: float, c: Candidate, min_len: float, max_len: float, duration: float) -> tuple[float, float]:
    """Garante limites válidos mesmo se a IA errar a conta."""
    lo, hi = max(0.0, c.context_start - 5), min(duration, c.context_end + 5)
    start = max(lo, min(start, hi))
    end = max(lo, min(end, hi))
    if end <= start:
        start, end = c.start_s, c.end_s
    if end - start > max_len:
        end = start + max_len
    if end - start < min_len:
        end = min(duration, start + min_len)
        if end - start < min_len:
            start = max(0.0, end - min_len)
    return round(start, 2), round(end, 2)


# ------------------------------------------------------------------ opções de título e hashtags (avulso)
POST_SYSTEM = """Você escreve títulos e hashtags para cortes de GTA 6 de criadores brasileiros, postados no TikTok,
Reels e Shorts. O título é a legenda do post (não vai dentro do vídeo) e precisa fazer a pessoa parar de rolar a tela.

""" + TITLE_RULES + "\n\n" + HASHTAG_RULES


def clean_titles(raw: Any, limit: int = 5) -> list[str]:
    """Normaliza a lista vinda da IA: textos não vazios, sem repetição, até 150 caracteres, no máximo `limit`."""
    out: list[str] = []
    for t in raw or []:
        t = " ".join(str(t).split()).strip().strip('"')[:150]
        if t and t.lower() not in {o.lower() for o in out}:
            out.append(t)
    return out[:limit]


def clean_hashtags(raw: Any, limit: int = 8) -> list[str]:
    """#minúsculas, sem acento, espaço ou pontuação, sem repetição ("GTA 6" -> #gta6, "#Explosão" -> #explosao).
    Um item com várias hashtags ("#gta6 #coringa") vira várias; sem isso, as palavras são juntadas."""
    out: list[str] = []
    for item in raw or []:
        text = str(item)
        pieces = text.split("#") if text.count("#") > 1 else [text]
        for piece in pieces:
            tag = unicodedata.normalize("NFKD", piece).encode("ascii", "ignore").decode().lower()
            tag = re.sub(r"[^a-z0-9_]", "", tag)[:40]
            if tag and not tag.isdigit() and f"#{tag}" not in out:
                out.append(f"#{tag}")
    return out[:limit]


def _call_titles(content: list[dict]) -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {
            "titles": {"type": "array", "items": {"type": "string"}},
            "hashtags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["titles", "hashtags"],
        "additionalProperties": False,
    }
    # Tarefa curta: esforço baixo responde em poucos segundos
    return _request(POST_SYSTEM, content, schema, effort="low", max_tokens=4000)


def suggest_post(clip: dict[str, Any], *, avoid: list[str] | None = None,
                 caller: ClaudeCaller | None = None) -> tuple[list[str], list[str]]:
    """Gera 5 opções de título e as hashtags do segmento para um corte já analisado."""
    caller = caller or _call_titles
    lines = [
        f"Criador: {clip.get('creator')}",
        f"Vídeo de origem: {clip.get('source_title')}",
        f"Duração do corte: {clip.get('duration_s', 0):.0f}s | Categoria: {clip.get('category')}",
        f"Título interno atual: {clip.get('title')}",
        f"O que acontece: {clip.get('summary') or '—'}",
        f"Gancho dos primeiros segundos: {clip.get('hook') or '—'}",
        f"Por que funciona: {clip.get('rationale') or '—'}",
    ]
    if avoid:
        lines.append("Opções já mostradas (escreva 5 NOVAS, diferentes destas):\n" + "\n".join(f"- {t}" for t in avoid))
    lines.append("Devolva as 5 opções em `titles` e as hashtags em `hashtags`.")
    data = caller([{"type": "text", "text": "\n".join(lines)}])
    titles = clean_titles(data.get("titles"))
    if not titles:
        raise AIError("A IA não devolveu opções de título.")
    return titles, clean_hashtags(data.get("hashtags"))
