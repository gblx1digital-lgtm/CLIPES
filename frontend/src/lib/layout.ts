/**
 * Porte exato de backend/app/services/layout.py (compute_regions) para a prévia 9:16 no navegador
 * mostrar o mesmo enquadramento que o ffmpeg vai renderizar.
 */
import type { Layout } from "./api";

export const OUT_W = 1080;
export const OUT_H = 1920;

export const DEFAULT_LAYOUT: Layout = {
  mode: "full",
  cam: null,
  cam_height: 0.3,
  focus_x: 0.5,
  focus_y: 0.5,
  zoom: 1,
  cam_source: null,
};

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const even = (v: number) => {
  const i = Math.round(v);
  return i - (i % 2);
};

export function normalizeLayout(l: Partial<Layout> | null | undefined): Layout {
  const out: Layout = { ...DEFAULT_LAYOUT, ...(l || {}) } as Layout;
  out.cam_height = clamp(out.cam_height, 0.18, 0.45);
  out.focus_x = clamp(out.focus_x, 0, 1);
  out.focus_y = clamp(out.focus_y, 0, 1);
  out.zoom = clamp(out.zoom, 1, 3);
  if (out.cam) {
    const x = clamp(out.cam.x, 0, 0.98);
    const y = clamp(out.cam.y, 0, 0.98);
    out.cam = { x, y, w: clamp(out.cam.w, 0.02, 1 - x), h: clamp(out.cam.h, 0.02, 1 - y) };
  }
  if (out.mode === "split" && !out.cam) out.mode = "full";
  return out;
}

type Rect = { x: number; y: number; w: number; h: number };

function fitAspect(cx: number, cy: number, w: number, h: number, aspect: number, sw: number, sh: number): Rect {
  if (w / h > aspect) h = w / aspect;
  else w = h * aspect;
  const scale = Math.min(1, sw / w, sh / h);
  w *= scale;
  h *= scale;
  const x = clamp(cx - w / 2, 0, sw - w);
  const y = clamp(cy - h / 2, 0, sh - h);
  return { w: even(w), h: even(h), x: even(x), y: even(y) };
}

export type Regions = {
  mode: "split" | "full";
  cam?: Rect;
  camOut?: [number, number];
  game: Rect;
  gameOut: [number, number];
};

export function computeRegions(layout: Layout, sw: number, sh: number, outW = OUT_W, outH = OUT_H): Regions {
  const l = normalizeLayout(layout);
  let gameH = outH;
  const r: Partial<Regions> = { mode: l.mode };
  if (l.mode === "split" && l.cam) {
    const bandH = even(outH * l.cam_height);
    gameH = outH - bandH;
    const cw = l.cam.w * sw;
    const ch = l.cam.h * sh;
    r.cam = fitAspect(l.cam.x * sw + cw / 2, l.cam.y * sh + ch / 2, cw, ch, outW / bandH, sw, sh);
    r.camOut = [outW, bandH];
  }
  const aspect = outW / gameH;
  let gh = sh / l.zoom;
  let gw = gh * aspect;
  if (gw > sw) {
    gw = sw;
    gh = gw / aspect;
  }
  const gx = l.focus_x * sw - gw / 2;
  const gy = l.focus_y * sh - gh / 2;
  r.game = { w: even(gw), h: even(gh), x: even(clamp(gx, 0, sw - gw)), y: even(clamp(gy, 0, sh - gh)) };
  r.gameOut = [outW, gameH];
  return r as Regions;
}

/** Desenha um quadro do vídeo-fonte no canvas 9:16 (mesmo resultado do render final). */
export function drawVertical(ctx: CanvasRenderingContext2D, video: HTMLVideoElement, layout: Layout) {
  const sw = video.videoWidth;
  const sh = video.videoHeight;
  const W = ctx.canvas.width;
  const H = ctx.canvas.height;
  if (!sw || !sh) return;
  const r = computeRegions(layout, sw, sh, OUT_W, OUT_H);
  const k = W / OUT_W;
  ctx.imageSmoothingQuality = "high";
  let y = 0;
  if (r.mode === "split" && r.cam && r.camOut) {
    ctx.drawImage(video, r.cam.x, r.cam.y, r.cam.w, r.cam.h, 0, 0, W, r.camOut[1] * k);
    y = r.camOut[1] * k;
  }
  ctx.drawImage(video, r.game.x, r.game.y, r.game.w, r.game.h, 0, y, W, H - y);
}
