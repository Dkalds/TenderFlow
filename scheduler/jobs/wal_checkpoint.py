"""WAL checkpoint — truncate the SQLite write-ahead log to reclaim disk space."""

from __future__ import annotations

from typing import Any


def run() -> dict[str, Any]:
    """Execute ``PRAGMA wal_checkpoint(TRUNCATE)`` and return the result."""
    from db.database import connect

    with connect() as c:
        row = c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    return {"blocked": row[0], "wal_pages": row[1], "checkpointed": row[2]} if row else {}
