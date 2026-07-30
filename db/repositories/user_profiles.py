"""Repositorio de perfiles de usuario para scoring personalizado (Feature B).

Cada usuario puede tener un perfil con pesos de scoring propios, keywords de
afinidad, filtros de CPV/CCAA y rango de importe ejecutable.

Almacenado en user_profiles (migracion v49): PK = user_key, columnas JSON.
"""

from __future__ import annotations

import json
from typing import Any

from db.database import connect, connect_read
from observability.logging import get_logger

log = get_logger(__name__)


def get_user_profile(user_key: str, organization_id: int | None = None) -> dict[str, Any] | None:
    """Carga el perfil del usuario. Devuelve None si no tiene perfil."""
    with connect_read() as c:
        if organization_id is None:
            row = c.execute(
                "SELECT user_key, weights_json, afinidad_keywords_json, "
                "cpvs_json, ccaa_json, importe_min, importe_max, updated_at, "
                "organization_id, visibility "
                "FROM user_profiles WHERE user_key = ?",
                (user_key,),
            ).fetchone()
        else:
            row = c.execute(
                "SELECT user_key, weights_json, afinidad_keywords_json, "
                "cpvs_json, ccaa_json, importe_min, importe_max, updated_at, "
                "organization_id, visibility "
                "FROM user_profiles WHERE organization_id = ? "
                "AND (visibility = 'organization' OR user_key = ?) "
                "ORDER BY CASE WHEN user_key = ? THEN 0 ELSE 1 END, updated_at DESC LIMIT 1",
                (organization_id, user_key, user_key),
            ).fetchone()
    if row is None:
        return None
    cols = [
        "user_key",
        "weights_json",
        "afinidad_keywords_json",
        "cpvs_json",
        "ccaa_json",
        "importe_min",
        "importe_max",
        "updated_at",
        "organization_id",
        "visibility",
    ]
    raw = dict(zip(cols, row, strict=False))
    # Deserializar JSON columns
    result: dict[str, Any] = {"user_key": raw["user_key"], "updated_at": raw["updated_at"]}
    for json_col in ("weights_json", "afinidad_keywords_json", "cpvs_json", "ccaa_json"):
        key = json_col.replace("_json", "")
        try:
            result[key] = json.loads(raw[json_col]) if raw[json_col] else None
        except (json.JSONDecodeError, TypeError):
            result[key] = None
    result["importe_min"] = raw["importe_min"]
    result["importe_max"] = raw["importe_max"]
    result["organization_id"] = raw["organization_id"]
    result["visibility"] = raw["visibility"]
    return result


def upsert_user_profile(
    user_key: str,
    profile: dict[str, Any],
    organization_id: int | None = None,
    visibility: str = "private",
) -> None:
    """Crea o actualiza el perfil del usuario."""
    from db.database import now_utc_iso

    weights = profile.get("weights")
    afinidad = profile.get("afinidad_keywords")
    cpvs = profile.get("cpvs")
    ccaas = profile.get("ccaa")
    importe_min = profile.get("importe_min")
    importe_max = profile.get("importe_max")

    with connect() as c:
        c.execute(
            "INSERT INTO user_profiles "
            "(user_key, weights_json, afinidad_keywords_json, cpvs_json, ccaa_json, "
            " importe_min, importe_max, updated_at, organization_id, visibility) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_key) DO UPDATE SET "
            "weights_json = excluded.weights_json, "
            "afinidad_keywords_json = excluded.afinidad_keywords_json, "
            "cpvs_json = excluded.cpvs_json, "
            "ccaa_json = excluded.ccaa_json, "
            "importe_min = excluded.importe_min, "
            "importe_max = excluded.importe_max, "
            "updated_at = excluded.updated_at, "
            "organization_id = excluded.organization_id, "
            "visibility = excluded.visibility",
            (
                user_key,
                json.dumps(weights) if weights is not None else None,
                json.dumps(afinidad) if afinidad is not None else None,
                json.dumps(cpvs) if cpvs is not None else None,
                json.dumps(ccaas) if ccaas is not None else None,
                importe_min,
                importe_max,
                now_utc_iso(),
                organization_id,
                visibility,
            ),
        )
    log.info("user_profile_upserted", user_key=user_key[:8])


def delete_user_profile(user_key: str) -> bool:
    """Elimina el perfil del usuario. Devuelve True si existia."""
    with connect() as c:
        cur = c.execute("DELETE FROM user_profiles WHERE user_key = ?", (user_key,))
        return bool(cur.rowcount > 0)
