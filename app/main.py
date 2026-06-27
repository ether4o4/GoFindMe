"""FastAPI application factory.

Serves the JSON API and the static dashboard from the same origin (no CORS).
On startup it applies the schema and launches the job-queue workers; on shutdown
it stops them.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__, db, jobs, security
from .config import resource_base, settings
from .vault import vault
from . import (routes_auth, routes_data, routes_jobs, routes_orchestrate,
               routes_providers, routes_reports, routes_tools, routes_vault)

ROOT = resource_base()
STATIC = ROOT / "static"
LEGACY = ROOT / "legacy"

_STRICT_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)
# The preserved legacy single-file app uses inline script/style; relax CSP there only.
_LEGACY_CSP = "default-src 'self' 'unsafe-inline' data:; frame-ancestors 'none'"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    await jobs.start_queue()
    try:
        yield
    finally:
        await jobs.stop_queue()


app = FastAPI(title="GoFindMe", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    is_legacy = request.url.path.startswith("/legacy")
    response.headers["Content-Security-Policy"] = _LEGACY_CSP if is_legacy else _STRICT_CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response


for r in (routes_auth, routes_vault, routes_providers, routes_tools, routes_jobs,
          routes_orchestrate, routes_data, routes_reports):
    app.include_router(r.router)


@app.get("/api/health", tags=["health"])
async def health() -> dict:
    return {
        "ok": True,
        "version": __version__,
        "setup_complete": security.setup_complete(),
        "vault_mode": "plaintext" if settings().vault_plaintext else "encrypted",
        "vault_unlocked": vault.unlocked,
    }


@app.get("/", include_in_schema=False)
async def index() -> Response:
    idx = STATIC / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return Response("GoFindMe frontend not built", status_code=404)


# Static assets (css/js) and the preserved legacy launcher.
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
if LEGACY.exists():
    app.mount("/legacy", StaticFiles(directory=LEGACY, html=True), name="legacy")
