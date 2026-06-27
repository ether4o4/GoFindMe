"""Tool registry, safe dispatcher, streaming subprocess spawner, and the
install/update manager.

Everything that executes a child process funnels through ``spawn_stream`` with an
argv **list** and ``shell=False``. Targets are validated first; install refs are
validated against tight charsets; managers are an allowlist. No string is ever
handed to a shell.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Awaitable, Callable

from . import db
from .config import settings
from .util import audit, strip_ansi
from .validators import ValidationError, build_argv, validate

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class ToolSpec:
    name: str
    bin: str
    categories: list[str]
    accepts: list[str]
    run_template: str                 # full command using {bin} and {target}
    timeout_s: int = 180
    auto_runnable: bool = True         # eligible for Search-All / direct run
    interactive: bool = False          # GUI/REPL — never spawned, copy-command only
    install_method: str = "none"       # pip|pipx|go|git|npm|none
    install_ref: str | None = None
    version_cmd: str | None = None     # template, e.g. "{bin} --version"
    stdin_template: str | None = None  # if set, target is piped to stdin, not argv
    notes: str = ""
    source: str = "builtin"

    def public(self) -> dict:
        d = asdict(self)
        d.pop("stdin_template", None)
        return d


# Built-in manifest. Interactive/GUI frameworks are listed for visibility only.
BUILTIN: list[ToolSpec] = [
    # --- username ---
    ToolSpec("sherlock", "sherlock", ["username"], ["username"],
             "{bin} --print-found --timeout 30 --no-color {target}", 240,
             install_method="pip", install_ref="sherlock-project"),
    ToolSpec("maigret", "maigret", ["username"], ["username"],
             "{bin} --timeout 30 --no-color {target}", 300,
             install_method="pip", install_ref="maigret"),
    ToolSpec("blackbird", "blackbird", ["username", "email"], ["username", "email"],
             "{bin} -u {target}", 240, install_method="git",
             install_ref="https://github.com/p1ngul1n0/blackbird",
             notes="Cloned to data/tools; run with its own python entrypoint."),
    ToolSpec("nexfil", "nexfil", ["username"], ["username"],
             "{bin} -u {target}", 240, install_method="git",
             install_ref="https://github.com/thewhiteh4t/nexfil"),
    # --- email ---
    ToolSpec("holehe", "holehe", ["email"], ["email"],
             "{bin} --only-used {target}", 180, install_method="pip", install_ref="holehe"),
    ToolSpec("h8mail", "h8mail", ["email"], ["email"],
             "{bin} -t {target}", 180, install_method="pip", install_ref="h8mail"),
    ToolSpec("ghunt", "ghunt", ["email"], ["email"],
             "{bin} email {target}", 180, install_method="pip", install_ref="ghunt",
             notes="Requires a one-time `ghunt login` with Google cookies."),
    # --- phone ---
    ToolSpec("phoneinfoga", "phoneinfoga", ["phone"], ["phone"],
             "{bin} scan -n {target}", 120, install_method="none",
             notes="Install the binary from sundowndev/phoneinfoga releases."),
    # --- domain ---
    ToolSpec("subfinder", "subfinder", ["domain"], ["domain"],
             "{bin} -silent -d {target}", 300, install_method="go",
             install_ref="github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest"),
    ToolSpec("amass", "amass", ["domain"], ["domain"],
             "{bin} enum -passive -d {target}", 600, install_method="go",
             install_ref="github.com/owasp-amass/amass/v4/...@master",
             notes="Heavy; capped to one concurrent run."),
    ToolSpec("findomain", "findomain", ["domain"], ["domain"],
             "{bin} -t {target} -q", 240, install_method="none",
             notes="Install the binary from findomain/findomain releases."),
    ToolSpec("assetfinder", "assetfinder", ["domain"], ["domain"],
             "{bin} --subs-only {target}", 180, install_method="go",
             install_ref="github.com/tomnomnom/assetfinder@latest"),
    ToolSpec("theHarvester", "theHarvester", ["domain"], ["domain"],
             "{bin} -d {target} -b duckduckgo,bing,crtsh,otx", 300,
             install_method="pip", install_ref="theHarvester"),
    ToolSpec("gau", "gau", ["domain"], ["domain"],
             "{bin} {target}", 240, install_method="go",
             install_ref="github.com/lc/gau/v2/cmd/gau@latest"),
    ToolSpec("waybackurls", "waybackurls", ["domain"], ["domain"],
             "{bin} {target}", 180, install_method="go",
             install_ref="github.com/tomnomnom/waybackurls@latest"),
    ToolSpec("katana", "katana", ["domain"], ["domain"],
             "{bin} -silent -u https://{target}", 300, install_method="go",
             install_ref="github.com/projectdiscovery/katana/cmd/katana@latest"),
    ToolSpec("hakrawler", "hakrawler", ["domain"], ["domain"],
             "{bin} -u", 180, install_method="go",
             install_ref="github.com/hakluke/hakrawler@latest",
             stdin_template="https://{target}"),
    ToolSpec("waymore", "waymore", ["domain"], ["domain"],
             "{bin} -i {target} -mode U", 300, install_method="pip", install_ref="waymore"),
    ToolSpec("bbot", "bbot", ["domain"], ["domain"],
             "{bin} -t {target} -f subdomain-enum -y -o {target}", 600,
             install_method="pip", install_ref="bbot",
             notes="Modular recon framework; passive subdomain preset."),
    ToolSpec("whois", "whois", ["domain", "ip"], ["domain", "ip"],
             "{bin} {target}", 30, install_method="none",
             notes="Usually provided by the OS (whois package)."),
    # --- ip / domain (key tools that overlap providers) ---
    ToolSpec("shodan-cli", "shodan", ["ip", "domain"], ["ip", "domain"],
             "{bin} host {target}", 60, install_method="pip", install_ref="shodan",
             notes="Run `shodan init <key>` once; or use the Shodan provider instead."),
    # --- image / metadata (needs an uploaded file; see notes) ---
    ToolSpec("exiftool", "exiftool", ["image"], ["image"],
             "{bin} -json {target}", 60, install_method="none",
             notes="Runs on an uploaded file. Install via your OS package manager."),
    ToolSpec("mat2", "mat2", ["image"], ["image"],
             "{bin} --show {target}", 60, install_method="pip", install_ref="mat2",
             notes="Inspect/strip file metadata on an uploaded file."),
    # --- interactive / GUI frameworks: visibility + copy-command only ---
    ToolSpec("spiderfoot", "sf", ["username", "email", "domain", "ip"], [],
             "{bin}", 0, auto_runnable=False, interactive=True,
             install_method="pip", install_ref="spiderfoot",
             notes="Runs its own web server; launch separately."),
    ToolSpec("recon-ng", "recon-ng", ["domain", "email"], [],
             "{bin}", 0, auto_runnable=False, interactive=True,
             install_method="pip", install_ref="recon-ng",
             notes="Interactive console."),
    ToolSpec("maltego", "maltego", ["username", "email", "domain", "ip"], [],
             "{bin}", 0, auto_runnable=False, interactive=True,
             notes="GUI application."),
    ToolSpec("osmedeus", "osmedeus", ["domain"], [],
             "{bin}", 0, auto_runnable=False, interactive=True,
             notes="Heavy workflow engine; run separately."),
    ToolSpec("theharvester-foca", "foca", ["domain"], [],
             "{bin}", 0, auto_runnable=False, interactive=True,
             notes="FOCA is a Windows GUI document-metadata tool."),
    ToolSpec("moriarty", "moriarty", ["phone", "email", "username"], [],
             "{bin}", 0, auto_runnable=False, interactive=True,
             notes="Interactive project; launch separately."),
]


def _custom_specs() -> list[ToolSpec]:
    out: list[ToolSpec] = []
    for r in db.query("SELECT * FROM custom_tools ORDER BY name"):
        out.append(ToolSpec(
            name=r["name"], bin=r["bin"],
            categories=json.loads(r["categories"] or "[]"),
            accepts=json.loads(r["accepts"] or "[]"),
            run_template=r["run_template"], timeout_s=r["timeout_s"],
            auto_runnable=bool(r["auto_runnable"]), interactive=bool(r["interactive"]),
            install_method=r["install_method"], install_ref=r["install_ref"],
            version_cmd=r["version_cmd"], notes=r["notes"] or "", source="custom",
        ))
    return out


def registry() -> dict[str, ToolSpec]:
    """Built-in manifest merged with user-defined custom tools (custom wins)."""
    reg = {s.name: s for s in BUILTIN}
    for s in _custom_specs():
        reg[s.name] = s
    return reg


def get_spec(name: str) -> ToolSpec | None:
    return registry().get(name)


# --- availability (cached briefly) ---
_avail_cache: dict[str, tuple[float, str | None]] = {}
_AVAIL_TTL = 20.0


def resolve_bin(bin_name: str) -> str | None:
    now = time.time()
    hit = _avail_cache.get(bin_name)
    if hit and now - hit[0] < _AVAIL_TTL:
        return hit[1]
    path = shutil.which(bin_name)
    _avail_cache[bin_name] = (now, path)
    return path


def tool_view(spec: ToolSpec) -> dict:
    path = resolve_bin(spec.bin)
    d = spec.public()
    d["available"] = path is not None
    d["path"] = path
    return d


def list_tools() -> list[dict]:
    return [tool_view(s) for s in registry().values()]


# ---------------------------------------------------------------------------
# Low-level streaming spawner (the single choke point for child processes)
# ---------------------------------------------------------------------------

OutputCb = Callable[[str], Awaitable[None] | None]

# Minimal env for tool RUN jobs — no secrets, no proxy.
_RUN_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "GOPATH", "GOBIN")
# Manage jobs additionally need proxy + go module env to fetch packages.
_MGMT_ENV_KEYS = _RUN_ENV_KEYS + (
    "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
    "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "GOPROXY", "GOMODCACHE", "GOCACHE", "PIP_INDEX_URL",
)


def _env(keys: tuple[str, ...]) -> dict[str, str]:
    return {k: os.environ[k] for k in keys if k in os.environ}


async def spawn_stream(
    argv: list[str],
    timeout_s: int,
    on_output: OutputCb | None = None,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> tuple[str, int | None, str]:
    """Run argv (no shell), streaming combined stdout/stderr.

    Returns (status, returncode, full_output) where status is
    done|error|timeout|cancelled-equivalent handled by the caller.
    """
    cap = settings().output_cap_bytes
    buf: list[str] = []
    size = 0
    truncated = False

    async def emit(text: str) -> None:
        nonlocal size, truncated
        if size < cap:
            buf.append(text)
            size += len(text)
            if size >= cap and not truncated:
                truncated = True
                buf.append("\n[output truncated]\n")
            if on_output:
                res = on_output(text)
                if asyncio.iscoroutine(res):
                    await res

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env or _env(_RUN_ENV_KEYS),
            cwd=cwd,
        )
    except FileNotFoundError:
        return "error", None, "executable not found"
    except Exception as exc:  # pragma: no cover - defensive
        return "error", None, f"spawn failed: {exc}"

    if stdin is not None and proc.stdin is not None:
        try:
            proc.stdin.write(stdin.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
        except Exception:
            pass

    deadline = time.monotonic() + max(1, timeout_s)
    assert proc.stdout is not None
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                raise
            if not line:
                break
            await emit(strip_ansi(line.decode("utf-8", "replace")))
        rc = await asyncio.wait_for(proc.wait(), timeout=max(1, deadline - time.monotonic()))
        status = "done" if rc == 0 else "error"
        return status, rc, "".join(buf)
    except asyncio.TimeoutError:
        _kill(proc)
        await emit("\n[timed out]\n")
        return "timeout", None, "".join(buf)
    except asyncio.CancelledError:
        _kill(proc)
        raise


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        pass


# ---------------------------------------------------------------------------
# Dispatcher — validate, build argv, run a single tool against a target
# ---------------------------------------------------------------------------


def build_tool_argv(spec: ToolSpec, target: str) -> tuple[list[str], str | None]:
    """Validate target for the spec and return (argv, stdin)."""
    bin_path = resolve_bin(spec.bin)
    if not bin_path:
        raise FileNotFoundError(f"{spec.bin} is not installed")
    if spec.interactive or not spec.auto_runnable:
        raise PermissionError(f"{spec.name} is interactive/GUI and is not auto-run")
    # Re-validate server-side against an accepted type (never trust client).
    ttype = next((t for t in spec.accepts if _valid_for(target, t)), None)
    if ttype is None:
        raise ValidationError(f"{target!r} is not a valid input for {spec.name}")
    stdin = None
    if spec.stdin_template:
        stdin = spec.stdin_template.replace("{target}", target)
    argv = build_argv(spec.run_template, bin_path, target)
    return argv, stdin


def _valid_for(target: str, ttype: str) -> bool:
    try:
        validate(target, ttype)
        return True
    except ValidationError:
        return False


# ---------------------------------------------------------------------------
# Tool manager — install / update / version, via an allowlist of managers
# ---------------------------------------------------------------------------

_SAFE_PKG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]{0,99}$")
_SAFE_GOREF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,200}(@[A-Za-z0-9._/\-]{1,80})?$")
_SAFE_GITURL = re.compile(r"^https://[A-Za-z0-9.\-]{1,255}/[A-Za-z0-9._/\-]{1,200}$")

TOOLS_DIR = settings().db_path.parent / "tools"


class ManageError(ValueError):
    pass


def _pip() -> list[str]:
    return [sys.executable, "-m", "pip"]


def install_argv(spec: ToolSpec, update: bool) -> tuple[list[str], str | None]:
    """Return (argv, cwd) for an install/update of a tool. Raises ManageError if
    the method or ref is not allowlisted/valid."""
    m = spec.install_method
    ref = spec.install_ref or ""
    if m == "none":
        raise ManageError(f"{spec.name} has no automated installer; install it manually.")
    if m in ("pip", "pipx", "npm") and not _SAFE_PKG.match(ref):
        raise ManageError(f"Unsafe package ref: {ref!r}")
    if m == "go" and not _SAFE_GOREF.match(ref):
        raise ManageError(f"Unsafe go module ref: {ref!r}")
    if m == "git" and not _SAFE_GITURL.match(ref):
        raise ManageError(f"git ref must be an https repo URL: {ref!r}")

    if m == "pip":
        argv = _pip() + ["install"] + (["--upgrade"] if update else []) + [ref]
        return argv, None
    if m == "pipx":
        argv = ["pipx", "upgrade", spec.bin] if update else ["pipx", "install", ref]
        return argv, None
    if m == "npm":
        return ["npm", "install", "-g", ref], None
    if m == "go":
        return ["go", "install", ref], None
    if m == "git":
        dest = TOOLS_DIR / spec.name
        if update and dest.exists():
            return ["git", "-C", str(dest), "pull", "--ff-only"], None
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        return ["git", "clone", "--depth", "1", ref, str(dest)], None
    raise ManageError(f"Unknown install method: {m}")


def version_argv(spec: ToolSpec) -> list[str] | None:
    bin_path = resolve_bin(spec.bin)
    if not bin_path:
        return None
    tmpl = spec.version_cmd or "{bin} --version"
    try:
        return build_argv(tmpl, bin_path, "")
    except ValidationError:
        return None


def manager_available(method: str) -> bool:
    return {
        "pip": True,
        "pipx": shutil.which("pipx") is not None,
        "npm": shutil.which("npm") is not None,
        "go": shutil.which("go") is not None,
        "git": shutil.which("git") is not None,
        "none": False,
    }.get(method, False)


def mgmt_env() -> dict[str, str]:
    return _env(_MGMT_ENV_KEYS)


# ---------------------------------------------------------------------------
# Custom tool CRUD (the "add new software easily" registry)
# ---------------------------------------------------------------------------

_VALID_METHODS = {"pip", "pipx", "go", "git", "npm", "none"}


def upsert_custom_tool(data: dict) -> ToolSpec:
    from .util import now_iso
    name = (data.get("name") or "").strip()
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$", name):
        raise ManageError("Invalid tool name")
    if name in {s.name for s in BUILTIN}:
        raise ManageError("Name collides with a built-in tool")
    bin_name = (data.get("bin") or "").strip()
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$", bin_name):
        raise ManageError("Invalid bin name")
    run_template = (data.get("run_template") or "").strip()
    if "{target}" not in run_template:
        raise ManageError("run_template must contain {target}")
    if "{bin}" not in run_template:
        run_template = "{bin} " + run_template
    # Validate the template compiles to a safe argv (dummy bin/target).
    build_argv(run_template, "/usr/bin/true", "validation-sample")
    method = (data.get("install_method") or "none").strip()
    if method not in _VALID_METHODS:
        raise ManageError("Invalid install_method")
    accepts = data.get("accepts") or []
    cats = data.get("categories") or accepts
    spec_for_install = ToolSpec(
        name=name, bin=bin_name, categories=cats, accepts=accepts,
        run_template=run_template, install_method=method,
        install_ref=(data.get("install_ref") or None),
    )
    if method != "none":
        install_argv(spec_for_install, update=False)  # raises on unsafe ref
    db.execute(
        "INSERT INTO custom_tools (name, categories, accepts, bin, run_template, "
        "install_method, install_ref, version_cmd, timeout_s, auto_runnable, interactive, "
        "notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(name) DO UPDATE SET categories=excluded.categories, accepts=excluded.accepts, "
        "bin=excluded.bin, run_template=excluded.run_template, install_method=excluded.install_method, "
        "install_ref=excluded.install_ref, version_cmd=excluded.version_cmd, "
        "timeout_s=excluded.timeout_s, auto_runnable=excluded.auto_runnable, "
        "interactive=excluded.interactive, notes=excluded.notes, updated_at=excluded.updated_at",
        (name, json.dumps(cats), json.dumps(accepts), bin_name, run_template, method,
         data.get("install_ref"), data.get("version_cmd"), int(data.get("timeout_s") or 180),
         1 if data.get("auto_runnable", True) else 0, 1 if data.get("interactive") else 0,
         data.get("notes"), now_iso(), now_iso()),
    )
    audit("audit", "mgmt", "custom tool saved", tool=name)
    return get_spec(name)  # type: ignore[return-value]


def delete_custom_tool(name: str) -> bool:
    n = db.write("DELETE FROM custom_tools WHERE name=?", (name,))
    if n:
        audit("audit", "mgmt", "custom tool deleted", tool=name)
    return bool(n)
