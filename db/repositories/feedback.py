"""Repository para ml_feedback."""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts


class FeedbackRepository:
    def insert(self, *, expediente: str, relevante: bool, nota: str) -> str:
        """Inserta feedback y devuelve el timestamp de creación."""
        now = now_utc_iso()
        with connect() as c:
            c.execute(
                "INSERT INTO ml_feedback (expediente, relevante, nota, created_at) "
                "VALUES (?, ?, ?, ?)",
                (expediente, 1 if relevante else 0, nota, now),
            )
        return now

    def stats(self) -> dict[str, Any]:
        with connect_read() as c:
            row = c.execute(
                "SELECT "
                "  COUNT(*) AS total, "
                "  SUM(CASE WHEN relevante=1 THEN 1 ELSE 0 END) AS positivos, "
                "  SUM(CASE WHEN relevante=0 THEN 1 ELSE 0 END) AS negativos, "
                "  MAX(created_at) AS last_feedback_at "
                "FROM ml_feedback"
            ).fetchone()
        if not row:
            return {"total": 0, "positivos": 0, "negativos": 0, "last_feedback_at": None}
        return dict(zip(["total", "positivos", "negativos", "last_feedback_at"], row, strict=False))

    def exists_idempotency(self, key: str) -> dict[str, Any] | None:
        """Devuelve la respuesta cacheada si la idempotency key ya existe."""
        with connect_read() as c:
            row = c.execute(
                "SELECT response_json, created_at FROM idempotency_keys "
                "WHERE idem_key = ? AND endpoint = 'feedback'",
                (key,),
            ).fetchone()
        if not row:
            return None
        import json
        try:
            return json.loads(row[0])
        except Exception:
            return None

    def store_idempotency(self, key: str, response: dict[str, Any]) -> None:
        import json
        with connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO idempotency_keys "
                "(idem_key, endpoint, response_json, created_at) "
                "VALUES (?, 'feedback', ?, ?)",
                (key, json.dumps(response, ensure_ascii=False), now_utc_iso()),
            )
