"""Court / procurement-grade investigation report (self-contained HTML → PDF).

Renders a standalone, print-optimized HTML document for a case: letterhead,
case metadata (examiner, legal authority, dates), executive summary, subject
identifiers, findings with source provenance, timeline, methodology (tools &
providers used), an audit excerpt, and a chain-of-custody integrity block
(tamper-evident audit tip hash + a SHA-256 of the report body). The browser's
Print-to-PDF turns it into a filable document. All dynamic values are HTML-escaped.
"""
from __future__ import annotations

import hashlib
import html
import json

from . import __version__, audit_chain, db
from .util import now_iso


def _esc(v) -> str:
    return html.escape("" if v is None else str(v))


def _loads(v):
    if isinstance(v, (dict, list)):
        return v
    if not v:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None


def _summary_cell(summary) -> str:
    s = _loads(summary) or {}
    if not isinstance(s, dict):
        return _esc(str(s))
    parts = []
    for k, v in s.items():
        if k == "found":
            continue
        if isinstance(v, list):
            v = f"{len(v)} item(s): " + ", ".join(map(str, v[:6])) + ("…" if len(v) > 6 else "")
        parts.append(f"<b>{_esc(k)}</b>: {_esc(v)}")
    return "<br>".join(parts) or "&mdash;"


def _finding_result(summary) -> tuple[str, str]:
    s = _loads(summary) or {}
    found = s.get("found") if isinstance(s, dict) else None
    if found is True:
        return "HIT", "hit"
    if found is False:
        return "clear", "clear"
    return "info", "info"


def render_case_html(cid: int) -> str | None:
    case = db.query_one("SELECT * FROM cases WHERE id=?", (cid,))
    if not case:
        return None
    case = dict(case)
    findings = [dict(r) for r in db.query(
        "SELECT * FROM findings WHERE case_id=? ORDER BY created_at", (cid,))]
    timeline = [dict(r) for r in db.query(
        "SELECT * FROM timeline_events WHERE case_id=? ORDER BY occurred_at", (cid,))]
    notes = [dict(r) for r in db.query(
        "SELECT * FROM notes WHERE case_id=? ORDER BY created_at", (cid,))]
    accounts = [dict(r) for r in db.query(
        "SELECT * FROM accounts WHERE case_id=? ORDER BY service", (cid,))]
    audit_rows = audit_chain.recent(40)
    integrity = audit_chain.verify()

    sources = sorted({f["source_name"] for f in findings})
    hits = sum(1 for f in findings if (_loads(f["summary"]) or {}).get("found") is True)
    generated = now_iso()

    # --- findings table rows ---
    frows = []
    for f in findings:
        label, cls = _finding_result(f["summary"])
        frows.append(
            f"<tr><td>{_esc(f['source_name'])}</td>"
            f"<td>{_esc(f['source_kind'])}</td>"
            f"<td>{_esc(f['target'])}<br><span class='dim'>{_esc(f['target_type'])}</span></td>"
            f"<td><span class='pill {cls}'>{_esc(label)}</span></td>"
            f"<td>{_summary_cell(f['summary'])}</td>"
            f"<td class='dim'>{_esc((f['created_at'] or '').replace('T',' '))}</td></tr>"
        )
    findings_tbl = ("".join(frows) or
                    "<tr><td colspan='6' class='dim'>No findings recorded for this case.</td></tr>")

    trows = "".join(
        f"<tr><td>{_esc(e.get('occurred_at') or '—')}</td><td>{_esc(e.get('event_type'))}</td>"
        f"<td>{_esc(e.get('title'))}<br><span class='dim'>{_esc(e.get('detail') or '')}</span></td></tr>"
        for e in timeline) or "<tr><td colspan='3' class='dim'>No timeline events.</td></tr>"

    arows = "".join(
        f"<tr><td>{_esc(a.get('service'))}</td><td>{_esc(a.get('status') or 'unknown')}</td>"
        f"<td>{'Yes' if a.get('has_2fa') else 'No/Unknown'}</td>"
        f"<td>{_esc(a.get('recovery_status') or '—')}</td></tr>"
        for a in accounts)
    accounts_block = (f"""
      <h2>Tracked Accounts <span class="count">{len(accounts)}</span></h2>
      <table><thead><tr><th>Service</th><th>Status</th><th>2FA</th><th>Recovery</th></tr></thead>
      <tbody>{arows}</tbody></table>""" if accounts else "")

    notes_block = ""
    if notes:
        items = "".join(f"<li>{_esc(n['body'])} <span class='dim'>"
                        f"({_esc((n['created_at'] or '').replace('T',' '))})</span></li>" for n in notes)
        notes_block = f"<h2>Investigator Notes <span class='count'>{len(notes)}</span></h2><ul class='notes'>{items}</ul>"

    audit_rows_html = "".join(
        f"<tr><td class='dim'>{_esc((r['ts'] or '').replace('T',' '))}</td>"
        f"<td>{_esc(r.get('actor'))}</td><td>{_esc(r.get('category'))}</td>"
        f"<td>{_esc(r.get('action'))}</td><td class='mono dim'>{_esc(r.get('hash_short'))}</td></tr>"
        for r in audit_rows) or "<tr><td colspan='5' class='dim'>No audit events.</td></tr>"

    methodology = ", ".join(_esc(s) for s in sources) or "—"

    body = f"""
  <header class="rpt-head">
    <div class="mark">&#9678;</div>
    <div>
      <div class="org">GoFindMe Investigations Console</div>
      <div class="doc">Investigation Report</div>
    </div>
    <div class="ref">
      <div class="reflabel">Case reference</div>
      <div class="refno">{_esc(case.get('ref') or ('#' + str(case['id'])))}</div>
    </div>
  </header>

  <section class="meta">
    <div><span class="k">Title</span><span class="v">{_esc(case.get('title'))}</span></div>
    <div><span class="k">Subject</span><span class="v">{_esc(case.get('subject') or '—')} <span class="dim">({_esc(case.get('subject_type') or 'n/a')})</span></span></div>
    <div><span class="k">Status</span><span class="v">{_esc((case.get('status') or '').upper())} &middot; priority {_esc(case.get('priority'))}</span></div>
    <div><span class="k">Examiner</span><span class="v">{_esc(case.get('examiner') or '—')}</span></div>
    <div><span class="k">Legal authority</span><span class="v">{_esc(case.get('authority') or '—')}</span></div>
    <div><span class="k">Opened</span><span class="v">{_esc((case.get('created_at') or '').replace('T',' '))}</span></div>
    <div><span class="k">Report generated</span><span class="v">{_esc(generated.replace('T',' '))} UTC</span></div>
    <div><span class="k">Engine</span><span class="v">GoFindMe v{_esc(__version__)}</span></div>
  </section>

  <section class="stats">
    <div class="stat"><div class="n">{len(findings)}</div><div class="l">Findings</div></div>
    <div class="stat"><div class="n">{hits}</div><div class="l">Positive hits</div></div>
    <div class="stat"><div class="n">{len(sources)}</div><div class="l">Sources queried</div></div>
    <div class="stat"><div class="n">{len(timeline)}</div><div class="l">Timeline events</div></div>
  </section>

  <h2>Executive Summary</h2>
  <p class="prose">{_esc(case.get('summary')) or '<span class="dim">No executive summary was recorded for this investigation.</span>'}</p>

  <h2>Findings <span class="count">{len(findings)}</span></h2>
  <table class="findings">
    <thead><tr><th>Source</th><th>Type</th><th>Target</th><th>Result</th><th>Detail</th><th>Recorded (UTC)</th></tr></thead>
    <tbody>{findings_tbl}</tbody>
  </table>

  {accounts_block}

  <h2>Timeline <span class="count">{len(timeline)}</span></h2>
  <table><thead><tr><th>When</th><th>Type</th><th>Event</th></tr></thead><tbody>{trows}</tbody></table>

  {notes_block}

  <h2>Methodology &amp; Sources</h2>
  <p class="prose">This report was produced by GoFindMe, which dispatches an allowlisted set of
  OSINT tools and queries configured data providers against the subject's identifiers. Tool inputs are
  validated and executed without a shell; provider lookups are performed server-side. Sources engaged in
  this investigation: <b>{methodology}</b>.</p>

  <h2>Chain of Custody &amp; Integrity</h2>
  <div class="coc {'ok' if integrity['ok'] else 'bad'}">
    <div><span class="k">Audit trail</span><span class="v">{'INTACT — hash chain verified' if integrity['ok'] else 'BROKEN at entry #' + str(integrity['broken_at'])}</span></div>
    <div><span class="k">Audit entries</span><span class="v">{integrity['count']}</span></div>
    <div><span class="k">Audit tip hash</span><span class="v mono">{_esc(integrity['tip'])}</span></div>
  </div>
  <table class="audit"><thead><tr><th>Time (UTC)</th><th>Actor</th><th>Category</th><th>Action</th><th>Hash</th></tr></thead>
  <tbody>{audit_rows_html}</tbody></table>

  <footer class="rpt-foot">
    <div>GoFindMe Investigations Console &middot; Case {_esc(case.get('ref') or case['id'])} &middot; Generated {_esc(generated.replace('T',' '))} UTC</div>
    <div class="dim">This document was generated from digital evidence held in the GoFindMe case datastore.
    Integrity is attested by the tamper-evident audit chain above and the document fingerprint below.</div>
    <div class="fp">Document fingerprint (SHA-256): <span class="mono" id="__fp__">%%FINGERPRINT%%</span></div>
  </footer>
"""

    doc = _PAGE.replace("%%TITLE%%", _esc(case.get('ref') or 'GoFindMe Report')).replace("%%BODY%%", body)
    # Fingerprint the rendered body (minus the placeholder) for a stable content hash.
    fp = hashlib.sha256(body.replace("%%FINGERPRINT%%", "").encode("utf-8")).hexdigest()
    return doc.replace("%%FINGERPRINT%%", fp)


_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>%%TITLE%% — GoFindMe Report</title>
<style>
  :root{--ink:#12151c;--dim:#6b7280;--line:#e4e7ec;--brand:#0f766e;--bad:#b42318;--ok:#067647;}
  *{box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    color:var(--ink);margin:0;background:#f3f4f6;line-height:1.5}
  .sheet{max-width:960px;margin:24px auto;background:#fff;padding:44px 52px 60px;
    box-shadow:0 1px 3px rgba(0,0,0,.12);border-radius:6px}
  .rpt-head{display:flex;align-items:center;gap:16px;border-bottom:3px solid var(--brand);padding-bottom:16px}
  .rpt-head .mark{font-size:40px;color:var(--brand);line-height:1}
  .rpt-head .org{font-weight:800;font-size:18px;letter-spacing:-.2px}
  .rpt-head .doc{color:var(--dim);font-size:13px;text-transform:uppercase;letter-spacing:1px}
  .rpt-head .ref{margin-left:auto;text-align:right}
  .rpt-head .reflabel{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--dim)}
  .rpt-head .refno{font-weight:800;font-size:18px;color:var(--brand)}
  .meta{display:grid;grid-template-columns:1fr 1fr;gap:8px 32px;margin:22px 0}
  .meta>div{display:flex;justify-content:space-between;gap:12px;border-bottom:1px dotted var(--line);padding:5px 0;font-size:13.5px}
  .meta .k{color:var(--dim)}.meta .v{font-weight:600;text-align:right}
  .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0}
  .stat{border:1px solid var(--line);border-radius:8px;padding:12px 14px;text-align:center}
  .stat .n{font-size:26px;font-weight:800;color:var(--brand)}.stat .l{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px}
  h2{font-size:14px;text-transform:uppercase;letter-spacing:.6px;color:var(--ink);margin:30px 0 10px;
    padding-bottom:6px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:8px}
  h2 .count{font-size:11px;color:#fff;background:var(--brand);border-radius:10px;padding:1px 8px;font-weight:700;letter-spacing:0}
  .prose{font-size:13.5px;margin:0 0 8px}
  table{width:100%;border-collapse:collapse;font-size:12.5px;margin:6px 0 4px}
  th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
  th{font-size:10.5px;text-transform:uppercase;letter-spacing:.4px;color:var(--dim);background:#fafafa}
  .dim{color:var(--dim)}.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;word-break:break-all}
  .pill{font-size:10px;font-weight:800;padding:2px 8px;border-radius:20px;text-transform:uppercase;letter-spacing:.4px}
  .pill.hit{background:#fef3f2;color:var(--bad)}.pill.clear{background:#ecfdf3;color:var(--ok)}.pill.info{background:#f2f4f7;color:var(--dim)}
  ul.notes{font-size:13px;margin:6px 0;padding-left:20px}ul.notes li{margin:4px 0}
  .coc{border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:8px 0}
  .coc.ok{border-left:4px solid var(--ok)}.coc.bad{border-left:4px solid var(--bad)}
  .coc>div{display:flex;justify-content:space-between;gap:12px;padding:3px 0;font-size:12.5px}
  .coc .k{color:var(--dim)}
  .rpt-foot{margin-top:34px;padding-top:14px;border-top:1px solid var(--line);font-size:11px;color:var(--dim)}
  .rpt-foot .fp{margin-top:8px}
  .toolbar{max-width:960px;margin:14px auto -6px;display:flex;gap:10px;justify-content:flex-end}
  .toolbar button{font:inherit;font-size:13px;font-weight:600;padding:9px 16px;border-radius:8px;border:1px solid var(--brand);
    background:var(--brand);color:#fff;cursor:pointer}
  .toolbar button.ghost{background:#fff;color:var(--brand)}
  @media print{body{background:#fff}.sheet{box-shadow:none;margin:0;max-width:none;border-radius:0;padding:0}.toolbar{display:none}}
</style></head>
<body>
  <div class="toolbar">
    <button onclick="window.print()">Print / Save as PDF</button>
    <button class="ghost" onclick="window.close()">Close</button>
  </div>
  <div class="sheet">%%BODY%%</div>
</body></html>"""
