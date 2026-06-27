"""Detection, Search-All fan-out, and findings read endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import orchestrate, security
from .validators import ValidationError

router = APIRouter(prefix="/api", tags=["orchestrate"])


class Target(BaseModel):
    target: str = Field(min_length=1, max_length=256)
    type: str | None = None


@router.post("/detect")
async def detect(body: Target, _t: str = security.Auth) -> dict:
    return orchestrate.detect(body.target)


@router.post("/search-all")
async def search_all(body: Target, _t: str = security.Auth) -> dict:
    try:
        return orchestrate.search_all(body.target, body.type)
    except ValidationError as exc:
        raise HTTPException(422, str(exc))


@router.get("/findings")
async def findings(target: str, type: str | None = None, _t: str = security.Auth) -> list[dict]:
    return orchestrate.findings_for(target, type)
