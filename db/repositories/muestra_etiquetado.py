"""Muestra estratificada para el etiquetado humano de «¿es TI?» (F2, plan 3.2).

La muestra de F2 del plan de tres niveles (``tecnologia_pliego``,
``--muestra 4000``) es la de **entrada del LLM**: 4.000 filas estratificadas por
fuente x CPV x idioma x keyword x banda del modelo, pendientes de señal LLM.
Esta es otra pregunta: ~400 licitaciones que **una persona** etiqueta sin ver la
propuesta de nadie, para que el golden (``tests/fixtures/golden_ti.jsonl``) no
dependa de que antes se haya lanzado el LLM (D3 sigue pendiente).

Estratos: fuente (``pscp``/``ted``/``placsp``/``otras``) x CPV (48/72/otros) x
si tiene keyword x año de publicación (uno por año desde ``anio_desde``, el
resto en ``antes`` y ``sin_fecha``). El año está porque el holdout del golden es
temporal (el 50 % más reciente, ``services.ml.golden_ti.repartir``): sin él, la
muestra podría caer casi entera a un lado del corte. No se estratifica por banda
del modelo: el golden es el que va a juzgar a ese modelo.

Fuera las filas que ``licitaciones_duplicados`` marca ``confirmed``: etiquetar
dos veces el mismo contrato gasta tiempo humano y pesa doble en el gate.

La selección es la misma técnica que ``TecnologiaPliegoRepository.
list_muestra_pending_llm_signal``: ``row_number()`` por estrato ordenado por
``md5(id_externo || semilla)`` y cortado en la cuota que calcula
``services.ml.muestra_estratificada.repartir_cuotas``. Misma semilla y misma
tabla, misma muestra.

Sin ``%`` literal en el SQL: se ejecuta con parámetros por nombre (ver el
comentario de ``_ESTRATO_MUESTRA_SQL`` en ``tecnologia_pliego``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any  # filas psycopg heterogéneas, como el resto de db/repositories

from db.database import connect_read
from db.repositories.base import rows_to_dicts

#: Las dos consultas recorren ``licitaciones`` entera para agrupar o rankear;
#: son manuales y puntuales, con techo propio (mismo criterio que la muestra
#: del LLM).
_STATEMENT_TIMEOUT_MS = 120_000

ESTRATO_ETIQUETADO_SQL = (
    "("
    "CASE WHEN l.fuente = 'pscp' THEN 'pscp' "
    "WHEN l.fuente = 'ted' THEN 'ted' "
    "WHEN starts_with(l.fuente, 'placsp') OR starts_with(l.fuente, 'bulk_') THEN 'placsp' "
    "ELSE 'otras' END"
    " || '|' || "
    "CASE WHEN coalesce(l.cpv, '') ~ '(^|[^0-9])48[0-9]{6}' THEN '48' "
    "WHEN coalesce(l.cpv, '') ~ '(^|[^0-9])72[0-9]{6}' THEN '72' "
    "ELSE 'otros' END"
    " || '|' || "
    "CASE WHEN coalesce(l.tecnologia, '') <> '' THEN 'kw' ELSE 'sin_kw' END"
    " || '|' || "
    "CASE WHEN coalesce(l.fecha_publicacion, '') !~ '^[0-9]{4}' THEN 'sin_fecha' "
    "WHEN substr(l.fecha_publicacion, 1, 4)::int < %(anio_desde)s THEN 'antes' "
    "ELSE substr(l.fecha_publicacion, 1, 4) END"
    ")"
)

_SIN_DUPLICADOS_SQL = (
    "NOT EXISTS (SELECT 1 FROM licitaciones_duplicados d "
    "WHERE d.licitacion_id = l.id_externo AND d.status = 'confirmed')"
)

SQL_TAMANOS = (
    f"SELECT {ESTRATO_ETIQUETADO_SQL} AS estrato, count(*) AS n "
    f"FROM licitaciones l WHERE {_SIN_DUPLICADOS_SQL} GROUP BY 1 ORDER BY 1"
)

SQL_SELECCION = (
    "WITH cupos AS ("
    "  SELECT * FROM unnest(%(estratos)s::text[], %(cuotas)s::int[]) AS u(estrato, cuota)"
    "), rankeadas AS ("
    f"  SELECT l.id_externo, {ESTRATO_ETIQUETADO_SQL} AS estrato, "
    "         row_number() OVER ("
    f"           PARTITION BY {ESTRATO_ETIQUETADO_SQL} "
    "           ORDER BY md5(l.id_externo || %(semilla)s)"
    "         ) AS rango "
    f"  FROM licitaciones l WHERE {_SIN_DUPLICADOS_SQL}"
    ") "
    "SELECT r.estrato, r.rango, l.id_externo, l.fuente, l.fecha_publicacion, l.titulo, "
    "left(l.descripcion, 1500) AS descripcion, l.cpv, l.organo_contratacion, l.url "
    "FROM rankeadas r "
    "JOIN cupos q ON q.estrato = r.estrato AND r.rango <= q.cuota "
    "JOIN licitaciones l ON l.id_externo = r.id_externo "
    "ORDER BY r.estrato, r.rango"
)


def tamanos_estratos(*, anio_desde: int) -> dict[str, int]:
    """Tamaño de cada estrato (sin duplicados confirmados)."""
    with connect_read(statement_timeout_ms=_STATEMENT_TIMEOUT_MS) as c:
        cur = c.execute(SQL_TAMANOS, {"anio_desde": anio_desde})
        return {str(fila[0]): int(fila[1]) for fila in cur.fetchall()}


def seleccionar(
    *, cuotas: Mapping[str, int], semilla: str, anio_desde: int
) -> list[dict[str, Any]]:
    """Las licitaciones de la muestra, en orden determinista (estrato, rango)."""
    if not cuotas:
        return []
    estratos = sorted(cuotas)
    with connect_read(statement_timeout_ms=_STATEMENT_TIMEOUT_MS) as c:
        cur = c.execute(
            SQL_SELECCION,
            {
                "estratos": estratos,
                "cuotas": [int(cuotas[e]) for e in estratos],
                "semilla": semilla,
                "anio_desde": anio_desde,
            },
        )
        return rows_to_dicts(cur)
