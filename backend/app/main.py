"""API HTTP. Não faz processamento pesado: tudo vai para a fila (worker)."""
from __future__ import annotations

import base64
import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import clips, creators, operations, videos
from .config import get_settings
from .db import init_db
from .logging_setup import setup_logging

setup_logging("api")
log = logging.getLogger("clipes.api")
settings = get_settings()
init_db()

app = FastAPI(title="Clipes GTA 6", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Senha única para o painel inteiro (navegador pede usuário e senha)."""
    if settings.app_password and request.url.path != "/api/health":
        ok = False
        header = request.headers.get("authorization", "")
        if header.lower().startswith("basic "):
            try:
                user, _, pwd = base64.b64decode(header[6:]).decode("utf-8").partition(":")
                ok = secrets.compare_digest(user, settings.app_user) and secrets.compare_digest(pwd, settings.app_password)
            except Exception:  # noqa: BLE001
                ok = False
        if not ok:
            return JSONResponse(status_code=401, content={"detail": "Acesso restrito."},
                                headers={"WWW-Authenticate": 'Basic realm="Clipes", charset="UTF-8"'})
    return await call_next(request)


for r in (creators.router, videos.router, clips.router, operations.router):
    app.include_router(r)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Erro não tratado em %s %s", request.method, request.url.path)
    msg = str(exc).strip().splitlines()[0][:200] if str(exc).strip() else ""
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        msg = "Sem espaço em disco no servidor. Aumente o volume no Railway ou apague vídeos antigos."
    return JSONResponse(status_code=500, content={"detail": f"Erro interno ({type(exc).__name__}): {msg}" if msg
                                                  else f"Erro interno ({type(exc).__name__})."})


@app.get("/api/health")
def health():
    return {"ok": True}


# Frontend compilado (produção): serve o SPA na mesma origem da API
dist = settings.frontend_dist
if (dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Rota não encontrada."})
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
