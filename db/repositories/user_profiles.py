"""Repositorio de perfiles de usuario para scoring personalizado (Feature B).

Cada usuario puede tener un perfil con pesos de scoring propios, keywords de
afinidad, filtros de CPV/CCAA y rango de importe ejecutable.

Almacenado en user_profiles (migracion v49): PK = user_key, columnas JSON.

Desde v129 (ADR-030 fase 2) la fila lleva también ``user_id`` y la lectura es
dual: con ``user_id`` conocido se busca por él —y por ``user_key`` sólo en las
filas que el backfill no resolvió—; sin él, por ``user_key`` como siempre.

Desde v135 (fase 3) la PK es ``user_id`` y **la escritura ya no pone
``user_key``**: el upsert es un ``ON CONFLICT (user_id)`` y un usuario tiene,
por construcción, un único perfil. La lectura dual se queda: no cuesta nada
(todas las filas tienen ``user_id``) y es la que sigue sirviendo las filas
viejas a quien llame sin id. Por eso todo llamador debe pasar ``user_id``:
sin él sólo se ven los perfiles escritos antes de esta fase.
"""

from __future__ import annotations

import json
from typing import Any

from db.database import connect, connect_read
from observability.logging import get_logger

log = get_logger(__name__)

#: Predicado de identidad dual. Parámetros: ``(user_id, user_key, user_id)``.
#: Ver ``db/repositories/watchlist.py`` para el razonamiento.
_IDENT = "(user_id = %s OR (user_key = %s AND (user_id IS NULL OR %s::int IS NULL)))"

_PROFILE_COLS = (
    "SELECT user_key, weights_json, afinidad_keywords_json, "
    "cpvs_json, ccaa_json, importe_min, importe_max, updated_at, "
    "organization_id, visibility, user_id FROM user_profiles "
)


def get_user_profile(
    user_key: str, organization_id: int, *, user_id: int | None = None
) -> dict[str, Any] | None:
    """Perfil visible dentro de ``organization_id``. ``None`` si no hay.

    ``organization_id`` es obligatoria. Tenía default ``None`` y esa rama caía
    a ``WHERE user_key = %s``, sin ámbito: quien omitía el argumento no elegía
    esa semántica, la heredaba en silencio. El camino sin organización sigue
    existiendo, pero hay que pedirlo por su nombre
    (:func:`get_own_user_profile`).

    El propio va antes que el compartido; entre varios propios (un usuario que
    cambió de correo y guardó bajo las dos claves antes de v129), el de la
    clave actual y después el más reciente.
    """
    with connect_read() as c:
        row = c.execute(
            _PROFILE_COLS + "WHERE organization_id = %s "
            f"AND (visibility = 'organization' OR {_IDENT}) "
            f"ORDER BY CASE WHEN {_IDENT} THEN 0 ELSE 1 END, "
            "CASE WHEN user_key = %s THEN 0 ELSE 1 END, updated_at DESC LIMIT 1",
            (organization_id, user_id, user_key, user_id, user_id, user_key, user_id, user_key),
        ).fetchone()
    return _row_to_profile(row)


def get_own_user_profile(user_key: str, *, user_id: int | None = None) -> dict[str, Any] | None:
    """Perfil propio del usuario, deliberadamente sin ámbito de organización.

    Es el camino del export GDPR (Art. 15/20) y de los llamadores que todavía
    no tienen una organización resuelta: la pregunta ahí es «qué guarda el
    sistema sobre esta persona», no «qué ve este equipo». Se separa de
    :func:`get_user_profile` para que la ausencia de ámbito sea una decisión
    escrita en el nombre de la función y no el default de un parámetro.
    """
    with connect_read() as c:
        row = c.execute(
            _PROFILE_COLS + f"WHERE {_IDENT} "
            "ORDER BY CASE WHEN user_key = %s THEN 0 ELSE 1 END, updated_at DESC LIMIT 1",
            (user_id, user_key, user_id, user_key),
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
        "user_id",
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
    result["user_id"] = raw["user_id"]
    return result


def upsert_user_profile(
    profile: dict[str, Any],
    organization_id: int,
    visibility: str = "private",
    *,
    user_id: int,
) -> None:
    """Crea o actualiza el perfil del usuario.

    ``organization_id`` sin default: escribir una fila con organización nula
    la deja invisible para :func:`get_user_profile`, que sí filtra por ámbito.

    Desde v135 (ADR-030 fase 3) la PK es ``user_id`` y la escritura sólo
    conoce esa identidad: ``user_id`` es obligatorio y la columna ``user_key``
    ya no se escribe. Las filas anteriores la conservan —nadie la borra— y el
    ``ON CONFLICT`` no la toca, así que un perfil viejo sigue leyéndose igual
    por cualquiera de los dos caminos de la lectura dual.
    """
    from db.database import now_utc_iso

    weights = profile.get("weights")
    afinidad = profile.get("afinidad_keywords")
    cpvs = profile.get("cpvs")
    ccaas = profile.get("ccaa")
    importe_min = profile.get("importe_min")
    importe_max = profile.get("importe_max")
    valores = (
        json.dumps(weights) if weights is not None else None,
        json.dumps(afinidad) if afinidad is not None else None,
        json.dumps(cpvs) if cpvs is not None else None,
        json.dumps(ccaas) if ccaas is not None else None,
        importe_min,
        importe_max,
        now_utc_iso(),
        organization_id,
        visibility,
    )

    with connect() as c:
        c.execute(
            "INSERT INTO user_profiles "
            "(weights_json, afinidad_keywords_json, cpvs_json, ccaa_json, "
            " importe_min, importe_max, updated_at, organization_id, visibility, user_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "weights_json = excluded.weights_json, "
            "afinidad_keywords_json = excluded.afinidad_keywords_json, "
            "cpvs_json = excluded.cpvs_json, "
            "ccaa_json = excluded.ccaa_json, "
            "importe_min = excluded.importe_min, "
            "importe_max = excluded.importe_max, "
            "updated_at = excluded.updated_at, "
            "organization_id = excluded.organization_id, "
            "visibility = excluded.visibility",
            (*valores, user_id),
        )
    log.info("user_profile_upserted", user_id=user_id)


def delete_user_profile(user_key: str, *, user_id: int | None = None) -> bool:
    """Elimina el perfil del usuario. Devuelve True si existia."""
    with connect() as c:
        cur = c.execute(
            f"DELETE FROM user_profiles WHERE {_IDENT}",
            (user_id, user_key, user_id),
        )
        return bool(cur.rowcount > 0)
