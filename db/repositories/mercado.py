"""SQL de cuota de mercado, concentración (HHI) y dossier competitivo.

Nace moviendo aquí las consultas de ``services/competitive/mercado.py``, que
era una de las entradas del ratchet TID251 de ``pyproject.toml`` (ADR-022: todo
el SQL vive en ``db/``). En el servicio se queda lo que no es SQL (ADR-024):
qué filtros lleva cada alcance del dossier, la ventana de comparación, los
desgloses, las medianas y los movimientos.

**De dónde salen los fragmentos.** Todos de ``db/sql_fragments.py``: el universo
estrecho y su grafía ``l2``, el universo de empresas vigiladas, el anti-join de
duplicados y ``round_sql``. Son las mismas definiciones que ``services/`` sigue
importando a través de los reexports de ``services/sql_fragments.py`` y
``services/dedupe.py``, y la grafía ``l2`` sale del mismo helper que usaba el
servicio, así que el SQL no cambia ni un carácter respecto a cuando se armaba
allí. El servicio no pasa
fragmentos sueltos: el universo llega por nombre y se traduce aquí, y lo único
que llega ya armado es un :class:`Alcance`, que arma :func:`alcance_sql` de este
mismo módulo.

**Dedupe.** Toda consulta sobre ``licitaciones``/``adjudicaciones`` de este
módulo excluye los duplicados cross-fuente con ``exclude_duplicados_sql()``:
directamente, o a través de :func:`alcance_sql`, que la siembra en todo alcance
que construye. Las funciones que reciben un :class:`Alcance` ya hecho lo
comprueban en código con :func:`_exigir_dedupe` antes de abrir conexión: una
tupla construida a mano sin la cláusula falla en vez de inflar el dossier.

**Qué texto acaba dentro del SQL.** Lo que llega del llamador y elige un
fragmento (``segment_by``, ``sort``, ``universo``) pasa por una tabla cerrada de
este módulo, y los valores van con ``%s``. La única entrada que sigue siendo SQL
ya hecho es un :class:`Alcance` construido a mano: su ``where`` se interpola tal
cual, y ``_exigir_dedupe`` solo comprueba que traiga el anti-join. ``db/**`` no
pasa S608, así que ningún lint avisaría; por eso ``Alcance`` solo debe salir de
:func:`alcance_sql`.

Los ``Any`` del módulo están solo en dos alias, :data:`Fila` y
:data:`ParamsSql`, que dicen por qué; las firmas usan los alias en vez de
repetir ``Any``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any, Final, Literal, NamedTuple

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from db.sql_fragments import (
    TECHNOLOGY_OBSERVED_SQL,
    WATCHED_COMPANY_AWARDS_SQL,
    exclude_duplicados_sql,
    round_sql,
    technology_observed_sql,
)

# Las tres tablas que traducen una elección del llamador a SQL son privadas y de
# solo lectura: lo que contienen acaba dentro de la consulta, y congelarlas
# impide que un importador amplíe en silencio lo que se puede elegir.

#: Universos de análisis que admiten el dossier y el listado. El servicio los
#: nombra (``analysis_universe``) y :func:`alcance_sql` interpola el predicado.
UniversoAnalisis = Literal["technology_observed", "watched_company_awards_observed"]

#: Predicado de cada universo. Un nombre fuera de la tabla falla con
#: ``KeyError`` en :func:`alcance_sql`, igual que cuando la tabla vivía en el
#: servicio.
_UNIVERSO_SQL: Final[Mapping[str, str]] = MappingProxyType(
    {
        "technology_observed": TECHNOLOGY_OBSERVED_SQL,
        "watched_company_awards_observed": WATCHED_COMPANY_AWARDS_SQL,
    }
)

#: Columna de segmentación de :func:`concentracion_hhi`. ``segment_by`` llega
#: del cliente y solo sus claves, nunca su valor, deciden qué expresión entra en
#: el SQL.
_SEGMENT_COLUMNS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "cpv": "substr(l.cpv, 1, 2)",
        "ccaa": "l.ccaa",
        "organo": "l.organo_contratacion",
        "tecnologia": "l.tecnologia",
    }
)

#: Órdenes admitidos del listado de adjudicaciones. Un ``sort`` desconocido cae
#: en ``fecha_desc`` en vez de fallar, igual que antes de la migración.
_AWARD_SORT_SQL: Final[Mapping[str, str]] = MappingProxyType(
    {
        "fecha_desc": "a.fecha_adjudicacion IS NULL, a.fecha_adjudicacion DESC",
        "fecha_asc": "a.fecha_adjudicacion IS NULL, a.fecha_adjudicacion ASC",
        "importe_desc": "a.importe_adjudicado IS NULL, a.importe_adjudicado DESC",
        "importe_asc": "a.importe_adjudicado IS NULL, a.importe_adjudicado ASC",
    }
)

#: Parámetros posicionales de una consulta, en el orden de sus ``%s``. ``Any``
#: porque mezclan ids, fechas ISO, prefijos CPV, CCAA e importes según el filtro.
ParamsSql = list[Any]

#: Una fila de ``rows_to_dicts``. ``Any`` porque cada columna trae su propio
#: tipo: ids, textos, importes, fechas ISO o ``NULL``.
Fila = dict[str, Any]

# La grafía ``l2`` del universo, para la subconsulta del HHI. Sale del helper
# canónico por la misma razón que el original: el índice parcial de v84 solo
# sirve el texto literal del predicado.
_TECHNOLOGY_OBSERVED_L2_SQL = technology_observed_sql("l2")


class Alcance(NamedTuple):
    """``WHERE`` de un alcance de adjudicaciones y sus parámetros, en orden.

    Lo construye :func:`alcance_sql`, que siempre siembra
    ``exclude_duplicados_sql()``: las funciones que reciben un ``Alcance`` no
    repiten la cláusula porque ya viene dentro, pero sí comprueban que esté
    (:func:`_exigir_dedupe`), porque una tupla se puede construir a mano.
    Esa comprobación no valida el resto de ``where``, que se interpola tal
    cual: construirlo a mano es escribir SQL, y solo con fragmentos constantes.
    """

    where: str
    params: ParamsSql


@dataclass(frozen=True)
class DenominadorCuota:
    """Denominador del agregado de cuota/HHI y el linaje de sus filas."""

    registros: int
    importe_eur: float
    linaje: list[Fila]  # fuente y versiones de filtro/modelo, cada una texto o NULL


@dataclass(frozen=True)
class PaginaAdjudicaciones:
    """Una página del listado de adjudicaciones y los límites que la acotaron.

    ``limit`` y ``offset`` son los efectivos, no los pedidos: la respuesta los
    devuelve para que el cliente pagine con lo que de verdad se aplicó.
    """

    total: int
    items: list[Fila]
    limit: int
    offset: int


@dataclass(frozen=True)
class FilasPerfil:
    """Filas crudas del dossier de una empresa, leídas en una sola conexión."""

    identidades: list[Fila]
    historia: list[Fila]
    actividad: list[Fila]
    base: list[Fila]
    posicion: list[Fila]
    utes: list[Fila]
    actividad_utes: list[Fila]
    miembros_utes: list[Fila]


def denominador_cuota(
    *,
    cpv_prefix: str | None = None,
    ccaa: str | None = None,
    desde: str | None = None,
) -> DenominadorCuota:
    """Registros e importe del segmento observado, más el linaje que los produjo.

    El ``WHERE`` es el del ranking de cuota de este módulo: universo estrecho,
    importe positivo, sin duplicados confirmados y los mismos tres filtros
    opcionales. Así el importe que se declara como denominador es la suma sobre
    la que ese ranking calcula ``cuota_pct``. El anti-join se escribe aquí
    también: compartir alcance con otra consulta no lo aporta.
    """
    clauses = [TECHNOLOGY_OBSERVED_SQL, "a.importe_adjudicado > 0", exclude_duplicados_sql()]
    params: ParamsSql = []
    if cpv_prefix:
        clauses.append("l.cpv LIKE %s")
        params.append(f"{cpv_prefix}%")
    if ccaa:
        clauses.append("l.ccaa = %s")
        params.append(ccaa)
    if desde:
        clauses.append("a.fecha_adjudicacion >= %s")
        params.append(desde)
    where = " AND ".join(clauses)
    # S608 no aplica: `where` solo junta fragmentos constantes; valores con %s.
    totals_sql = f"""
        SELECT COUNT(*), COALESCE(SUM(a.importe_adjudicado), 0)
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        WHERE {where}
    """
    lineage_sql = f"""
        SELECT DISTINCT l.fuente, l.filter_version, l.classifier_model_version
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        WHERE {where}
    """
    with connect_read() as c:
        row = c.execute(totals_sql, params).fetchone()
        lineage = rows_to_dicts(c.execute(lineage_sql, params))
    return DenominadorCuota(
        registros=int(row[0] or 0),
        importe_eur=float(row[1] or 0),
        linaje=lineage,
    )


def cuota_mercado(
    *,
    cpv_prefix: str | None = None,
    ccaa: str | None = None,
    desde: str | None = None,
    limit: int = 50,
) -> list[Fila]:
    """Ranking de empresas por importe adjudicado con su cuota % del segmento.

    Los filtros van siempre con ``%s``; ``limit`` se acota a ``[1, 500]``.
    """
    filters = ""
    params: ParamsSql = []
    if cpv_prefix:
        filters += " AND l.cpv LIKE %s"
        params.append(f"{cpv_prefix}%")
    if ccaa:
        filters += " AND l.ccaa = %s"
        params.append(ccaa)
    if desde:
        filters += " AND a.fecha_adjudicacion >= %s"
        params.append(desde)

    # S608 no aplica: `filters` es texto constante de este módulo y `round_sql`
    # solo recibe expresiones constantes de aquí; los valores van con %s.
    sql = f"""
        WITH segmento AS (
            SELECT a.empresa_id,
                   COALESCE(e.nombre_canonico, a.nombre) AS empresa,
                   MAX(COALESCE(e.es_ute, 0)) AS es_ute,
                   COUNT(*) AS contratos,
                   COALESCE(SUM(a.importe_adjudicado), 0) AS importe,
                   {round_sql("AVG(a.n_ofertas_recibidas)", 1)} AS ofertas_medias
            FROM adjudicaciones a
            JOIN licitaciones l ON l.id_externo = a.licitacion_id
            LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
            WHERE {TECHNOLOGY_OBSERVED_SQL} AND a.importe_adjudicado > 0
              AND {exclude_duplicados_sql()} {filters}
            GROUP BY a.empresa_id, empresa
        )
        SELECT empresa_id, empresa, es_ute, contratos, importe, ofertas_medias,
               {round_sql("importe * 100.0 / NULLIF((SELECT SUM(importe) FROM segmento), 0)", 2)}
                   AS cuota_pct
        FROM segmento
        ORDER BY importe DESC
        LIMIT %s
    """
    params.append(max(1, min(int(limit), 500)))
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


def concentracion_hhi(
    *,
    segment_by: str = "cpv",
    min_contratos: int = 5,
) -> list[Fila]:
    """HHI por segmento sobre el universo observado y sin duplicados.

    ``segment_by`` llega del cliente y se valida contra la whitelist
    ``_SEGMENT_COLUMNS`` antes de construir el SQL: lo que se interpola es la
    expresión de la whitelist, nunca la cadena recibida. El resto del texto
    interpolado son fragmentos de ``db/sql_fragments.py`` y ``round_sql`` sobre
    una expresión constante de aquí.

    No es la única entrada del módulo que elige un fragmento: el ``sort`` del
    listado pasa por su propia whitelist (``_AWARD_SORT_SQL``) y el universo del
    dossier por ``_UNIVERSO_SQL``.
    """
    if segment_by not in _SEGMENT_COLUMNS:
        raise ValueError(
            f"segment_by inválido: {segment_by!r} (válidos: {sorted(_SEGMENT_COLUMNS)})"
        )
    seg_col = _SEGMENT_COLUMNS[segment_by]

    # S608 no aplica: `seg_col` sale de la whitelist, `round_sql` recibe una
    # expresión constante de aquí y el resto son fragmentos constantes; el único
    # valor va con %s.
    sql = f"""
        WITH por_empresa AS (
            SELECT {seg_col} AS segmento,
                   a.empresa_id,
                   SUM(a.importe_adjudicado) AS importe
            FROM adjudicaciones a
            JOIN licitaciones l ON l.id_externo = a.licitacion_id
            WHERE a.importe_adjudicado > 0 AND {seg_col} IS NOT NULL
              AND {TECHNOLOGY_OBSERVED_SQL}
              AND {exclude_duplicados_sql()}
            GROUP BY segmento, a.empresa_id
        ),
        totales AS (
            SELECT segmento,
                   SUM(importe) AS total,
                   COUNT(*) AS empresas
            FROM por_empresa GROUP BY segmento
        )
        SELECT * FROM (
            SELECT p.segmento,
                   t.empresas,
                   t.total AS importe_total,
                   (SELECT COUNT(*) FROM adjudicaciones a2
                    JOIN licitaciones l2 ON l2.id_externo = a2.licitacion_id
                    WHERE {seg_col.replace("l.", "l2.")} = p.segmento
                      AND a2.importe_adjudicado > 0
                      AND {_TECHNOLOGY_OBSERVED_L2_SQL}
                      AND {exclude_duplicados_sql("l2.id_externo")}) AS contratos,
                   {round_sql("SUM((p.importe * 100.0 / t.total) * (p.importe * 100.0 / t.total))", 0)}
                       AS hhi
            FROM por_empresa p
            JOIN totales t ON t.segmento = p.segmento
            GROUP BY p.segmento, t.empresas, t.total
        ) seg
        WHERE contratos >= %s
        ORDER BY hhi DESC
    """
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, [max(1, int(min_contratos))]))


def alcance_sql(
    *,
    universo: UniversoAnalisis,
    empresa_id: int | None = None,
    empresa_ids: list[int] | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    cpv_prefix: str | None = None,
    ccaas: list[str] | None = None,
    tecnologias: list[str] | None = None,
    importe_min: float | None = None,
) -> Alcance:
    """Alcance compartido de adjudicaciones, con valores siempre parametrizados.

    ``universo`` se traduce a su predicado con ``_UNIVERSO_SQL``; un nombre que
    no esté en la tabla lanza ``KeyError`` antes de construir nada, así que lo
    que se interpola nunca es la cadena recibida. ``empresa_ids`` agrupa varias
    identidades del maestro bajo un único dossier y tiene prioridad sobre
    ``empresa_id`` cuando llegan ambos.

    La exclusión de duplicados va sembrada aquí y no en cada consulta: así la
    siguiente función que reciba un :class:`Alcance` no puede olvidarla.
    """
    clauses = [_UNIVERSO_SQL[universo], exclude_duplicados_sql()]
    params: ParamsSql = []
    if empresa_ids:
        placeholders = ", ".join("%s" for _ in empresa_ids)
        clauses.append(f"a.empresa_id IN ({placeholders})")
        params.extend(empresa_ids)
    elif empresa_id is not None:
        clauses.append("a.empresa_id = %s")
        params.append(empresa_id)
    if fecha_desde is not None:
        clauses.append("a.fecha_adjudicacion >= %s")
        params.append(fecha_desde.isoformat())
    if fecha_hasta is not None:
        clauses.append("a.fecha_adjudicacion <= %s")
        params.append(fecha_hasta.isoformat())
    if cpv_prefix:
        clauses.append("l.cpv LIKE %s")
        params.append(f"{cpv_prefix}%")
    if ccaas:
        placeholders = ", ".join("%s" for _ in ccaas)
        clauses.append(f"l.ccaa IN ({placeholders})")
        params.extend(ccaas)
    if tecnologias:
        placeholders = ", ".join("%s" for _ in tecnologias)
        clauses.append(f"l.tecnologia IN ({placeholders})")
        params.extend(tecnologias)
    if importe_min is not None:
        clauses.append("l.importe >= %s")
        params.append(max(0.0, float(importe_min)))
    return Alcance(" AND ".join(clauses), params)


def _exigir_dedupe(*alcances: Alcance | None) -> None:
    """Rechaza cualquier alcance que no excluya los duplicados cross-fuente.

    ``Alcance`` es una tupla pública que se puede construir sin pasar por
    :func:`alcance_sql`. Sin esta comprobación, que el dossier y el listado
    deduplican dependería de que todos los llamadores lo hagan bien, y el fallo
    sería silencioso: una métrica inflada no rompe nada. Por eso falla antes de
    abrir conexión. ``None`` se acepta porque la base del dossier es opcional.

    Lanza ``RuntimeError`` y no ``ValueError`` porque que salte nunca es un
    dato malo del cliente, sino un invariante del servidor roto. Con
    ``ValueError``, ``api/errors.py`` respondería 400 «valor inválido» y lo
    dejaría en un ``warning``; así llega al manejador genérico, que responde 500
    y lo registra como error.
    """
    clausula = exclude_duplicados_sql()
    for alcance in alcances:
        if alcance is not None and clausula not in alcance.where:
            raise RuntimeError(
                "alcance sin exclude_duplicados_sql(): constrúyelo con alcance_sql()"
            )


def filas_perfil_empresa(
    group_ids: list[int],
    *,
    alcance: Alcance,
    alcance_base: Alcance | None,
    alcance_mercado: Alcance,
    alcance_historia: Alcance,
) -> FilasPerfil:
    """Todas las lecturas del dossier competitivo, en una conexión de lectura.

    Los cuatro alcances llegan construidos por :func:`alcance_sql`; qué filtros
    lleva cada uno es decisión del servicio. ``alcance_base`` es ``None`` cuando
    no hay ventana de fechas: la base coincide entonces con la actividad y se
    reutilizan sus filas en vez de repetir la consulta.
    """
    _exigir_dedupe(alcance, alcance_base, alcance_mercado, alcance_historia)
    scope_where, scope_params = alcance
    market_where, market_params = alcance_mercado
    history_where, history_params = alcance_historia
    activity_select = """
        SELECT a.licitacion_id,
               l.titulo,
               a.fecha_adjudicacion,
               a.importe_adjudicado,
               a.n_ofertas_recibidas,
               l.importe AS presupuesto_licitacion,
               l.organo_contratacion,
               l.ccaa,
               l.cpv,
               l.tecnologia
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
    """
    # S608 no aplica en todo el bloque: los WHERE salen de `alcance_sql` y los
    # placeholders se generan por conteo; todos los valores van con %s.
    with connect_read() as c:
        id_placeholders = ", ".join("%s" for _ in group_ids)
        identity_rows = rows_to_dicts(
            c.execute(
                "SELECT e.empresa_id, e.nombre_canonico, e.nif_canonico, e.es_ute, "
                "       g.nombre AS grupo "
                "FROM empresas e LEFT JOIN grupos_empresariales g ON g.grupo_id = e.grupo_id "
                f"WHERE e.empresa_id IN ({id_placeholders})",
                group_ids,
            )
        )
        history_rows = rows_to_dicts(
            c.execute(
                f"""
                SELECT COUNT(*) AS contratos,
                       COALESCE(SUM(a.importe_adjudicado), 0) AS importe_total,
                       MIN(a.fecha_adjudicacion) AS primera_adjudicacion,
                       MAX(a.fecha_adjudicacion) AS ultima_adjudicacion
                FROM adjudicaciones a
                JOIN licitaciones l ON l.id_externo = a.licitacion_id
                WHERE {history_where}
                """,
                history_params,
            )
        )
        scope_rows = rows_to_dicts(
            c.execute(f"{activity_select} WHERE {scope_where}", scope_params)
        )
        baseline_rows = (
            scope_rows
            if alcance_base is None
            else rows_to_dicts(
                c.execute(
                    f"{activity_select} WHERE {alcance_base.where}",
                    alcance_base.params,
                )
            )
        )
        # Cuando hay varias identidades agrupadas, se suman como un único
        # competidor antes de rankear frente al resto (que siguen sueltos por
        # empresa_id) — así la cuota/posición reflejan al competidor real, no
        # a una de sus identidades sueltas.
        position_rows = rows_to_dicts(
            c.execute(
                f"""
                WITH segmento AS (
                    SELECT a.empresa_id,
                           COALESCE(SUM(a.importe_adjudicado), 0) AS importe
                    FROM adjudicaciones a
                    JOIN licitaciones l ON l.id_externo = a.licitacion_id
                    WHERE a.empresa_id IS NOT NULL AND {market_where}
                    GROUP BY a.empresa_id
                ),
                agrupado AS (
                    SELECT CASE WHEN empresa_id IN ({id_placeholders}) THEN -1 ELSE empresa_id END
                               AS gid,
                           importe
                    FROM segmento
                ),
                sumado AS (
                    SELECT gid, SUM(importe) AS importe
                    FROM agrupado
                    GROUP BY gid
                ),
                ranked AS (
                    SELECT gid,
                           importe,
                           RANK() OVER (ORDER BY importe DESC) AS rank,
                           COUNT(*) OVER () AS empresas,
                           SUM(importe) OVER () AS importe_segmento
                    FROM sumado
                )
                SELECT gid AS empresa_id, rank, empresas, importe_segmento,
                       importe * 100.0 / NULLIF(importe_segmento, 0) AS cuota_pct
                FROM ranked WHERE gid = -1
                """,
                [*market_params, *group_ids],
            )
        )
        # UTEs en las que participa como miembro (v35, ute_miembros) -- no
        # como entidad propia. cuota_mercado()/concentracion_hhi() ya tratan
        # a la UTE como participante independiente para no contar dos veces
        # el mismo importe en el agregado del segmento; esto es visibilidad
        # adicional sobre ESTE dossier, sin tocar ese cómputo.
        ute_identity_rows = rows_to_dicts(
            c.execute(
                "SELECT DISTINCT u.ute_empresa_id, e.nombre_canonico AS ute_nombre "
                "FROM ute_miembros u JOIN empresas e ON e.empresa_id = u.ute_empresa_id "
                f"WHERE u.miembro_empresa_id IN ({id_placeholders})",
                group_ids,
            )
        )
        ute_ids = [int(row["ute_empresa_id"]) for row in ute_identity_rows]
        ute_activity_rows: list[Fila] = []
        ute_miembros_rows: list[Fila] = []
        if ute_ids:
            ute_placeholders = ", ".join("%s" for _ in ute_ids)
            ute_activity_rows = rows_to_dicts(
                c.execute(
                    f"""
                    SELECT a.empresa_id AS ute_empresa_id,
                           COUNT(*) AS contratos,
                           COALESCE(SUM(a.importe_adjudicado), 0) AS importe_total
                    FROM adjudicaciones a
                    JOIN licitaciones l ON l.id_externo = a.licitacion_id
                    WHERE a.empresa_id IN ({ute_placeholders}) AND {market_where}
                    GROUP BY a.empresa_id
                    """,
                    [*ute_ids, *market_params],
                )
            )
            ute_miembros_rows = rows_to_dicts(
                c.execute(
                    "SELECT u.ute_empresa_id, m.nombre_canonico "
                    "FROM ute_miembros u JOIN empresas m ON m.empresa_id = u.miembro_empresa_id "
                    f"WHERE u.ute_empresa_id IN ({ute_placeholders}) "
                    f"AND u.miembro_empresa_id NOT IN ({id_placeholders})",
                    [*ute_ids, *group_ids],
                )
            )
    return FilasPerfil(
        identidades=identity_rows,
        historia=history_rows,
        actividad=scope_rows,
        base=baseline_rows,
        posicion=position_rows,
        utes=ute_identity_rows,
        actividad_utes=ute_activity_rows,
        miembros_utes=ute_miembros_rows,
    )


def adjudicaciones_empresa(
    alcance: Alcance,
    *,
    q: str | None = None,
    organo: str | None = None,
    sort: str = "fecha_desc",
    limit: int = 25,
    offset: int = 0,
) -> PaginaAdjudicaciones:
    """Total y página de adjudicaciones de un alcance, con búsqueda y orden.

    ``alcance`` llega de :func:`alcance_sql`. ``limit`` y ``offset`` se acotan
    aquí, junto a la consulta que materializa las filas, para que ningún
    llamador pueda saltarse el tope; la página devuelve los valores efectivos
    porque la respuesta del listado los expone.
    """
    _exigir_dedupe(alcance)
    where, scope_params = alcance
    params = list(scope_params)
    clauses = [where]
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        clauses.append(
            "(LOWER(COALESCE(l.titulo, '')) LIKE %s "
            "OR LOWER(COALESCE(l.organo_contratacion, '')) LIKE %s "
            "OR LOWER(COALESCE(a.licitacion_id, '')) LIKE %s)"
        )
        params.extend([needle, needle, needle])
    if organo and organo.strip():
        clauses.append("LOWER(COALESCE(l.organo_contratacion, '')) LIKE %s")
        params.append(f"%{organo.strip().lower()}%")
    full_where = " AND ".join(clauses)
    safe_limit = max(1, min(int(limit), 500))
    safe_offset = max(0, int(offset))
    order_sql = _AWARD_SORT_SQL.get(sort, _AWARD_SORT_SQL["fecha_desc"])

    # S608 no aplica: `full_where` y `order_sql` salen de fragmentos constantes
    # y de la whitelist de orden; los valores van con %s.
    with connect_read() as c:
        total = int(
            c.execute(
                f"""
                SELECT COUNT(*)
                FROM adjudicaciones a
                JOIN licitaciones l ON l.id_externo = a.licitacion_id
                WHERE {full_where}
                """,
                params,
            ).fetchone()[0]
        )
        items = rows_to_dicts(
            c.execute(
                f"""
                SELECT a.licitacion_id,
                       l.titulo,
                       l.organo_contratacion,
                       a.fecha_adjudicacion,
                       l.cpv,
                       l.ccaa,
                       l.tecnologia,
                       l.importe AS presupuesto_licitacion,
                       a.importe_adjudicado,
                       CASE
                         WHEN l.importe > 0 AND a.importe_adjudicado IS NOT NULL
                         THEN (1.0 - (a.importe_adjudicado * 1.0) / l.importe) * 100
                         ELSE NULL
                       END AS baja_pct,
                       a.n_ofertas_recibidas
                FROM adjudicaciones a
                JOIN licitaciones l ON l.id_externo = a.licitacion_id
                WHERE {full_where}
                ORDER BY {order_sql}
                LIMIT %s OFFSET %s
                """,
                [*params, safe_limit, safe_offset],
            )
        )
    return PaginaAdjudicaciones(total=total, items=items, limit=safe_limit, offset=safe_offset)
