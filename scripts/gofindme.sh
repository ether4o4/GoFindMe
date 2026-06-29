#!/usr/bin/env bash
# GoFindMe — self-updating launcher for macOS / Linux.
#
# Run from a cloned repo:
#   git clone https://github.com/ether4o4/GoFindMe && cd GoFindMe
#   ./scripts/gofindme.sh
# Every run it pulls the latest code, ensures deps in a local venv, then starts
# the server and opens the dashboard.
set -e
cd "$(dirname "$0")/.."

PORT="${GOFINDME_PORT:-8000}"

if [ -d .git ]; then
  echo "==> Checking for updates..."
  git pull --ff-only 2>/dev/null && echo "    up to date." || echo "    (skipped)"
fi

if [ ! -d .venv ]; then
  echo "==> Creating virtual environment..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
echo "==> Ensuring dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

URL="http://127.0.0.1:${PORT}/"
(
  for _ in $(seq 1 40); do
    curl -fsS "${URL}api/health" >/dev/null 2>&1 && break
    sleep 0.5
  done
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  elif command -v open >/dev/null 2>&1; then open "$URL"
  else echo "Open $URL"; fi
) >/dev/null 2>&1 &

echo "==> GoFindMe running at $URL   (press Ctrl+C to stop)"
exec python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning
