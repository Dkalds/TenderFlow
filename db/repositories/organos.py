"""Persistencia del maestro de órganos de contratación (C1.2, ADR-032, D22).

Todo el SQL del maestro vive aquí (ADR-022). La lógica de resolución —qué
grafías son el mismo órgano, cuándo hace falta que lo mire un humano— está en
``services/organos.py``: es dominio, no persistencia.

El esquema lo crea ``v114``; ``licitaciones.organo_id`` lo añade ``v115``.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

#: Estados de la cola de revisión. Mismo vocabulario que `empresa_review_queue`.
ESTADOS_REVISION = ("pending", "accepted", "rejected")


def get_by_dir3(dir3: str) -> dict[str, Any] | None:
    """Órgano por su código DIR3. Es la resolución sin ambigüedad."""
    with connect_read() as c:
        filas = rows_to_dicts(c.execute("SELECT * FROM organos WHERE dir3 = %s LIMIT 1", (dir3,)))
    return filas[0] if filas else None


def get_by_nombre_normalizado(nombre_normalizado: str) -> dict[str, Any] | None:
    """Órgano por su nombre normalizado, mirando también los alias.

    Los alias importan: el maestro guarda **una** grafía canónica, y las demás
    llegan por `organo_aliases`. Sin consultarlos, cada variante crearía un
    órgano nuevo y el maestro no serviría de nada.
    """
    with connect_read() as c:
        filas = rows_to_dicts(
            c.execute(
                "SELECT o.* FROM organos o "
                "WHERE o.nombre_normalizado = %s "
                "UNION ALL "
                "SELECT o.* FROM organos o "
                "JOIN organo_aliases a ON a.organo_id = o.organo_id "
                "WHERE a.alias_normalizado = %s "
                "LIMIT 1",
                (nombre_normalizado, nombre_normalizado),
            )
        )
    return filas[0] if filas else None


def crear(
    *,
    nombre_canonico: str,
    nombre_normalizado: str,
    dir3: str | None = None,
    ccaa: str | None = None,
    tipo: str | None = None,
    url_perfil: str | None = None,
) -> int:
    """Crea un órgano y devuelve su id. Idempotente por DIR3 y por nombre.

    El `ON CONFLICT DO NOTHING` más el `SELECT` de rescate cubren la carrera
    entre dos lotes del backfill: los índices únicos de `v114` son la garantía
    real, y este código solo evita que la carrera sea un error.
    """
    ahora = now_utc_iso()
    with connect() as c:
        c.execute(
            "INSERT INTO organos "
            "(dir3, nombre_canonico, nombre_normalizado, ccaa, tipo, url_perfil, "
            " created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (dir3, nombre_canonico, nombre_normalizado, ccaa, tipo, url_perfil, ahora, ahora),
        )
        fila = c.execute(
            "SELECT organo_id FROM organos WHERE nombre_normalizado = %s",
            (nombre_normalizado,),
        ).fetchone()
    if not fila:
        raise RuntimeError(f"no se pudo crear ni recuperar el órgano {nombre_normalizado!r}")
    return int(fila[0])


def anadir_alias(
    organo_id: int,
    *,
    alias_normalizado: str,
    alias_original: str | None = None,
    dir3_variante: str | None = None,
    fuente: str = "",
    confianza: float = 1.0,
) -> None:
    """Registra una grafía del órgano. Idempotente por `(organo_id, alias)`."""
    with connect() as c:
        c.execute(
            "INSERT INTO organo_aliases "
            "(organo_id, alias_normalizado, alias_original, dir3_variante, fuente, "
            " confianza, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (
                organo_id,
                alias_normalizado,
                alias_original,
                dir3_variante,
                fuente,
                confianza,
                now_utc_iso(),
            ),
        )


def encolar_revision(
    *,
    nombre_original: str,
    alias_normalizado: str,
    dir3: str | None = None,
    candidato_organo_id: int | None = None,
    score: float = 0.0,
) -> None:
    """Encola una fusión dudosa para que la decida un humano.

    Dos organismos distintos pueden tener nombres casi idénticos —los «Servicio
    de Salud» de dos comunidades— y fusionarlos junta dos historiales de
    contratación que no son el mismo. Ese error no se detecta mirando la ficha,
    así que no se decide solo.
    """
    with connect() as c:
        c.execute(
            "INSERT INTO organo_review_queue "
            "(nombre_original, alias_normalizado, dir3, candidato_organo_id, score, "
            " status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, 'pending', %s) "
            "ON CONFLICT DO NOTHING",
            (nombre_original, alias_normalizado, dir3, candidato_organo_id, score, now_utc_iso()),
        )


def listar_pendientes(*, limit: int = 200) -> list[dict[str, Any]]:
    """Cola de revisión pendiente, la más reciente primero."""
    with connect_read() as c:
        return rows_to_dicts(
            c.execute(
                "SELECT q.*, o.nombre_canonico AS candidato_nombre "
                "FROM organo_review_queue q "
                "LEFT JOIN organos o ON o.organo_id = q.candidato_organo_id "
                "WHERE q.status = 'pending' "
                "ORDER BY q.created_at DESC LIMIT %s",
                (limit,),
            )
        )


def asignar_a_licitaciones(organo_id: int, *, nombre_normalizado: str, limit: int) -> int:
    """Asigna `organo_id` a un lote de licitaciones con esa grafía.

    Por lotes porque la tabla tiene ~706k filas: un `UPDATE` de una sola pasada
    mantiene un lock largo sobre la tabla núcleo y bloquea la ingesta en curso.
    """
    with connect() as c:
        cur = c.execute(
            "UPDATE licitaciones SET organo_id = %s "
            "WHERE id_externo IN ("
            "  SELECT id_externo FROM licitaciones "
            "  WHERE organo_id IS NULL AND organo_contratacion IS NOT NULL "
            "    AND lower(btrim(organo_contratacion)) = %s "
            "  LIMIT %s"
            ")",
            (organo_id, nombre_normalizado, limit),
        )
        return int(cur.rowcount) if hasattr(cur, "rowcount") else 0


def grafias_sin_resolver(*, limit: int = 5_000) -> list[dict[str, Any]]:
    """Grafías distintas de `organo_contratacion` que aún no tienen `organo_id`.

    Ordenadas por volumen: resolver primero las que más expedientes arrastran
    hace que la cobertura suba rápido y que el delta sea visible desde el primer
    lote.
    """
    with connect_read() as c:
        return rows_to_dicts(
            c.execute(
                "SELECT organo_contratacion AS nombre, "
                "       lower(btrim(organo_contratacion)) AS nombre_plano, "
                "       COUNT(*) AS expedientes, "
                "       MAX(ccaa) AS ccaa "
                "FROM licitaciones "
                "WHERE organo_id IS NULL AND organo_contratacion IS NOT NULL "
                "  AND btrim(organo_contratacion) <> '' "
                "GROUP BY organo_contratacion "
                "ORDER BY COUNT(*) DESC LIMIT %s",
                (limit,),
            )
        )


def cobertura(*, fuente: str | None = None, desde: str | None = None) -> dict[str, int]:
    """Cuántos expedientes tienen `organo_id` resuelto.

    Es la métrica del criterio de aceptación de C1.2 (≥ 95 % de PLACSP en los
    últimos doce meses), y por eso acepta acotar por fuente y por fecha en vez
    de devolver solo el total.
    """
    condiciones = ["organo_contratacion IS NOT NULL"]
    params: list[Any] = []
    if fuente:
        condiciones.append("fuente = %s")
        params.append(fuente)
    if desde:
        condiciones.append("COALESCE(fecha_publicacion, fecha_extraccion) >= %s")
        params.append(desde)
    where = " AND ".join(condiciones)
    with connect_read() as c:
        fila = c.execute(
            "SELECT COUNT(*) AS total, "
            "  COUNT(organo_id) AS resueltos "
            f"FROM licitaciones WHERE {where}",
            params,
        ).fetchone()
    total = int(fila[0] or 0) if fila else 0
    resueltos = int(fila[1] or 0) if fila else 0
    return {"total": total, "resueltos": resueltos, "sin_resolver": total - resueltos}


def candidatos_por_palabras(palabras: list[str], *, limit: int = 50) -> list[dict[str, Any]]:
    """Órganos cuyo nombre normalizado contiene alguna de *palabras*.

    Acota el conjunto contra el que `services/organos.py` calcula similitud:
    comparar contra el maestro entero en cada grafía sería O(n) por resolución y
    el backfill no terminaría. Perder un candidato que no comparte ninguna
    palabra larga no cuesta nada — su similitud Jaccard sería 0 de todos modos.
    """
    if not palabras:
        return []
    condiciones = " OR ".join(["nombre_normalizado LIKE %s"] * len(palabras))
    params: list[Any] = [f"%{p}%" for p in palabras]
    params.append(limit)
    with connect_read() as c:
        return rows_to_dicts(
            c.execute(
                f"SELECT organo_id, nombre_normalizado FROM organos WHERE {condiciones} LIMIT %s",
                params,
            )
        )
