#!/usr/bin/env bash
# GoFindMe — VPS installer (Debian/Ubuntu). Sets up the server + common OSINT
# tools, runs it as a systemd service bound to localhost, then prints how to
# reach it from your phone. The VPS runs the tools; your phone is just the screen.
#
# Usage on the VPS:
#   sudo apt-get install -y git
#   git clone https://github.com/ether4o4/GoFindMe && cd GoFindMe
#   sudo bash scripts/install-vps.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_USER="${SUDO_USER:-$(id -un)}"
PORT="${GOFINDME_PORT:-8000}"

echo "==> Installing system packages..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git pipx whois \
  libimage-exiftool-perl curl

echo "==> Creating Python environment and installing GoFindMe..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip >/dev/null
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Installing common OSINT tools (pipx, system-wide)..."
export PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin
sudo mkdir -p /opt/pipx
for t in sherlock-project maigret holehe h8mail theHarvester waymore; do
  sudo env PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install "$t" \
    || echo "   ($t skipped — install later from the Tools tab)"
done

if command -v go >/dev/null 2>&1; then
  echo "==> Installing Go-based tools..."
  for m in \
    github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest \
    github.com/tomnomnom/assetfinder@latest \
    github.com/lc/gau/v2/cmd/gau@latest \
    github.com/tomnomnom/waybackurls@latest \
    github.com/projectdiscovery/katana/cmd/katana@latest \
    github.com/hakluke/hakrawler@latest; do
    sudo env GOBIN=/usr/local/bin go install "$m" || echo "   ($m skipped)"
  done
else
  echo "==> Go not found — skipping Go tools. To add subfinder/gau/katana later:"
  echo "    sudo apt-get install -y golang-go && re-run this script."
fi

echo "==> Creating systemd service (bound to 127.0.0.1:$PORT — not exposed raw)..."
sudo tee /etc/systemd/system/gofindme.service >/dev/null <<EOF
[Unit]
Description=GoFindMe OSINT console
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
Environment=GOFINDME_BIND=127.0.0.1
Environment=GOFINDME_PORT=$PORT
ExecStart=$APP_DIR/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port $PORT --log-level warning
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now gofindme

cat <<EOF

============================================================
 GoFindMe is running on the VPS at 127.0.0.1:$PORT
 (service: 'sudo systemctl status gofindme' / 'journalctl -u gofindme -f')

 It is NOT publicly exposed yet. Reach it from your phone with ONE of:

 1) Tailscale  (recommended — private, HTTPS, no open ports, no domain)
      curl -fsSL https://tailscale.com/install.sh | sh
      sudo tailscale up
      sudo tailscale serve --bg $PORT
    Then install the Tailscale app on your phone (same account) and open the
    https://<machine>.<tailnet>.ts.net URL it prints.

 2) Public domain via Caddy (auto-HTTPS)
      sudo apt-get install -y caddy
      sudo caddy reverse-proxy --from your.domain.com --to 127.0.0.1:$PORT

 3) Quick test from a PC (SSH tunnel, no exposure)
      ssh -L $PORT:127.0.0.1:$PORT user@your-vps   # then open http://127.0.0.1:$PORT

 First visit: create your owner account, then add API keys in the Vault.
 Do NOT bind 0.0.0.0 to the public internet without TLS — use option 1 or 2.
============================================================
EOF
