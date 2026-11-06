"""Scoring y pipeline: proyecciones acotadas, percentiles y contexto del Radar."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, TypedDict

from db.database import connect_read
from db.repositories.aggregates.filtros import (
    LicitacionesFilters,
    _build_where,
)
from db.repositories.base import rows_to_dicts, typed_rows
from db.repositories.tecnologia_pliego import SENTINELS
from db.sql_fragments import (
    TECHNOLOGY_OBSERVED_SQL,
    columna_nucleo_sql,
    fecha_valida_sql,
    importe_select_sql,
    importe_sql,
    iso_guard,
)
from shared.estados import ESTADOS_CERRADOS, abierta_sql_marcadores


class OrganoLicitacionFila(TypedDict):
    id_externo: str
    titulo: str
    organo_contratacion: str
    importe: float | None
    cpv: str | None
    tipo_contrato: str | None
    estado: str | None
    fecha_publicacion: str | None
    fecha_limite: str | None
    ccaa: str | None
    tecnologia: str | None
    url: str | None


class CompetenciaCpv4Fila(TypedDict):
    cpv4: str
    #: ``AVG`` de un entero: ``numeric`` en Postgres, ``Decimal`` en Python.
    media_ofertas: Decimal


class ScoringMixin:
    """Scoring y pipeline: proyecciones acotadas, percentiles y contexto del Radar."""

    # ── Drill-down por órgano ────────────────────────────────────────────

    def licitaciones_por_organo(
        self, organo: str, filters: LicitacionesFilters
    ) -> list[OrganoLicitacionFila]:
        """Proyección ACOTADA de las licitaciones de UN órgano (ADR-023).

        El scoring y la estacionalidad del drill-down operan en pandas sobre
        este subconjunto — acotado por definición al órgano pedido.
        ``fecha_limite`` está porque el ranking usa el motor de scoring real,
        que puntúa el plazo: sin esa columna todas las filas del drill-down
        saldrían marcadas ``sin_plazo``.
        """
        where, params = _build_where(filters)
        sql = (
            "SELECT id_externo, titulo, organo_contratacion, importe, cpv, "
            "       tipo_contrato, estado, fecha_publicacion, fecha_limite, "
            "       ccaa, tecnologia, url "
            "FROM licitaciones "
            f"WHERE {where} AND organo_contratacion = %s"
        )
        with connect_read() as c:
            return typed_rows(
                OrganoLicitacionFila, rows_to_dicts(c.execute(sql, [*params, organo]))
            )

    # ── Scoring / pipeline: proyecciones acotadas y contexto ─────────────

    # Columnas que _score_row (services/analytics/scoring.py) necesita leer.
    # `descripcion` no se expone en la respuesta: es insumo de la afinidad, que
    # antes solo miraba el título — y el título de un pliego español rara vez
    # nombra la tecnología. En PLACSP viene del `<summary>` ATOM, así que son
    # cadenas cortas sobre ~1,6 k filas.
    # `fuente` no puntúa: viaja con `url` porque es lo que decide cómo se
    # etiqueta ese enlace en el inspector del Radar (PLACSP, TED, PSCP…).
    _SCORING_COLS = (
        "id_externo, titulo, descripcion, organo_contratacion, importe, cpv, "
        "fecha_limite, estado, ccaa, tecnologia, fecha_publicacion, ml_tech_principal, url, "
        "fuente, procedimiento, tramitacion"
    )

    @classmethod
    def _scoring_cols(cls) -> str:
        """``_SCORING_COLS`` con el importe del núcleo tipado vigente (T2).

        Apagado devuelve ``_SCORING_COLS`` byte a byte. Encendido proyecta la
        sombra casteada con ``AS importe``, para que la fila siga teniendo la
        clave que lee ``services/analytics/scoring.py``.
        """
        return cls._SCORING_COLS.replace(
            "organo_contratacion, importe,",
            f"organo_contratacion, {importe_select_sql(None)},",
            1,
        )

    def importe_percentiles(self) -> tuple[float, float]:
        """(P10, P90) de importe sobre TODA la tabla.

        Fallback de ``importe_percentiles_universo`` para cuando el universo
        vivo tiene tan pocos importes que sus percentiles serían ruido: ahí una
        distribución estable —aunque contaminada— discrimina mejor que una
        calculada sobre un puñado de filas. No lo llames directamente desde el
        scoring; el llamante es ``services.analytics.scoring_signals``.

        Sin filtros a propósito. ``percentile_cont`` interpola linealmente,
        igual que ``Series.quantile`` por defecto.
        """
        sql = (
            "SELECT percentile_cont(0.10) WITHIN GROUP (ORDER BY importe), "
            "       percentile_cont(0.90) WITHIN GROUP (ORDER BY importe) "
            "FROM licitaciones WHERE importe IS NOT NULL"
        )
        with connect_read() as c:
            row = c.execute(sql).fetchone()
        if row is None or row[0] is None:
            return 0.0, 0.0
        return float(row[0]), float(row[1] or 0.0)

    def importe_percentiles_universo(
        self,
        *,
        hoy_iso: str,
        cerrados: tuple[str, ...] = ESTADOS_CERRADOS,
    ) -> tuple[float, float, int]:
        """(P10, P90, nº de importes) sobre el universo puntuable.

        El predicado es **el mismo** que el de ``scoring_candidates``: si uno
        cambia, el otro también. La dimensión ``importe`` del score normaliza
        una oportunidad contra la distribución de este resultado, así que la
        población de referencia tiene que ser aquella en la que esa oportunidad
        compite —el mercado abierto de hoy—, no la tabla entera: de sus
        1.640.915 filas (medido 2026-08-11) el 91% son avisos agregados de PSCP
        sin plazo propio que nunca fueron oportunidades. Con esa referencia, un
        contrato de 300 k€ se comparaba contra un corpus cuyos percentiles
        describen otro mercado.

        Devuelve también el conteo para que el llamante decida si la muestra da
        para percentiles o conviene caer al fallback global.
        """
        # Mismo predicado que `scoring_candidates`, también sobre el núcleo
        # tipado (T2): si el universo leyera la sombra y su distribución de
        # referencia el texto, cada fila se compararía contra otro mercado.
        abierta = abierta_sql_marcadores("estado", n=len(cerrados))
        guard = fecha_valida_sql("fecha_limite", None)
        fecha_limite = columna_nucleo_sql("fecha_limite", None)
        importe = importe_sql(None)
        sql = (
            f"SELECT percentile_cont(0.10) WITHIN GROUP (ORDER BY {importe}), "
            f"       percentile_cont(0.90) WITHIN GROUP (ORDER BY {importe}), "
            f"       COUNT({importe}) "
            "FROM licitaciones "
            f"WHERE {abierta} "
            f"  AND {guard} AND {fecha_limite} >= %s "
            f"  AND {importe} IS NOT NULL"
        )
        with connect_read() as c:
            row = c.execute(sql, [*cerrados, hoy_iso]).fetchone()
        if row is None or row[0] is None:
            return 0.0, 0.0, 0
        return float(row[0]), float(row[1] or 0.0), int(row[2] or 0)

    # Máximo de ofertas recibidas por expediente en la ventana pedida. Va como
    # sub-select y no como join directo contra ``adjudicaciones`` porque una
    # licitación multi-lote tiene una adjudicación por lote: sin colapsarlas
    # antes, sus ofertas pesarían una vez por lote en la media del segmento.
    _COMPETENCIA_SUB = (
        "SELECT a.licitacion_id, MAX(a.n_ofertas_recibidas) AS max_ofertas "
        "FROM adjudicaciones a "
        "WHERE a.n_ofertas_recibidas IS NOT NULL "
        "  AND a.fecha_adjudicacion >= %s "
        "GROUP BY a.licitacion_id"
    )

    def competencia_ofertas_por_cpv4(
        self, *, cutoff_iso: str
    ) -> tuple[list[CompetenciaCpv4Fila], float | None]:
        """(filas ``cpv4``/``media_ofertas``, media global) del universo del radar.

        Señal de competencia del scoring: cuántas ofertas suele recibir un
        expediente del segmento. La media global es el fallback para los CPV-4
        sin muestra propia, y por eso **no** aplica el ``HAVING`` ni el filtro de
        ``cpv``: cuenta todo lo que el universo tenga en la ventana.

        El predicado del universo se interpola desde
        :data:`db.sql_fragments.TECHNOLOGY_OBSERVED_SQL` y no se escribe a mano,
        porque ``v84_lic_universo_cpv_index`` crea un índice **parcial** con ese
        mismo texto: el planificador solo lo usa si puede demostrar que este
        WHERE implica el predicado del índice, y no normaliza variantes del
        ``COALESCE``. Una copia divergente aquí no rompería el resultado —
        volvería en silencio al Parallel Seq Scan de 9,5 s que motivó el índice.
        Las dos columnas que la consulta pide de ``licitaciones``
        (``id_externo`` para el join, ``cpv`` para el segmento) son exactamente
        las del índice, para que el nodo pueda resolverse sin bajar al heap.

        Vivía en ``services/analytics/scoring_signals.py``; baja aquí por
        ADR-022 (todo el SQL en ``db/``) al tocarla para el índice.

        ``cutoff_iso`` llega calculado por el llamante (ventana de 24 meses de
        calendario), como el resto de ventanas relativas de este módulo: el
        resultado no depende del reloj de quien lo corre.
        """
        por_cpv4 = (
            "SELECT substr(l.cpv, 1, 4) AS cpv4, AVG(sub.max_ofertas) AS media_ofertas "
            f"FROM ({self._COMPETENCIA_SUB}) sub "
            "JOIN licitaciones l ON l.id_externo = sub.licitacion_id "
            f"WHERE {TECHNOLOGY_OBSERVED_SQL} "
            "  AND l.cpv IS NOT NULL "
            "  AND length(l.cpv) >= 4 "
            "GROUP BY cpv4 "
            "HAVING COUNT(*) >= 3"
        )
        # Misma forma que la de arriba —agregar ``adjudicaciones`` primero y
        # unir después— y no el join sobre las filas crudas: el join entra con
        # una fila por expediente en vez de una por lote. Da el mismo número
        # (``id_externo`` es la PK, así que la unión es 1:1) leyendo menos.
        global_sql = (
            "SELECT AVG(sub.max_ofertas) AS media_global "
            f"FROM ({self._COMPETENCIA_SUB}) sub "
            "JOIN licitaciones l ON l.id_externo = sub.licitacion_id "
            f"WHERE {TECHNOLOGY_OBSERVED_SQL}"
        )
        with connect_read() as c:
            rows = rows_to_dicts(c.execute(por_cpv4, [cutoff_iso]))
            row_global = c.execute(global_sql, [cutoff_iso]).fetchone()
        media_global = (
            float(row_global[0]) if row_global is not None and row_global[0] is not None else None
        )
        return typed_rows(CompetenciaCpv4Fila, rows), media_global

    def scoring_candidates(
        self,
        *,
        hoy_iso: str,
        filters: LicitacionesFilters | None = None,
        cerrados: tuple[str, ...] = ESTADOS_CERRADOS,
    ) -> list[dict[str, Any]]:
        """Proyección acotada de candidatas a oportunidad: abiertas y en plazo.

        ADR-023: el scoring puntuaba la tabla entera vía pandas; una
        licitación cerrada/adjudicada nunca es una "oportunidad", así que el
        universo puntuable excluye los estados terminales.

        Se enumeran los estados **cerrados**, no los abiertos, que es la regla
        de ``shared.estados``: con la allowlist anterior (``PUB``/``EV``) todo
        expediente en un estado abierto que no fuera esos dos —``ADM``, el más
        común— quedaba fuera del Radar sin dejar rastro. Se vio al mandar el
        Radar a puntuar de verdad: con los 15 expedientes del seed (12 ``ADM``,
        3 ``ADJ``) el ranking salía vacío.

        **El estado no acotaba nada por sí solo.** Medido en producción el
        2026-08-11: de 1.640.915 filas, 1.501.273 no estaban en estado terminal
        —el 91%—, porque 1.460.719 llegaban de PSCP con ``PUBLICACIÓ
        AGREGADA``, que no es RES/ADJ/ANUL. Cargar eso en pandas son 1,5 M filas
        por 12 columnas en cada request: la API se quedaba sin memoria y Render
        reiniciaba la instancia (diez reinicios el 2026-08-11, uno por cada
        carga del Radar), o el ``statement_timeout`` mataba la consulta y el
        usuario veía "Error al cargar la bandeja del radar".

        Desde el 2026-08-26 esa fase sí tiene código propio (``AGR``) y sí es
        terminal —v91 la normalizó y ``shared.estados`` la cuenta cerrada—, así
        que hoy el filtro de estado por sí solo ya descarta el grueso. **El
        plazo vivo sigue siendo necesario igualmente**, por lo que se explica
        abajo: es una condición sobre la oportunidad, no un apaño de volumen, y
        quitarla volvería a meter en el Radar los expedientes abiertos cuyo
        plazo venció.

        Por eso el universo exige además **plazo vivo**: sin fecha límite en el
        futuro no hay nada que presentar, y el Radar es una bandeja de
        decisión. Eso deja 1.643 filas, tres órdenes de magnitud menos. Lo que
        cae son las 1.466.309 abiertas sin ``fecha_limite`` (99,5% de ellas
        ``PUBLICACIÓ AGREGADA``, avisos agregados sin plazo propio que nunca
        fueron oportunidades individuales) y las 33.321 con el plazo ya
        vencido.

        Consecuencia deliberada: este universo ya **no** coincide con
        ``total_activas`` del resumen, que sigue contando por estado. Son dos
        preguntas distintas —"cuántas siguen vivas en el sistema" frente a "a
        cuántas puedo presentarme hoy"— y el ranking necesita la segunda. Lo
        que v91 arregló no es esa divergencia sino que ``total_activas``
        respondiera mal a *su* pregunta: contaba 657.156 sobre 691.974 porque
        las publicaciones agregadas pasaban por abiertas.

        ``hoy_iso`` se inyecta (no ``now()`` en SQL) como en
        ``overview_para_hoy``: el corte queda fijado por el llamante y los
        tests no dependen del reloj.

        El predicado de estado + plazo está replicado en
        ``importe_percentiles_universo``, que calcula la distribución de
        referencia de la dimensión ``importe``: si cambia aquí, cambia allí.
        """
        # T2: una de las cinco consultas calientes. Plazo, filtros e importe
        # proyectado pasan por el núcleo tipado; con el flag apagado el SQL es
        # el de siempre (lo fija `tests/test_nucleo_tipado_consultas.py`).
        where, params = _build_where(
            filters or LicitacionesFilters(), nucleo=True, presentacion=True
        )
        abierta = abierta_sql_marcadores("estado", n=len(cerrados))
        guard = fecha_valida_sql("fecha_limite", None)
        fecha_limite = columna_nucleo_sql("fecha_limite", None)
        # C4.2 / D23 — el Radar enseña un contrato una vez.
        #
        # Este universo no excluía **ningún** duplicado, ni siquiera los
        # `confirmed`: TED acuña un `publication-number` por anuncio y PSCP cae
        # al `id` de la fila cuando no hay expediente, así que el mismo contrato
        # llegaba al Radar tantas veces como veces se hubiera reemitido. Desde
        # 2026-09-06 se excluían aquí a mano con la variante de presentación
        # (esconde también `pending`); desde 2026-10-17 la pide con
        # `presentacion=True` a `build_licitaciones_where` —viene dentro de
        # `where`—, que es la misma llave que usan el overview, el Resumen y el
        # calendario: el Radar es una lista que alguien lee, no una métrica de
        # cuota de mercado. El razonamiento completo está en ADR-026.
        sql = (
            f"SELECT {self._scoring_cols()} FROM licitaciones "
            f"WHERE {where} "
            f"  AND {abierta} "
            f"  AND {guard} AND {fecha_limite} >= %s"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [*params, *cerrados, hoy_iso]))

    def licitaciones_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        """Proyección de scoring para una lista exacta de ids (modo page-aligned)."""
        if not ids:
            return []
        placeholders = ",".join("%s" for _ in ids)
        sql = (
            f"SELECT {self._scoring_cols()} FROM licitaciones WHERE id_externo IN ({placeholders})"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, ids))

    def tech_signal_by_ids(
        self, ids: list[str], *, tecnologia: str | None = None
    ) -> dict[str, float]:
        """Fuerza de la señal técnica [0,1] por licitación, para las ids dadas.

        Combina las dos evidencias que el sistema ya produce y hasta ahora solo
        servían para filtrar o etiquetar:

        - ``licitacion_tecnologia_pliego``: derivada del **texto real de los
          pliegos**, con términos citables. Es la más fuerte de las dos y
          sobrevive al clobber de ``db/upsert.py``.
        - ``licitacion_tecnologia_score``: probabilidad del clasificador ML.

        Se toma el máximo: una tecnología confirmada por cualquiera de las dos
        vías está confirmada. Con ``tecnologia``, la fuerza es la de ESA
        tecnología (es el ranking de "las mejores oportunidades SAP", no "las
        mejores oportunidades que además son SAP"); sin filtro, la máxima sobre
        cualquiera.

        Se consulta **por ids** y no se cachea entera a propósito:
        ``licitacion_tecnologia_score`` tiene una fila por (licitación, label)
        sobre toda la tabla, así que puede llegar a millones — el patrón de
        carga completa que usan las otras señales aquí reventaría la memoria
        del proceso. El universo puntuable son ~1,6 k ids y ambas consultas
        atacan sus claves primarias.

        No usa ``licitaciones.ml_proba_max``: `db/upsert.py` la sobreescribe en
        cada re-scrape (esa es justamente la razón de existir de la tabla de
        pliego).
        """
        if not ids:
            return {}
        filtro_tech = " AND tecnologia = %s" if tecnologia else ""
        # Los sentinels («sin tecnología», «etiquetas sin cita») no son señal:
        # con su score 0 convertirían un «no se sabe» en fuerza 0.0.
        params: list[object] = [ids, list(SENTINELS)]
        if tecnologia:
            params.append(tecnologia)
        params.append(ids)
        if tecnologia:
            params.append(tecnologia)
        sql = (
            "SELECT licitacion_id, MAX(fuerza) AS fuerza FROM ("
            "  SELECT licitacion_id, MAX(score) AS fuerza"
            "    FROM licitacion_tecnologia_pliego"
            "   WHERE licitacion_id = ANY(%s) AND tecnologia <> ALL(%s)"
            f"{filtro_tech}"
            "   GROUP BY licitacion_id"
            "  UNION ALL"
            "  SELECT licitacion_id, MAX(probabilidad) AS fuerza"
            "    FROM licitacion_tecnologia_score"
            "   WHERE licitacion_id = ANY(%s)"
            f"{filtro_tech}"
            "   GROUP BY licitacion_id"
            ") sub GROUP BY licitacion_id"
        )
        with connect_read() as c:
            rows = rows_to_dicts(c.execute(sql, params))
        return {
            str(r["licitacion_id"]): float(r["fuerza"])
            for r in rows
            if r["licitacion_id"] is not None and r["fuerza"] is not None
        }

    def pipeline_window(
        self,
        filters: LicitacionesFilters,
        *,
        hoy_iso: str,
        hasta_iso: str,
    ) -> list[dict[str, Any]]:
        """Licitaciones con fecha_limite en (hoy, hoy+dias] — la ventana del pipeline.

        Proyección acotada por construcción: la ventana de vencimientos (≤365
        días) es una fracción pequeña de la tabla, y los buckets/scoring
        posteriores operan en Python sobre ese resultado ya reducido.
        """
        where, params = _build_where(filters, presentacion=True)
        guard = iso_guard("fecha_limite")
        sql = (
            f"SELECT {self._SCORING_COLS} FROM licitaciones "
            f"WHERE {where} AND {guard} AND fecha_limite > %s AND fecha_limite < %s "
            "ORDER BY fecha_limite"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [*params, hoy_iso, hasta_iso]))
