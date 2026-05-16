"""Feature store ligero — cache de embeddings y predicciones por entidad.

La tabla ``feature_store`` (ya en SCHEMA) almacena features computadas para
evitar re-cómputo en cada petición:

  entity_type : "licitacion" | "fragment" | "cpv"
  entity_id   : id_externo / hash del texto
  feature_name: "embedding_v1" | "sap_score" | "labels_v2" | "tfidf_vector"
  value_json  : JSON serializado de la feature (lista de floats, dict, etc.)
  version     : versión del modelo/vectorizador
  computed_at : ISO timestamp
"""

from __future__ import annotations

import json
from typing import Any

from db.database import connect, now_utc_iso


def set_feature(
    entity_type: str,
    entity_id: str,
    feature_name: str,
    value: Any,
    *,
    version: str = "v1",
) -> None:
    """Guarda o actualiza una feature en el store."""
    value_json = json.dumps(value, ensure_ascii=False)
    with connect() as c:
        c.execute(
            "INSERT INTO feature_store "
            "(entity_type, entity_id, feature_name, value_json, version, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(entity_type, entity_id, feature_name, version) "
            "DO UPDATE SET value_json=excluded.value_json, computed_at=excluded.computed_at",
            (entity_type, entity_id, feature_name, value_json, version, now_utc_iso()),
        )


def get_feature(
    entity_type: str,
    entity_id: str,
    feature_name: str,
    *,
    version: str = "v1",
) -> Any | None:
    """Recupera una feature o None si no existe."""
    with connect() as c:
        row = c.execute(
            "SELECT value_json FROM feature_store "
            "WHERE entity_type=? AND entity_id=? AND feature_name=? AND version=?",
            (entity_type, entity_id, feature_name, version),
        ).fetchone()
    return json.loads(row[0]) if row else None


def get_features_bulk(
    entity_type: str,
    entity_ids: list[str],
    feature_name: str,
    *,
    version: str = "v1",
) -> dict[str, Any]:
    """Recupera un dict {entity_id: value} para múltiples entidades."""
    if not entity_ids:
        return {}
    placeholders = ",".join("?" for _ in entity_ids)
    with connect() as c:
        rows = c.execute(
            f"SELECT entity_id, value_json FROM feature_store "
            f"WHERE entity_type=? AND feature_name=? AND version=? "
            f"AND entity_id IN ({placeholders})",
            [entity_type, feature_name, version, *entity_ids],
        ).fetchall()
    return {row[0]: json.loads(row[1]) for row in rows}


def delete_feature(
    entity_type: str,
    entity_id: str,
    feature_name: str | None = None,
    *,
    version: str | None = None,
) -> int:
    """Elimina features; si feature_name es None, borra todas las del entity."""
    with connect() as c:
        if feature_name is None:
            cur = c.execute(
                "DELETE FROM feature_store WHERE entity_type=? AND entity_id=?",
                (entity_type, entity_id),
            )
        elif version is None:
            cur = c.execute(
                "DELETE FROM feature_store WHERE entity_type=? AND entity_id=? AND feature_name=?",
                (entity_type, entity_id, feature_name),
            )
        else:
            cur = c.execute(
                "DELETE FROM feature_store "
                "WHERE entity_type=? AND entity_id=? AND feature_name=? AND version=?",
                (entity_type, entity_id, feature_name, version),
            )
        return cur.rowcount if hasattr(cur, "rowcount") else 0


def purge_stale_features(*, older_than_days: int = 30) -> int:
    """Elimina features no actualizadas en N días (para evitar crecimiento indefinido)."""
    from datetime import UTC, datetime, timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
    with connect() as c:
        cur = c.execute("DELETE FROM feature_store WHERE computed_at < ?", (cutoff,))
        return cur.rowcount if hasattr(cur, "rowcount") else 0


def feature_stats() -> dict[str, Any]:
    """Estadísticas del feature store (tamaño por tipo/nombre)."""
    with connect() as c:
        rows = c.execute(
            "SELECT entity_type, feature_name, version, COUNT(*) as n "
            "FROM feature_store GROUP BY entity_type, feature_name, version "
            "ORDER BY n DESC LIMIT 100"
        ).fetchall()
    return [{"entity_type": r[0], "feature_name": r[1], "version": r[2], "n": r[3]} for r in rows]
