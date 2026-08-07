"""Repository para ml_feedback."""

from __future__ import annotations

from typing import Any, cast

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)


class FeedbackRepository:
    def insert(
        self,
        *,
        expediente: str,
        relevante: bool,
        nota: str,
        tecnologia: str | None = None,
        tecnologias_secundarias: list[str] | None = None,
        model_version: int | None = None,
        user_id: int | None = None,
    ) -> str:
        """Inserta feedback y devuelve el timestamp de creación."""
        import json

        now = now_utc_iso()
        ts_json = (
            json.dumps(tecnologias_secundarias, ensure_ascii=False)
            if tecnologias_secundarias
            else None
        )
        with connect() as c:
            c.execute(
                "INSERT INTO ml_feedback "
                "(expediente, relevante, nota, tecnologia, tecnologias_secundarias, model_version, user_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    expediente,
                    1 if relevante else 0,
                    nota,
                    tecnologia,
                    ts_json,
                    model_version,
                    user_id,
                    now,
                ),
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

    def labeled_expedientes(self, prefix: str = "active_learning_dashboard:") -> set[str]:
        """Devuelve expedientes ya etiquetados (por prefijo de nota)."""
        with connect_read() as c:
            rows = c.execute(
                "SELECT DISTINCT expediente FROM ml_feedback WHERE nota LIKE ? || '%'",
                (prefix,),
            ).fetchall()
        return {str(r[0]) for r in rows}

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
            return cast(dict[str, Any], json.loads(row[0]))
        except Exception:
            # Un JSON corrupto en la caché de idempotencia se presenta como
            # "esta key no existe", así que la petición se reprocesa como nueva
            # — justo lo que la idempotencia venía a evitar.
            log.warning("feedback_idempotency_payload_corrupto", exc_info=True)
            return None

    def store_idempotency(self, key: str, response: dict[str, Any]) -> None:
        import json

        with connect() as c:
            c.execute(
                "INSERT INTO idempotency_keys "
                "(idem_key, endpoint, response_json, created_at) "
                "VALUES (?, 'feedback', ?, ?) "
                "ON CONFLICT(idem_key, endpoint) DO NOTHING",
                (key, json.dumps(response, ensure_ascii=False), now_utc_iso()),
            )

    def export_all(self, limit: int = 10_000) -> list[dict[str, Any]]:
        """Exporta todo el ML feedback (anónimo, sin FK a usuario). Para GDPR."""
        with connect_read() as c:
            cur = c.execute("SELECT * FROM ml_feedback LIMIT ?", (limit,))
            return rows_to_dicts(cur)

    def export_for_user(self, user_id: int, limit: int = 10_000) -> list[dict[str, Any]]:
        """Exporta exclusivamente el feedback atribuible a un usuario."""
        with connect_read() as c:
            cur = c.execute("SELECT * FROM ml_feedback WHERE user_id = ? LIMIT ?", (user_id, limit))
            return rows_to_dicts(cur)

    def delete_for_user(self, user_id: int) -> int:
        """Elimina el feedback personal como parte del derecho de supresión."""
        with connect() as c:
            cur = c.execute("DELETE FROM ml_feedback WHERE user_id = ?", (user_id,))
            return int(cur.rowcount or 0)
