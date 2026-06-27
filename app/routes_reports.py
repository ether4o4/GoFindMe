"""Dashboard overview metrics, report export, and honest import placeholders."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from . import db, security
from .util import now_iso

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/overview")
async def overview(_t: str = security.Auth) -> dict:
    def scalar(sql: str, params=()) -> int:
        row = db.query_one(sql, params)
        return int(list(row)[0]) if row else 0

    accounts_no_2fa = scalar("SELECT COUNT(*) FROM accounts WHERE has_2fa IS NULL OR has_2fa=0")
    breached = db.query(
        "SELECT DISTINCT target FROM findings WHERE source_name='hibp' AND summary LIKE '%\"found\": true%'")
    return {
        "identity_items": scalar("SELECT COUNT(*) FROM identity_items"),
        "accounts": scalar("SELECT COUNT(*) FROM accounts"),
        "accounts_without_2fa": accounts_no_2fa,
        "timeline_events": scalar("SELECT COUNT(*) FROM timeline_events"),
        "findings": scalar("SELECT COUNT(*) FROM findings"),
        "breached_emails": [r["target"] for r in breached],
        "jobs_total": scalar("SELECT COUNT(*) FROM jobs"),
        "jobs_running": scalar("SELECT COUNT(*) FROM jobs WHERE status='running'"),
    }


def _gather(target: str) -> dict:
    findings = db.query("SELECT * FROM findings WHERE target=? ORDER BY created_at DESC", (target,))
    accounts = db.query("SELECT * FROM accounts ORDER BY service")
    timeline = db.query("SELECT * FROM timeline_events ORDER BY occurred_at")
    identity = db.query("SELECT * FROM identity_items ORDER BY kind, value")
    return {
        "target": target,
        "generated": now_iso(),
        "identity": [dict(r) for r in identity],
        "accounts": [dict(r) for r in accounts],
        "timeline": [dict(r) for r in timeline],
        "findings": [_finding(dict(r)) for r in findings],
    }


def _finding(d: dict) -> dict:
    if d.get("summary"):
        try:
            d["summary"] = json.loads(d["summary"])
        except Exception:
            pass
    d.pop("raw", None)
    return d


def _markdown(data: dict) -> str:
    lines = [f"# GoFindMe Report — {data['target'] or '(none)'}",
             "", f"_Generated: {data['generated']}_", ""]
    lines.append(f"## Identity ({len(data['identity'])})")
    for it in data["identity"]:
        lines.append(f"- **{it['kind']}**: {it['value']}" + (f" — {it['label']}" if it.get('label') else ""))
    lines += ["", f"## Accounts ({len(data['accounts'])})"]
    for a in data["accounts"]:
        twofa = "2FA" if a.get("has_2fa") else "no-2FA"
        lines.append(f"- **{a['service']}** ({a.get('status') or 'unknown'}, {twofa})"
                     + (f" — {a['url']}" if a.get('url') else ""))
    lines += ["", f"## Timeline ({len(data['timeline'])})"]
    for e in data["timeline"]:
        lines.append(f"- {e.get('occurred_at') or '?'} — {e['title']}")
    lines += ["", f"## Findings ({len(data['findings'])})"]
    for f in data["findings"]:
        s = f.get("summary") or {}
        lines.append(f"- **{f['source_name']}** [{f['target_type']}] → {json.dumps(s)}")
    return "\n".join(lines) + "\n"


@router.get("/reports/export")
async def export(target: str, format: str = "json", _t: str = security.Auth):
    data = _gather(target.strip())
    if format == "md":
        return PlainTextResponse(_markdown(data), headers={
            "Content-Disposition": f'attachment; filename="gofindme-{target}.md"'})
    return JSONResponse(data, headers={
        "Content-Disposition": f'attachment; filename="gofindme-{target}.json"'})


# --- honest placeholders for v2 importers ---
@router.post("/import/{kind}")
async def import_stub(kind: str, _t: str = security.Auth):
    raise HTTPException(501, f"{kind} import is planned but not implemented yet")
