# GoFindMe — Deployment & Administration Guide

**Product:** GoFindMe — self-hosted OSINT / digital-footprint & DFIR investigation console
**Version:** 1.0.0
**Audience:** system administrators, security engineers, and IT procurement reviewers deploying GoFindMe on government or enterprise infrastructure.

GoFindMe is a single-tenant (one owner account) FastAPI application. It runs allowlisted reconnaissance CLI tools as argv lists (never through a shell), queries third-party OSINT provider APIs **server-side**, and stores all findings plus a personal-footprint dataset in one SQLite database. Every device that reaches the server shares that one database, so multi-device access requires no synchronization layer.

> **Authorized-use notice.** GoFindMe executes reconnaissance tooling and queries external services on the operator's behalf. Deploy and operate it only for investigations you are legally authorized to conduct, and observe each upstream provider's terms of service.

---

## Table of contents

1. [Deployment models](#1-deployment-models)
2. [System requirements & prerequisites](#2-system-requirements--prerequisites)
3. [Server install (VPS / on-prem)](#3-server-install-vps--on-prem)
4. [Configuration reference (all environment variables)](#4-configuration-reference)
5. [First run & administration](#5-first-run--administration)
6. [Data management (storage, backup, restore, export)](#6-data-management)
7. [Updating](#7-updating)
8. [Hardening checklist for production](#8-hardening-checklist-for-production)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Deployment models

GoFindMe ships the same backend (`app/`) in four delivery form-factors. Pick by team size, who runs the recon tools, and network sensitivity.

| Model | Who it's for | Runs CLI tools? | Data location | Reach |
|-------|--------------|-----------------|---------------|-------|
| **(a) One-click desktop app** | Single investigator, laptop-only | Yes, using the host's system Python/Go/Git | Per-user application-data dir (see §6) | `http://127.0.0.1:8000` (loopback only) |
| **(b) Shared on-prem server / VPS** | A team; multi-device access to one dataset | Yes, all tools installed on the server | `<install-dir>/data/gofindme.db` | Private tunnel or TLS reverse proxy |
| **(c) On-phone (Termux)** | Mobile investigator wanting tools on the handset | Yes (Termux package set) | `~/GoFindMe/data/gofindme.db` on the phone | `http://127.0.0.1:8000` on the device |
| **(c) On-phone (Android APK)** | Mobile, zero-setup, data layer + providers only | **No** — tool management is disabled | App private sandbox storage | In-app WebView (`127.0.0.1:8000`) |
| **(d) Air-gapped / classified** | No outbound provider calls permitted; tools-only | Yes | As per model (b) or (a) | Internal only |

### (a) One-click desktop app (single investigator)

A packaged, self-contained executable (built by `desktop/GoFindMe.spec`, published to the rolling `desktop-latest` GitHub release). No Python install is required on the target machine. On launch (`desktop/launcher.py`) it:

- Stores data in a **per-user** directory (see §6) rather than the working directory.
- Forces `GOFINDME_BIND=127.0.0.1` (loopback only — never network-exposed).
- Opens the default browser at `http://127.0.0.1:8000/`.
- **Leaves tool management enabled**: install/update runs against the host's *system* Python/Go (not the frozen runtime inside the executable), and installed tools are detected from `PATH` plus the Go and Python script directories.

Use when: one analyst, one workstation, no requirement to share the dataset. Closing the console window stops the server.

### (b) Shared on-prem server / VPS (team, one shared DB)

The recommended model for a team. A single always-on Linux host installs and runs **all** CLI tools; analysts open the dashboard from any browser/phone on the private network. Because there is one server-side SQLite database, every device sees the same cases, findings, and footprint data with no manual sync. Install with `scripts/install-vps.sh` (see §3).

Use when: multiple investigators, shared case data, heavy CLI tooling that benefits from a full Linux box.

### (c) On-phone (Termux vs. APK)

- **Termux launcher** (`scripts/gofindme-termux.sh`): runs the **full** app *with* tool support on the phone. It uses the Termux `python-cryptography` system package and pins **pydantic v1** so nothing needs a Rust toolchain. Data lives in the cloned repo under `~/GoFindMe/data/`.
- **Android APK** (Chaquopy, `android/`): a self-contained app bundling a Python runtime and running the server inside a WebView. On a phone there are **no external CLI tools**, so the APK runs the **providers, encrypted vault, and personal-footprint data layer only**; tool install/update is disabled (`GOFINDME_ALLOW_TOOL_MGMT=0`). Password hashing falls back to `pbkdf2_sha256` (no argon2 backend on Android).

Use Termux when you want the tool-runner on the handset; use the APK for a no-setup data/provider console. For serious CLI workloads, prefer model (b) and point the phone's browser at the server.

### (d) Air-gapped / classified-network considerations

GoFindMe is designed to degrade cleanly to **tools-only** operation with no outbound calls:

- **Outbound is limited to a hardcoded provider host allowlist.** Provider destination hosts are compiled into `app/providers.py`; the target you submit only ever lands in a path/query parameter (URL-encoded by `httpx`), never the host — an SSRF guard that also refuses private/reserved IP destinations.
- **No provider is contacted unless it is selected.** During a "Search All", a provider is only run if it is *keyless* or has a key configured in the vault. If you configure **no** API keys, the only providers that could attempt egress are the keyless ones (`crtsh`, `greynoise`, `emailrep`, and `leakcheck` via its public endpoint). The keyless `pivots` source makes **no** outbound request of its own — it only builds "open in browser" links — so it is safe even air-gapped. On an isolated network the egress requests simply fail and are recorded as errors; all CLI tools continue to run fully offline against local binaries.
- **To guarantee zero external calls,** run the CLI tools only (do not invoke provider lookups), keep the vault empty of keys, and rely on the network boundary. There is no code path that phones home outside the provider host allowlist.
- **Proxy / inspection support:** all outbound HTTP honors `HTTPS_PROXY` and a custom CA via `GOFINDME_CA_BUNDLE` / `SSL_CERT_FILE` (see §4), so a controlled egress proxy or internal CA can be enforced where limited outbound is permitted.
- Deploy as model (a) or (b), bound to loopback or a private interface only, with tool management left on so analysts can install approved tools from an internal package mirror.

---

## 2. System requirements & prerequisites

### Core runtime

| Requirement | Detail |
|-------------|--------|
| **Python** | 3.11 or newer (`requires-python >= 3.11`; release builds use 3.11). Not needed for the packaged desktop `.exe`/binary or the Android APK. |
| **OS** | Linux (recommended for servers), macOS, Windows. Android via Termux/APK. |
| **Python dependencies** | `fastapi`, `uvicorn[standard]`, `httpx`, `cryptography`, `pydantic` (v2 on servers/desktop; v1 on Termux/Android), `python-multipart`, `passlib[argon2]` — see `requirements.txt`. |
| **Disk** | Small base footprint; grows with findings/output. Per-job stdout is capped (default 5 MiB, see `GOFINDME_OUTPUT_CAP`) to bound DB/memory growth. |
| **No external services** | No Redis, Celery, or separate database — the job queue is in-process `asyncio` and storage is a single SQLite file in WAL mode. |

### Optional toolchains (only for installing OSINT tools)

The OSINT tools are **not** bundled. GoFindMe detects what is present and runs only installed tools. To install tools from the dashboard (or manually), the relevant toolchain must be on `PATH`:

| Toolchain | Enables install of | Notes |
|-----------|--------------------|-------|
| **Python + pip** | `sherlock`, `maigret`, `holehe`, `h8mail`, `theHarvester`, `waymore`, `ghunt`, `bbot`, `shodan-cli`, `mat2`, … | Uses the system Python's `pip`. |
| **pipx** | Same Python tools, isolated per-tool | Preferred for CLI tools on a shared server (used by `install-vps.sh`). |
| **Go** | `subfinder`, `amass`, `assetfinder`, `gau`, `waybackurls`, `katana`, `hakrawler` | `go install`; binaries land in `GOBIN`/`$GOPATH/bin`. |
| **Git** | git-based tools (e.g. `blackbird`, `nexfil`) | Clones the repo and pip-installs its own `requirements.txt`. |
| **npm** | any npm-distributed custom tool | `npm install -g`. |

System packages the VPS installer also pulls in: `whois`, `libimage-exiftool-perl` (for `exiftool`), `curl`.

Building artifacts from source (maintainers only): the **desktop** build needs `pyinstaller`; the **Android** build needs JDK 17 + Android SDK/NDK and Gradle 8.7 (Chaquopy).

---

## 3. Server install (VPS / on-prem)

### 3.1 Automated install (Debian / Ubuntu)

`scripts/install-vps.sh` provisions the app, a Python venv, a common set of OSINT tools (via `pipx`, plus Go tools if Go is present), and a hardened `systemd` service bound to loopback.

```bash
sudo apt-get install -y git
git clone https://github.com/ether4o4/GoFindMe && cd GoFindMe
sudo bash scripts/install-vps.sh
```

What it does:

- Installs `python3`, `python3-venv`, `python3-pip`, `git`, `pipx`, `whois`, `libimage-exiftool-perl`, `curl`.
- Creates `.venv` and installs `requirements.txt`.
- Installs `sherlock-project`, `maigret`, `holehe`, `h8mail`, `theHarvester`, `waymore` via `pipx` into `/opt/pipx` with binaries in `/usr/local/bin`.
- If `go` is present, installs `subfinder`, `assetfinder`, `gau`, `waybackurls`, `katana`, `hakrawler` into `/usr/local/bin`.
- Writes and enables the `gofindme` systemd service, **bound to `127.0.0.1`**, running as the invoking (`sudo`) user.

Service management:

```bash
sudo systemctl status gofindme
sudo systemctl restart gofindme
journalctl -u gofindme -f          # live logs
```

### 3.2 The systemd unit

The installer writes `/etc/systemd/system/gofindme.service`. Reference (values interpolated at install time):

```ini
[Unit]
Description=GoFindMe OSINT console
After=network.target

[Service]
Type=simple
User=<invoking-user>
WorkingDirectory=<install-dir>
Environment=GOFINDME_BIND=127.0.0.1
Environment=GOFINDME_PORT=8000
ExecStart=<install-dir>/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

`WorkingDirectory` is the install directory, so the default database resolves to `<install-dir>/data/gofindme.db`. To pin data elsewhere or add settings, append more `Environment=` lines (e.g. `Environment=GOFINDME_DB=/var/lib/gofindme/gofindme.db`) or an `EnvironmentFile=`, then `sudo systemctl daemon-reload && sudo systemctl restart gofindme`.

> **Do not** change `--host` to `0.0.0.0` in the unit unless the port is fronted by a TLS reverse proxy or confined to a private tunnel interface. The application's login and cookie security assume HTTPS when reached over a network.

### 3.3 Manual install (any Linux)

```bash
git clone https://github.com/ether4o4/GoFindMe && cd GoFindMe
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # edit as needed (see §4)
./run.sh                    # serves http://127.0.0.1:8000 by default
```

`run.sh` sources a local `.env` if present, prints the bind/port and vault mode, warns loudly if you bind `0.0.0.0`, then `exec`s `uvicorn app.main:app`.

### 3.4 Reaching the server securely

Never expose the raw port to the public internet. Choose one:

**Option 1 — Tailscale serve (recommended: private HTTPS, no open ports, no domain)**

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale serve --bg 8000
# Install Tailscale on the phone/laptop (same tailnet), then open the
# https://<machine>.<tailnet>.ts.net URL it prints.
```

**Option 2 — Caddy (public domain, automatic HTTPS)**

```bash
sudo apt-get install -y caddy
sudo caddy reverse-proxy --from your.domain.example --to 127.0.0.1:8000
```

Or a `Caddyfile`:

```
your.domain.example {
    reverse_proxy 127.0.0.1:8000
}
```

**Option 3 — nginx + TLS (terminate certs, proxy to loopback)**

```nginx
server {
    listen 443 ssl;
    server_name your.domain.example;

    ssl_certificate     /etc/letsencrypt/live/your.domain.example/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your.domain.example/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # Server-Sent Events: live tool/job output streams over a long-lived
        # connection — disable proxy buffering so output is not withheld.
        proxy_buffering    off;
        proxy_read_timeout 3600s;
    }
}
```

When fronted by a reverse proxy the app keeps binding to `127.0.0.1`; the proxy is the only network listener. (SSE streaming powers live job output — keep response buffering off and read timeouts generous on whichever proxy you choose.)

**Option 4 — SSH tunnel (quick test, no exposure)**

```bash
ssh -L 8000:127.0.0.1:8000 user@your-vps    # then open http://127.0.0.1:8000
```

**Option 5 — private tunnel + direct bind.** On Tailscale/WireGuard you may set `GOFINDME_BIND=0.0.0.0` so uvicorn listens on the tunnel interface and browse to `http://<machine>:8000` from another device on the tunnel. Only acceptable because the tunnel — not the public internet — is the exposed surface.

---

## 4. Configuration reference

All configuration is environment-driven (`app/config.py`). `run.sh` loads a local `.env`; systemd uses `Environment=`/`EnvironmentFile=`. Defaults are safe for a single-user box on loopback. Booleans accept `1`, `true`, `yes`, or `on` (case-insensitive); anything else is false.

| Variable | Default | Guidance |
|----------|---------|----------|
| `GOFINDME_BIND` | `127.0.0.1` | Listen address. Keep loopback for desktop/single-host. Set `0.0.0.0` **only** behind a private tunnel (Tailscale/WireGuard) or a TLS reverse proxy with auth. |
| `GOFINDME_PORT` | `8000` | TCP port for uvicorn. Change to avoid conflicts; update the reverse proxy / tunnel to match. |
| `GOFINDME_DB` | `./data/gofindme.db` | SQLite database path (resolved to an absolute path; parent dir auto-created). Point at a dedicated, backed-up, ideally encrypted volume in production. |
| `GOFINDME_UPLOADS_DIR` | `./data/uploads` | Directory for uploaded files (created on first run). |
| `GOFINDME_VAULT_MODE` | `encrypted` | `encrypted` (default) seals API keys with AES-256-GCM behind your passphrase. `plaintext` stores keys unencrypted on disk — only for throwaway/lab use. |
| `GOFINDME_VAULT_IDLE_MINUTES` | `30` | Minutes of inactivity before an unlocked vault auto-locks in memory. Lower it on shared/high-sensitivity hosts. |
| `GOFINDME_TOKEN_TTL_DAYS` | `7` | Lifetime of a login bearer token. Tokens live only in process memory, so a restart invalidates all sessions. Lower for stricter session policy. |
| `GOFINDME_MAX_CONCURRENCY` | `4` | Max tools/providers executing at once (floored at 1). Raise on a beefy server; lower to throttle load or rate-limited providers. |
| `GOFINDME_ALLOW_TOOL_MGMT` | `1` (enabled) | Allows install/update of OSINT tools from the dashboard (runs allowlisted package managers). Set `0` to disable in locked-down environments; only the authenticated owner can ever trigger it. |
| `GOFINDME_CA_BUNDLE` | *(unset)* | Path to a custom CA bundle for outbound provider HTTPS (e.g. an internal-inspection CA). Falls back to `SSL_CERT_FILE` if unset. |
| `GOFINDME_OUTPUT_CAP` | `5242880` (5 MiB) | Per-job stdout cap in bytes; bounds memory and DB growth. Raise only if truncated tool output is a problem. |

**Also honored from the standard environment** (via `httpx` `trust_env`, not GoFindMe-specific): `HTTPS_PROXY` routes all outbound provider calls through a proxy; `SSL_CERT_FILE` supplies a CA bundle (equivalent to `GOFINDME_CA_BUNDLE`). These are how you enforce egress control in constrained networks.

> The login password and the vault passphrase are **never** read from environment variables or files — they are set interactively at runtime (see §5). `.env` contains nothing secret by default.

To inspect the effective configuration of a running instance, query the unauthenticated health endpoint — useful for confirming the actual DB path on any platform:

```bash
curl -s http://127.0.0.1:8000/api/health
# {"ok":true,"version":"1.0.0","setup_complete":...,"vault_mode":"encrypted",
#  "vault_unlocked":...,"db_path":"...","data_dir":"...","packaged":...,"tool_mgmt":...}
```

---

## 5. First run & administration

### 5.1 Create the owner account (one-time)

GoFindMe is single-tenant: exactly one owner account (`id=1`). On first visit the dashboard prompts you to create it.

- Choose a strong username and password. **Minimum password length is 8 characters** (enforced server-side).
- The password is hashed with **Argon2id** (or `pbkdf2_sha256` where the argon2 backend is unavailable, e.g. Android). The plaintext is never stored.
- Setup is a one-time operation; the create-account endpoint returns `409 Conflict` once an owner exists. There is no built-in self-service reset — see §9.
- Every `/api/*` route is authenticated. Login yields an opaque bearer token (valid `GOFINDME_TOKEN_TTL_DAYS` days) held only in server memory. Login attempts are rate-limited (8 failures per 5-minute window → `429`).

### 5.2 Set the vault passphrase

If `GOFINDME_VAULT_MODE=encrypted` (the default), unlock the vault from the dashboard and set a passphrase on first use:

- The **first unlock establishes** the passphrase (stored only as an encrypted check-blob to validate future unlocks). It is **never stored in plaintext**.
- Keys are AES-256-GCM encrypted; the key is derived with PBKDF2-HMAC-SHA256 (200,000 iterations). The passphrase is held in memory only while unlocked and drops on idle auto-lock (`GOFINDME_VAULT_IDLE_MINUTES`) or on restart.
- **There is no passphrase recovery.** A lost passphrase means the encrypted API keys are unrecoverable (re-enter them under a new passphrase after clearing the vault). Record it in your organization's secrets manager.

### 5.3 Add API keys (providers)

In the dashboard's vault/providers area, add keys for the providers you use. Supported providers: `crtsh` (keyless), `emailrep` (keyless), `greynoise` (keyless/community), `shodan`, `censys`, `virustotal`, `hibp`, `hunter`, `abuseipdb`, `securitytrails`, `ipinfo`, `leakcheck`, `intelx`, `dehashed`. A one-click **Test connection** validates each key. Some providers (e.g. Censys, DeHashed) take a two-part `id:secret` value. Keys are encrypted immediately and are never placed in a subprocess environment or written to logs; the audit log records that a provider was called, never the key.

### 5.4 Install tools

With `GOFINDME_ALLOW_TOOL_MGMT=1`, use the **Tools** tab to check versions and install/update tools; output streams live like any job. The dashboard reports which package managers are available on the host (`pip`, `pipx`, `go`, `git`, `npm`). Only installed tools are auto-run; everything else shows "not installed". You can also define a **custom tool** (name, binary, accepted input types, run template, install method) in the UI — it inherits the same no-shell, argv-only execution guarantees. Package refs for installs are allowlist-validated.

If tool management is disabled, install tools manually on the host (the app detects binaries on `PATH` plus the Go and Python script directories).

---

## 6. Data management

### 6.1 Where the database lives

There is exactly **one** SQLite database per deployment (WAL mode). Its location depends on the model:

| Deployment | Default database path |
|------------|-----------------------|
| Manual / `run.sh` / systemd | `<working-dir>/data/gofindme.db` (systemd `WorkingDirectory`) |
| Desktop — Windows | `%LOCALAPPDATA%\GoFindMe\gofindme.db` |
| Desktop — macOS | `~/Library/Application Support/GoFindMe/gofindme.db` |
| Desktop — Linux | `${XDG_DATA_HOME:-~/.local/share}/GoFindMe/gofindme.db` |
| Termux | `~/GoFindMe/data/gofindme.db` |
| Android APK | App private sandbox storage (query `/api/health` for the exact `db_path`) |

Uploads live alongside at `GOFINDME_UPLOADS_DIR` (default `./data/uploads`). Confirm the effective path on any instance via `GET /api/health` (`db_path` and `data_dir` fields).

### 6.2 WAL sidecar files (important for backups)

The database runs in **WAL mode** (`PRAGMA journal_mode = WAL`), so at runtime you will see three files:

```
gofindme.db        # main database
gofindme.db-wal    # write-ahead log (recent, not-yet-checkpointed writes)
gofindme.db-shm    # shared-memory index
```

A backup that copies only `gofindme.db` while the server is running can miss the latest committed writes still in the `-wal` file. Use one of the two procedures below.

### 6.3 Backup — cold copy (simplest, recommended)

Stop the service so the WAL is checkpointed and the DB is quiescent, then copy all three files (or the whole `data/` directory):

```bash
sudo systemctl stop gofindme
cp -a /path/to/data/gofindme.db     /backup/gofindme.db
cp -a /path/to/data/gofindme.db-wal /backup/ 2>/dev/null || true
cp -a /path/to/data/gofindme.db-shm /backup/ 2>/dev/null || true
# or simply: cp -a /path/to/data /backup/data-$(date +%F)
sudo systemctl start gofindme
```

### 6.4 Backup — hot copy (no downtime)

Use SQLite's online backup / `VACUUM INTO`, which produces one consistent single-file snapshot without stopping the service:

```bash
sqlite3 /path/to/data/gofindme.db ".backup '/backup/gofindme-$(date +%F).db'"
# or, equivalently:
sqlite3 /path/to/data/gofindme.db "VACUUM INTO '/backup/gofindme-$(date +%F).db'"
```

The resulting file is a self-contained snapshot (no `-wal`/`-shm` needed) and can be restored on its own. Automate this on a schedule (cron/systemd timer) and store copies off-host, ideally on encrypted storage.

### 6.5 Restore

```bash
sudo systemctl stop gofindme
# Remove any stale sidecar files before dropping in a restored single-file DB:
rm -f /path/to/data/gofindme.db-wal /path/to/data/gofindme.db-shm
cp -a /backup/gofindme-YYYY-MM-DD.db /path/to/data/gofindme.db
sudo systemctl start gofindme
```

On startup the app applies the schema idempotently (safe on an existing DB), runs its lightweight column migrations, and marks any job left `running`/`queued` from the prior process as errored (`server_restart`) — so a restored or restarted instance never shows phantom in-flight jobs.

### 6.6 Retention

There is no automatic purge. Manage growth by:

- Keeping `GOFINDME_OUTPUT_CAP` at a sane bound (default 5 MiB/job).
- Deleting old cases/findings from the dashboard when no longer needed.
- Reclaiming space after large deletes: `sudo systemctl stop gofindme && sqlite3 /path/to/data/gofindme.db "VACUUM;" && sudo systemctl start gofindme`.

### 6.7 Case export

Investigative output can be exported per target and per case:

- **Per-target report** — Markdown or JSON (identity, accounts, timeline, findings):
  ```bash
  # Authenticated request; -b passes the login cookie or use an Authorization: Bearer header.
  curl -s "http://127.0.0.1:8000/api/reports/export?target=<TARGET>&format=md" \
       -H "Authorization: Bearer <TOKEN>" -o report.md
  curl -s "http://127.0.0.1:8000/api/reports/export?target=<TARGET>&format=json" \
       -H "Authorization: Bearer <TOKEN>" -o report.json
  ```
  (Both are also one-click in the dashboard.)
- **Per-case printable report** — a self-contained HTML document at `GET /api/cases/{id}/report`, suitable for archiving or printing to PDF.

Exports are the portable artifacts for evidence handoff; the SQLite database is the system of record.

---

## 7. Updating

GoFindMe uses **rolling releases** and self-updating launchers, so how an update reaches each deployment differs.

| Deployment | Update mechanism | Action |
|------------|------------------|--------|
| Desktop app (packaged) | GitHub Actions builds per-OS binaries on push to `main`, published to the rolling `desktop-latest` release. | Re-download the binary for your OS and replace the old one. Your per-user data dir is untouched. |
| Android APK | GitHub Actions builds a debug-signed APK, published to the rolling `android-latest` release (stable URL). | Re-download `gofindme-debug.apk` and reinstall. |
| macOS / Linux launcher | `scripts/gofindme.sh` runs `git pull --ff-only` and re-ensures deps on every launch. | Just run the launcher again. |
| Termux launcher | `scripts/gofindme-termux.sh` pulls latest + installs missing deps each run. | Run the launcher again. |
| Windows launcher | `run-windows.bat` runs `git pull --ff-only` and reinstalls requirements on launch. | Run the batch file again. |
| VPS / systemd | Not auto-updating (service runs a fixed clone + venv). | See below. |

**Updating a VPS / systemd install:**

```bash
cd /path/to/GoFindMe
sudo systemctl stop gofindme
git pull --ff-only
.venv/bin/pip install -r requirements.txt
sudo systemctl start gofindme
```

Schema migrations are applied automatically on startup (idempotent), so an update never requires a manual DB step. Take a backup (§6) before updating a production instance.

---

## 8. Hardening checklist for production

The server executes tools and holds API keys, so this is **not optional**.

- [ ] **Run as a non-root, dedicated, low-privilege user.** The systemd unit sets `NoNewPrivileges=true` and `PrivateTmp=true`; keep them. Consider adding `ProtectSystem=strict`, `ProtectHome=`, and a `ReadWritePaths=` for the data dir.
- [ ] **Keep the bind on loopback** (`GOFINDME_BIND=127.0.0.1`) and put a TLS reverse proxy (Caddy/nginx) or a private tunnel (Tailscale/WireGuard) in front. Never expose the raw port to the internet.
- [ ] **Terminate TLS** with a real certificate. Login and cookie security assume HTTPS over any network path.
- [ ] **Firewall.** Allow only the proxy/tunnel; block the app port from all other sources (`ufw`, security groups, host firewall). With Tailscale `serve` there are no open inbound ports at all.
- [ ] **Encrypt the disk / data volume.** The database can hold sensitive findings and (encrypted) key blobs; full-disk or volume encryption protects data at rest beyond the vault.
- [ ] **Keep the vault in `encrypted` mode.** Never use `plaintext` in production. Store the passphrase in your org secrets manager (there is no recovery).
- [ ] **Tighten timeouts.** Lower `GOFINDME_VAULT_IDLE_MINUTES` and `GOFINDME_TOKEN_TTL_DAYS` to match policy on shared/sensitive hosts.
- [ ] **Disable tool management** (`GOFINDME_ALLOW_TOOL_MGMT=0`) once the required tools are installed, or in locked-down/air-gapped environments, to remove the package-manager execution surface.
- [ ] **Control egress.** Where limited outbound is allowed, force it through an inspection proxy (`HTTPS_PROXY`) and pin your CA (`GOFINDME_CA_BUNDLE`). Where none is allowed, rely on the network boundary and leave the vault empty of keys (tools-only).
- [ ] **Back up regularly** (§6) and test restores. Store snapshots off-host on encrypted media.
- [ ] **Review the audit log.** Logins, vault unlocks, and every tool/provider call are recorded (never the key). Monitor `journalctl -u gofindme` and the in-app audit view.
- [ ] **Keep a non-public bind while the vault is unlocked.** An unlocked process holds keys in memory by design — its network exposure and OS user privilege are the mitigations.

Built-in protections you inherit automatically: no-shell argv execution with strict anchored target validators (re-validated at execution time), same-origin only (no CORS), a strict Content-Security-Policy plus `X-Content-Type-Options`, `X-Frame-Options: DENY`, and `Referrer-Policy: no-referrer`, SSRF guards (hardcoded provider hosts, private/reserved IPs refused), per-job timeouts, and output caps.

---

## 9. Troubleshooting

| Symptom | Cause | Resolution |
|---------|-------|-----------|
| Tool **install fails** with "no automated installer" or "`<mgr>` is not available on this host" | The required toolchain (pip/pipx/go/git/npm) is not on `PATH`. | Install the toolchain (e.g. `sudo apt-get install golang-go` for Go tools) and retry. Check availability at **Tools → managers** or `GET /api/tools/managers`. |
| Install returns **403 "Tool management is disabled"** | `GOFINDME_ALLOW_TOOL_MGMT=0` (default on the Android APK). | Set `GOFINDME_ALLOW_TOOL_MGMT=1` and restart, or install the tool manually on the host. |
| Packaged desktop app can't install a tool ("in-app install needs a system Python") | The frozen executable is not a Python interpreter; installs need a **system** Python/Go on `PATH`. | Install system Python (and Go for Go tools), then retry — installs and detection use those, not the bundled runtime. |
| Provider lookup returns **`no_key_configured`** | The provider requires an API key and none is set. | Add the key in the vault (§5.3), or ignore it in air-gapped/tools-only operation. |
| Provider lookup returns **`vault_locked`** | The vault auto-locked (idle) or was never unlocked. | Unlock the vault; consider raising `GOFINDME_VAULT_IDLE_MINUTES`. |
| Provider returns **`invalid_or_unauthorized_key`** / **`rate_limited`** / **`upstream_error_5xx`** | Bad/expired key (401/403), throttling (429), or upstream outage (5xx). | Re-check the key with **Test connection**; back off on rate limits (lower `GOFINDME_MAX_CONCURRENCY`); retry later for upstream errors. |
| All provider calls fail on an isolated network | Air-gapped / no egress — expected. | Operate tools-only; provider errors are benign. To route through a proxy where permitted, set `HTTPS_PROXY`. |
| Outbound TLS fails with certificate errors | An internal inspection CA is in the path. | Point `GOFINDME_CA_BUNDLE` (or `SSL_CERT_FILE`) at the CA bundle. |
| **Port already in use** / server won't start | Another process holds `GOFINDME_PORT` (default 8000). | Change `GOFINDME_PORT` (and the proxy/tunnel to match). Find the holder: `sudo ss -ltnp 'sport = :8000'`. |
| Can't reach the dashboard from another device | Bound to loopback (`127.0.0.1`) — by design. | Use a tunnel (Tailscale/WireGuard) or a TLS reverse proxy (§3.4); only set `GOFINDME_BIND=0.0.0.0` on a private tunnel interface. |
| Restored/copied DB shows stale data or errors on open | Backup missed the `-wal` file, or stale `-shm`/`-wal` left beside a single-file restore. | Back up with the service stopped or via `.backup`/`VACUUM INTO` (§6.4); before restoring a single-file snapshot, delete `-wal`/`-shm` first (§6.5). |
| Jobs show as `error: server_restart` | The process restarted while jobs were in flight. | Expected — the app fails orphaned jobs on startup. Re-run the search. |
| Login returns **429 Too many attempts** | More than 8 failed logins in 5 minutes. | Wait a few minutes and retry with correct credentials. |
| **Forgot the owner password or vault passphrase** | No self-service reset by design (single-user, no plaintext secrets). | Password: with server access, clear the owner row and re-run first-time setup (or restore a pre-change backup). Vault passphrase: it is unrecoverable — clear the vault and re-enter API keys under a new passphrase. |
| Live tool output doesn't stream behind a proxy | The proxy is buffering the SSE response. | Disable response buffering and raise read timeouts on the proxy (see the nginx snippet in §3.4). |

---

*This guide reflects GoFindMe 1.0.0. Verify the effective runtime configuration of any instance with `GET /api/health`, and consult `.env.example` and `app/config.py` for the authoritative list of settings.*
