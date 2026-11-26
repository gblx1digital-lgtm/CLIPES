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
STATIC_STD = 12.0  # desvio padrão temporal (tons de cinza 0-255) abaixo do qual o pixel é "parado"


def detect_webcam(frames: list) -> dict[str, Any] | None:
    """Acha a webcam do streamer em quadros espalhados pelo vídeo (BGR, todos do mesmo tamanho).

    Critério: um rosto que aparece mais de uma vez no mesmo lugar, que se mexe, e que está cercado por
    fundo PARADO (o quarto do streamer) dentro de um retângulo fixo. Rostos de personagens mudam de lugar;
    logos e marcas d'água (ex.: um leão no canto) ficam soltos no meio da gameplay, que muda o tempo todo,
    e são descartados. Retorna a região da webcam (normalizada 0-1) ou None.
    """
    import cv2

    if len(frames) < 3:
        return None
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    return pick_webcam(grays, _face_boxes(grays))


def _face_boxes(grays: list) -> list[tuple[float, float, float, float]]:
    """Rostos (x, y, w, h normalizados) de todos os quadros. Detecta em 2x: rosto de webcam costuma ser pequeno."""
    import cv2

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    H, W = grays[0].shape[:2]
    min_side = int(W * 2 * 0.025)
    boxes = []
    for g in grays:
        big = cv2.resize(cv2.equalizeHist(g), None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        for (x, y, w, h) in cascade.detectMultiScale(big, scaleFactor=1.1, minNeighbors=5, minSize=(min_side, min_side)):
            if w / (2 * W) > 0.25:  # rosto enorme = câmera em tela cheia, não overlay
                continue
            boxes.append((x / (2 * W), y / (2 * H), w / (2 * W), h / (2 * H)))
    return boxes


def pick_webcam(grays: list, boxes: list[tuple[float, float, float, float]]) -> dict[str, Any] | None:
    """Escolhe, entre os rostos detectados, o que está numa webcam e mede o retângulo dela."""
    import cv2
    import numpy as np

    if not boxes or len(grays) < 3:
        return None
    H, W = grays[0].shape[:2]
    std = np.stack(grays).astype(np.float32).std(axis=0)
    static = (std < STATIC_STD).astype(np.uint8)

    def px(x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
        return (int(_clamp(x0, 0, 1) * W), int(_clamp(y0, 0, 1) * H), int(_clamp(x1, 0, 1) * W), int(_clamp(y1, 0, 1) * H))

    arr = np.array(boxes, dtype=np.float64)
    centers = arr[:, :2] + arr[:, 2:] / 2
    near = np.linalg.norm(centers[:, None, :] - centers[None, :, :], axis=2) < 0.06
    used = np.zeros(len(arr), dtype=bool)
    # Fecha buracos do fundo parado (a pessoa se mexe no meio do quarto) para medir o retângulo inteiro
    k = max(3, int(W * 0.03)) | 1
    closed = cv2.morphologyEx(static, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    n_lab, labels, stats, _ = cv2.connectedComponentsWithStats(closed, 8)

    best: tuple[float, dict[str, Any]] | None = None
    for i in np.argsort(-near.sum(axis=1)):
        if used[i]:
            continue
        members = near[i] & ~used
        used |= members
        count = int(members.sum())
        if count < 2:
            continue
        fx, fy, fw, fh = np.median(arr[members], axis=0).tolist()
        fcx, fcy = fx + fw / 2, fy + fh / 2
        # O rosto precisa se mexer (foto/avatar parado não é webcam)...
        x0, y0, x1, y1 = px(fx, fy, fx + fw, fy + fh)
        if x1 <= x0 or y1 <= y0 or float(std[y0:y1, x0:x1].mean()) < STATIC_STD:
            continue
        # ...e estar cercado de fundo parado (quarto do streamer), não de gameplay
        rx0, ry0, rx1, ry1 = px(fcx - 1.5 * fw, fcy - 1.5 * fh, fcx + 1.5 * fw, fcy + 1.5 * fh)
        ring = static[ry0:ry1, rx0:rx1].astype(bool)
        ix0, iy0, ix1, iy1 = px(fcx - 0.6 * fw, fcy - 0.6 * fh, fcx + 0.6 * fw, fcy + 0.6 * fh)
        mask = np.ones_like(ring)
        mask[max(0, iy0 - ry0):max(0, iy1 - ry0), max(0, ix0 - rx0):max(0, ix1 - rx0)] = False
        ring_static = float(ring[mask].mean()) if mask.any() else 0.0
        if ring_static < 0.15:
            continue

        # Retângulo da webcam = região parada ligada ao fundo em volta do rosto
        ids = set(np.unique(labels[ry0:ry1, rx0:rx1]).tolist()) - {0}
        bx0, by0, bx1, by1 = x0, y0, x1, y1
        for lab in ids:
            sx, sy, sw, sh, area = stats[lab]
            if area < 0.002 * W * H:
                continue
            bx0, by0, bx1, by1 = min(bx0, sx), min(by0, sy), max(bx1, sx + sw), max(by1, sy + sh)
        rect = (float(bx0) / W, float(by0) / H, float(bx1 - bx0) / W, float(by1 - by0) / H)
        if rect[2] * rect[3] > 0.4 or rect[2] < 1.5 * fw or rect[3] < 1.5 * fh:
            # Região parada grande demais (tela de menu, faixas pretas) ou pequena demais: estimativa pelo rosto
            cw, ch = min(fw * 3.4, 0.5), min(fh * 3.0, 0.6)
            rect = (_clamp(fcx - cw / 2, 0, 1 - cw), _clamp(fcy - ch * 0.42, 0, 1 - ch), cw, ch)
        score = count * (0.5 + ring_static)
        if best is None or score > best[0]:
            cx, cy, cw, ch = rect
            cam_px_aspect = (cw * W) / max(1e-6, ch * H)
            best = (score, {
                "cam": {"x": round(cx, 4), "y": round(cy, 4), "w": round(cw, 4), "h": round(ch, 4)},
                "face": {"x": round(fx, 4), "y": round(fy, 4), "w": round(fw, 4), "h": round(fh, 4)},
                "stability": round(count / len(grays), 2),
                # Faixa do topo com a mesma proporção da webcam: mostra a webcam inteira, sem pedaço do jogo
                "cam_height": round(float(_clamp(OUT_W / cam_px_aspect / OUT_H, 0.22, 0.42)), 3),
            })
    return best[1] if best else None


def initial_layout(creator_default: dict[str, Any] | None, detected: dict[str, Any] | None) -> dict[str, Any]:
    """Ordem de preferência: layout padrão do criador > webcam detectada > gameplay em tela cheia."""
    if creator_default and creator_default.get("cam"):
        return normalize_layout({**creator_default, "mode": creator_default.get("mode", "split"), "cam_source": "creator_default"})
    if detected and detected.get("cam"):
        return normalize_layout({"mode": "split", "cam": detected["cam"], "cam_height": detected.get("cam_height", 0.30),
                                 "cam_source": "detected"})
    return normalize_layout({"mode": "full", **({k: creator_default[k] for k in ("focus_x", "zoom") if k in creator_default} if creator_default else {})})
