"""Fluxo completo com vídeo real gerado pelo ffmpeg. A chamada ao Claude é substituída por um
avaliador determinístico (os testes não gastam a API nem dependem de rede)."""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import Job
from app.services import ai_analysis, media
from app.services.settings_store import save_automation
from app.worker import main as worker


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _drain(max_jobs=10):
    n = 0
    while n < max_jobs and worker.run_one("test-worker"):
        n += 1
    return n


def fake_claude(content):
    """Lê os candidatos do prompt e aprova todos com notas altas."""
    text = "\n".join(b["text"] for b in content if b["type"] == "text")
    clips = []
    for block in text.split("=== Candidato ")[1:]:
        idx = int(block.split(" ", 1)[0])
        line = next(l for l in block.splitlines() if l.startswith("Sugestão automática"))
        a, b = line.split(":", 1)[1].replace("s", "").split(" a ")
        clips.append({"candidate_index": idx, "keep": True, "start_s": float(a), "end_s": float(b),
                      "title": f"Momento {idx}", "summary": "Reação forte", "hook": "Grito no início",
                      "category": "reacoes", "rationale": "Pico de áudio claro",
                      "scores": {k: 8 for k in ai_analysis._output_schema()["properties"]["clips"]["items"]["properties"]["scores"]["properties"]}})
    images = sum(1 for b in content if b["type"] == "image")
    assert images > 0, "a IA deve receber quadros do vídeo"
    return {"clips": clips}


def test_full_pipeline(client, test_video, monkeypatch):
    r = client.post("/api/creators", json={"name": "Criador Teste", "media_authorized": True})
    assert r.status_code == 201, r.text
    creator_id = r.json()["id"]

    # Upload sem confirmar direitos é recusado
    with open(test_video, "rb") as f:
        r = client.post("/api/videos/upload", data={"creator_id": creator_id, "rights_basis": "own"},
                        files={"file": ("live.mp4", f, "video/mp4")})
    assert r.status_code == 400

    with open(test_video, "rb") as f:
        r = client.post("/api/videos/upload",
                        data={"creator_id": creator_id, "rights_basis": "own", "confirm_rights": "true", "title": "Live GTA 6"},
                        files={"file": ("live.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    video_id = r.json()["video"]["id"]

    # 1) Sem chave da Anthropic: ingestão funciona, análise falha com mensagem clara e sem retentativa
    _drain()
    v = client.get(f"/api/videos/{video_id}").json()
    assert v["media_status"] == "ready" and v["width"] == 1920 and v["has_audio"]
    assert v["analysis_status"] == "failed"
    assert "ANTHROPIC_API_KEY" in v["analysis_error"]
    assert v["analysis_meta"]["candidates"], "candidatos por sinais devem ser registrados mesmo sem IA"
    with SessionLocal() as db:
        j = db.query(Job).filter(Job.type == "analyze_video").one()
        assert j.status == "failed" and j.attempts == 1

    # 2) Com IA (simulada): cortes são criados, pontuados e ordenados
    monkeypatch.setattr(ai_analysis, "_call_claude", fake_claude)
    r = client.post(f"/api/videos/{video_id}/analyze")
    assert r.status_code == 200
    _drain()
    v = client.get(f"/api/videos/{video_id}").json()
    assert v["analysis_status"] == "done", v["analysis_error"]
    clips = client.get("/api/clips").json()
    assert clips["total"] >= 2
    scores = [c["viral_score"] for c in clips["items"]]
    assert scores == sorted(scores, reverse=True)
    top = clips["items"][0]
    assert top["status"] == "pending_review" and top["thumbnail_url"]
    assert 15 <= top["duration_s"] <= 60
    assert client.get(top["thumbnail_url"]).status_code == 200

    # Filtros
    assert client.get("/api/clips", params={"category": "reacoes"}).json()["total"] == clips["total"]
    assert client.get("/api/clips", params={"category": "bugs"}).json()["total"] == 0
    assert client.get("/api/clips", params={"min_score": 101}).json()["total"] == 0

    # Exportar exige aprovação
    assert client.post(f"/api/clips/{top['id']}/export", json={}).status_code == 400

    # 3) Editor: ajustar corte e layout, aprovar e exportar
    r = client.patch(f"/api/clips/{top['id']}", json={
        "start_s": 30.0, "end_s": 50.0, "status": "approved",
        "layout": {"mode": "split", "cam": {"x": 0.7, "y": 0.05, "w": 0.25, "h": 0.3}, "cam_height": 0.28},
    })
    assert r.status_code == 200, r.text
    assert r.json()["layout"]["cam_source"] == "manual"
    r = client.post(f"/api/clips/{top['id']}/export", json={"quality": "standard"})
    assert r.status_code == 201, r.text
    export_id = r.json()["id"]
    _drain()
    exp = next(e for e in client.get("/api/exports").json() if e["id"] == export_id)
    assert exp["status"] == "done", exp
    r = client.get(exp["download_url"])
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
    assert "attachment" in r.headers["content-disposition"]

    from app.services import storage
    from app.models import Export
    with SessionLocal() as db:
        path = storage.abs_path(db.get(Export, export_id).path)
    info = media.probe(path)
    assert (info.width, info.height) == (1080, 1920)
    assert info.has_audio and info.audio_codec == "aac" and info.video_codec == "h264"
    assert abs(info.duration - 20.0) < 0.2

    # Reanálise: pendentes são substituídos, aprovado é preservado, nada fica bloqueado
    before = client.get("/api/clips").json()["total"]
    assert client.post(f"/api/videos/{video_id}/analyze").status_code == 200
    _drain()
    after = client.get("/api/clips").json()
    assert after["total"] == before
    assert any(c["id"] == top["id"] and c["status"] == "approved" for c in after["items"])

    # Dashboard reflete o estado
    d = client.get("/api/dashboard").json()
    assert d["stats"]["clips_approved"] == 1 and d["stats"]["clips_exported"] == 1
    assert d["stats"]["videos_analyzed"] == 1
    assert any(a["kind"] == "export" for a in d["activity"])

    # Streaming da fonte suporta Range (seek no editor)
    r = client.get(f"/api/videos/{video_id}/stream", headers={"Range": "bytes=0-1023"})
    assert r.status_code == 206 and len(r.content) == 1024



def test_failed_ai_batch_keeps_clips_from_other_batches(client, test_video, monkeypatch):
    """Se um lote da IA falha (rede, recusa), os cortes que os outros lotes acharam não são descartados."""
    from app.config import get_settings
    from app.services.ai_analysis import AIError

    r = client.post("/api/creators", json={"name": "Criador Lotes", "media_authorized": True})
    creator_id = r.json()["id"]
    with open(test_video, "rb") as f:
        r = client.post("/api/videos/upload",
                        data={"creator_id": creator_id, "rights_basis": "own", "confirm_rights": "true", "title": "Live lotes"},
                        files={"file": ("lotes.mp4", f, "video/mp4")})
    video_id = r.json()["video"]["id"]

    def flaky(content):
        text = "\n".join(b["text"] for b in content if b["type"] == "text")
        if "=== Candidato 0 ===" in text:
            raise AIError("Falha de conexão com a API Anthropic (ReadError).")
        return fake_claude(content)

    monkeypatch.setattr(get_settings(), "ai_max_candidates_per_request", 1)  # um candidato por lote
    monkeypatch.setattr(ai_analysis, "_call_claude", flaky)
    _drain()
    v = client.get(f"/api/videos/{video_id}").json()
    assert v["analysis_status"] == "done", v["analysis_error"]
    assert v["analysis_meta"]["ai_failed_batches"] == 1
    assert client.get("/api/clips", params={"creator_id": creator_id}).json()["total"] >= 1
    d = client.get("/api/dashboard").json()
    assert any("lotes" in a["message"] and a["level"] == "warning" for a in d["activity"])

    # Todos os lotes falhando: a análise falha com o motivo real (e tenta de novo depois)
    def down(content):
        raise AIError("Falha de conexão com a API Anthropic (ConnectError).")

    monkeypatch.setattr(ai_analysis, "_call_claude", down)
    assert client.post(f"/api/videos/{video_id}/analyze").status_code == 200
    worker.run_one("test-worker")
    v = client.get(f"/api/videos/{video_id}").json()
    assert v["analysis_status"] == "queued" and "ConnectError" in v["analysis_error"]

def test_automation_validation(client):
    r = client.put("/api/automation", json={"min_clip_seconds": 70, "max_clip_seconds": 60})
    assert r.status_code == 422
    r = client.put("/api/automation", json={"approval_mode": "automatic", "max_clips_per_day": 5})
    assert r.status_code == 200 and r.json()["approval_mode"] == "automatic"
    client.put("/api/automation", json={"approval_mode": "manual"})


def test_platform_urls_are_not_downloaded(client):
    cid = client.post("/api/creators", json={"name": "Outro", "media_authorized": True}).json()["id"]
    r = client.post("/api/videos/from-url", json={"creator_id": cid, "url": "https://www.youtube.com/watch?v=abc",
                                                  "rights_basis": "authorized", "confirm_rights": True})
    assert r.status_code == 201
    _drain()
    v = client.get(f"/api/videos/{r.json()['video']['id']}").json()
    assert v["media_status"] == "failed" and "não é permitido" in v["media_error"]


def test_monitor_without_keys_fails_clearly(client):
    cid = client.post("/api/creators", json={"name": "Canal", "youtube_handle": "@algum"}).json()["id"]
    job = client.post(f"/api/creators/{cid}/check").json()
    _drain()
    j = next(x for x in client.get("/api/jobs").json() if x["id"] == job["id"])
    assert j["status"] == "failed" and "YOUTUBE_API_KEY" in j["error"]


def test_orphaned_progress_is_unstuck(client):
    from app.models import Creator, SourceVideo
    from app.worker.handlers import reconcile_orphans

    with SessionLocal() as db:
        c = Creator(name="Órfão")
        db.add(c)
        db.flush()
        v = SourceVideo(creator_id=c.id, platform="upload", external_id="orfao", title="x",
                        media_status="ready", analysis_status="running")
        db.add(v)
        db.commit()
        assert reconcile_orphans(db) >= 1
        db.refresh(v)
        assert v.analysis_status == "failed" and "Reanalisar" in v.analysis_error
