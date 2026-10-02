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
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(entity_type, entity_id, feature_name, version) "
            "DO UPDATE SET value_json=excluded.value_json, computed_at=excluded.computed_at",
            (entity_type, entity_id, feature_name, value_json, version, now_utc_iso()),
        )


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
    placeholders = ",".join("%s" for _ in entity_ids)
    with connect() as c:
        rows = c.execute(
            f"SELECT entity_id, value_json FROM feature_store "
            f"WHERE entity_type=%s AND feature_name=%s AND version=%s "
            f"AND entity_id IN ({placeholders})",
            [entity_type, feature_name, version, *entity_ids],
        ).fetchall()
    return {row[0]: json.loads(row[1]) for row in rows}
