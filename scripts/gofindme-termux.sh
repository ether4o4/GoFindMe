#!/data/data/com.termux/files/usr/bin/bash
# GoFindMe — Termux launcher (mobile).
#
# Every run: ensures dependencies, pulls the latest code, then starts the server
# and opens the dashboard. Fast on subsequent runs (only installs when needed).
#
# One-time setup (paste into Termux):
#   pkg install -y git
#   git clone https://github.com/ether4o4/GoFindMe ~/GoFindMe
#   bash ~/GoFindMe/scripts/gofindme-termux.sh
# Then to auto-launch whenever you open Termux, add this line to ~/.bashrc:
#   bash ~/GoFindMe/scripts/gofindme-termux.sh
set -e

REPO_URL="${GOFINDME_REPO:-https://github.com/ether4o4/GoFindMe}"
PORT="${GOFINDME_PORT:-8000}"

# --- locate (or clone) the repo ---
if [ -f "app/main.py" ] && [ -d ".git" ]; then
  REPO_DIR="$(pwd)"
elif [ -d "$HOME/GoFindMe/.git" ]; then
  REPO_DIR="$HOME/GoFindMe"
else
  echo "==> First run: cloning GoFindMe..."
  command -v git >/dev/null 2>&1 || pkg install -y git
  git clone --depth 1 "$REPO_URL" "$HOME/GoFindMe"
  REPO_DIR="$HOME/GoFindMe"
fi
cd "$REPO_DIR"

# --- check for updates ---
echo "==> Checking for updates..."
git pull --ff-only 2>/dev/null && echo "    up to date." || echo "    (skipped — offline or local changes)"

# --- ensure dependencies (only when something is missing) ---
# Termux-friendly set: cryptography from the system package, pydantic v1 so no
# Rust build is needed; everything else is pure Python.
if ! python -c "import fastapi, uvicorn, httpx, pydantic, passlib, cryptography" >/dev/null 2>&1; then
  echo "==> Installing dependencies (first run only, ~1-2 min)..."
  pkg install -y python git python-cryptography
  pip install --quiet fastapi "uvicorn" httpx "pydantic<2" python-multipart passlib
fi

# --- open the dashboard once the server is up, then run it ---
URL="http://127.0.0.1:${PORT}/"
(
  for _ in $(seq 1 40); do
    if curl -fsS "${URL}api/health" >/dev/null 2>&1; then break; fi
    sleep 0.5
  done
  if command -v termux-open-url >/dev/null 2>&1; then termux-open-url "$URL"
  else echo "Open $URL in your browser."; fi
) &

echo "==> GoFindMe running at $URL   (press Ctrl+C to stop)"
exec python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning
