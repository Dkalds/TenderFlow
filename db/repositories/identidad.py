"""Identidad de una licitación: resolución de ids anteriores e inventario de pisadas.

Fase A del RFC ``2026-10-24-rfc-identidad-placsp-organo-expediente``. Tres
preguntas, todas sobre ``licitaciones`` y ``licitaciones_id_anterior`` (v163):

1. **¿A qué fila apunta este id?** :func:`resolver_id_licitacion` devuelve el
   id exacto si existe y, si no, la fila a la que su alias redirige. Es la única
   función que las rutas de la API, la ficha pública y el MCP usan para
   aceptar un ``id_externo`` que un cliente guardó antes de una re-key.
2. **¿Qué ids viejos tuvo una fila?** :func:`registrar_id_anterior` escribe el
   alias (lo usará la migración de re-key de la fase B, con ``motivo`` propio) e
   :func:`ids_anteriores_de` los lista.
3. **¿De qué órgano es cada fila ya escrita?** :func:`filas_placsp_sin_organo_ref`
   y :func:`rellenar_organo_ref_fuente` sostienen la fase 2 del RFC
   (``scripts/rellenar_organo_ref_placsp.py``, lógica en
   ``scraper.relleno_organo_placsp``): el cruce por ``idEvl`` con los ZIP
   mensuales que da a cada fila el órgano que la escribió, sin el que la
   re-key (``v164_identidad_placsp_rekey``) no puede construir su clave.
   :func:`organo_ref_por_nombre` es su último respaldo, opt-in.
   :func:`colisiones_del_rekey_placsp` y :func:`borrar_licitaciones_en_colision`
   despejan la guarda «ya existen con la clave nueva» de esa revisión.
4. **¿Cuántas filas PLACSP pisó otro órgano?** :func:`inventario_pisadas_placsp`
   es la consulta de detección del RFC (§«Las filas ya pisadas») sobre
   ``licitaciones_history``: para cada ``id_externo`` de PLACSP, los órganos que
   aparecen en algún snapshot y no son el de la fila actual, con la similitud de
   órgano y título frente a ella. ``sim_organo < 0,5 AND sim_titulo < 0,5`` es
   pisada segura; el resto, renombre probable. Es una **cota inferior**: el
   historial empieza el 2026-05-22 y solo escribe snapshot cuando cambia un
   campo de ``HISTORY_TRACKED_FIELDS``.

Solo lectura salvo :func:`registrar_id_anterior`,
:func:`rellenar_organo_ref_fuente` y :func:`borrar_licitaciones_en_colision`. Todo el SQL vive aquí (ADR-022).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import NamedTuple, TypedDict

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts, typed_rows
from shared.identidad_placsp import PREFIJOS_ACOTADOS_POR_ORGANO

__all__ = [
    "ColisionRekey",
    "FilaSinOrgano",
    "IdResuelto",
    "ResumenPisadas",
    "borrar_licitaciones_en_colision",
    "colisiones_del_rekey_placsp",
    "contar_expedientes_que_conviven",
    "contar_placsp_sin_organo_ref",
    "filas_placsp_sin_organo_ref",
    "ids_anteriores_de",
    "inventario_pisadas_placsp",
    "organo_ref_por_nombre",
    "registrar_id_anterior",
    "rellenar_organo_ref_fuente",
    "resolver_id_licitacion",
    "resumen_pisadas_placsp",
]

#: Umbral de `similarity` (pg_trgm) por debajo del cual órgano y título se
#: consideran distintos. Es el del RFC; el inventario lo devuelve por par para
#: que quien revise pueda mover la raya sin volver a consultar.
UMBRAL_SIMILITUD = 0.5

#: Filas del feed principal de PLACSP, en los dos carriles.
_ES_PLACSP_SQL = "(l.fuente = 'placsp' OR l.fuente LIKE 'bulk\\_%')"

#: Toda fila cuya clave re-escribe ``v164_identidad_placsp_rekey``: el feed
#: principal, empresas vigiladas (y su carril bulk) y agregadas. Contratos
#: menores no: nació acotada.
_FAMILIA_REKEY_SQL = (
    "(l.fuente = 'placsp' OR l.fuente LIKE 'bulk\\_%' "
    "OR l.fuente = 'placsp_watched_company_awards' "
    "OR l.fuente LIKE 'placsp\\_watched\\_company\\_awards\\_bulk\\_%' "
    "OR l.fuente = 'placsp_agregadas')"
)

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


class PisadaPlacsp(TypedDict):
    """Una fila de :func:`inventario_pisadas_placsp` (los alias de su `SELECT`)."""

    id_externo: str
    organo_actual: str | None
    organo_ref_fuente_actual: str | None
    organo_perdido: str
    primera: datetime | str
    ultima: datetime | str
    snapshots: int
    carriles: list[str]
    sim_organo: float | None
    sim_titulo: float | None


def inventario_pisadas_placsp() -> list[PisadaPlacsp]:
    """Un par (``id_externo``, órgano perdido) por fila PLACSP con otro órgano en su historial.

    Columnas: ``id_externo``, ``organo_actual``, ``organo_ref_fuente_actual``,
    ``organo_perdido`` (plegado), ``primera``/``ultima`` (captura), ``snapshots``,
    ``carriles`` (``source`` de la historia: ``bulk_YYYYMM`` dice qué ZIP lo
    trajo), ``sim_organo`` y ``sim_titulo`` (``similarity`` de pg_trgm frente a
    la fila actual). Requiere ``pg_trgm`` (v143).
    """
    with connect_read() as c:
        return typed_rows(PisadaPlacsp, rows_to_dicts(c.execute(_INVENTARIO_SQL)))


class ResumenPisadas(NamedTuple):
    """Las cifras del inventario, como las anota el RFC."""

    ids_afectados: int
    pares: int
    pares_seguros: int
    pares_dudosos: int


def resumen_pisadas_placsp(
    pares: list[PisadaPlacsp], *, umbral: float = UMBRAL_SIMILITUD
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
            f"WHERE {_FAMILIA_REKEY_SQL} "
            "AND coalesce(l.organo_ref_fuente, '') = '' GROUP BY l.fuente ORDER BY l.fuente"
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


# ── Relleno de ``organo_ref_fuente`` (fase 2 del RFC) ───────────────────────


class FilaSinOrgano(TypedDict):
    """Una fila de la familia de la re-key sin ``organo_ref_fuente``."""

    id_externo: str
    fuente: str
    url: str | None
    organo_contratacion: str | None
    fecha_actualizacion_fuente: str | None
    fecha_publicacion: str | None


def filas_placsp_sin_organo_ref() -> list[FilaSinOrgano]:
    """Las filas que la re-key no puede re-escribir todavía: sin órgano de la fuente.

    Es la entrada del cruce de ``scripts/rellenar_organo_ref_placsp.py``. Unas
    25.000 filas en producción como mucho (2026-10-25): caben en memoria.
    """
    with connect_read() as c:
        cur = c.execute(
            "SELECT l.id_externo, l.fuente, l.url, l.organo_contratacion, "
            "l.fecha_actualizacion_fuente::text AS fecha_actualizacion_fuente, "
            "l.fecha_publicacion::text AS fecha_publicacion "
            f"FROM licitaciones l WHERE {_FAMILIA_REKEY_SQL} "
            "AND coalesce(l.organo_ref_fuente, '') = '' ORDER BY l.id_externo"
        )
        return typed_rows(FilaSinOrgano, rows_to_dicts(cur))


def rellenar_organo_ref_fuente(asignaciones: Sequence[tuple[str, str]]) -> int:
    """Escribe ``organo_ref_fuente`` en las filas que aún no lo tienen. Devuelve cuántas.

    ``asignaciones`` son pares ``(id_externo, órgano)``. **Nunca pisa** un valor
    ya escrito (solo toca filas con la columna vacía): reejecutar el relleno, o
    cruzarse con la ingesta —que desde la fase A la escribe con el valor de la
    entrada—, no cambia nada. Es lo que hace idempotente al script.
    """
    if not asignaciones:
        return 0
    actualizadas = 0
    with connect() as c:
        for id_externo, organo in asignaciones:
            cur = c.execute(
                "UPDATE licitaciones SET organo_ref_fuente = %s "
                "WHERE id_externo = %s AND coalesce(organo_ref_fuente, '') = ''",
                (organo, id_externo),
            )
            actualizadas += cur.rowcount or 0
    return actualizadas


def organo_ref_por_nombre() -> dict[str, str]:
    """Último respaldo del relleno: el órgano deducido del nombre, solo si es inequívoco.

    Para cada fila sin órgano, el ``organo_ref_fuente`` que **todas** las filas
    de la familia con el mismo ``organo_contratacion`` (plegado) ya tienen,
    cuando es uno solo. ``ID_PLATAFORMA`` es 1:1 con el nombre del órgano en el
    feed (0 de 4.830 entradas con dos nombres, RFC §«Lo medido»), pero un nombre
    genérico podría no serlo: por eso se exige unanimidad y el script lo usa
    solo con ``--respaldo-por-nombre``, después del cruce por ``idEvl``.
    """
    with connect_read() as c:
        filas = c.execute(
            "WITH conocidos AS ("
            "  SELECT lower(btrim(l.organo_contratacion)) AS nombre, "
            "         min(l.organo_ref_fuente) AS organo "
            f"  FROM licitaciones l WHERE {_FAMILIA_REKEY_SQL} "
            "    AND coalesce(l.organo_ref_fuente, '') <> '' "
            "    AND coalesce(btrim(l.organo_contratacion), '') <> '' "
            "  GROUP BY 1 HAVING count(DISTINCT l.organo_ref_fuente) = 1"
            ") "
            "SELECT l.id_externo, k.organo FROM licitaciones l "
            "JOIN conocidos k ON k.nombre = lower(btrim(l.organo_contratacion)) "
            f"WHERE {_FAMILIA_REKEY_SQL} AND coalesce(l.organo_ref_fuente, '') = ''"
        ).fetchall()
    return {str(f[0]): str(f[1]) for f in filas}


# ── Colisiones de la re-key (guarda «ya existen con la clave nueva» de v164) ──

#: Expresiones del mapa ``viejo → nuevo`` de ``v164_identidad_placsp_rekey``,
#: copiadas de allí (una migración no se importa). Si cambian en la revisión,
#: cambian aquí: el test de integración aplica v164 después de borrar y
#: comprobaría que la guarda sigue encontrando la clave ocupada.
_ES_WATCHED_SQL = (
    "(l.fuente = 'placsp_watched_company_awards' "
    "OR l.fuente LIKE 'placsp\\_watched\\_company\\_awards\\_bulk\\_%')"
)
_PREFIJO_REKEY_SQL = (
    f"CASE WHEN {_ES_PLACSP_SQL} THEN 'placsp' "
    f"WHEN {_ES_WATCHED_SQL} THEN 'placsp_watched_company_awards' "
    "ELSE 'placsp_agregadas' END"
)
_CABEZA_NUEVA_SQL = (
    f"(({_PREFIJO_REKEY_SQL}) || ':' || "
    "replace(replace(l.organo_ref_fuente, '%', '%25'), ':', '%3A') || ':')"
)
_EXPEDIENTE_VIEJO_SQL = (
    f"CASE WHEN {_ES_PLACSP_SQL} THEN l.id_externo "
    "ELSE substr(l.id_externo, length(l.fuente) + 2) END"
)
_FORMA_VIEJA_SQL = (
    f"({_ES_PLACSP_SQL} OR left(l.id_externo, length(l.fuente) + 1) = l.fuente || ':')"
)

_COLISIONES_SQL = f"""
WITH mapa AS (
    SELECT l.id_externo AS viejo, {_CABEZA_NUEVA_SQL} || {_EXPEDIENTE_VIEJO_SQL} AS nuevo
    FROM licitaciones l
    WHERE {_FAMILIA_REKEY_SQL}
      AND coalesce(l.organo_ref_fuente, '') <> ''
      AND {_FORMA_VIEJA_SQL}
      AND left(l.id_externo, length({_CABEZA_NUEVA_SQL})) <> {_CABEZA_NUEVA_SQL}
)
SELECT m.nuevo AS id_externo, m.viejo AS id_viejo, n.fuente,
       (EXISTS (SELECT 1 FROM pursuits p WHERE p.licitacion_id = m.nuevo)
        OR EXISTS (SELECT 1 FROM follows f
                   WHERE f.target_type = 'licitacion' AND f.target_id = m.nuevo)
        OR EXISTS (SELECT 1 FROM watchlist_items w WHERE w.id_externo = m.nuevo)
       ) AS datos_de_usuario
FROM mapa m
JOIN licitaciones n ON n.id_externo = m.nuevo
ORDER BY m.nuevo
"""


class ColisionRekey(TypedDict):
    """Una fila escrita ya con la clave nueva que es el destino de una fila vieja."""

    id_externo: str
    id_viejo: str
    fuente: str
    datos_de_usuario: bool


def colisiones_del_rekey_placsp() -> list[ColisionRekey]:
    """Las filas por las que ``v164`` abortaría con «ya existen con la clave nueva».

    Son las que un escritor de la fase B guardó antes de migrar (incidente
    #577, 2026-10-27/28): copias recientes de un expediente que también existe
    con la clave vieja. Solo cuentan las que una fila vieja **con órgano** va a
    ocupar; por eso la lista crece a medida que avanza el relleno de
    ``organo_ref_fuente``, y se mide después de él. ``datos_de_usuario`` marca
    las que tienen pursuits, follows o watchlist: el runbook no las borra.
    """
    with connect_read() as c:
        return typed_rows(ColisionRekey, rows_to_dicts(c.execute(_COLISIONES_SQL)))


def borrar_licitaciones_en_colision(ids: Sequence[str]) -> int:
    """Borra estas filas de la clave nueva, salvo las que tengan datos de usuario.

    Paso «ya existen con la clave nueva» de ``docs/runbooks/rekey-placsp-organo.md``:
    la fila vieja se queda (tiene el historial y los datos de usuario) y la
    reingesta vuelve a traer lo que la nueva tenía de más reciente. Las hijas
    con ``ON DELETE CASCADE`` se van con ella; ``licitaciones_history`` y
    ``resoluciones_recurso`` no la tienen y se limpian antes. Las columnas sin
    FK (eventos, notificaciones) quedan con el id, que ``v164`` da enseguida a
    la fila vieja del mismo expediente. Una transacción: si algo falla, nada.
    """
    if not ids:
        return 0
    lista = list(ids)
    usuario = (
        "NOT EXISTS (SELECT 1 FROM pursuits p WHERE p.licitacion_id = x.id) "
        "AND NOT EXISTS (SELECT 1 FROM follows f "
        "  WHERE f.target_type = 'licitacion' AND f.target_id = x.id) "
        "AND NOT EXISTS (SELECT 1 FROM watchlist_items w WHERE w.id_externo = x.id)"
    )
    with connect() as c:
        c.execute(
            "CREATE TEMP TABLE _borrar_colision ON COMMIT DROP AS "
            "SELECT x.id FROM unnest(%s::text[]) AS x(id) "
            f"WHERE {usuario}",
            (lista,),
        )
        c.execute(
            "DELETE FROM licitaciones_history h USING _borrar_colision b WHERE h.id_externo = b.id"
        )
        c.execute(
            "UPDATE resoluciones_recurso r SET licitacion_id = NULL "
            "FROM _borrar_colision b WHERE r.licitacion_id = b.id"
        )
        cur = c.execute(
            "DELETE FROM licitaciones l USING _borrar_colision b WHERE l.id_externo = b.id"
        )
        return cur.rowcount or 0
