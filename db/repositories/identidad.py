"""Identidad de una licitación: resolución de ids anteriores e inventario de pisadas.

Fase A del RFC ``2026-10-24-rfc-identidad-placsp-organo-expediente``. Tres
preguntas, todas sobre ``licitaciones`` y ``licitaciones_id_anterior`` (v159):

1. **¿A qué fila apunta este id?** :func:`resolver_id_licitacion` devuelve el
   id exacto si existe y, si no, la fila a la que su alias redirige. Es la única
   función que las rutas de la API, la ficha pública y el MCP usan para
   aceptar un ``id_externo`` que un cliente guardó antes de una re-key.
2. **¿Qué ids viejos tuvo una fila?** :func:`registrar_id_anterior` escribe el
   alias (lo usará la migración de re-key de la fase B, con ``motivo`` propio) e
   :func:`ids_anteriores_de` los lista.
3. **¿Cuántas filas PLACSP pisó otro órgano?** :func:`inventario_pisadas_placsp`
   es la consulta de detección del RFC (§«Las filas ya pisadas») sobre
   ``licitaciones_history``: para cada ``id_externo`` de PLACSP, los órganos que
   aparecen en algún snapshot y no son el de la fila actual, con la similitud de
   órgano y título frente a ella. ``sim_organo < 0,5 AND sim_titulo < 0,5`` es
   pisada segura; el resto, renombre probable. Es una **cota inferior**: el
   historial empieza el 2026-05-22 y solo escribe snapshot cuando cambia un
   campo de ``HISTORY_TRACKED_FIELDS``.

Solo lectura salvo :func:`registrar_id_anterior`. Todo el SQL vive aquí
(ADR-022).
"""

from __future__ import annotations

from typing import Any, NamedTuple

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from shared.identidad_placsp import PREFIJOS_ACOTADOS_POR_ORGANO

__all__ = [
    "IdResuelto",
    "ResumenPisadas",
    "contar_expedientes_que_conviven",
    "contar_placsp_sin_organo_ref",
    "ids_anteriores_de",
    "inventario_pisadas_placsp",
    "registrar_id_anterior",
    "resolver_id_licitacion",
    "resumen_pisadas_placsp",
]

#: Umbral de `similarity` (pg_trgm) por debajo del cual órgano y título se
#: consideran distintos. Es el del RFC; el inventario lo devuelve por par para
#: que quien revise pueda mover la raya sin volver a consultar.
UMBRAL_SIMILITUD = 0.5

#: Filas del feed principal de PLACSP, en los dos carriles.
_ES_PLACSP_SQL = "(l.fuente = 'placsp' OR l.fuente LIKE 'bulk\\_%')"

#: Clave ya acotada por órgano: ``^(placsp|…):[^:]*:`` (misma alternancia que
#: ``shared.identidad_placsp``).
_CLAVE_ACOTADA_RE = "^(" + "|".join(PREFIJOS_ACOTADOS_POR_ORGANO) + "):[^:]*:"


class IdResuelto(NamedTuple):
    """El ``id_externo`` vigente de una licitación y cómo se llegó a él."""

    id_externo: str
    #: ``True`` si el id pedido era un alias de ``licitaciones_id_anterior``.
    via_alias: bool


def resolver_id_licitacion(id_externo: str) -> IdResuelto | None:
    """El id exacto si la fila existe; si no, el destino de su alias; si no, ``None``.

    Dos consultas por la clave primaria de cada tabla. El orden importa: una
    fila que exista con ese id manda aunque también haya un alias con el mismo
    texto (no debería pasar —la re-key inserta el alias al borrar la vieja—,
    pero si pasara, el dato real gana a la redirección).
    """
    with connect_read() as c:
        fila = c.execute(
            "SELECT id_externo FROM licitaciones WHERE id_externo = %s", (id_externo,)
        ).fetchone()
        if fila is not None:
            return IdResuelto(str(fila[0]), via_alias=False)
        alias = c.execute(
            "SELECT id_externo FROM licitaciones_id_anterior WHERE id_anterior = %s",
            (id_externo,),
        ).fetchone()
    if alias is None:
        return None
    return IdResuelto(str(alias[0]), via_alias=True)


def registrar_id_anterior(id_anterior: str, id_externo: str, *, motivo: str) -> bool:
    """Guarda que ``id_anterior`` redirige a ``id_externo``. ``False`` si ya existía.

    ``ON CONFLICT DO NOTHING``: el primer alias de un id manda; reejecutar la
    re-key no reescribe redirecciones. La FK exige que ``id_externo`` exista.
    """
    with connect() as c:
        cur = c.execute(
            "INSERT INTO licitaciones_id_anterior (id_anterior, id_externo, motivo, creado_en) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (id_anterior) DO NOTHING",
            (id_anterior, id_externo, motivo, now_utc_iso()),
        )
        return bool(cur.rowcount)


def ids_anteriores_de(id_externo: str) -> list[str]:
    """Los ids que una fila tuvo antes, en orden estable."""
    with connect_read() as c:
        filas = c.execute(
            "SELECT id_anterior FROM licitaciones_id_anterior "
            "WHERE id_externo = %s ORDER BY creado_en, id_anterior",
            (id_externo,),
        ).fetchall()
    return [str(f[0]) for f in filas]


# ── Inventario de pisadas ───────────────────────────────────────────────────

_INVENTARIO_SQL = f"""
WITH snap AS (
  SELECT h.id_externo, h.source, h.captured_at,
         (h.snapshot_json::jsonb) ->> 'organo_contratacion' AS organo,
         (h.snapshot_json::jsonb) ->> 'titulo' AS titulo
  FROM licitaciones_history h
  JOIN licitaciones l ON l.id_externo = h.id_externo
  WHERE {_ES_PLACSP_SQL}
    AND h.snapshot_json LIKE '{{%}}'
)
SELECT s.id_externo,
       l.organo_contratacion AS organo_actual,
       l.organo_ref_fuente AS organo_ref_fuente_actual,
       lower(btrim(s.organo)) AS organo_perdido,
       min(s.captured_at) AS primera,
       max(s.captured_at) AS ultima,
       count(*) AS snapshots,
       array_agg(DISTINCT s.source) AS carriles,
       max(similarity(lower(s.organo), lower(coalesce(l.organo_contratacion, '')))) AS sim_organo,
       max(similarity(lower(coalesce(s.titulo, '')), lower(coalesce(l.titulo, '')))) AS sim_titulo
FROM snap s
JOIN licitaciones l ON l.id_externo = s.id_externo
WHERE s.organo IS NOT NULL
  AND lower(btrim(s.organo)) <> lower(btrim(coalesce(l.organo_contratacion, '')))
GROUP BY s.id_externo, l.organo_contratacion, l.organo_ref_fuente, lower(btrim(s.organo))
ORDER BY s.id_externo, lower(btrim(s.organo))
"""


def inventario_pisadas_placsp() -> list[dict[str, Any]]:
    """Un par (``id_externo``, órgano perdido) por fila PLACSP con otro órgano en su historial.

    Columnas: ``id_externo``, ``organo_actual``, ``organo_ref_fuente_actual``,
    ``organo_perdido`` (plegado), ``primera``/``ultima`` (captura), ``snapshots``,
    ``carriles`` (``source`` de la historia: ``bulk_YYYYMM`` dice qué ZIP lo
    trajo), ``sim_organo`` y ``sim_titulo`` (``similarity`` de pg_trgm frente a
    la fila actual). Requiere ``pg_trgm`` (v143).
    """
    with connect_read() as c:
        return rows_to_dicts(c.execute(_INVENTARIO_SQL))


class ResumenPisadas(NamedTuple):
    """Las cifras del inventario, como las anota el RFC."""

    ids_afectados: int
    pares: int
    pares_seguros: int
    pares_dudosos: int


def resumen_pisadas_placsp(
    pares: list[dict[str, Any]], *, umbral: float = UMBRAL_SIMILITUD
) -> ResumenPisadas:
    """Agrega el inventario: cuántos ids, cuántos pares y cuántos son pisada segura."""
    seguros = sum(
        1
        for p in pares
        if float(p["sim_organo"] or 0.0) < umbral and float(p["sim_titulo"] or 0.0) < umbral
    )
    return ResumenPisadas(
        ids_afectados=len({p["id_externo"] for p in pares}),
        pares=len(pares),
        pares_seguros=seguros,
        pares_dudosos=len(pares) - seguros,
    )


def contar_placsp_sin_organo_ref() -> dict[str, int]:
    """Filas PLACSP sin ``organo_ref_fuente``, por fuente (puerta 1 de la fase B).

    La fase B no puede empezar mientras alguna quede: sin órgano no hay clave
    nueva que darle.
    """
    with connect_read() as c:
        filas = c.execute(
            "SELECT l.fuente, count(*) FROM licitaciones l "
            f"WHERE ({_ES_PLACSP_SQL} OR l.fuente = 'placsp_watched_company_awards') "
            "AND l.organo_ref_fuente IS NULL GROUP BY l.fuente ORDER BY l.fuente"
        ).fetchall()
    return {str(f[0]): int(f[1]) for f in filas}


def contar_expedientes_que_conviven() -> int:
    """Expedientes con la clave nueva que hoy tienen más de una fila (distintos órganos).

    Con la clave vieja esto era imposible —se pisaban—, así que la cifra es la
    medida directa de lo que la clave nueva recupera (consulta 9 del RFC). 0
    hasta que la fase B escriba la clave nueva.
    """
    with connect_read() as c:
        fila = c.execute(
            "SELECT count(*) FROM ("
            f"  SELECT regexp_replace(l.id_externo, '{_CLAVE_ACOTADA_RE}', '') AS exp "
            f"  FROM licitaciones l WHERE l.id_externo ~ '{_CLAVE_ACOTADA_RE}' "
            "  GROUP BY 1 HAVING count(*) > 1"
            ") x"
        ).fetchone()
    return int(fila[0]) if fila else 0
