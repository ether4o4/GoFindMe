"""Desktop launcher for the packaged GoFindMe executable.

Stores data in a per-user directory, starts the server on 127.0.0.1, and opens
the default browser. Closing the console window stops the server.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    d = base / "GoFindMe"
    d.mkdir(parents=True, exist_ok=True)
    return d


def main() -> None:
    data = _data_dir()
    os.environ.setdefault("GOFINDME_DB", str(data / "gofindme.db"))
    os.environ.setdefault("GOFINDME_UPLOADS_DIR", str(data / "uploads"))
    os.environ.setdefault("GOFINDME_BIND", "127.0.0.1")
    # A frozen build has no bundled Python/pip, so in-app tool install can't work
    # (sys.executable is the app itself). Disable it; installed tools on PATH still run.
    os.environ.setdefault("GOFINDME_ALLOW_TOOL_MGMT", "0")
    port = int(os.environ.get("GOFINDME_PORT", "8000"))

    # Imported after env is set so app.config picks up the data paths.
    import uvicorn
    from app.main import app

    url = f"http://127.0.0.1:{port}/"

    def _open() -> None:
        time.sleep(1.5)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_open, daemon=True).start()

    print("=" * 56)
    print(f"  GoFindMe is running at {url}")
    print(f"  Data is stored in: {data}")
    print("  Keep this window open. Close it to stop GoFindMe.")
    print("=" * 56)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
