"""Ambiente isolado para testes: banco e armazenamento temporários, sem chaves reais."""
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="clipes-test-"))
# TEST_DATABASE_URL permite rodar a suíte contra Postgres (banco vazio)
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_TMP / 'test.db'}"
os.environ["STORAGE_DIR"] = str(_TMP / "storage")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["YOUTUBE_API_KEY"] = ""
os.environ["TWITCH_CLIENT_ID"] = ""
os.environ["TWITCH_CLIENT_SECRET"] = ""
os.environ["TRANSCRIPTION_PROVIDER"] = "none"
os.environ["FRONTEND_DIST"] = str(_TMP / "no-dist")


def make_test_video(path: Path, duration: int = 150) -> Path:
    """Vídeo 1920x1080 com 3 'cenas' diferentes e áudio baixo com dois picos fortes (40s e 100s)."""
    seg = duration // 3
    vf = (
        f"testsrc2=size=1920x1080:rate=30:duration={seg}[a];"
        f"rgbtestsrc=size=1920x1080:rate=30:duration={seg}[b];"
        f"smptebars=size=1920x1080:rate=30:duration={duration - 2 * seg}[c];"
        "[a][b][c]concat=n=3:v=1:a=0,format=yuv420p[v]"
    )
    af = (
        f"anoisesrc=d={duration}:c=pink:a=0.02:r=44100[n];"
        f"sine=frequency=440:duration={duration}:sample_rate=44100,"
        "volume='if(between(t,40,44)+between(t,100,103),6,0.01)':eval=frame[s];"
        "[n][s]amix=inputs=2:normalize=0[aout]"
    )
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-filter_complex", vf + ";" + af, "-map", "[v]", "-map", "[aout]",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-c:a", "aac", "-shortest", str(path)],
                   check=True)
    return path


@pytest.fixture(scope="session")
def test_video() -> Path:
    return make_test_video(_TMP / "fixture.mp4")
