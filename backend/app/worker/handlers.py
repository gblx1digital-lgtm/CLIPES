"""Handlers dos jobs da fila. Cada handler recebe (db, job) e lança exceção em caso de falha."""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..logging_setup import redact_secrets
from ..models import ActivityEvent, Clip, Creator, Export, Job, SourceVideo, utcnow
from ..queue import jobs as q
from ..services import activity, layout as layout_svc, media, render, scoring, storage, transcription
from ..services.ai_analysis import AIUnavailable, CandidateEvidence, analyze_candidates
from ..services.candidates import find_candidates
from ..services.settings_store import get_automation
from ..services.signals import SignalSummary, audio_profile
from ..services.sources import drive, twitch, youtube
from ..services.sources.base import SourceNotConfigured, matches_keywords

log = logging.getLogger("clipes.worker")


class PermanentError(RuntimeError):
    """Erro que não se resolve tentando de novo (configuração, permissão, arquivo inválido)."""


NON_RETRYABLE = (PermanentError, AIUnavailable, SourceNotConfigured)

BLOCKED_HOSTS = ("youtube.com", "youtu.be", "twitch.tv", "tiktok.com", "instagram.com", "kick.com")


# ============================================================== monitoramento
def handle_monitor_creator(db: Session, job: Job) -> str:
    s = get_settings()
    creator = db.get(Creator, job.payload["creator_id"])
    if creator is None:
        raise PermanentError("Criador não existe mais.")
    auto = get_automation(db)
    found: list = []
    errors: list[str] = []
    checked_any = False
    live: dict | None = None

    if creator.youtube_handle or creator.youtube_channel_id:
        if not s.youtube_configured:
            errors.append("YouTube: YOUTUBE_API_KEY não configurada")
        else:
            checked_any = True
            try:
                if not creator.youtube_channel_id:
                    creator.youtube_channel_id = youtube.resolve_channel(creator.youtube_handle)["channel_id"]
                recent = youtube.list_recent(creator.youtube_channel_id)
                for v in recent:
                    if v.live_now and live is None:
                        live = {"title": v.title, "url": v.url, "started_at": v.published_at}
                found += [v for v in recent if not v.live_now]
            except Exception as e:  # noqa: BLE001
                errors.append(f"YouTube: {e}")
    q.progress(db, job, 45, "YouTube verificado")

    if creator.twitch_login or creator.twitch_user_id:
        if not s.twitch_configured:
            errors.append("Twitch: TWITCH_CLIENT_ID/SECRET não configurados")
        else:
            checked_any = True
            try:
                if not creator.twitch_user_id:
                    creator.twitch_user_id = twitch.resolve_user(creator.twitch_login)["user_id"]
                found += twitch.list_recent(creator.twitch_user_id)
                if live is None:
                    live = twitch.live_stream(creator.twitch_user_id)
            except Exception as e:  # noqa: BLE001
                errors.append(f"Twitch: {e}")
    q.progress(db, job, 70, "Twitch verificada")

    drive_new = 0
    if creator.drive_folder_id:
        if not s.drive_key:
            errors.append("Google Drive: chave Google não configurada")
        elif not creator.media_authorized:
            errors.append("Google Drive: marque o criador como autorizado para importar a pasta")
        else:
            checked_any = True
            try:
                drive_new = _import_drive_folder(db, creator)
            except Exception as e:  # noqa: BLE001
                errors.append(f"Google Drive: {e}")
    q.progress(db, job, 85, "Google Drive verificado")
    _update_live(db, creator, live)

    creator.last_checked_at = utcnow()
    creator.last_check_error = redact_secrets("; ".join(errors)) or None
    db.commit()

    if not checked_any:
        msg = "; ".join(errors) or "Criador sem canal do YouTube, Twitch ou pasta do Google Drive cadastrados."
        raise PermanentError(msg)

    new = 0
    for v in found:
        if not matches_keywords(v.title, auto.title_keywords):
            continue
        exists = db.scalar(select(SourceVideo.id).where(SourceVideo.platform == v.platform,
                                                        SourceVideo.external_id == v.external_id))
        if exists:
            continue
        sv = SourceVideo(creator_id=creator.id, platform=v.platform, external_id=v.external_id, title=v.title[:500],
                         url=v.url, published_at=v.published_at, duration_s=v.duration_s,
                         thumbnail_url=v.thumbnail_url, is_live_vod=v.is_live_vod)
        db.add(sv)
        db.flush()
        new += 1
        activity.record(db, "discovery", f"Novo vídeo de {creator.name}: {v.title[:120]}", ref_type="video",
                        ref_id=sv.id, commit=False)
    db.commit()
    summary = f"{creator.name}: {len(found)} vídeos verificados, {new} novos de GTA 6"
    if creator.drive_folder_id:
        summary += f", {drive_new} arquivos novos no Drive"
    activity.record(db, "monitor", summary + (f" (avisos: {'; '.join(errors)})" if errors else ""),
                    level="warning" if errors else "info", ref_type="creator", ref_id=creator.id)
    return summary


def _update_live(db: Session, creator: Creator, live: dict | None) -> None:
    was_live = bool(creator.live_now)
    if live:
        creator.live_now = True
        creator.live_title = (live.get("title") or "")[:500]
        creator.live_url = live.get("url")
        if not was_live:
            creator.live_since = live.get("started_at") or utcnow()
            activity.record(db, "live", f"{creator.name} está AO VIVO: {creator.live_title[:120]}", level="success",
                            ref_type="creator", ref_id=creator.id, commit=False)
    elif was_live:
        creator.live_now = False
        activity.record(db, "live", f"{creator.name} encerrou a live. O VOD aparece na descoberta quando for publicado.",
                        ref_type="creator", ref_id=creator.id, commit=False)
    db.commit()


def _import_drive_folder(db: Session, creator: Creator) -> int:
    """Arquivos novos da pasta autorizada viram vídeos e entram direto na fila de ingestão."""
    new = 0
    for f in drive.list_videos(creator.drive_folder_id):
        exists = db.scalar(select(SourceVideo.id).where(SourceVideo.platform == "drive", SourceVideo.external_id == f["id"]))
        if exists:
            continue
        title = f["name"].rsplit(".", 1)[0][:500]
        sv = SourceVideo(creator_id=creator.id, platform="drive", external_id=f["id"], title=title,
                         url=drive.file_link(f["id"]), published_at=f["created_at"], duration_s=f["duration_s"],
                         rights_basis="authorized",
                         rights_note=f"Pasta do Google Drive autorizada. {creator.authorization_note or ''}".strip(),
                         media_status="ingesting")
        db.add(sv)
        db.flush()
        q.enqueue(db, "ingest_media", {"video_id": sv.id, "drive_file_id": f["id"]}, ref_type="video", ref_id=sv.id,
                  priority=30, commit=False)
        activity.record(db, "discovery", f"Novo arquivo no Drive de {creator.name}: {title[:120]}", ref_type="video",
                        ref_id=sv.id, commit=False)
        new += 1
    db.commit()
    return new


# ============================================================== ingestão de mídia
def handle_ingest_media(db: Session, job: Job) -> str:
    video = db.get(SourceVideo, job.payload["video_id"])
    if video is None:
        raise PermanentError("Vídeo não existe mais.")
    if not video.rights_basis:
        raise PermanentError("Sem registro de direitos/autorização para esta mídia.")
    video.media_status = "ingesting"
    video.media_error = None
    db.commit()
    try:
        url = job.payload.get("url")
        if job.payload.get("drive_file_id"):
            path = _download_direct(db, job, video, drive.download_url(job.payload["drive_file_id"]))
        elif url:
            path = _download_direct(db, job, video, url)
        else:
            path = storage.abs_path(video.media_path)
            if path is None or not path.exists():
                raise PermanentError("Arquivo de mídia não encontrado no armazenamento.")
        q.progress(db, job, 82, "Lendo metadados")
        info = media.probe(path)
        if not media.browser_playable(path, info):
            # O editor precisa reproduzir a fonte no navegador: converte mantendo a qualidade
            q.progress(db, job, 85, "Convertendo para MP4 (H.264/AAC)")
            path = media.make_playable_mp4(path, info)
            info = media.probe(path)
    except Exception as e:
        video.media_status = "failed"
        video.media_error = redact_secrets(str(e))[:2000]
        db.commit()
        raise
    video.media_path = storage.rel_path(path)
    video.duration_s, video.width, video.height = info.duration, info.width, info.height
    video.fps, video.has_audio = info.fps, info.has_audio
    video.media_status = "ready"
    if not video.thumbnail_url:
        try:
            media.extract_frame(path, info.duration * 0.1, storage.video_thumb_path(video.id), width=480)
            video.thumbnail_url = f"/api/videos/{video.id}/thumbnail"
        except media.MediaError:
            log.warning("Miniatura do vídeo %s falhou", video.id)
    db.commit()
    activity.record(db, "ingest", f"Mídia pronta: {video.title[:100]} ({info.width}x{info.height}, {info.duration / 60:.1f} min)",
                    level="success", ref_type="video", ref_id=video.id)
    if get_automation(db).auto_analyze:
        _queue_analysis(db, video)
    return f"Mídia pronta ({info.width}x{info.height})"


def _download_direct(db: Session, job: Job, video: SourceVideo, url: str) -> Path:
    """Baixa um ARQUIVO de vídeo de um link direto autorizado (ex.: link de download enviado pelo criador).
    Páginas de plataformas (YouTube, Twitch, TikTok...) são bloqueadas: os termos dessas plataformas
    não permitem download automatizado."""
    host = (urlparse(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS):
        raise PermanentError("Download automático de páginas de plataformas não é permitido. "
                             "Envie o arquivo autorizado pelo upload ou use um link direto de arquivo.")
    # Extensão neutra: depois do download o ffprobe decide e o arquivo é remuxado para MP4 (sem perda)
    dst = storage.source_dir(video.id) / "source.download"
    tmp = dst.with_suffix(".part")
    try:
        _stream_to_file(db, job, url, tmp)
    except httpx.HTTPError as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Falha de rede no download ({type(e).__name__}).") from None
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(dst)
    return dst


def _stream_to_file(db: Session, job: Job, url: str, tmp: Path) -> None:
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30, read=120)) as client:
        with client.stream("GET", url) as r:
            if r.status_code >= 400:
                raise PermanentError(f"Download falhou: HTTP {r.status_code}")
            ctype = r.headers.get("content-type", "")
            if not (ctype.startswith("video/") or ctype.startswith("application/octet-stream") or ctype.startswith("binary/")):
                raise PermanentError(f"O link não aponta para um arquivo de vídeo (content-type: {ctype or 'desconhecido'}).")
            total = int(r.headers.get("content-length") or 0)
            got = 0
            last = 0.0
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1024 * 1024):
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        pct = got / total * 80
                        if pct - last >= 2:
                            last = pct
                            q.progress(db, job, pct, f"Baixando {got / 1e6:.0f}/{total / 1e6:.0f} MB")
                            if q.is_cancelled(db, job):
                                tmp.unlink(missing_ok=True)
                                raise PermanentError("Cancelado.")


def _queue_analysis(db: Session, video: SourceVideo) -> None:
    video.analysis_status = "queued"
    video.analysis_error = None
    q.enqueue(db, "analyze_video", {"video_id": video.id}, ref_type="video", ref_id=video.id, priority=50, commit=False)
    db.commit()


# ============================================================== análise
def handle_analyze_video(db: Session, job: Job, *, ai_caller=None) -> str:
    s = get_settings()
    video = db.get(SourceVideo, job.payload["video_id"])
    if video is None:
        raise PermanentError("Vídeo não existe mais.")
    if video.media_status != "ready" or not video.media_path:
        raise PermanentError("A mídia deste vídeo ainda não está disponível.")
    src = storage.abs_path(video.media_path)
    auto = get_automation(db)
    creator = video.creator
    video.analysis_status = "running"
    video.analysis_error = None
    db.commit()

    try:
        result = _analyze(db, job, video, src, auto, creator, ai_caller)
    except Exception as e:
        video.analysis_status = "failed"
        video.analysis_error = redact_secrets(str(e))[:2000]
        db.commit()
        activity.record(db, "analysis", f"Análise falhou em “{video.title[:80]}”: {str(e)[:200]}", level="error",
                        ref_type="video", ref_id=video.id)
        raise
    finally:
        shutil.rmtree(storage.work_dir(video.id) / "frames", ignore_errors=True)
    return result


def _analyze(db, job, video, src, auto, creator, ai_caller) -> str:  # noqa: ANN001
    s = get_settings()
    work = storage.work_dir(video.id)
    meta: dict = {"started_at": utcnow().isoformat()}

    q.progress(db, job, 3, "Lendo vídeo")
    info = media.probe(src)
    duration = info.duration

    profile = None
    if info.has_audio:
        q.progress(db, job, 8, "Extraindo áudio")
        wav = media.extract_audio_wav(src, work / "audio.wav")
        q.progress(db, job, 18, "Medindo intensidade do áudio")
        profile = audio_profile(wav)
    limit = min(16, auto.max_clips_per_video * 2)
    scenes = _scene_changes(db, job, src, duration, profile, auto, limit, meta)
    meta["scene_changes"] = len(scenes)

    transcript = []
    tstatus = transcription.provider_status()
    if tstatus["available"] and info.has_audio:
        q.progress(db, job, 49, "Transcrevendo fala")
        try:
            transcript = transcription.transcribe(work / "audio.wav")
        except Exception as e:  # noqa: BLE001
            meta["transcription_error"] = str(e)[:300]
            activity.record(db, "analysis", f"Transcrição indisponível ({str(e)[:120]}); seguindo sem ela.", level="warning",
                            ref_type="video", ref_id=video.id)
    meta["transcript_segments"] = len(transcript)
    signals = SignalSummary(audio=profile, scene_changes=scenes, transcript=transcript)

    q.progress(db, job, 50, "Procurando webcam do streamer")
    sample_times = [duration * (0.03 + 0.94 * i / 23) for i in range(24)]
    detected = layout_svc.detect_webcam(media.extract_frames_gray(src, sample_times))
    video.layout_hint = detected
    db.commit()

    q.progress(db, job, 52, "Selecionando momentos candidatos")
    cands = find_candidates(signals, duration, min_len=auto.min_clip_seconds, max_len=auto.max_clip_seconds, limit=limit)
    meta["candidates"] = [{"start_s": c.start_s, "end_s": c.end_s, "peak_s": c.peak_s, "signal_score": c.signal_score,
                           **c.features} for c in cands]
    video.analysis_meta = dict(meta)  # cópia: o mesmo dict reatribuído não é salvo
    db.commit()
    if not cands:
        video.analysis_status = "done"
        video.analyzed_at = utcnow()
        db.commit()
        return "Nenhum momento candidato encontrado"

    # Evidências para a IA (quadros + transcrição por candidato)
    frames_dir = work / "frames"
    frames_dir.mkdir(exist_ok=True)
    evidences: list[CandidateEvidence] = []
    per = max(2, s.ai_frames_per_candidate)
    for i, c in enumerate(cands):
        times = _frame_times(c, per)
        frames = []
        for j, t in enumerate(times):
            p = frames_dir / f"c{i}_{j}.jpg"
            try:
                media.extract_frame(src, t, p, width=512)
                frames.append((t, p))
            except media.MediaError:
                continue
        evidences.append(CandidateEvidence(index=i, candidate=c,
                                           transcript=signals.transcript_text(c.context_start, c.context_end)[:6000],
                                           frames=frames))

    video_meta = {"creator": creator.name, "title": video.title, "platform": video.platform, "duration": duration}
    # Lotes avaliados em paralelo pela IA (a sessão do banco só é usada nesta thread)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    decisions = []
    failures: list[Exception] = []
    batch = max(1, s.ai_max_candidates_per_request)
    chunks = [evidences[b:b + batch] for b in range(0, len(evidences), batch)]
    q.progress(db, job, 56, f"IA avaliando {len(evidences)} momentos")
    with ThreadPoolExecutor(max_workers=min(3, len(chunks))) as pool:
        futures = [pool.submit(analyze_candidates, video_meta, chunk, min_len=auto.min_clip_seconds,
                               max_len=auto.max_clip_seconds, duration=duration, caller=ai_caller) for chunk in chunks]
        for done, fut in enumerate(as_completed(futures), 1):
            try:
                decisions += fut.result()
            except AIUnavailable:
                # Chave, modelo ou requisição inválidos: os outros lotes falhariam do mesmo jeito
                for f in futures:
                    f.cancel()
                raise
            except Exception as e:  # noqa: BLE001
                # Um lote com problema (rede, recusa, resposta truncada) não descarta o que os outros acharam
                log.warning("Lote da IA falhou no vídeo %s: %s", video.id, e)
                failures.append(e)
            q.progress(db, job, 56 + 34 * done / len(chunks), f"IA avaliou {done} de {len(chunks)} lotes")
            if q.is_cancelled(db, job):
                for f in futures:
                    f.cancel()
                raise PermanentError("Cancelado.")
    if failures:
        meta["ai_failed_batches"] = len(failures)
        if not decisions:
            raise failures[0]
        activity.record(db, "analysis",
                        f"IA falhou em {len(failures)} de {len(chunks)} lotes de “{video.title[:60]}” "
                        f"({str(failures[0])[:150]}); cortes criados com os demais. Reanalise para tentar de novo.",
                        level="warning", ref_type="video", ref_id=video.id)

    q.progress(db, job, 92, "Pontuando e organizando cortes")
    created = _create_clips(db, video, creator, cands, decisions, auto, info, src, detected)

    meta["ai_kept"] = sum(1 for d in decisions if d.keep)
    meta["ai_evaluated"] = len(decisions)
    meta["finished_at"] = utcnow().isoformat()
    video.analysis_meta = dict(meta)  # cópia: o mesmo dict reatribuído não é salvo
    video.analysis_status = "done"
    video.analyzed_at = utcnow()
    db.commit()
    why = ""
    if created == 0:
        why = (" (a IA não aprovou nenhum momento)" if meta["ai_kept"] == 0 else
               f" (nenhum momento aprovado atingiu a nota mínima de {auto.min_viral_score} ou o limite diário de cortes)")
    activity.record(db, "analysis",
                    f"IA analisou “{video.title[:80]}”: {len(cands)} candidatos, {created} cortes criados{why}",
                    level="success" if created else "warning", ref_type="video", ref_id=video.id)
    return f"{created} cortes criados de {len(cands)} candidatos{why}"


def _scene_changes(db, job, src, duration, profile, auto, limit, meta) -> list[float]:  # noqa: ANN001
    """Cortes de cena. Com áudio, analisa a imagem só nos trechos que o áudio apontou (muito mais rápido em
    lives longas); sem áudio, ou quando os trechos cobrem quase o vídeo todo, varre o vídeo inteiro."""
    windows: list[tuple[float, float]] = []
    if profile is not None:
        pre = find_candidates(SignalSummary(audio=profile, scene_changes=[]), duration,
                              min_len=auto.min_clip_seconds, max_len=auto.max_clip_seconds, limit=limit)
        windows = media.merge_windows([(max(0.0, c.start_s - 10), min(duration, c.end_s + 10)) for c in pre])
    covered = sum(b - a for a, b in windows)
    if not windows or covered > duration * 0.6:
        windows = [(0.0, duration)]
    meta["scene_scan_seconds"] = round(sum(b - a for a, b in windows), 1)
    total = sum(b - a for a, b in windows)
    scenes: list[float] = []
    done = 0.0
    for a, b in windows:
        span = b - a

        def report(frac: float, a=a, span=span, done=done) -> None:  # noqa: ANN001
            pct = (done + frac * span) / total
            q.progress(db, job, 22 + 26 * pct, f"Analisando imagem {pct * 100:.0f}%")

        scenes += media.detect_scene_changes(src, start=a, duration=span, on_progress=report)
        done += span
        if q.is_cancelled(db, job):
            raise PermanentError("Cancelado.")
    return sorted(scenes)


def _frame_times(c, n: int) -> list[float]:  # noqa: ANN001
    base = [c.start_s + 0.5, c.peak_s - 1.0, c.peak_s + 1.5, c.end_s - 2.0]
    if n > 4:
        extra = n - 4
        span = c.context_end - c.context_start
        base += [c.context_start + span * (k + 1) / (extra + 1) for k in range(extra)]
    return sorted(max(c.context_start, min(t, c.context_end - 0.1)) for t in base[:n])


def _create_clips(db, video, creator, cands, decisions, auto, info, src, detected) -> int:  # noqa: ANN001
    # Reanálise: descarta pendentes antigos deste vídeo (aprovados/rejeitados são preservados)
    for old in list(video.clips):
        if old.status == "pending_review" and old.render_status in ("none", "failed"):
            thumb = storage.abs_path(old.thumbnail_path)
            if thumb:
                thumb.unlink(missing_ok=True)
            video.clips.remove(old)  # delete-orphan remove do banco
    db.flush()
    existing = [(c.start_s, c.end_s) for c in video.clips]

    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today = db.scalar(select(func.count(Clip.id)).where(Clip.discovered_at >= start_of_day)) or 0
    remaining_today = max(0, auto.max_clips_per_day - today)

    ranked = []
    for d in decisions:
        if not d.keep:
            continue
        cand = cands[d.candidate_index]
        score = scoring.final_score(d.scores, cand.signal_score)
        if score < auto.min_viral_score:
            continue
        boost = 5 if d.category in auto.priority_categories else 0
        ranked.append((score + boost, score, d, cand))
    ranked.sort(key=lambda r: r[0], reverse=True)

    limit = min(auto.max_clips_per_video, remaining_today)
    created = 0
    base_layout = layout_svc.initial_layout(creator.default_layout, detected)
    for _rank, score, d, cand in ranked:
        if created >= limit:
            break
        if any(_overlap(d.start_s, d.end_s, a, b) > 0.5 for a, b in existing):
            continue
        tier = scoring.tier_for(score)
        approved = auto.approval_mode == "automatic" and score >= auto.auto_approve_min_score
        clip = Clip(
            source_video_id=video.id, creator_id=creator.id, start_s=d.start_s, end_s=d.end_s,
            title=d.title, title_options=d.title_options or None, summary=d.summary, hook=d.hook,
            category=d.category, viral_score=score, tier=tier,
            score_breakdown=scoring.breakdown(d.scores, cand.signal_score), rationale=d.rationale,
            signals={**cand.features, "peak_s": cand.peak_s, "signal_score": cand.signal_score},
            analysis_source=f"claude:{get_settings().ai_model}",
            status="approved" if approved else "pending_review", auto_approved=approved,
            reviewed_at=utcnow() if approved else None, layout=base_layout,
        )
        db.add(clip)
        db.flush()
        try:
            t = storage.thumb_path(clip.id)
            render.render_thumbnail(src, t, t=min(d.start_s + 1.0, d.end_s), layout=base_layout,
                                    src_w=info.width, src_h=info.height)
            clip.thumbnail_path = storage.rel_path(t)
        except media.MediaError as e:
            log.warning("Miniatura falhou para clip %s: %s", clip.id, e)
        existing.append((d.start_s, d.end_s))
        created += 1
        label = scoring.TIER_LABELS[tier]
        activity.record(db, "clip", f"Corte encontrado ({score}/100 · {label}): {d.title}",
                        level="success" if tier == "alto" else "info", ref_type="clip", ref_id=clip.id, commit=False)
    if ranked and remaining_today == 0:
        activity.record(db, "clip", "Limite diário de cortes atingido; demais momentos ignorados hoje.", level="warning",
                        commit=False)
    db.commit()
    return created


def _overlap(a1: float, a2: float, b1: float, b2: float) -> float:
    inter = max(0.0, min(a2, b2) - max(a1, b1))
    shortest = max(1e-6, min(a2 - a1, b2 - b1))
    return inter / shortest


# ============================================================== renderização
def handle_render_export(db: Session, job: Job) -> str:
    exp = db.get(Export, job.payload["export_id"])
    if exp is None:
        raise PermanentError("Exportação não existe mais.")
    clip = exp.clip
    video = clip.source_video
    src = storage.abs_path(video.media_path)
    if not src or not src.exists():
        raise PermanentError("Mídia original não está mais disponível.")
    exp.status = "rendering"
    clip.render_status = "rendering"
    db.commit()
    dst = storage.export_path(clip.id, exp.id)
    try:
        render.render_vertical(
            src, dst, start=exp.start_s, end=exp.end_s, layout=exp.layout, src_w=video.width, src_h=video.height,
            has_audio=bool(video.has_audio), src_fps=video.fps, quality=exp.quality,
            on_progress=lambda pct: q.progress(db, job, pct, f"Renderizando {pct:.0f}%"),
            should_cancel=lambda: q.is_cancelled(db, job),
        )
        out = media.probe(dst)
    except Exception as e:
        exp.status = "failed"
        exp.error = redact_secrets(str(e))[:2000]
        clip.render_status = "failed"
        db.commit()
        activity.record(db, "export", f"Exportação falhou: {clip.title[:80]} — {str(e)[:150]}", level="error",
                        ref_type="clip", ref_id=clip.id)
        raise
    exp.status = "done"
    exp.path = storage.rel_path(dst)
    exp.size_bytes = dst.stat().st_size
    exp.width, exp.height = out.width, out.height
    exp.finished_at = utcnow()
    clip.render_status = "done"
    db.commit()
    activity.record(db, "export", f"MP4 {out.width}x{out.height} pronto: {clip.title[:80]}", level="success",
                    ref_type="clip", ref_id=clip.id)
    return f"Exportado {out.width}x{out.height}, {exp.size_bytes / 1e6:.1f} MB"


def on_requeue(db: Session, job: Job) -> None:
    """Job voltou para a fila após erro temporário: o estado visível volta a 'na fila'."""
    ref = job.payload or {}
    if job.type == "analyze_video":
        v = db.get(SourceVideo, ref.get("video_id"))
        if v:
            v.analysis_status = "queued"
    elif job.type == "ingest_media":
        v = db.get(SourceVideo, ref.get("video_id"))
        if v:
            v.media_status = "ingesting"
    elif job.type == "render_export":
        e = db.get(Export, ref.get("export_id"))
        if e:
            e.status = "queued"
            e.clip.render_status = "queued"
    db.commit()


def reconcile_orphans(db: Session) -> int:
    """Destrava vídeos/exportações que ficaram 'em andamento' sem nenhum job ativo
    (ex.: o servidor reiniciou no meio do processamento)."""
    active = {(j.type, j.ref_id) for j in db.scalars(select(Job).where(Job.status.in_(q.ACTIVE_STATUSES))).all()}
    msg = "Interrompido porque o servidor reiniciou. Clique em Reanalisar."
    n = 0
    for v in db.scalars(select(SourceVideo).where(SourceVideo.analysis_status.in_(("queued", "running")))).all():
        if ("analyze_video", v.id) not in active:
            v.analysis_status, v.analysis_error = "failed", msg
            n += 1
    for v in db.scalars(select(SourceVideo).where(SourceVideo.media_status == "ingesting")).all():
        if ("ingest_media", v.id) not in active:
            v.media_status, v.media_error = "failed", "Preparação interrompida (servidor reiniciou). Envie a mídia de novo."
            n += 1
    for e in db.scalars(select(Export).where(Export.status.in_(("queued", "rendering")))).all():
        if ("render_export", e.id) not in active:
            e.status, e.error = "failed", "Interrompido (servidor reiniciou). Tente exportar de novo."
            e.clip.render_status = "failed"
            n += 1
    db.commit()
    return n


def scrub_stored_secrets(db: Session) -> int:
    """Esconde chaves de API que versões anteriores gravaram em mensagens de erro (aparecem no painel)."""
    targets = [(Job, "error"), (SourceVideo, "analysis_error"), (SourceVideo, "media_error"), (Export, "error"),
               (Creator, "last_check_error"), (ActivityEvent, "message")]
    n = 0
    for model, field in targets:
        col = getattr(model, field)
        rows = db.scalars(select(model).where(or_(col.like("%sk-ant-%"), col.like("%AIza%"), col.like("%key=%")))).all()
        for row in rows:
            old = getattr(row, field)
            new = redact_secrets(old)
            if new != old:
                setattr(row, field, new)
                n += 1
    db.commit()
    return n


HANDLERS = {
    "monitor_creator": handle_monitor_creator,
    "ingest_media": handle_ingest_media,
    "analyze_video": handle_analyze_video,
    "render_export": handle_render_export,
}


def due_monitors(db: Session) -> int:
    """Agenda verificação dos criadores conforme a frequência configurada."""
    auto = get_automation(db)
    if not auto.monitoring_enabled:
        return 0
    limit = utcnow() - timedelta(minutes=auto.monitor_interval_minutes)
    n = 0
    for c in db.scalars(select(Creator).where(Creator.active.is_(True))).all():
        if not (c.youtube_handle or c.youtube_channel_id or c.twitch_login or c.twitch_user_id or c.drive_folder_id):
            continue
        if c.last_checked_at is None or c.last_checked_at < limit:
            before = db.scalar(select(func.count(Job.id)).where(Job.type == "monitor_creator", Job.ref_id == c.id,
                                                                Job.status.in_(q.ACTIVE_STATUSES)))
            if not before:
                q.enqueue(db, "monitor_creator", {"creator_id": c.id}, ref_type="creator", ref_id=c.id, priority=80)
                n += 1
    return n
