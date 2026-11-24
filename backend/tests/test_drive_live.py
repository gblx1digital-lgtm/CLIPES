"""Pasta do Google Drive e aviso de live, com as APIs externas substituídas por versões locais."""
import functools
import http.server
import threading

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.sources import drive, twitch, youtube
from app.services.sources.base import DiscoveredVideo
from app.worker import main as worker


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture()
def file_server(test_video):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(test_video.parent))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/{test_video.name}"
    srv.shutdown()


def _drain(n=10):
    while n and worker.run_one("t"):
        n -= 1


def test_parse_folder_id():
    assert drive.parse_folder_id("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp?usp=sharing") == "1AbCdEfGhIjKlMnOp"
    assert drive.parse_folder_id("https://drive.google.com/open?id=1AbCdEfGhIjKlMnOp") == "1AbCdEfGhIjKlMnOp"
    assert drive.parse_folder_id("") is None
    with pytest.raises(ValueError):
        drive.parse_folder_id("https://example.com/qualquer")


def test_drive_folder_imports_and_live_alert(client, monkeypatch, file_server):
    s = get_settings()
    monkeypatch.setattr(s, "google_api_key", "chave-teste")
    monkeypatch.setattr(s, "youtube_api_key", "chave-teste")
    monkeypatch.setattr(drive, "list_videos", lambda folder: [
        {"id": "arquivo1", "name": "live dia 1.mp4", "size": 1, "created_at": None, "duration_s": None}])
    monkeypatch.setattr(drive, "download_url", lambda fid: file_server)
    monkeypatch.setattr(youtube, "resolve_channel", lambda h: {"channel_id": "UCteste"})
    live_state = {"on": True}

    def fake_recent(channel_id):
        vids = [DiscoveredVideo("youtube", "vod1", "GTA 6 dia 1", "https://youtube.com/watch?v=vod1", None, 3600, None)]
        if live_state["on"]:
            vids.append(DiscoveredVideo("youtube", "live1", "AO VIVO GTA 6", "https://youtube.com/watch?v=live1",
                                        None, None, None, live_now=True))
        return vids
    monkeypatch.setattr(youtube, "list_recent", fake_recent)

    # sem autorização a pasta não é importada
    r = client.post("/api/creators", json={"name": "Drive Criador", "youtube_handle": "@canal",
                                           "drive_folder": "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["drive_folder_id"] == "1AbCdEfGhIjKlMnOp"
    client.post(f"/api/creators/{cid}/check")
    _drain(1)
    c = next(x for x in client.get("/api/creators").json() if x["id"] == cid)
    assert "autorizado" in c["last_check_error"]
    assert c["live_now"] is True and c["live_title"] == "AO VIVO GTA 6"

    # autorizado: arquivo vira vídeo, é baixado e fica pronto; a live em andamento não vira vídeo
    client.patch(f"/api/creators/{cid}", json={"media_authorized": True})
    client.put("/api/automation", json={"auto_analyze": False})
    client.post(f"/api/creators/{cid}/check")
    _drain()
    videos = [v for v in client.get(f"/api/videos?creator_id={cid}").json()]
    by_id = {v["external_id"]: v for v in videos}
    assert "live1" not in by_id and "vod1" in by_id
    dv = by_id["arquivo1"]
    assert dv["platform"] == "drive" and dv["rights_basis"] == "authorized"
    assert dv["media_status"] == "ready", dv["media_error"]
    assert dv["width"] == 1920

    # a chave nunca é gravada no payload dos jobs
    assert all("chave-teste" not in str(j["payload"]) for j in client.get("/api/jobs").json())

    # a live acabou: estado volta e a atividade registra
    live_state["on"] = False
    client.post(f"/api/creators/{cid}/check")
    _drain()
    c = next(x for x in client.get("/api/creators").json() if x["id"] == cid)
    assert c["live_now"] is False
    msgs = [a["message"] for a in client.get("/api/activity").json()]
    assert any("está AO VIVO" in m for m in msgs) and any("encerrou a live" in m for m in msgs)
    client.put("/api/automation", json={"auto_analyze": True})


def test_missing_columns_are_added(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    import app.db as dbmod
    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE creators (id INTEGER PRIMARY KEY, name VARCHAR(120))"))
    old = dbmod.engine
    dbmod.engine = eng
    try:
        dbmod._add_missing_columns()
    finally:
        dbmod.engine = old
    cols = {c["name"] for c in inspect(eng).get_columns("creators")}
    assert {"drive_folder_id", "live_now", "media_authorized"} <= cols
