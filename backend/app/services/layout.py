"""Enquadramento vertical 9:16.

Layouts:
  split -> webcam do streamer em faixa no topo (pequena, proporcional) + gameplay em destaque embaixo
  full  -> gameplay ocupando a tela inteira, com recorte 9:16 inteligente (foco horizontal ajustável)

Sem textos, legendas, emojis, marcas d'água, transições ou efeitos: só recorte e escala (lanczos).
Coordenadas da webcam são normalizadas (0-1) em relação ao vídeo original.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("clipes.layout")

OUT_W, OUT_H = 1080, 1920

DEFAULT_LAYOUT: dict[str, Any] = {
    "mode": "full",
    "cam": None,
    "cam_height": 0.30,
    "focus_x": 0.5,
    "focus_y": 0.5,
    "zoom": 1.0,
    "cam_source": None,
}


def normalize_layout(layout: dict[str, Any] | None) -> dict[str, Any]:
    out = {**DEFAULT_LAYOUT, **(layout or {})}
    out["mode"] = out["mode"] if out["mode"] in ("split", "full") else "full"
    out["cam_height"] = _clamp(float(out["cam_height"]), 0.18, 0.45)
    out["focus_x"] = _clamp(float(out["focus_x"]), 0.0, 1.0)
    out["focus_y"] = _clamp(float(out["focus_y"]), 0.0, 1.0)
    out["zoom"] = _clamp(float(out["zoom"]), 1.0, 3.0)
    cam = out.get("cam")
    if cam:
        x, y = _clamp(float(cam["x"]), 0, 0.98), _clamp(float(cam["y"]), 0, 0.98)
        w, h = _clamp(float(cam["w"]), 0.02, 1 - x), _clamp(float(cam["h"]), 0.02, 1 - y)
        out["cam"] = {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)}
    else:
        out["cam"] = None
    if out["mode"] == "split" and not out["cam"]:
        out["mode"] = "full"
    return out


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _even(v: float) -> int:
    i = int(round(v))
    return i - (i % 2)


def _fit_aspect(cx: float, cy: float, w: float, h: float, aspect: float, src_w: int, src_h: int) -> tuple[int, int, int, int]:
    """Ajusta (w,h) para a proporção pedida expandindo em torno do centro, dentro do quadro."""
    if w / h > aspect:
        h = w / aspect
    else:
        w = h * aspect
    scale = min(1.0, src_w / w, src_h / h)
    w, h = w * scale, h * scale
    x = _clamp(cx - w / 2, 0, src_w - w)
    y = _clamp(cy - h / 2, 0, src_h - h)
    return _even(w), _even(h), _even(x), _even(y)


def compute_regions(layout: dict[str, Any], src_w: int, src_h: int, out_w: int = OUT_W, out_h: int = OUT_H) -> dict[str, Any]:
    lay = normalize_layout(layout)
    regions: dict[str, Any] = {"mode": lay["mode"], "out_w": out_w, "out_h": out_h}
    if lay["mode"] == "split":
        band_h = _even(out_h * lay["cam_height"])
        game_h = out_h - band_h
        c = lay["cam"]
        cw, ch = c["w"] * src_w, c["h"] * src_h
        cx, cy = c["x"] * src_w + cw / 2, c["y"] * src_h + ch / 2
        regions["cam"] = dict(zip(("w", "h", "x", "y"), _fit_aspect(cx, cy, cw, ch, out_w / band_h, src_w, src_h)))
        regions["cam_out"] = (out_w, band_h)
    else:
        game_h = out_h
    aspect = out_w / game_h
    gh = src_h / lay["zoom"]
    gw = gh * aspect
    if gw > src_w:
        gw = src_w
        gh = gw / aspect
    gx = lay["focus_x"] * src_w - gw / 2
    gy = lay["focus_y"] * src_h - gh / 2
    regions["game"] = {"w": _even(gw), "h": _even(gh), "x": _even(_clamp(gx, 0, src_w - gw)), "y": _even(_clamp(gy, 0, src_h - gh))}
    regions["game_out"] = (out_w, game_h)
    return regions


def build_filter(layout: dict[str, Any], src_w: int, src_h: int, out_w: int = OUT_W, out_h: int = OUT_H) -> str:
    r = compute_regions(layout, src_w, src_h, out_w, out_h)
    g = r["game"]
    gw_out, gh_out = r["game_out"]
    game = f"crop={g['w']}:{g['h']}:{g['x']}:{g['y']},scale={gw_out}:{gh_out}:flags=lanczos,setsar=1"
    if r["mode"] == "split":
        c = r["cam"]
        cw_out, ch_out = r["cam_out"]
        cam = f"crop={c['w']}:{c['h']}:{c['x']}:{c['y']},scale={cw_out}:{ch_out}:flags=lanczos,setsar=1"
        return (f"[0:v]split=2[cs][gs];[cs]{cam}[cam];[gs]{game}[game];"
                f"[cam][game]vstack=inputs=2,format=yuv420p[v]")
    return f"[0:v]{game},format=yuv420p[v]"


# ------------------------------------------------------------------ detecção de webcam
def detect_webcam(frames: list) -> dict[str, Any] | None:
    """Procura um rosto que aparece de forma estável no mesmo lugar (overlay de webcam).

    Rostos de personagens do jogo se movem; a webcam do streamer fica fixa. Exigimos o
    mesmo local em boa parte dos quadros amostrados e um rosto pequeno em relação à tela.
    Retorna a região estimada da webcam (normalizada) ou None.
    """
    import cv2
    import numpy as np

    if not frames:
        return None
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    H, W = frames[0].shape[:2]
    boxes: list[tuple[float, float, float, float]] = []
    for img in frames:
        gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(int(W * 0.03), int(W * 0.03)))
        for (x, y, w, h) in faces:
            if w / W > 0.25:  # rosto enorme = câmera em tela cheia, não overlay
                continue
            boxes.append((x / W, y / H, w / W, h / H))
    if not boxes:
        return None

    centers = np.array([[b[0] + b[2] / 2, b[1] + b[3] / 2] for b in boxes])
    best_idx, best_count = 0, 0
    for i, c in enumerate(centers):
        count = int((np.linalg.norm(centers - c, axis=1) < 0.06).sum())
        if count > best_count:
            best_idx, best_count = i, count
    stability = best_count / len(frames)
    if stability < 0.4:
        return None

    near = np.linalg.norm(centers - centers[best_idx], axis=1) < 0.06
    fx, fy, fw, fh = np.median(np.array(boxes)[near], axis=0).tolist()
    # A webcam costuma mostrar cabeça e ombros: ~3x a largura do rosto, rosto no terço superior
    cw, ch = min(fw * 3.4, 0.5), min(fh * 3.0, 0.6)
    fcx, fcy = fx + fw / 2, fy + fh / 2
    cx = _clamp(fcx - cw / 2, 0, 1 - cw)
    cy = _clamp(fcy - ch * 0.42, 0, 1 - ch)
    return {
        "cam": {"x": round(cx, 4), "y": round(cy, 4), "w": round(cw, 4), "h": round(ch, 4)},
        "face": {"x": round(fx, 4), "y": round(fy, 4), "w": round(fw, 4), "h": round(fh, 4)},
        "stability": round(stability, 2),
    }


def initial_layout(creator_default: dict[str, Any] | None, detected: dict[str, Any] | None) -> dict[str, Any]:
    """Ordem de preferência: layout padrão do criador > webcam detectada > gameplay em tela cheia."""
    if creator_default and creator_default.get("cam"):
        return normalize_layout({**creator_default, "mode": creator_default.get("mode", "split"), "cam_source": "creator_default"})
    if detected and detected.get("cam"):
        return normalize_layout({"mode": "split", "cam": detected["cam"], "cam_source": "detected"})
    return normalize_layout({"mode": "full", **({k: creator_default[k] for k in ("focus_x", "zoom") if k in creator_default} if creator_default else {})})
