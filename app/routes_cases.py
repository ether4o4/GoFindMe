"""Case (investigation) endpoints: CRUD, scoped search, graph, and report."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import cases, graph, orchestrate, report, security
from .validators import ValidationError

router = APIRouter(prefix="/api/cases", tags=["cases"])


class CaseBody(BaseModel):
    title: str | None = None
    subject: str | None = None
    subject_type: str | None = None
    examiner: str | None = None
    authority: str | None = None
    priority: str = "normal"
    summary: str | None = None
    status: str | None = None


class CaseSearch(BaseModel):
    target: str = Field(min_length=1, max_length=256)
    type: str | None = None


@router.get("")
async def list_cases(status: str | None = None, _t: str = security.Auth) -> list[dict]:
    return cases.list_cases(status)


@router.post("")
async def create_case(body: CaseBody, _t: str = security.Auth) -> dict:
    return cases.create_case(title=body.title, subject=body.subject,
                             subject_type=body.subject_type, examiner=body.examiner,
                             authority=body.authority, priority=body.priority)


@router.get("/{cid}")
async def get_case(cid: int, _t: str = security.Auth) -> dict:
    c = cases.get_case(cid)
    if not c:
        raise HTTPException(404, "No such case")
    return c


@router.put("/{cid}")
async def update_case(cid: int, body: CaseBody, _t: str = security.Auth) -> dict:
    c = cases.update_case(cid, **body.model_dump(exclude_none=True))
    if not c:
        raise HTTPException(404, "No such case")
    return c


@router.delete("/{cid}")
async def delete_case(cid: int, _t: str = security.Auth) -> dict:
    if not cases.delete_case(cid):
        raise HTTPException(404, "No such case")
    return {"ok": True}


@router.get("/{cid}/findings")
async def case_findings(cid: int, _t: str = security.Auth) -> list[dict]:
    import json
    rows = orchestrate.db.query(
        "SELECT * FROM findings WHERE case_id=? ORDER BY created_at DESC", (cid,))
    out = []
    for r in rows:
        d = dict(r)
        for f in ("summary", "raw"):
            if d.get(f):
                try:
                    d[f] = json.loads(d[f])
                except Exception:
                    pass
        out.append(d)
    return out


@router.post("/{cid}/search")
async def case_search(cid: int, body: CaseSearch, _t: str = security.Auth) -> dict:
    if not cases.get_case(cid):
        raise HTTPException(404, "No such case")
    try:
        return orchestrate.search_all(body.target, body.type, case_id=cid)
    except ValidationError as exc:
        raise HTTPException(422, str(exc))


@router.get("/{cid}/graph")
async def case_graph(cid: int, _t: str = security.Auth) -> dict:
    if not cases.get_case(cid):
        raise HTTPException(404, "No such case")
    return graph.build_for_case(cid)


@router.get("/{cid}/report", response_class=HTMLResponse)
async def case_report(cid: int, _t: str = security.Auth) -> HTMLResponse:
    html_doc = report.render_case_html(cid)
    if html_doc is None:
        raise HTTPException(404, "No such case")
    return HTMLResponse(html_doc)
