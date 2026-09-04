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


_PROFILE_COLS = (
    "SELECT user_key, weights_json, afinidad_keywords_json, "
    "cpvs_json, ccaa_json, importe_min, importe_max, updated_at, "
    "organization_id, visibility FROM user_profiles "
)


def get_user_profile(user_key: str, organization_id: int) -> dict[str, Any] | None:
    """Perfil visible dentro de ``organization_id``. ``None`` si no hay.

    ``organization_id`` es obligatoria. Tenía default ``None`` y esa rama caía
    a ``WHERE user_key = %s``, sin ámbito: quien omitía el argumento no elegía
    esa semántica, la heredaba en silencio. El camino sin organización sigue
    existiendo, pero hay que pedirlo por su nombre
    (:func:`get_own_user_profile`).
    """
    with connect_read() as c:
        row = c.execute(
            _PROFILE_COLS + "WHERE organization_id = %s "
            "AND (visibility = 'organization' OR user_key = %s) "
            "ORDER BY CASE WHEN user_key = %s THEN 0 ELSE 1 END, updated_at DESC LIMIT 1",
            (organization_id, user_key, user_key),
        ).fetchone()
    return _row_to_profile(row)


def get_own_user_profile(user_key: str) -> dict[str, Any] | None:
    """Perfil propio del usuario, deliberadamente sin ámbito de organización.

    Es el camino del export GDPR (Art. 15/20) y de los llamadores que todavía
    no tienen una organización resuelta: la pregunta ahí es «qué guarda el
    sistema sobre esta persona», no «qué ve este equipo». Se separa de
    :func:`get_user_profile` para que la ausencia de ámbito sea una decisión
    escrita en el nombre de la función y no el default de un parámetro.
    """
    with connect_read() as c:
        row = c.execute(
            _PROFILE_COLS + "WHERE user_key = %s",
            (user_key,),
        ).fetchone()
    return _row_to_profile(row)


def _row_to_profile(row: Any) -> dict[str, Any] | None:
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
    organization_id: int,
    visibility: str = "private",
) -> None:
    """Crea o actualiza el perfil del usuario.

    ``organization_id`` sin default: escribir una fila con organización nula
    la deja invisible para :func:`get_user_profile`, que sí filtra por ámbito.
    """
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
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
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
        cur = c.execute("DELETE FROM user_profiles WHERE user_key = %s", (user_key,))
        return bool(cur.rowcount > 0)
