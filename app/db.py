"""SQLite access layer.

One short-lived connection per call (WAL mode lets many readers + one writer
coexist). Synchronous sqlite3 calls are wrapped with ``asyncio.to_thread`` by
callers that run on the event loop, so a blocking write never stalls it.
"""
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import settings

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


def _connect() -> sqlite3.Connection:
    s = settings()
    conn = sqlite3.connect(s.db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db() -> None:
    """Apply the schema idempotently and reconcile stale jobs from a prior run."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        # Any job left 'running' or 'queued' when the process died is unreachable now.
        conn.execute(
            "UPDATE jobs SET status='error', error='server_restart', "
            "finished_at=datetime('now') WHERE status IN ('running','queued')"
        )
        conn.commit()


@contextmanager
def cursor(write: bool = False) -> Iterator[sqlite3.Cursor]:
    conn = _connect()
    try:
        yield conn.cursor()
        if write:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with cursor() as cur:
        cur.execute(sql, tuple(params))
        return cur.fetchall()


def query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    with cursor() as cur:
        cur.execute(sql, tuple(params))
        return cur.fetchone()


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    """Run a write (INSERT); return lastrowid."""
    with cursor(write=True) as cur:
        cur.execute(sql, tuple(params))
        return cur.lastrowid or 0


def write(sql: str, params: Iterable[Any] = ()) -> int:
    """Run a write (UPDATE/DELETE); return affected row count."""
    with cursor(write=True) as cur:
        cur.execute(sql, tuple(params))
        return cur.rowcount


# --- async wrappers (use from request/job code on the event loop) ---
async def aquery(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return await asyncio.to_thread(query, sql, tuple(params))


async def aquery_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return await asyncio.to_thread(query_one, sql, tuple(params))


async def aexecute(sql: str, params: Iterable[Any] = ()) -> int:
    return await asyncio.to_thread(execute, sql, tuple(params))


async def awrite(sql: str, params: Iterable[Any] = ()) -> int:
    return await asyncio.to_thread(write, sql, tuple(params))


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
