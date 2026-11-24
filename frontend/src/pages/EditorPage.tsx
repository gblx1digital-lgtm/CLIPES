import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Crosshair, Download, Pause, Play, Repeat, RotateCcw, Save, Scissors, UserSquare2, Volume2, VolumeX } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useClipActions } from "../components/ClipViewer";
import { Badge, CLIP_STATUS, EmptyState, ErrorBox, PageHeader, Section, Segmented, Select, useToast } from "../components/ui";
import { VerticalPreview } from "../components/VerticalPlayer";
import { api, type CamRect, type Clip, type ClipDetail, type Layout } from "../lib/api";
import { fmtDateTime, fmtTimecode } from "../lib/format";
import { computeRegions, normalizeLayout } from "../lib/layout";

export default function EditorPage() {
  const [params, setParams] = useSearchParams();
  const clipId = params.get("clip") ? Number(params.get("clip")) : null;
  const { data: list } = useQuery({
    queryKey: ["clips", "editor-list"],
    queryFn: () => api.get<{ items: Clip[] }>("/api/clips?status=pending_review,approved&page_size=100&sort=score"),
  });
  const { data: clip, error, isLoading } = useQuery({
    queryKey: ["clip", clipId],
    queryFn: () => api.get<ClipDetail>(`/api/clips/${clipId}`),
    enabled: clipId != null,
    refetchInterval: (q) => (q.state.data && ["queued", "rendering"].includes(q.state.data.render_status) ? 2000 : false),
  });

  return (
    <>
      <PageHeader
        title="Editor"
        description={clip ? `${clip.creator_name} · ${clip.title}` : "Ajuste o corte, o enquadramento vertical e exporte em MP4 1080×1920"}
        actions={
          <Select className="w-72" value={clipId ? String(clipId) : ""} onChange={(v) => setParams(v ? { clip: v } : {})}>
            <option value="">Selecione um corte…</option>
            {clip && !list?.items.some((c) => c.id === clip.id) && <option value={clip.id}>{clip.title}</option>}
            {list?.items.map((c) => (
              <option key={c.id} value={c.id}>
                [{c.viral_score}] {c.title} — {c.creator_name}
              </option>
            ))}
          </Select>
        }
      />
      <div className="p-6">
        <ErrorBox error={error} />
        {!clipId ? (
          <div className="card">
            <EmptyState
              icon={<Scissors size={16} />}
              title="Escolha um corte para editar"
              description="Selecione um corte acima ou abra um corte na Central de Clipes e clique em “Abrir no editor”."
              action={<Link to="/clipes" className="btn-secondary">Ir para a Central de Clipes</Link>}
            />
          </div>
        ) : isLoading || !clip ? (
          <div className="skeleton h-[560px]" />
        ) : !clip.source?.stream_url ? (
          <div className="card"><EmptyState icon={<Scissors size={16} />} title="Mídia original indisponível" description="O arquivo de origem deste corte não está mais no armazenamento." /></div>
        ) : (
          <Editor key={clip.id} clip={clip} />
        )}
      </div>
    </>
  );
}

function Editor({ clip }: { clip: ClipDetail }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { exportClip } = useClipActions();
  const src = clip.source!;
  const videoRef = useRef<HTMLVideoElement>(null);
  const [videoEl, setVideoEl] = useState<HTMLVideoElement | null>(null);
  const [start, setStart] = useState(clip.start_s);
  const [end, setEnd] = useState(clip.end_s);
  const [layout, setLayout] = useState<Layout>(normalizeLayout(clip.layout));
  const [time, setTime] = useState(clip.start_s);
  const [playing, setPlaying] = useState(false);
  const [loopSel, setLoopSel] = useState(true);
  const [muted, setMuted] = useState(false);
  const [quality, setQuality] = useState<string>("");
  const [camDraft, setCamDraft] = useState<CamRect>(layout.cam ?? clip.source?.layout_hint?.cam ?? { x: 0.72, y: 0.04, w: 0.25, h: 0.3 });

  const dirty = start !== clip.start_s || end !== clip.end_s || JSON.stringify(normalizeLayout(layout)) !== JSON.stringify(normalizeLayout(clip.layout));
  const duration = src.duration_s;

  useEffect(() => setVideoEl(videoRef.current), []);

  // Reprodução: em modo "loop" a seleção [start, end] repete
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    let raf = 0;
    const tick = () => {
      if (!v.paused && loopSel && v.currentTime >= end) v.currentTime = start;
      setTime(v.currentTime);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    return () => {
      cancelAnimationFrame(raf);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
    };
  }, [start, end, loopSel]);

  const seek = useCallback((t: number) => {
    const v = videoRef.current;
    if (v) v.currentTime = Math.max(0, Math.min(duration, t));
  }, [duration]);

  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      if (loopSel && (v.currentTime < start || v.currentTime >= end - 0.05)) v.currentTime = start;
      void v.play();
    } else v.pause();
  }, [loopSel, start, end]);

  const setIn = useCallback((t: number) => setStart(Math.max(0, Math.min(t, end - 1))), [end]);
  const setOut = useCallback((t: number) => setEnd(Math.min(duration, Math.max(t, start + 1))), [duration, start]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select")) return;
      if (e.code === "Space") { e.preventDefault(); togglePlay(); }
      else if (e.key === "i" || e.key === "I") setIn(videoRef.current?.currentTime ?? start);
      else if (e.key === "o" || e.key === "O") setOut(videoRef.current?.currentTime ?? end);
      else if (e.key === "ArrowLeft") seek((videoRef.current?.currentTime ?? 0) - (e.shiftKey ? 5 : 0.5));
      else if (e.key === "ArrowRight") seek((videoRef.current?.currentTime ?? 0) + (e.shiftKey ? 5 : 0.5));
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [togglePlay, setIn, setOut, seek, start, end]);

  const save = useMutation({
    mutationFn: (extra?: Record<string, unknown>) => api.patch<ClipDetail>(`/api/clips/${clip.id}`, { start_s: start, end_s: end, layout, ...(extra ?? {}) }),
    onSuccess: (c) => {
      qc.setQueryData(["clip", clip.id], c);
      void qc.invalidateQueries({ queryKey: ["clips"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e: Error) => toast("bad", e.message),
  });
  const saveCreatorDefault = useMutation({
    mutationFn: () => api.patch(`/api/creators/${clip.creator_id}`, { default_layout: { ...layout, cam_source: "creator_default" } }),
    onSuccess: () => toast("good", `Layout salvo como padrão de ${clip.creator_name}. Novos cortes já usarão esse enquadramento.`),
    onError: (e: Error) => toast("bad", e.message),
  });

  const doExport = async () => {
    try {
      if (dirty || clip.status !== "approved") {
        await save.mutateAsync(clip.status !== "approved" ? { status: "approved" } : undefined);
      }
      await exportClip.mutateAsync({ id: clip.id, quality: quality || undefined });
    } catch {
      /* toasts já exibidos */
    }
  };

  const setMode = (mode: "split" | "full") => {
    if (mode === "split") setLayout((l) => normalizeLayout({ ...l, mode, cam: l.cam ?? camDraft }));
    else setLayout((l) => normalizeLayout({ ...l, mode }));
  };
  const updateCam = (c: CamRect) => {
    setCamDraft(c);
    setLayout((l) => normalizeLayout({ ...l, mode: "split", cam: c, cam_source: "manual" }));
  };

  const activeExport = clip.exports.find((e) => e.status === "queued" || e.status === "rendering");
  const regions = useMemo(() => computeRegions(layout, src.width, src.height), [layout, src.width, src.height]);

  return (
    <div className="grid gap-5 2xl:grid-cols-[1fr_340px] xl:grid-cols-[1fr_320px]">
      <div className="min-w-0 space-y-4">
        <Section
          title={<span className="flex items-center gap-2">Vídeo original <span className="font-mono text-2xs font-normal text-faint">{src.width}×{src.height} · {src.fps?.toFixed(0)} fps</span></span>}
          actions={
            <div className="flex items-center gap-2">
              <Badge tone={CLIP_STATUS[clip.status].tone} dot>{CLIP_STATUS[clip.status].label}</Badge>
              {dirty && <Badge tone="warn">Alterações não salvas</Badge>}
            </div>
          }
        >
          <div className="p-4">
            <div className="relative mx-auto w-full overflow-hidden rounded-md bg-black" style={{ aspectRatio: `${src.width} / ${src.height}`, maxHeight: "52vh", maxWidth: `calc(52vh * ${src.width / src.height})` }}>
              <video ref={videoRef} src={src.stream_url!} preload="auto" playsInline muted={muted} className="absolute inset-0 h-full w-full" onClick={togglePlay} crossOrigin="anonymous"
                onLoadedMetadata={(e) => { e.currentTarget.currentTime = clip.start_s; }} />
              {/* Área de gameplay que entra no vídeo final */}
              <div className="pointer-events-none absolute border border-dashed border-white/50"
                style={{ left: `${(regions.game.x / src.width) * 100}%`, top: `${(regions.game.y / src.height) * 100}%`, width: `${(regions.game.w / src.width) * 100}%`, height: `${(regions.game.h / src.height) * 100}%`, boxShadow: "0 0 0 9999px rgb(0 0 0 / 0.35)" }}>
                <span className="absolute left-1 top-1 rounded bg-black/70 px-1 text-[10px] text-white/80">Gameplay</span>
              </div>
              {layout.mode === "split" && layout.cam && <CamBox cam={layout.cam} onChange={updateCam} />}
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button className="btn-secondary btn-icon" onClick={togglePlay} aria-label={playing ? "Pausar" : "Reproduzir"}>{playing ? <Pause size={14} /> : <Play size={14} />}</button>
              <button className={clsx("btn-ghost btn-sm", loopSel && "bg-hover text-fg")} onClick={() => setLoopSel((x) => !x)} title="Repetir somente o trecho selecionado">
                <Repeat size={13} /> Tocar só o corte
              </button>
              <button className="btn-ghost btn-icon h-7 w-7" onClick={() => setMuted((m) => !m)} aria-label="Som">{muted ? <VolumeX size={14} /> : <Volume2 size={14} />}</button>
              <span className="font-mono text-xs tabular-nums text-muted">{fmtTimecode(time)} / {fmtTimecode(duration)}</span>
              <span className="ml-auto hidden text-2xs text-faint lg:inline">
                <span className="kbd">Espaço</span> play · <span className="kbd">I</span>/<span className="kbd">O</span> início/fim no cursor · <span className="kbd">←</span><span className="kbd">→</span> 0,5s
              </span>
            </div>

            <Timeline duration={duration} start={start} end={end} time={time} onSeek={seek} onStart={setIn} onEnd={setOut} />

            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <TimeField label="Início" value={start} onChange={setIn} onCursor={() => setIn(time)} onGo={() => seek(start)} />
              <TimeField label="Fim" value={end} onChange={setOut} onCursor={() => setOut(time)} onGo={() => seek(Math.max(start, end - 3))} />
              <div>
                <p className="label">Duração do corte</p>
                <div className="flex h-8 items-center gap-2">
                  <span className={clsx("font-mono text-[15px] tabular-nums", end - start > 120 && "text-warn")}>{fmtTimecode(end - start)}</span>
                  {end - start > 120 && <span className="text-2xs text-warn">acima de 2 min</span>}
                  <button className="btn-ghost btn-sm ml-auto" onClick={() => { setStart(clip.start_s); setEnd(clip.end_s); }} title="Voltar à sugestão da IA">
                    <RotateCcw size={12} /> Sugestão da IA
                  </button>
                </div>
              </div>
            </div>
          </div>
        </Section>
        {save.error && <ErrorBox error={save.error} />}
      </div>

      <div className="space-y-4">
        <Section title="Resultado 9:16">
          <div className="space-y-4 p-4">
            <div className="mx-auto w-full max-w-[260px]">
              <VerticalPreview src={src.stream_url!} externalVideo={videoEl} start={start} end={end} layout={layout} showControls={false} enforceRange={false} />
            </div>
            <Segmented
              full
              value={layout.mode}
              onChange={setMode}
              options={[{ value: "split", label: "Webcam + jogo" }, { value: "full", label: "Tela cheia" }]}
            />
            {layout.mode === "split" && (
              <Slider label="Tamanho da webcam" value={layout.cam_height} min={0.18} max={0.45} step={0.01} display={`${Math.round(layout.cam_height * 100)}% da altura`}
                onChange={(v) => setLayout((l) => normalizeLayout({ ...l, cam_height: v }))} />
            )}
            <Slider label="Posição da gameplay" value={layout.focus_x} min={0} max={1} step={0.005} display={layout.focus_x < 0.45 ? "esquerda" : layout.focus_x > 0.55 ? "direita" : "centro"}
              onChange={(v) => setLayout((l) => normalizeLayout({ ...l, focus_x: v }))} />
            <Slider label="Zoom da gameplay" value={layout.zoom} min={1} max={2} step={0.01} display={`${layout.zoom.toFixed(2)}×`}
              onChange={(v) => setLayout((l) => normalizeLayout({ ...l, zoom: v }))} />
            {layout.mode === "split" && (
              <p className="text-2xs leading-relaxed text-faint">Arraste o retângulo da webcam no vídeo original para posicioná-lo; use os cantos para redimensionar.</p>
            )}
            <div className="flex flex-wrap gap-2">
              {clip.source?.layout_hint?.cam && (
                <button className="btn-ghost btn-sm" onClick={() => updateCam(clip.source!.layout_hint!.cam)}>
                  <Crosshair size={12} /> Webcam detectada
                </button>
              )}
              <button className="btn-ghost btn-sm" onClick={() => setLayout(normalizeLayout(clip.layout))}><RotateCcw size={12} /> Desfazer layout</button>
              <button className="btn-ghost btn-sm" onClick={() => saveCreatorDefault.mutate()} disabled={saveCreatorDefault.isPending} title="Usar este enquadramento nos próximos cortes deste criador">
                <UserSquare2 size={12} /> Padrão do criador
              </button>
            </div>
          </div>
        </Section>

        <Section title="Salvar e exportar">
          <div className="space-y-3 p-4">
            <button className="btn-secondary w-full" disabled={!dirty || save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => toast("good", "Corte salvo.") })}>
              <Save size={14} /> {save.isPending ? "Salvando…" : "Salvar alterações"}
            </button>
            <div className="flex gap-2">
              <Select className="flex-1" value={quality} onChange={setQuality}>
                <option value="">Qualidade padrão (Automações)</option>
                <option value="standard">Padrão · menor arquivo</option>
                <option value="high">Alta</option>
                <option value="max">Máxima</option>
              </Select>
            </div>
            <button className="btn-primary w-full" disabled={!!activeExport || exportClip.isPending || save.isPending || end - start > 180} onClick={doExport}>
              <Download size={14} /> {clip.status === "approved" ? "Exportar MP4 1080×1920" : "Aprovar e exportar MP4"}
            </button>
            <p className="text-2xs leading-relaxed text-faint">H.264 + AAC, 1080×1920, áudio sincronizado. Sem textos, legendas ou efeitos.</p>
            {clip.exports.length > 0 && (
              <div className="divide-y divide-line/[0.06] rounded-md border hairline">
                {clip.exports.slice(0, 4).map((e) => (
                  <div key={e.id} className="flex items-center gap-2 px-2.5 py-2 text-xs">
                    <Badge tone={e.status === "done" ? "good" : e.status === "failed" ? "bad" : "info"}>{e.status === "done" ? "Pronto" : e.status === "failed" ? "Falhou" : "Renderizando"}</Badge>
                    <span className="text-muted">{fmtTimecode(e.duration_s)}</span>
                    <span className="ml-auto text-2xs text-faint">{fmtDateTime(e.created_at)}</span>
                    {e.download_url && <a className="btn-ghost btn-icon h-6 w-6" href={e.download_url} title="Baixar"><Download size={12} /></a>}
                  </div>
                ))}
                <Link to="/exportacoes" className="block px-2.5 py-1.5 text-center text-2xs text-muted hover:text-fg">Ver exportações</Link>
              </div>
            )}
          </div>
        </Section>
      </div>
    </div>
  );
}

function Slider({ label, value, min, max, step, display, onChange }: { label: string; value: number; min: number; max: number; step: number; display: string; onChange: (v: number) => void }) {
  return (
    <div>
      <div className="mb-1.5 flex justify-between text-xs">
        <span className="text-muted">{label}</span>
        <span className="font-mono text-2xs text-faint">{display}</span>
      </div>
      <input type="range" className="w-full" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </div>
  );
}

function TimeField({ label, value, onChange, onCursor, onGo }: { label: string; value: number; onChange: (v: number) => void; onCursor: () => void; onGo: () => void }) {
  const [text, setText] = useState(value.toFixed(1));
  useEffect(() => setText(value.toFixed(1)), [value]);
  return (
    <div>
      <p className="label">{label} <span className="font-normal text-faint">({fmtTimecode(value)})</span></p>
      <div className="flex gap-1">
        <button className="btn-secondary btn-icon w-7 shrink-0" onClick={() => onChange(value - 0.5)} aria-label="-0,5s">−</button>
        <input className="input text-center font-mono" value={text} onChange={(e) => setText(e.target.value)}
          onBlur={() => { const v = parseFloat(text.replace(",", ".")); if (isFinite(v)) onChange(v); else setText(value.toFixed(1)); }}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
        <button className="btn-secondary btn-icon w-7 shrink-0" onClick={() => onChange(value + 0.5)} aria-label="+0,5s">+</button>
        <button className="btn-ghost btn-sm shrink-0 px-2" onClick={onCursor} title="Usar posição atual do vídeo">Cursor</button>
        <button className="btn-ghost btn-icon w-7 shrink-0" onClick={onGo} title="Ir para este ponto"><Play size={11} /></button>
      </div>
    </div>
  );
}

/** Linha do tempo com zoom ao redor do corte + minimapa do vídeo inteiro. */
function Timeline({ duration, start, end, time, onSeek, onStart, onEnd }: { duration: number; start: number; end: number; time: number; onSeek: (t: number) => void; onStart: (t: number) => void; onEnd: (t: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<null | "start" | "end" | "seek">(null);
  const [view, setView] = useState(() => calcView(start, end, duration));
  useEffect(() => {
    if (!drag) setView(calcView(start, end, duration));
  }, [start, end, duration, drag]);

  const toTime = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect();
    return view[0] + Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * (view[1] - view[0]);
  };
  useEffect(() => {
    if (!drag) return;
    const move = (e: PointerEvent) => {
      const t = Math.round(toTime(e.clientX) * 10) / 10;
      if (drag === "start") onStart(t);
      else if (drag === "end") onEnd(t);
      else onSeek(t);
    };
    const up = () => setDrag(null);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag, view]);

  const pct = (t: number) => ((t - view[0]) / (view[1] - view[0])) * 100;
  const ticks = useMemo(() => {
    const span = view[1] - view[0];
    const stepOpts = [1, 2, 5, 10, 15, 30, 60, 120, 300];
    const step = stepOpts.find((s) => span / s <= 12) ?? 600;
    const out: number[] = [];
    for (let t = Math.ceil(view[0] / step) * step; t <= view[1]; t += step) out.push(t);
    return out;
  }, [view]);

  return (
    <div className="mt-4 select-none">
      <div
        ref={ref}
        className="relative h-14 cursor-pointer rounded-md border hairline bg-bg"
        onPointerDown={(e) => { if ((e.target as HTMLElement).dataset.handle) return; onSeek(toTime(e.clientX)); setDrag("seek"); }}
      >
        {ticks.map((t) => (
          <div key={t} className="pointer-events-none absolute bottom-0 top-0 border-l border-line/[0.05]" style={{ left: `${pct(t)}%` }}>
            <span className="absolute bottom-0.5 left-1 font-mono text-[9px] text-faint">{fmtTimecode(t).replace(/\.\d$/, "")}</span>
          </div>
        ))}
        <div className="pointer-events-none absolute inset-y-1.5 rounded-sm border border-accent/60 bg-accent/15" style={{ left: `${pct(start)}%`, width: `${pct(end) - pct(start)}%` }} />
        {(["start", "end"] as const).map((h) => (
          <div
            key={h}
            data-handle={h}
            onPointerDown={(e) => { e.stopPropagation(); setDrag(h); }}
            className="absolute inset-y-0 z-10 w-3 -translate-x-1/2 cursor-ew-resize"
            style={{ left: `${pct(h === "start" ? start : end)}%` }}
            title={h === "start" ? "Arraste para ajustar o início" : "Arraste para ajustar o fim"}
          >
            <div data-handle={h} className="mx-auto h-full w-[3px] rounded-full bg-accent" />
          </div>
        ))}
        {time >= view[0] && time <= view[1] && (
          <div className="pointer-events-none absolute inset-y-0 z-20 w-px bg-fg" style={{ left: `${pct(time)}%` }}>
            <div className="absolute -left-[4px] -top-1 h-2 w-[9px] rounded-sm bg-fg" />
          </div>
        )}
      </div>
      <div className="relative mt-2 h-1.5 cursor-pointer rounded-full bg-line/[0.06]" onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); onSeek(((e.clientX - r.left) / r.width) * duration); }} title="Vídeo completo">
        <div className="absolute inset-y-0 rounded-full bg-fg/15" style={{ left: `${(view[0] / duration) * 100}%`, width: `${((view[1] - view[0]) / duration) * 100}%` }} />
        <div className="absolute inset-y-0 rounded-full bg-accent" style={{ left: `${(start / duration) * 100}%`, width: `${Math.max(0.4, ((end - start) / duration) * 100)}%` }} />
        <div className="absolute -top-0.5 h-2.5 w-px bg-fg" style={{ left: `${(time / duration) * 100}%` }} />
      </div>
    </div>
  );
}

function calcView(start: number, end: number, duration: number): [number, number] {
  const pad = Math.max(10, (end - start) * 0.75);
  return [Math.max(0, start - pad), Math.min(duration, end + pad)];
}

/** Retângulo arrastável/redimensionável da webcam (coordenadas normalizadas). */
function CamBox({ cam, onChange }: { cam: CamRect; onChange: (c: CamRect) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const start = (e: React.PointerEvent, mode: "move" | "nw" | "ne" | "sw" | "se") => {
    e.preventDefault();
    e.stopPropagation();
    const parent = ref.current!.parentElement!.getBoundingClientRect();
    const sx = e.clientX;
    const sy = e.clientY;
    const c0 = { ...cam };
    const move = (ev: PointerEvent) => {
      const dx = (ev.clientX - sx) / parent.width;
      const dy = (ev.clientY - sy) / parent.height;
      let { x, y, w, h } = c0;
      if (mode === "move") {
        x = clamp(c0.x + dx, 0, 1 - w);
        y = clamp(c0.y + dy, 0, 1 - h);
      } else {
        if (mode.includes("w")) { x = clamp(c0.x + dx, 0, c0.x + c0.w - 0.05); w = c0.x + c0.w - x; }
        if (mode.includes("e")) { w = clamp(c0.w + dx, 0.05, 1 - c0.x); }
        if (mode.includes("n")) { y = clamp(c0.y + dy, 0, c0.y + c0.h - 0.05); h = c0.y + c0.h - y; }
        if (mode.includes("s")) { h = clamp(c0.h + dy, 0.05, 1 - c0.y); }
      }
      onChange({ x, y, w, h });
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  return (
    <div
      ref={ref}
      onPointerDown={(e) => start(e, "move")}
      className="absolute cursor-move border-2 border-accent bg-accent/10"
      style={{ left: `${cam.x * 100}%`, top: `${cam.y * 100}%`, width: `${cam.w * 100}%`, height: `${cam.h * 100}%` }}
    >
      <span className="pointer-events-none absolute left-1 top-1 whitespace-nowrap rounded bg-accent px-1 text-[10px] font-medium text-white">Webcam</span>
      {(["nw", "ne", "sw", "se"] as const).map((k) => (
        <span
          key={k}
          onPointerDown={(e) => start(e, k)}
          className={clsx(
            "absolute h-2.5 w-2.5 rounded-sm border border-white bg-accent",
            k.includes("n") ? "-top-1.5" : "-bottom-1.5",
            k.includes("w") ? "-left-1.5" : "-right-1.5",
            k === "nw" || k === "se" ? "cursor-nwse-resize" : "cursor-nesw-resize",
          )}
        />
      ))}
    </div>
  );
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
