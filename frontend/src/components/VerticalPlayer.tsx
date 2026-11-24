import clsx from "clsx";
import { Pause, Play, RotateCcw, Volume2, VolumeX } from "lucide-react";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import type { Layout } from "../lib/api";
import { fmtTimecode } from "../lib/format";
import { drawVertical } from "../lib/layout";

export type VerticalPlayerHandle = { video: HTMLVideoElement | null; seek: (t: number) => void; play: () => void; pause: () => void };

/**
 * Prévia 9:16 ao vivo: reproduz a fonte original e desenha no canvas o mesmo
 * enquadramento que o ffmpeg vai renderizar. Toca somente o intervalo [start, end].
 */
export const VerticalPreview = forwardRef<
  VerticalPlayerHandle,
  { src: string; start: number; end: number; layout: Layout; className?: string; externalVideo?: HTMLVideoElement | null; showControls?: boolean; enforceRange?: boolean }
>(function VerticalPreview({ src, start, end, layout, className, externalVideo, showControls = true, enforceRange = true }, ref) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const ownVideo = useRef<HTMLVideoElement>(null);
  const layoutRef = useRef(layout);
  const rangeRef = useRef({ start, end, enforceRange });
  layoutRef.current = layout;
  rangeRef.current = { start, end, enforceRange };
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [time, setTime] = useState(start);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const getVideo = useCallback(() => externalVideo ?? ownVideo.current, [externalVideo]);

  useImperativeHandle(ref, () => ({
    video: getVideo(),
    seek: (t: number) => {
      const v = getVideo();
      if (v) v.currentTime = t;
    },
    play: () => void getVideo()?.play(),
    pause: () => getVideo()?.pause(),
  }));

  useEffect(() => {
    const v = getVideo();
    const canvas = canvasRef.current;
    if (!v || !canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    let lastT = -1;
    const draw = () => {
      if (v.readyState >= 2) {
        drawVertical(ctx, v, layoutRef.current);
        if (!ready) setReady(true);
      }
      const { start: s, end: e, enforceRange: enforce } = rangeRef.current;
      if (enforce && !v.paused && v.currentTime >= e) {
        v.pause();
        v.currentTime = s;
      }
      if (Math.abs(v.currentTime - lastT) > 0.05) {
        lastT = v.currentTime;
        setTime(v.currentTime);
      }
      raf = requestAnimationFrame(draw);
    };
    const onLoaded = () => {
      if (!externalVideo && (v.currentTime < rangeRef.current.start || v.currentTime > rangeRef.current.end)) v.currentTime = rangeRef.current.start;
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onError = () => setError("Não foi possível carregar a mídia original.");
    v.addEventListener("loadedmetadata", onLoaded);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    v.addEventListener("error", onError);
    if (v.readyState >= 1) onLoaded();
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      v.removeEventListener("loadedmetadata", onLoaded);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
      v.removeEventListener("error", onError);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [getVideo, src]);

  // Redesenha quando o layout muda com o vídeo pausado
  useEffect(() => {
    const v = getVideo();
    const ctx = canvasRef.current?.getContext("2d");
    if (v && ctx && v.readyState >= 2) drawVertical(ctx, v, layout);
  }, [layout, getVideo]);

  const toggle = () => {
    const v = getVideo();
    if (!v) return;
    if (v.paused) {
      if (v.currentTime < start || v.currentTime >= end - 0.05) v.currentTime = start;
      void v.play();
    } else v.pause();
  };

  const pct = end > start ? ((time - start) / (end - start)) * 100 : 0;

  return (
    <div className={clsx("flex flex-col gap-2", className)}>
      {!externalVideo && <video ref={ownVideo} src={src} preload="auto" muted={muted} playsInline className="hidden" crossOrigin="anonymous" />}
      <div className="relative overflow-hidden rounded-lg border hairline bg-black" style={{ aspectRatio: "9 / 16" }}>
        <canvas ref={canvasRef} width={540} height={960} className="h-full w-full cursor-pointer" onClick={toggle} />
        {!ready && !error && <div className="skeleton absolute inset-0 rounded-none" />}
        {error && <div className="absolute inset-0 flex items-center justify-center p-4 text-center text-xs text-muted">{error}</div>}
        {ready && !playing && (
          <button onClick={toggle} className="absolute inset-0 m-auto flex h-12 w-12 items-center justify-center rounded-full bg-black/50 backdrop-blur transition hover:bg-black/70" aria-label="Reproduzir">
            <Play size={18} className="ml-0.5 fill-white text-white" />
          </button>
        )}
      </div>
      {showControls && (
        <div className="flex items-center gap-2">
          <button className="btn-ghost btn-icon h-7 w-7" onClick={toggle} aria-label={playing ? "Pausar" : "Reproduzir"}>
            {playing ? <Pause size={14} /> : <Play size={14} />}
          </button>
          <button className="btn-ghost btn-icon h-7 w-7" onClick={() => { const v = getVideo(); if (v) v.currentTime = start; }} aria-label="Voltar ao início">
            <RotateCcw size={13} />
          </button>
          <div
            className="relative h-1 flex-1 cursor-pointer rounded-full bg-line/[0.08]"
            onClick={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              const v = getVideo();
              if (v) v.currentTime = start + ((e.clientX - r.left) / r.width) * (end - start);
            }}
          >
            <div className="absolute inset-y-0 left-0 rounded-full bg-fg/80" style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
          </div>
          <span className="w-[86px] text-right font-mono text-2xs tabular-nums text-muted">
            {fmtTimecode(Math.max(0, time - start))} / {fmtTimecode(end - start)}
          </span>
          {!externalVideo && (
            <button className="btn-ghost btn-icon h-7 w-7" onClick={() => setMuted((m) => !m)} aria-label={muted ? "Ativar som" : "Silenciar"}>
              {muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
            </button>
          )}
        </div>
      )}
    </div>
  );
});

export function ExportedPlayer({ src, className }: { src: string; className?: string }) {
  return (
    <div className={clsx("overflow-hidden rounded-lg border hairline bg-black", className)} style={{ aspectRatio: "9 / 16" }}>
      <video src={src} controls playsInline preload="metadata" className="h-full w-full" />
    </div>
  );
}
