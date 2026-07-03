# GoFindMe — Investigations Console

A **self-hosted OSINT / DFIR investigations platform**. An investigator enters a target, and
GoFindMe opens a **case**, runs every available recon tool and data provider against it
(server-side, no browser-CORS wall), auto-builds a **relationship graph**, and organizes everything
into a **court-ready report** backed by a **tamper-evident audit trail** — all on infrastructure you
control. Simple enough to run from one search box; deep enough to stand up in procurement review.

> ⚠️ **Authorized use only.** GoFindMe executes reconnaissance tools and queries third-party APIs on
> your behalf. Use it only for investigations you are legally authorized to conduct, and follow each
> upstream service's terms of use.

### At a glance

- **One-click Investigate** → auto-opens a case (`GFM-2026-000N`) and runs tools + providers scoped
  to it, with live output.
- **Case management** — subject, examiner, legal authority, status/priority, scoped evidence.
- **Relationship graph** — an interactive, self-contained link-analysis view auto-derived from real
  findings and tracked accounts (no external JS; CSP-safe).
- **Court-ready reporting** — a branded, printable report with case metadata, findings provenance,
  timeline, methodology, and a **chain-of-custody integrity block** (verified audit-chain hash +
  document fingerprint).
- **Tamper-evident audit trail** — an append-only SHA-256 hash chain with one-click integrity
  verification.
- **Analytics** — live, computed metrics (hit rate, findings by source/type, 2FA gaps).

**Procurement docs:** [Security whitepaper](docs/SECURITY.md) ·
[Deployment & administration](docs/DEPLOYMENT.md) · [Data handling & privacy](docs/DATA_HANDLING.md)

It evolved from a single static `index.html` launcher (still preserved — see
[Legacy launcher](#legacy-launcher)) into a real backend app, because a browser page cannot run
Sherlock/Amass/etc., cannot call key-gated APIs (CORS), and has no shared storage.

---

## What it does

- **Search All** — type a target (username, email, phone, domain, IP, hash, BTC address); GoFindMe
  auto-detects the type, then fans out to every **installed** auto-runnable CLI tool *and* every
  configured/keyless API provider, streaming each tool's output live and aggregating provider
  results into cards.
- **Runs the tools for real** — an allowlisted dispatcher executes tools as argv lists (never a
  shell) and streams stdout to the dashboard over SSE.
- **Server-side API operations** — Shodan, VirusTotal, HIBP, Hunter, GreyNoise, AbuseIPDB,
  SecurityTrails, IPinfo, Censys, EmailRep, LeakCheck, IntelX, DeHashed, plus keyless crt.sh — all
  called from the server, so your local file:// CORS limits disappear. One-click **Test connection**.
- **Encrypted API vault** — keys sealed with AES-256-GCM (PBKDF2-SHA256, 200k iterations); the
  passphrase is never stored. Decrypted on demand, auto-locks when idle. Optional plaintext mode.
- **Manage tools from the dashboard** — check versions, **install / update** tools (pip, pipx, go,
  git, npm), or **Update all installed** — output streams like any other job.
- **Add new software easily** — define a custom tool (name, binary, accepted types, run template,
  install method) right in the UI; it joins the registry with the same no-shell safety.
- **Personal-footprint data layer** — Identity (emails/usernames/handles), Accounts + recovery
  status, a digital Timeline, and Notes — stored server-side, shared across all your devices.
- **Reports** — export a target's findings + accounts + timeline as Markdown or JSON.
- **Audit log** of logins, vault unlocks, and every tool/provider call (never the key).

---

## Quick start

```bash
git clone https://github.com/ether4o4/gofindme && cd gofindme
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
./run.sh                      # serves http://127.0.0.1:8000
```

Open the URL, create the owner account (one-time), and you're in. Configuration is via environment
variables (see `.env.example`); `run.sh` loads a local `.env` if present.

The OSINT tools themselves are **not** bundled — install the ones you want from the **Tools** tab
(or your own package manager). GoFindMe detects what's present and only runs installed tools;
everything else shows as "not installed".

### Reach it from your phone (shared, synced)

All devices talk to the one server, so data is shared automatically — there's nothing to sync by
hand. To reach it off `localhost`, **do not** expose it raw to the internet. Instead:

- **Recommended:** put the host on a private tunnel like **Tailscale / WireGuard**, then browse to
  `http://<machine>:8000` from your phone. Set `GOFINDME_BIND=0.0.0.0` so it listens on the tunnel
  interface.
- **Public:** only behind a TLS reverse proxy (Caddy/nginx) with a real certificate. The login +
  cookie security assume HTTPS in that case.

### Self-updating launchers (one command, opens straight to the app)

These pull the latest code, ensure dependencies, start the server, and open the dashboard for you.

- **Android (Termux):** the full app *with* tool support runs on your phone.
  ```bash
  pkg install -y git
  git clone https://github.com/ether4o4/GoFindMe ~/GoFindMe
  bash ~/GoFindMe/scripts/gofindme-termux.sh
  ```
  To launch automatically whenever you open Termux, append that last line to `~/.bashrc`. Uses the
  Termux `python-cryptography` package + pydantic v1, so there's no Rust build. (For a no-setup phone
  option, the Android **APK** in the `android-latest` release also works — it just can't run CLI tools.)
- **macOS / Linux:** `./scripts/gofindme.sh` from a clone.
- **Windows:** `run-windows.bat` from a clone (it now `git pull`s on launch). For a no-Python option,
  use the packaged `.exe` from the `desktop-latest` release (update it by re-downloading).

Each launcher checks for updates on start, so opening it always runs the latest version.

### Deploy on a VPS — run the tools there, control it from your phone (recommended)

This is the best setup: the VPS (a full Linux box) installs and runs **all** the CLI tools, and
your phone just opens the dashboard in a browser. The phone gets the VPS's full power, and your
data lives in one place.

```bash
sudo apt-get install -y git
git clone https://github.com/ether4o4/GoFindMe && cd GoFindMe
sudo bash scripts/install-vps.sh
```

The installer sets up the server + common OSINT tools (Sherlock, Maigret, Holehe, theHarvester,
and Go tools if Go is present), runs it as a `systemd` service on `127.0.0.1`, and prints how to
reach it from your phone. **Recommended: Tailscale** — `sudo tailscale serve --bg 8000` gives you a
private `https://…ts.net` URL with no open ports and no domain. (Or Caddy for a public HTTPS domain.)
Don't expose the port to the public internet without TLS.

---

## Architecture

```
 phone ─┐
 laptop ─┼──▶  FastAPI server  ──▶  SQLite (WAL)         one shared source of truth
 desktop ┘         │  ├─ tool dispatcher → asyncio.create_subprocess_exec (argv list, no shell)
                   │  ├─ provider layer  → httpx (server-side, proxy/CA aware)
                   │  ├─ encrypted vault → PBKDF2 + AES-256-GCM
                   │  └─ job queue       → live output via SSE
                   └─ serves the responsive vanilla-JS dashboard (same origin, no CORS)
```

- **Backend:** FastAPI + `uvicorn`, in-process `asyncio` job queue (no Celery/Redis).
- **Frontend:** responsive vanilla HTML/CSS/JS — no build step, mobile-friendly, dark theme.
- **Data:** one server-side SQLite DB in WAL mode → inherent multi-device sync.

| Path | Purpose |
|------|---------|
| `app/` | FastAPI backend (auth, vault, tools, jobs, providers, orchestrate, data, reports) |
| `static/` | The dashboard (`index.html`, `css/`, `js/`) |
| `legacy/` | The original single-file launcher, preserved and served at `/legacy` |
| `tests/` | pytest suite (offline by default; one network-marked live test) |

---

## Security model

Because the server now executes tools and holds API keys, the hardening below is **not optional**:

- **No shell, ever.** Targets pass strict anchored validators (whitelists that forbid whitespace,
  shell metacharacters, and leading `-`), are re-validated server-side at execution time, and are
  passed as discrete argv elements. Custom tools' run templates inherit the same guarantees.
- **Login required.** Single-user Argon2id password → opaque bearer token; every `/api/*` route is
  gated. Login attempts are rate-limited. Bind defaults to `127.0.0.1`.
- **Vault.** Keys are AES-256-GCM encrypted at rest, decrypted on demand, auto-locked when idle, and
  never placed in a subprocess environment or log. A stolen DB without the passphrase yields nothing.
  *Trade-off:* while unlocked, the server process holds keys in memory — keep it on a non-public bind
  and run it as a non-root user.
- **Tool management** (install/update) runs only an allowlist of package managers with validated
  refs; disable it with `GOFINDME_ALLOW_TOOL_MGMT=0`.
- Same-origin only (no CORS), strict CSP + security headers, SSRF guards (provider hosts are
  hardcoded; private/reserved IPs are refused), per-job timeouts and output caps.

See `.env.example` for every setting.

---

## Tools & providers

**Auto-runnable CLI tools** (install what you need): sherlock, maigret, blackbird, nexfil, holehe,
h8mail, ghunt, phoneinfoga, subfinder, amass, findomain, assetfinder, theHarvester, gau,
waybackurls, katana, hakrawler, waymore, bbot, whois, shodan-cli, exiftool, mat2.

**Manual / GUI frameworks** (listed for visibility + copy-command, never auto-executed): spiderfoot,
recon-ng, maltego, osmedeus, foca, moriarty.

**API providers:** crt.sh (keyless), emailrep (keyless), shodan, censys, virustotal, hibp, hunter,
greynoise, abuseipdb, securitytrails, ipinfo, leakcheck, intelx, dehashed.

---

## Roadmap (honestly scaffolded, not faked)

These are present as labeled placeholders / `501` endpoints to be filled in next:

- Relationship graph visualization (tables + CRUD exist; the visual canvas is pending).
- Analytics/privacy scoring beyond the real counts already computed.
- Browser / cloud (Takeout) / file-image importers.

---

## Legacy launcher

The original browser-only single-file console is preserved verbatim at `legacy/index.html` and
served at **`/legacy`**. It runs entirely client-side (builds commands, opens web pivots, encrypts
keys in `localStorage`) and is handy as an offline, install-free quick launcher.

---

## Development

```bash
pip install -r requirements-dev.txt
pytest                 # offline suite
pytest -m network      # include the live crt.sh path test (needs outbound network)
```

## License

Add your preferred license (MIT is a common choice for tooling like this).
