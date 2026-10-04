"""Lecturas de la competencia esperada de un expediente (ficha de la licitación).

Todo el SQL vive aquí (ADR-022). Qué se responde con estas lecturas —qué nivel
de segmento manda, cuándo una muestra basta, quién es la propia organización—
está en ``services/competitive/competencia_esperada.py``.

Cuatro reglas comunes a las consultas
-------------------------------------
1. **Acotadas por segmento.** Todas exigen el CPV-4 del expediente; el órgano y
   la comunidad autónoma solo estrechan. El bloque que sustituyen pedía el
   drill-down entero del órgano —todas sus licitaciones, puntuadas en pandas—
   para pintar tres nombres de cualquier CPV y de cualquier año.
2. **Universo analítico** (:func:`technology_observed_sql`), el mismo que el
   score y las cuentas (ADR-026): las fuentes regionales con el censo entero de
   su comunidad no son mercado comparable.
3. **Ex ante.** El expediente consultado nunca cuenta: si ya está adjudicado,
   su propio resultado no puede ser parte de la competencia que se esperaba.
4. **El órgano, con lectura dual** (C1.2, ADR-032 §C): ``organo_id`` cuando el
   maestro lo resolvió, más las filas aún sin resolver con el mismo nombre
   plegado; solo el nombre plegado cuando el expediente no tiene ``organo_id``.
   El plegado es :func:`organo_normalizado_sql`, que tiene índice propio
   (``idx_lic_organo_norm``, v146): la comparación por ``lower(btrim(...))`` no
   lo tiene y recorría la tabla entera.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from db.sql_fragments import (
    BAJA_PCT_SQL,
    BASE_COMPARABLE_SQL,
    SIN_IVA_CONOCIDO_SQL,
    VALID_PAIR_LOTE,
    empresa_key_sql,
    exclude_duplicados_sql,
    iso_guard,
    organo_normalizado_sql,
    technology_observed_sql,
)

__all__ = [
    "NivelSegmento",
    "Segmento",
    "expedientes_por_nivel",
    "objetivo",
    "ofertas_del_segmento",
    "rivales_del_segmento",
]

#: Los niveles de segmento, de más estrecho a más ancho. El CPV-4 está en los
#: tres: sin él no hay segmento (ver la regla 1 del docstring).
NivelSegmento = Literal["organo_cpv4", "cpv4_ccaa", "cpv4"]

_UNIVERSO = technology_observed_sql("l")

#: NIF normalizado en SQL con la misma regla que ``services.normalization.
#: normalize_nif`` (sin espacios, guiones ni puntos, en mayúsculas): es contra
#: lo que se comparan los NIF declarados por la organización.
_NIF_NORMALIZADO = r"upper(regexp_replace(a.nif, '[\s.-]', '', 'g'))"


@dataclass(frozen=True, slots=True)
class Segmento:
    """Dónde se compite: el CPV-4 del expediente y, si se conocen, su órgano y CCAA.

    ``organo_norm`` es el nombre del órgano ya plegado con
    :func:`db.sql_fragments.plegar_organo`, el gemelo Python de
    :func:`organo_normalizado_sql`.
    """

    cpv4: str
    organo_id: int | None = None
    organo_norm: str | None = None
    ccaa: str | None = None

    @property
    def tiene_organo(self) -> bool:
        return self.organo_id is not None or bool(self.organo_norm)


def objetivo(id_externo: str) -> dict[str, Any] | None:
    """El expediente cuya competencia se estima, con lo que hace falta para segmentarlo.

    ``titulo`` y ``descripcion`` van porque el predecesor (``services/similares``)
    ordena sus candidatos por parecido del texto.
    """
    with connect_read() as c:
        filas = rows_to_dicts(
            c.execute(
                "SELECT l.id_externo, l.titulo, l.descripcion, l.organo_contratacion, "
                "       l.organo_id, l.cpv, l.ccaa, l.fecha_publicacion "
                "FROM licitaciones l WHERE l.id_externo = %s LIMIT 1",
                (id_externo,),
            )
        )
    return filas[0] if filas else None


def _predicado_organo(segmento: Segmento) -> tuple[str, list[Any]]:
    """Condición «es del órgano del expediente», o ``FALSE`` si no se conoce.

    Con ``organo_id`` entran también las filas del mismo órgano que el maestro
    todavía no resolvió (``organo_id`` nulo y mismo nombre plegado): el backfill
    no llega al 100 % y sin ellas la muestra del órgano encoge en silencio. Las
    dos ramas van por índice (``idx_lic_organo_id`` e ``idx_lic_organo_norm``).
    """
    plegado = organo_normalizado_sql("l")
    if segmento.organo_id is not None and segmento.organo_norm:
        return (
            f"(l.organo_id = %s OR (l.organo_id IS NULL AND {plegado} = %s))",
            [segmento.organo_id, segmento.organo_norm],
        )
    if segmento.organo_id is not None:
        return "l.organo_id = %s", [segmento.organo_id]
    if segmento.organo_norm:
        return f"{plegado} = %s", [segmento.organo_norm]
    return "FALSE", []


def _predicado_ccaa(segmento: Segmento) -> tuple[str, list[Any]]:
    if segmento.ccaa:
        return "l.ccaa = %s", [segmento.ccaa]
    return "FALSE", []


def _predicado_nivel(segmento: Segmento, nivel: NivelSegmento) -> tuple[str, list[Any]]:
    """La condición que estrecha el CPV-4 hasta ``nivel``."""
    if nivel == "organo_cpv4":
        return _predicado_organo(segmento)
    if nivel == "cpv4_ccaa":
        return _predicado_ccaa(segmento)
    return "TRUE", []


def _base_adjudicaciones(
    segmento: Segmento, *, excluir: str, desde_iso: str
) -> tuple[list[str], list[Any]]:
    """``WHERE`` común: universo, CPV-4, ex ante y ventana sobre la adjudicación.

    El CPV-4 se compara con ``substr(l.cpv, 1, 4)``, la misma expresión por la
    que agrupa la señal de competencia del score
    (``AggregateRepository.competencia_ofertas_por_cpv4``): las dos tienen que
    contar el mismo segmento.
    """
    condiciones = [
        _UNIVERSO,
        "substr(l.cpv, 1, 4) = %s",
        "l.id_externo <> %s",
        "a.fecha_adjudicacion >= %s",
        iso_guard("a.fecha_adjudicacion"),
    ]
    return condiciones, [segmento.cpv4, excluir, desde_iso]


def ofertas_del_segmento(segmento: Segmento, *, excluir: str, desde_iso: str) -> dict[str, Any]:
    """Cuántas ofertas recibieron los expedientes del CPV-4 y, dentro, los del órgano.

    Una fila con los dos niveles a la vez: el del CPV-4 y el del órgano (que es
    un subconjunto suyo), para no recorrer el segmento dos veces.

    Por expediente cuenta el **máximo** de ``n_ofertas_recibidas`` de sus
    adjudicaciones (una por lote) y la media es entre expedientes: es la
    definición de la dimensión ``competencia`` del score, con la misma ventana
    sobre ``fecha_adjudicacion``. Por eso **no** excluye duplicados entre
    fuentes, igual que aquella: el número del CPV tiene que poder compararse con
    el que explica la barra del Radar. ``adjudicados`` cuenta también los
    expedientes que no publican el dato (TED nunca lo publica): es el
    denominador de la cobertura.

    Las bandas son las de ``services.ml.pricing_scenarios._competition_band``
    (1, 2-4, 5+): son las que acepta ``escenarios-precio?competencia_esperada``.
    """
    del_organo, params_organo = _predicado_organo(segmento)
    condiciones, params_base = _base_adjudicaciones(segmento, excluir=excluir, desde_iso=desde_iso)
    niveles = {"cpv4": "TRUE", "organo": "del_organo"}
    columnas = []
    for prefijo, filtro in niveles.items():
        columnas.extend(
            [
                f"COUNT(*) FILTER (WHERE {filtro}) AS {prefijo}_adjudicados",
                f"COUNT(ofertas) FILTER (WHERE {filtro}) AS {prefijo}_expedientes",
                f"CAST(AVG(ofertas) FILTER (WHERE {filtro}) AS FLOAT) AS {prefijo}_media",
                f"COUNT(*) FILTER (WHERE {filtro} AND ofertas <= 1) AS {prefijo}_banda_1",
                f"COUNT(*) FILTER (WHERE {filtro} AND ofertas BETWEEN 2 AND 4) "
                f"AS {prefijo}_banda_2_4",
                f"COUNT(*) FILTER (WHERE {filtro} AND ofertas >= 5) AS {prefijo}_banda_5",
            ]
        )
    # Solo se interpolan fragmentos constantes de `db.sql_fragments` y los
    # predicados de este módulo; todo valor viaja como parámetro.
    sql = (
        "WITH por_expediente AS ("
        "  SELECT a.licitacion_id, MAX(a.n_ofertas_recibidas) AS ofertas, "
        f"        bool_or({del_organo}) AS del_organo "
        "  FROM adjudicaciones a "
        "  JOIN licitaciones l ON l.id_externo = a.licitacion_id "
        f"  WHERE {' AND '.join(condiciones)} "
        "  GROUP BY a.licitacion_id"
        ") "
        f"SELECT {', '.join(columnas)} FROM por_expediente"
    )
    with connect_read() as c:
        filas = rows_to_dicts(c.execute(sql, [*params_organo, *params_base]))
    return filas[0] if filas else {}


def expedientes_por_nivel(
    segmento: Segmento, *, excluir: str, desde_iso: str
) -> dict[NivelSegmento, int]:
    """Expedientes adjudicados en cada nivel, para elegir sobre cuál se rankea.

    Una sola pasada por el CPV-4 con un ``FILTER`` por nivel: los tres niveles
    están anidados, así que el ancho contiene a los estrechos. Excluye los
    duplicados entre fuentes, como el ranking que viene después: es una métrica
    de mercado (cuota), no la señal del score.
    """
    del_organo, params_organo = _predicado_organo(segmento)
    de_la_ccaa, params_ccaa = _predicado_ccaa(segmento)
    condiciones, params_base = _base_adjudicaciones(segmento, excluir=excluir, desde_iso=desde_iso)
    condiciones.append(exclude_duplicados_sql("a.licitacion_id"))
    # Fragmentos constantes y predicados de este módulo; valores como parámetros.
    sql = (
        "SELECT "
        f"  COUNT(DISTINCT a.licitacion_id) FILTER (WHERE {del_organo}) AS organo_cpv4, "
        f"  COUNT(DISTINCT a.licitacion_id) FILTER (WHERE {de_la_ccaa}) AS cpv4_ccaa, "
        "  COUNT(DISTINCT a.licitacion_id) AS cpv4 "
        "FROM adjudicaciones a "
        "JOIN licitaciones l ON l.id_externo = a.licitacion_id "
        f"WHERE {' AND '.join(condiciones)}"
    )
    with connect_read() as c:
        filas = rows_to_dicts(c.execute(sql, [*params_organo, *params_ccaa, *params_base]))
    fila = filas[0] if filas else {}
    return {
        "organo_cpv4": int(fila.get("organo_cpv4") or 0),
        "cpv4_ccaa": int(fila.get("cpv4_ccaa") or 0),
        "cpv4": int(fila.get("cpv4") or 0),
    }


def rivales_del_segmento(
    segmento: Segmento,
    nivel: NivelSegmento,
    *,
    excluir: str,
    desde_iso: str,
    limite: int,
    propias_empresa_ids: Sequence[int] = (),
    propios_nifs: Sequence[str] = (),
) -> dict[str, Any]:
    """Quién gana en el segmento, con su cuota, y cómo se puja en él.

    Devuelve ``{"total": {...}, "rivales": [...]}``:

    - ``total``: expedientes e importe adjudicado del nivel —el denominador de
      las cuotas—, la baja mediana del ganador, la mediana de la baja de la
      oferta más baja (``oferta_minima``) y la parte de la propia organización.
    - ``rivales``: hasta ``limite`` empresas por importe adjudicado, cada una
      con sus expedientes, su baja mediana, su última adjudicación y los NIF con
      los que se presentó (para reconocer a la propia organización; no salen de
      ``services/``).

    La identidad de empresa es :func:`empresa_key_sql`, la misma del HHI y de
    «Contra mí»: dos definiciones de «quién es este competidor» darían dos
    respuestas a la misma pregunta. La parte propia se calcula aquí, sobre el
    nivel entero, y no con los rivales devueltos: la organización puede no
    estar entre los ``limite`` primeros y su cuota seguiría existiendo.

    Las bajas usan la fórmula por fila de :data:`BAJA_PCT_SQL` (presupuesto del
    lote cuando lo hay) y dejan fuera los presupuestos que se sabe que llevan
    IVA (:data:`SIN_IVA_CONOCIDO_SQL`): la base resultante es ``mixta``, como en
    ``/competitive/bajas``.
    """
    estrecha, params_nivel = _predicado_nivel(segmento, nivel)
    condiciones, params_base = _base_adjudicaciones(segmento, excluir=excluir, desde_iso=desde_iso)
    condiciones.extend([estrecha, exclude_duplicados_sql("a.licitacion_id")])
    baja_minima = f"(({BASE_COMPARABLE_SQL}) - a.oferta_minima) / ({BASE_COMPARABLE_SQL}) * 100"
    oferta_minima_valida = (
        f"({BASE_COMPARABLE_SQL}) > 0 AND a.oferta_minima > 0 "
        f"AND a.oferta_minima <= ({BASE_COMPARABLE_SQL}) * 1.5"
    )
    propia = f"(a.empresa_id = ANY(%s) OR {_NIF_NORMALIZADO} = ANY(%s))"
    # Solo fragmentos constantes de `db.sql_fragments` y predicados de este
    # módulo; todo valor viaja como parámetro.
    sql = (
        "WITH filas AS ("
        f"  SELECT {empresa_key_sql('a')} AS clave, a.empresa_id, a.nif, a.nombre, "
        "         NULLIF(btrim(e.nombre_canonico), '') AS nombre_canonico, "
        "         a.licitacion_id, a.importe_adjudicado, a.fecha_adjudicacion, "
        f"        {propia} AS es_propia, "
        f"        CASE WHEN {VALID_PAIR_LOTE} AND {SIN_IVA_CONOCIDO_SQL} "
        f"             THEN {BAJA_PCT_SQL} END AS baja_pct, "
        f"        CASE WHEN {oferta_minima_valida} AND {SIN_IVA_CONOCIDO_SQL} "
        f"             THEN {baja_minima} END AS baja_minima_pct "
        "  FROM adjudicaciones a "
        "  JOIN licitaciones l ON l.id_externo = a.licitacion_id "
        "  LEFT JOIN lotes lo ON lo.id = a.lote_id "
        "  LEFT JOIN empresas e ON e.empresa_id = a.empresa_id "
        f"  WHERE {' AND '.join(condiciones)}"
        "), total AS ("
        "  SELECT COUNT(DISTINCT licitacion_id) AS expedientes, "
        "         COALESCE(SUM(importe_adjudicado), 0) AS importe_total, "
        "         percentile_cont(0.5) WITHIN GROUP (ORDER BY baja_pct) AS baja_mediana_pct, "
        "         COUNT(baja_pct) AS bajas_n, "
        "         percentile_cont(0.5) WITHIN GROUP (ORDER BY baja_minima_pct) "
        "           AS baja_oferta_minima_mediana_pct, "
        "         COUNT(baja_minima_pct) AS ofertas_minimas_n, "
        "         COUNT(DISTINCT licitacion_id) FILTER (WHERE es_propia) AS propia_expedientes, "
        "         COALESCE(SUM(importe_adjudicado) FILTER (WHERE es_propia), 0) "
        "           AS propia_importe "
        "  FROM filas"
        "), rivales AS ("
        "  SELECT clave, MIN(empresa_id) AS empresa_id, "
        "         array_agg(DISTINCT nif) FILTER (WHERE nif IS NOT NULL) AS nifs, "
        "         COALESCE(MAX(nombre_canonico), "
        "                  (array_agg(nombre ORDER BY fecha_adjudicacion DESC NULLS LAST, "
        "                             nombre))[1]) "
        "           AS nombre, "
        "         COUNT(DISTINCT licitacion_id) AS expedientes, "
        "         COALESCE(SUM(importe_adjudicado), 0) AS importe, "
        "         percentile_cont(0.5) WITHIN GROUP (ORDER BY baja_pct) AS baja_mediana_pct, "
        "         COUNT(baja_pct) AS bajas_n, "
        "         MAX(fecha_adjudicacion) AS ultima_adjudicacion "
        "  FROM filas WHERE clave IS NOT NULL "
        "  GROUP BY clave "
        "  ORDER BY importe DESC, expedientes DESC, clave "
        "  LIMIT %s"
        ") "
        "SELECT t.expedientes AS total_expedientes, t.importe_total, "
        "       t.baja_mediana_pct AS total_baja_mediana_pct, t.bajas_n AS total_bajas_n, "
        "       t.baja_oferta_minima_mediana_pct, t.ofertas_minimas_n, "
        "       t.propia_expedientes, t.propia_importe, "
        "       r.clave, r.empresa_id, r.nifs, r.nombre, r.expedientes, r.importe, "
        "       r.baja_mediana_pct, r.bajas_n, r.ultima_adjudicacion "
        # LEFT JOIN desde `total`: sin rivales la consulta sigue devolviendo la
        # fila del denominador, que dice «0 expedientes» en vez de nada.
        "FROM total t LEFT JOIN rivales r ON TRUE "
        "ORDER BY r.importe DESC NULLS LAST, r.expedientes DESC NULLS LAST, r.clave"
    )
    # El orden importa: el SELECT de `filas` lleva los dos `ANY(%s)` de la
    # propia organización **antes** que su WHERE, y el LIMIT va al final.
    params = [
        list(propias_empresa_ids),
        list(propios_nifs),
        *params_base,
        *params_nivel,
        max(1, int(limite)),
    ]
    with connect_read() as c:
        filas = rows_to_dicts(c.execute(sql, params))
    if not filas:
        return {"total": {}, "rivales": []}
    primera = filas[0]
    total = {
        "expedientes": int(primera.get("total_expedientes") or 0),
        "importe_total": float(primera.get("importe_total") or 0.0),
        "baja_mediana_pct": primera.get("total_baja_mediana_pct"),
        "bajas_n": int(primera.get("total_bajas_n") or 0),
        "baja_oferta_minima_mediana_pct": primera.get("baja_oferta_minima_mediana_pct"),
        "ofertas_minimas_n": int(primera.get("ofertas_minimas_n") or 0),
        "propia_expedientes": int(primera.get("propia_expedientes") or 0),
        "propia_importe": float(primera.get("propia_importe") or 0.0),
    }
    rivales = [
        {
            "clave": str(fila["clave"]),
            "empresa_id": fila.get("empresa_id"),
            "nifs": list(fila.get("nifs") or []),
            "nombre": fila.get("nombre"),
            "expedientes": int(fila.get("expedientes") or 0),
            "importe": float(fila.get("importe") or 0.0),
            "baja_mediana_pct": fila.get("baja_mediana_pct"),
            "bajas_n": int(fila.get("bajas_n") or 0),
            "ultima_adjudicacion": fila.get("ultima_adjudicacion"),
        }
        for fila in filas
        if fila.get("clave") is not None
    ]
    return {"total": total, "rivales": rivales}
