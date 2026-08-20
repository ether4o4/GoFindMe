#!/data/data/com.termux/files/usr/bin/bash
# GoFindMe — Termux launcher (mobile).
#
# First run installs the small Python server stack. It also exposes a dead-simple
# `gofindme TARGET` command through $PREFIX/bin, so the common workflow is one line.
set -e

REPO_URL="${GOFINDME_REPO:-https://github.com/ether4o4/GoFindMe}"
PORT="${GOFINDME_PORT:-8000}"

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

echo "==> Checking for updates..."
git pull --ff-only 2>/dev/null && echo "    up to date." || echo "    (skipped — offline or local changes)"

# Make the one-command launcher available everywhere in Termux.
if [ -f "$REPO_DIR/scripts/gofindme" ]; then
  chmod +x "$REPO_DIR/scripts/gofindme" 2>/dev/null || true
  if [ -d "${PREFIX:-}/bin" ] && [ -w "${PREFIX:-}/bin" ]; then
    ln -sf "$REPO_DIR/scripts/gofindme" "$PREFIX/bin/gofindme"
  fi
fi

if ! python -c "import fastapi, uvicorn, httpx, pydantic, passlib, cryptography" >/dev/null 2>&1; then
  echo "==> Installing dependencies (first run only, ~1-2 min)..."
  pkg install -y python git python-cryptography curl
  pip install --quiet fastapi "uvicorn" httpx "pydantic<2" python-multipart passlib
fi

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
