import numpy as np

from app.services import scoring
from app.services.candidates import find_candidates
from app.services.layout import (build_filter, compute_regions, detect_webcam, initial_layout, normalize_layout,
                                 pick_webcam)
from app.services.signals import AudioProfile, SignalSummary, robust_z
from app.services.sources.base import matches_keywords, parse_iso8601_duration, parse_twitch_duration


def test_scoring_weights_sum_to_one():
    assert abs(sum(w for _l, w in scoring.CRITERIA.values()) - 1.0) < 1e-9


def test_scoring_range_and_tiers():
    perfect = {k: 10 for k in scoring.CRITERIA}
    assert scoring.final_score(perfect, 100) == 100
    assert scoring.final_score({}, 0) == 0
    assert scoring.tier_for(80) == "alto" and scoring.tier_for(60) == "medio" and scoring.tier_for(10) == "baixo"
    assert scoring.final_score({k: 99 for k in scoring.CRITERIA}, 500) == 100  # valores fora da faixa são limitados


def test_split_layout_regions_are_valid():
    lay = {"mode": "split", "cam": {"x": 0.75, "y": 0.02, "w": 0.22, "h": 0.25}, "cam_height": 0.3}
    r = compute_regions(lay, 1920, 1080)
    cam, game = r["cam"], r["game"]
    for reg in (cam, game):
        assert all(v % 2 == 0 for v in reg.values())
        assert reg["x"] >= 0 and reg["y"] >= 0
        assert reg["x"] + reg["w"] <= 1920 and reg["y"] + reg["h"] <= 1080
    # proporção da webcam igual à da faixa do topo (sem distorção)
    cw_out, ch_out = r["cam_out"]
    assert abs(cam["w"] / cam["h"] - cw_out / ch_out) < 0.02
    gw_out, gh_out = r["game_out"]
    assert ch_out + gh_out == 1920
    assert abs(game["w"] / game["h"] - gw_out / gh_out) < 0.02
    assert "vstack" in build_filter(lay, 1920, 1080)


def test_full_layout_is_9_16_and_respects_focus():
    left = compute_regions({"mode": "full", "focus_x": 0.0}, 1920, 1080)["game"]
    right = compute_regions({"mode": "full", "focus_x": 1.0}, 1920, 1080)["game"]
    assert left["x"] == 0 and right["x"] + right["w"] <= 1920 and right["x"] > 1000
    assert abs(left["w"] / left["h"] - 9 / 16) < 0.01


def test_split_without_cam_falls_back_to_full():
    assert normalize_layout({"mode": "split", "cam": None})["mode"] == "full"
    assert initial_layout(None, None)["mode"] == "full"
    det = {"cam": {"x": 0.7, "y": 0.0, "w": 0.3, "h": 0.3}}
    assert initial_layout(None, det)["mode"] == "split"


def test_detect_webcam_none_without_faces():
    frames = [np.zeros((360, 640, 3), np.uint8) for _ in range(5)]
    assert detect_webcam(frames) is None



def _webcam_scene(n=24, seed=1):
    """Quadros 640x360: gameplay mudando o tempo todo, webcam no canto superior esquerdo (quarto parado,
    pessoa se mexendo) e um logo no canto direito (desenho fixo meio transparente sobre a gameplay)."""
    rng = np.random.default_rng(seed)
    room = rng.integers(40, 200, (100, 154), dtype=np.uint8)     # quarto do streamer: textura fixa
    logo = rng.integers(0, 255, (40, 40), dtype=np.uint8)
    frames = []
    for _ in range(n):
        g = rng.integers(0, 255, (360, 640), dtype=np.uint8)     # gameplay
        g[41:141, 0:154] = room
        g[60:110, 55:95] = rng.integers(0, 255, (50, 40), dtype=np.uint8)  # pessoa se mexendo
        g[210:250, 590:630] = (0.6 * logo + 0.4 * g[210:250, 590:630]).astype(np.uint8)
        frames.append(g)
    return frames


def test_pick_webcam_ignores_logo_in_gameplay_and_measures_the_cam_box():
    grays = _webcam_scene()
    face = (60 / 640, 65 / 360, 30 / 640, 30 / 360)
    lion = (595 / 640, 215 / 360, 30 / 640, 30 / 360)
    det = pick_webcam(grays, [lion] * 11 + [face] * 4)  # o logo é "detectado" mais vezes que o rosto
    assert det is not None
    cam = det["cam"]
    assert cam["x"] < 0.02 and abs(cam["y"] - 41 / 360) < 0.03
    assert abs(cam["w"] - 154 / 640) < 0.03 and abs(cam["h"] - 100 / 360) < 0.03
    # faixa do topo com a proporção da webcam (154x100 -> ~1.54): sem pedaço de gameplay ao lado
    lay = initial_layout(None, det)
    r = compute_regions(lay, 1920, 1080)
    assert lay["mode"] == "split" and abs(r["cam"]["w"] / r["cam"]["h"] - (154 / 100)) < 0.05
    assert r["cam"]["x"] + r["cam"]["w"] <= 0.25 * 1920


def test_pick_webcam_rejects_logo_only_and_static_avatar():
    grays = _webcam_scene()
    lion = (595 / 640, 215 / 360, 30 / 640, 30 / 360)
    assert pick_webcam(grays, [lion] * 12) is None
    # "rosto" parado (foto/avatar fixo no canto) não é webcam
    for g in grays:
        g[60:110, 55:95] = 128
    face = (60 / 640, 65 / 360, 30 / 640, 30 / 360)
    assert pick_webcam(grays, [face] * 6) is None

def test_candidates_find_audio_peaks():
    window = 0.5
    n = int(300 / window)
    db = np.full(n, -40.0, dtype=np.float32) + np.random.default_rng(0).normal(0, 1, n).astype(np.float32)
    for t in (60, 200):
        db[int(t / window): int((t + 4) / window)] = -8
    prof = AudioProfile(window_s=window, rms_db=db, z=robust_z(db))
    cands = find_candidates(SignalSummary(audio=prof, scene_changes=[]), 300, min_len=15, max_len=60, limit=4)
    peaks = sorted(c.peak_s for c in cands)
    assert any(abs(p - 61) < 6 for p in peaks) and any(abs(p - 201) < 6 for p in peaks)
    strongest = sorted(cands, key=lambda c: -c.signal_score)[:2]
    assert {round(c.peak_s / 100) for c in strongest} == {1, 2}
    for c in cands:
        assert 15 <= c.end_s - c.start_s <= 60
        assert c.start_s <= c.peak_s <= c.end_s


def test_short_video_is_single_candidate():
    cands = find_candidates(SignalSummary(audio=None, scene_changes=[]), 30, min_len=15, max_len=60, limit=5)
    assert len(cands) == 1 and cands[0].end_s == 30


def test_keyword_matching_and_durations():
    kws = ["gta 6", "gta vi"]
    assert matches_keywords("ROUBEI UM CARRO NO GTA 6!!", kws)
    assert matches_keywords("primeira live de gta vi", kws)
    assert matches_keywords("GTA6 RP", kws)
    assert not matches_keywords("Minecraft hardcore", kws)
    assert matches_keywords("qualquer coisa", [])
    assert parse_iso8601_duration("PT1H2M3S") == 3723
    assert parse_twitch_duration("3h2m1s") == 10921


def test_claude_call_omits_fallbacks_for_models_without_support(monkeypatch):
    import anthropic

    from app.config import get_settings
    from app.services import ai_analysis

    calls = {}

    class Resp:
        stop_reason = "end_turn"
        usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()
        content = [type("B", (), {"type": "text", "text": '{"clips": []}'})()]

    class Msgs:
        def __init__(self, kind):
            self.kind = kind

        def create(self, **kw):
            calls[self.kind] = kw
            return Resp()

    class FakeClient:
        def __init__(self, **kw):
            self.messages = Msgs("plain")
            self.beta = type("Beta", (), {"messages": Msgs("beta")})()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    s = get_settings()
    monkeypatch.setattr(s, "anthropic_api_key", "teste")
    monkeypatch.setattr(s, "ai_model", "claude-haiku-5-5")
    assert ai_analysis._call_claude([{"type": "text", "text": "x"}]) == {"clips": []}
    assert "plain" in calls and "fallbacks" not in calls["plain"]
    calls.clear()
    monkeypatch.setattr(s, "ai_model", "claude-opus-5-5")
    ai_analysis._call_claude([{"type": "text", "text": "x"}])
    assert calls["beta"]["fallbacks"] == "default"


def test_redact_secrets_hides_api_keys():
    from app.logging_setup import redact_secrets

    text = ("Falha de conexão com a API Anthropic (LocalProtocolError: Illegal header value "
            "b'Bearer sk-ant-api03-AbC_dEf-123\\n'). url 'https://www.googleapis.com/youtube/v3/search"
            "?part=snippet&key=AIzaSyA1234567890abcdefghijklmnopqrstu&maxResults=5'")
    out = redact_secrets(text)
    assert "sk-ant-api03" not in out and "AbC_dEf" not in out
    assert "AIzaSyA123" not in out and "key=***" in out
    assert out.startswith("Falha de conexão com a API Anthropic")


def test_anthropic_key_pasted_with_curl_example(monkeypatch):
    """Colar o comando curl de exemplo do console no lugar da chave: a plataforma usa só o sk-ant-..."""
    from app.config import Settings

    pasted = ('curl https://api.anthropic.com/v1/messages \\\n  --header "x-api-key: sk-ant-usr-AbC123_x-Y9AA" \\\n'
              '  --header "anthropic-version: 2026-10-21" \\\n  --header "content-type: application/json"\n')
    monkeypatch.setenv("ANTHROPIC_API_KEY", pasted)
    assert Settings().anthropic_api_key == "sk-ant-usr-AbC123_x-Y9AA"
    monkeypatch.setenv("ANTHROPIC_API_KEY", ' "sk-ant-api03-Zz9"\r\n')
    assert Settings().anthropic_api_key == "sk-ant-api03-Zz9"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert Settings().anthropic_api_key is None
