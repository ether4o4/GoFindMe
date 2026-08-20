"""Android entry point for the embedded GoFindMe server.

The native Activity calls :func:`start` with Android's private files directory.
The server is intentionally loopback-only and is started at most once per
Python runtime. A small crash log is retained in the same private directory so
startup failures can be diagnosed without exposing anything over the network.
"""
from __future__ import annotations

import os
import threading
import traceback

_STARTED = False
_LOCK = threading.Lock()


def start(data_dir: str) -> None:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True

    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, "uploads"), exist_ok=True)
    os.environ.setdefault("GOFINDME_DB", os.path.join(data_dir, "gofindme.db"))
    os.environ.setdefault("GOFINDME_UPLOADS_DIR", os.path.join(data_dir, "uploads"))
    os.environ.setdefault("GOFINDME_BIND", "127.0.0.1")
    os.environ.setdefault("GOFINDME_VAULT_MODE", "encrypted")
    os.environ.setdefault("GOFINDME_ALLOW_TOOL_MGMT", "0")
    os.environ.setdefault("GOFINDME_LOG_LEVEL", "warning")
    os.environ.setdefault("GOFINDME_AUDIT_ENABLED", "1")
    os.environ["GOFINDME_ANDROID_LOG"] = os.path.join(data_dir, "server-error.log")

    threading.Thread(target=_serve, name="gofindme-server", daemon=True).start()


def _serve() -> None:
    import asyncio

    try:
        import uvicorn
        from app.main import app

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=8000,
            log_level="warning",
            loop="asyncio",
            lifespan="on",
        )
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())
    except Exception:
        path = os.environ.get("GOFINDME_ANDROID_LOG")
        if path:
            try:
                with open(path, "a", encoding="utf-8") as fh:
                    traceback.print_exc(file=fh)
            except Exception:
                pass
        raise
