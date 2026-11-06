"""Overview: KPIs, embudo, mapa por CCAA y la tarjeta «Para hoy»."""

from __future__ import annotations

from typing import Any, TypedDict

from db.database import connect_read
from db.repositories.aggregates.filtros import (
    LicitacionesFilters,
    _build_where,
    _lectura,
)
from db.repositories.base import loose_distinct_count, rows_to_dicts, typed_rows
from db.sql_fragments import (
    empresa_key_sql,
    exclude_duplicados_presentacion_sql,
    importe_sql,
    iso_guard,
)
from shared.estados import abierta_sql


class ParaHoy(TypedDict):
    """Lo que devuelve :meth:`AggregateRepository.overview_para_hoy`."""

    calientes_hoy: int
    vencen_48h: int
    nuevas_24h: int
    total_activas: int
    #: Umbral de importe con el que se contó ``calientes_hoy``.
    importe_p75: float | None


def _para_hoy_vacio() -> ParaHoy:
    return {
        "calientes_hoy": 0,
        "vencen_48h": 0,
        "nuevas_24h": 0,
        "total_activas": 0,
        "importe_p75": None,
    }


# ── Formas de fila ──────────────────────────────────────────────────────
#
# Un ``TypedDict`` por SELECT: las claves son sus alias y los tipos los que
# psycopg devuelve para esas columnas (``COUNT`` → ``int``; ``SUM``/``AVG``
# de ``importe``, que es ``double precision`` → ``float``; ``AVG`` de un
# entero → ``Decimal``; las columnas de texto que admiten ``NULL`` →
# ``str | None``). Así un cambio de alias en el SQL lo detecta mypy en el
# servicio que construye el DTO, no un test de integración (si lo hay).


class KpisOverview(TypedDict):
    """Lo que devuelve :meth:`AggregateRepository.overview_kpis`."""

    total: int
    importe_total: float
    importe_medio: float
    organos: int


class EstadoConteoFila(TypedDict):
    estado: str
    n: int


class MesImporteFila(TypedDict):
    mes: str
    n_licitaciones: int
    importe: float


class OrganoTopFila(TypedDict):
    organo_contratacion: str
    n: int
    importe: float


class CcaaConteoFila(TypedDict):
    ccaa: str
    n: int
    #: ``NULL`` si ninguna fila de la comunidad trae importe.
    importe: float | None


class OverviewMixin:
    """Overview: KPIs, embudo, mapa por CCAA y la tarjeta «Para hoy»."""

    # ── Overview ──────────────────────────────────────────────────────────

    def overview_kpis(
        self, filters: LicitacionesFilters, *, conn: Any | None = None
    ) -> KpisOverview:
        """total, importe_total, importe_medio, organos_unicos — un SELECT.

        Una de las cinco consultas calientes de T2: filtros e importe pasan por
        el núcleo tipado (``nucleo=True`` e :func:`importe_sql`).
        """
        where, params = _build_where(filters, nucleo=True, presentacion=True)
        importe = importe_sql(None)
        sql = (
            "SELECT COUNT(*) AS total, "
            f"       COALESCE(SUM({importe}), 0) AS importe_total, "
            f"       AVG({importe}) AS importe_medio, "
            "       COUNT(DISTINCT organo_contratacion) AS organos "
            "FROM licitaciones WHERE " + where
        )
        with _lectura(conn) as c:
            row = c.execute(sql, params).fetchone()
        if row is None or int(row[0]) == 0:
            return {"total": 0, "importe_total": 0.0, "importe_medio": 0.0, "organos": 0}
        return {
            "total": int(row[0]),
            "importe_total": float(row[1] or 0.0),
            "importe_medio": float(row[2]) if row[2] is not None else 0.0,
            "organos": int(row[3] or 0),
        }

    def overview_por_estado(self, filters: LicitacionesFilters) -> list[EstadoConteoFila]:
        where, params = _build_where(filters, presentacion=True)
        sql = (
            "SELECT estado, COUNT(*) AS n FROM licitaciones "
            "WHERE " + where + " AND estado IS NOT NULL "
            "GROUP BY estado ORDER BY n DESC"
        )
        with connect_read() as c:
            return typed_rows(EstadoConteoFila, rows_to_dicts(c.execute(sql, params)))

    def overview_por_mes(self, filters: LicitacionesFilters) -> list[MesImporteFila]:
        where, params = _build_where(filters, presentacion=True)
        sql = (
            "SELECT substr(fecha_publicacion, 1, 7) AS mes, "
            "       COUNT(*) AS n_licitaciones, "
            "       COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            "WHERE " + where + " AND " + iso_guard("fecha_publicacion") + " "
            "GROUP BY mes ORDER BY mes"
        )
        with connect_read() as c:
            return typed_rows(MesImporteFila, rows_to_dicts(c.execute(sql, params)))

    def overview_top_organos(
        self, filters: LicitacionesFilters, n: int = 15
    ) -> list[OrganoTopFila]:
        where, params = _build_where(filters, presentacion=True)
        sql = (
            "SELECT organo_contratacion, COUNT(*) AS n, COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            "WHERE " + where + " AND organo_contratacion IS NOT NULL "
            "GROUP BY organo_contratacion ORDER BY n DESC LIMIT %s"
        )
        with connect_read() as c:
            return typed_rows(OrganoTopFila, rows_to_dicts(c.execute(sql, [*params, n])))

    def overview_funnel(self, filters: LicitacionesFilters) -> dict[str, int]:
        where, params = _build_where(filters, presentacion=True)
        # AGR, EJEC y CPM entran aquí desde v91, y no son un detalle: AGR es el
        # 93% del corpus (la publicación agregada de la PSCP catalana). Sin su
        # cubo, los cinco tramos originales sumaban el 7% de `total` y el embudo
        # del Resumen presentaba esa diferencia como si no existiera.
        codigos = ("PUB", "EV", "RES", "ADJ", "ANUL", "PRE", "AGR", "EJEC", "CPM")
        # Los códigos son constantes del vocabulario de `services.classification`
        # (ESTADO_LABELS), nunca entrada de usuario: se interpolan como literales
        # igual que hace `abierta_sql()`.
        filtros = ", ".join(
            f"COUNT(*) FILTER (WHERE estado = '{codigo}') AS c{i}"
            for i, codigo in enumerate(codigos)
        )
        sql = f"SELECT {filtros}, COUNT(*) AS total FROM licitaciones WHERE {where}"
        with connect_read() as c:
            row = c.execute(sql, params).fetchone()
        if row is None:
            return {**dict.fromkeys(codigos, 0), "total": 0}
        conteos = {codigo: int(row[i] or 0) for i, codigo in enumerate(codigos)}
        return {**conteos, "total": int(row[len(codigos)] or 0)}

    def overview_adjudicaciones_indicadores(
        self, *, conn: Any | None = None
    ) -> dict[str, float | None]:
        """HHI, % oferta única, lead time medio y % PYME, agregados en Postgres.

        Devuelve además ``adj_total`` y ``adj_con_n_ofertas``: la **cobertura**
        de ``pct_oferta_unica``, o sea sobre cuántas adjudicaciones del corpus se
        calcula ese porcentaje. No es un extra: sin esos dos contadores el
        servicio no puede distinguir "el 93 % de las adjudicaciones tuvo una sola
        oferta" de "el 93 % de las pocas filas que declaran el número de ofertas
        tuvo una sola", que es lo que de verdad decía el número en producción.

        Sustituye la carga full-table ``adjudicaciones⋈licitaciones`` que
        alimentaba estos tres KPIs vía pandas (27 s y ~170k filas por llamada
        medidos en prod, y bloqueada en Render por
        ``render_api_full_table_loads_blocked`` — que los dejaba a cero/None).
        Sin filtros a propósito: estos indicadores siempre ignoraron los
        filtros del endpoint (ver docstring de ``services/analytics/overview``).

        La clave de empresa replica ``services/adjudicaciones.py`` (NIF
        normalizado con fallback a nombre normalizado) usando además
        ``empresa_id`` — la resolución de entidad ya hecha en ingesta — como
        primera opción cuando existe.
        """
        empresa_key = empresa_key_sql("a")
        adj_guard = iso_guard("a.fecha_adjudicacion")
        pub_guard = iso_guard("l.fecha_publicacion")
        sql = (
            "SELECT "
            "  (SELECT COALESCE(SUM(POWER(cuota * 100, 2)), 0) FROM ( "
            "     SELECT SUM(a.importe_adjudicado) "
            "            / NULLIF(SUM(SUM(a.importe_adjudicado)) OVER (), 0) AS cuota "
            "     FROM adjudicaciones a "
            "     WHERE a.importe_adjudicado IS NOT NULL "
            f"      AND {empresa_key} IS NOT NULL "
            f"    GROUP BY {empresa_key} "
            "  ) shares) AS hhi, "
            "  (SELECT 100.0 * COUNT(*) FILTER (WHERE n_ofertas_recibidas = 1) "
            "          / NULLIF(COUNT(*) FILTER (WHERE n_ofertas_recibidas IS NOT NULL), 0) "
            "   FROM adjudicaciones) AS pct_oferta_unica, "
            "  (SELECT ROUND(AVG(lead)::numeric, 1) FROM ( "
            "     SELECT substr(a.fecha_adjudicacion, 1, 10)::date "
            "            - substr(l.fecha_publicacion, 1, 10)::date AS lead "
            "     FROM adjudicaciones a "
            "     JOIN licitaciones l ON l.id_externo = a.licitacion_id "
            f"    WHERE {adj_guard} AND {pub_guard} "
            "  ) t WHERE lead > 0) AS lead_time_medio, "
            # Denominador `COUNT(*)` (no solo las filas con es_pyme no nulo)
            # para dar el mismo resultado que services/analytics/competitors.py,
            # que trata el NULL como "no PYME". Dos KPIs con el mismo nombre y
            # distinta base serían peor que un solo número conservador.
            "  (SELECT 100.0 * COUNT(*) FILTER (WHERE es_pyme = 1) "
            "          / NULLIF(COUNT(*), 0) "
            "   FROM adjudicaciones) AS pct_pyme, "
            # Denominadores de la cobertura de `pct_oferta_unica`. Sin ellos,
            # `services/analytics/overview.py` no podía medir sobre cuántas filas
            # está calculando el porcentaje y devolvía cobertura *desconocida*,
            # con lo que la tira de Salud competitiva del Resumen se abstenía
            # siempre: la celda quedaba en «—» de forma permanente.
            #
            # Los dos números describen la misma base que el porcentaje de
            # arriba: `pct_oferta_unica` divide entre las filas con
            # `n_ofertas_recibidas` no nulo, y eso es exactamente
            # `adj_con_n_ofertas` sobre `adj_total`. Que valor y cobertura
            # compartan base es lo que hace la cobertura interpretable.
            #
            # `adj_con_es_pyme` NO se añade aquí a propósito: `pct_pyme` divide
            # entre `COUNT(*)` —el NULL cuenta como «no PYME», ver arriba—, así
            # que su valor y esa cobertura hablarían de bases distintas, y
            # publicarlo sin corregir antes el denominador sería pasar de ocultar
            # un número dudoso a enseñarlo. La condición está escrita en
            # `services/analytics/overview.py`, junto a `cobertura_pyme`.
            "  (SELECT COUNT(*) FROM adjudicaciones) AS adj_total, "
            "  (SELECT COUNT(*) FILTER (WHERE n_ofertas_recibidas IS NOT NULL) "
            "   FROM adjudicaciones) AS adj_con_n_ofertas"
        )
        with _lectura(conn) as c:
            row = c.execute(sql).fetchone()
        if row is None:
            return {
                "hhi": 0.0,
                "pct_oferta_unica": 0.0,
                "lead_time_medio": None,
                "pct_pyme": 0.0,
                # Sin fila no hay corpus que medir, y eso NO es cobertura 0 %
                # sino cobertura desconocida: `_cobertura` en el servicio trata
                # el universo a cero como desconocida y el consumidor se
                # abstiene, que es lo correcto aquí.
                "adj_total": 0.0,
                "adj_con_n_ofertas": 0.0,
            }
        hhi, pct_oferta_unica, lead_time, pct_pyme, adj_total, adj_con_n_ofertas = row
        lead_val = float(lead_time) if lead_time is not None and float(lead_time) > 0 else None
        return {
            "hhi": float(hhi or 0.0),
            "pct_oferta_unica": float(pct_oferta_unica or 0.0),
            "lead_time_medio": lead_val,
            "pct_pyme": float(pct_pyme or 0.0),
            "adj_total": float(adj_total or 0.0),
            "adj_con_n_ofertas": float(adj_con_n_ofertas or 0.0),
        }

    def overview_yoy_and_recent(
        self,
        filters: LicitacionesFilters,
        *,
        hace_30d_iso: str,
        hace_60d_iso: str,
    ) -> dict[str, float]:
        """Ventanas ``>= hoy-30d`` (SIN cota superior, igual que el pandas original:

        ``_yoy_delta_count``/``_importe_30d`` solo filtran por el límite
        inferior — una fecha de publicación futura, si existiera, se incluiría
        igual). ``lics_prev30d`` sí es un rango cerrado ``[hoy-60d, hoy-30d)``.
        """
        where, params = _build_where(filters, presentacion=True)
        col = "fecha_publicacion"
        guard = iso_guard(col)
        sql = (
            "SELECT "
            f"  COUNT(*) FILTER (WHERE {guard} AND {col} >= %s) AS lics_30d, "
            f"  COUNT(*) FILTER (WHERE {guard} AND {col} < %s AND {col} >= %s) AS lics_prev30d, "
            f"  COALESCE(SUM(importe) FILTER (WHERE {guard} AND {col} >= %s), 0)"
            "     AS importe_30d "
            "FROM licitaciones WHERE " + where
        )
        # OJO orden de binds: los ``?`` de la lista SELECT aparecen ANTES que
        # los del WHERE en el texto SQL final — el orden de los params debe
        # seguir la posición física del placeholder, no el orden en que se
        # construyen en Python.
        run_params = [hace_30d_iso, hace_30d_iso, hace_60d_iso, hace_30d_iso, *params]
        with connect_read() as c:
            row = c.execute(sql, run_params).fetchone()
        if row is None:
            return {"lics_30d": 0.0, "lics_prev30d": 0.0, "importe_30d": 0.0}
        lics_30d, lics_prev30d, importe_30d = row
        return {
            "lics_30d": float(lics_30d or 0),
            "lics_prev30d": float(lics_prev30d or 0),
            "importe_30d": float(importe_30d or 0.0),
        }

    def overview_concentracion_organos(
        self, filters: LicitacionesFilters, *, top_n: int = 10
    ) -> tuple[float, float]:
        """(top_n_importe, total_importe) agrupado por organo (dropna, min_count=1)."""
        where, params = _build_where(filters, presentacion=True)
        sql = (
            "SELECT SUM(importe) AS s FROM licitaciones "
            "WHERE " + where + " AND organo_contratacion IS NOT NULL "
            "GROUP BY organo_contratacion "
            "HAVING SUM(importe) IS NOT NULL "
            "ORDER BY s DESC"
        )
        with connect_read() as c:
            rows = c.execute(sql, params).fetchall()
        sums = [float(r[0]) for r in rows]
        return sum(sums[:top_n]), sum(sums)

    def overview_por_ccaa(self, filters: LicitacionesFilters) -> list[CcaaConteoFila]:
        """(ccaa, n, importe) por comunidad, de más a menos expedientes.

        ``importe`` es ``SUM(importe)`` tal cual: ``NULL`` si ninguna fila de la
        comunidad trae importe. Una sola agrupación sirve al reparto del Resumen
        y a la concentración geográfica de los indicadores de mercado
        (``services.analytics.overview.concentracion_top``), que antes hacía su
        propio ``GROUP BY ccaa`` para quedarse solo con las sumas.
        """
        where, params = _build_where(filters, presentacion=True)
        sql = (
            "SELECT ccaa, COUNT(*) AS n, SUM(importe) AS importe FROM licitaciones "
            "WHERE " + where + " AND ccaa IS NOT NULL "
            "GROUP BY ccaa ORDER BY n DESC, ccaa"
        )
        with connect_read() as c:
            return typed_rows(CcaaConteoFila, rows_to_dicts(c.execute(sql, params)))

    def overview_ccaa_cubiertas(self, filters: LicitacionesFilters) -> int:
        """CCAA distintas presentes en el ámbito.

        Sin filtros va por *loose index scan*: ``COUNT(DISTINCT ccaa)`` sobre la
        tabla entera medía 30,9 s de media en producción (35 llamadas, 84,5 s de
        pico) para devolver un número de dos cifras. Con filtros se mantiene el
        ``COUNT(DISTINCT)``, que ahí sí opera sobre un subconjunto y no puede
        saltar por el índice.
        """
        if filters.is_empty():
            with connect_read() as c:
                return loose_distinct_count(c, "licitaciones", "ccaa")
        where, params = _build_where(filters, presentacion=True)
        sql = "SELECT COUNT(DISTINCT ccaa) FROM licitaciones WHERE " + where
        with connect_read() as c:
            row = c.execute(sql, params).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def overview_tasa_anulacion(
        self, filters: LicitacionesFilters, *, hace_365d_iso: str, conn: Any | None = None
    ) -> tuple[int, int]:
        """(anul_count, total_count) sobre fecha_publicacion >= hoy-365d."""
        where, params = _build_where(filters, presentacion=True)
        guard = iso_guard("fecha_publicacion")
        sql = (
            "SELECT "
            "  COUNT(*) FILTER (WHERE estado = 'ANUL') AS anul, "
            "  COUNT(*) AS total "
            "FROM licitaciones "
            f"WHERE {where} AND {guard} AND fecha_publicacion >= %s"
        )
        with _lectura(conn) as c:
            row = c.execute(sql, [*params, hace_365d_iso]).fetchone()
        if row is None:
            return 0, 0
        return int(row[0] or 0), int(row[1] or 0)

    def importe_p75(self, *, conn: Any | None = None) -> float | None:
        """Percentil 75 de ``importe`` sobre toda la tabla.

        Alimenta el snapshot que habilita el camino rápido de
        :meth:`overview_para_hoy`, y es justo la parte cara de aquel cálculo:
        ``percentile_cont`` ordena todos los importes y con ``work_mem`` a
        3,5 MB eso se derrama a disco.

        ``None`` cuando no hay ningún importe. El llamante debe tratarlo como
        "sin umbral" y nunca como cero, que contaría todas las filas.
        """
        sql = (
            "SELECT percentile_cont(0.75) WITHIN GROUP (ORDER BY importe) "
            "FROM licitaciones WHERE importe IS NOT NULL"
        )
        with _lectura(conn) as c:
            row = c.execute(sql).fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])

    def count_total_activas(self, *, conn: Any | None = None) -> int:
        """Expedientes no terminales en toda la tabla, para el snapshot.

        Mismo universo de presentación que el listado (ADR-026 D23): el
        snapshot sirve el total global de ``/resumen`` y tiene que contar lo que
        la lista enseña, sin las republicaciones ``pending`` y ``confirmed``.
        """
        sql = (
            f"SELECT COUNT(*) FROM licitaciones WHERE {abierta_sql()} "
            f"AND {exclude_duplicados_presentacion_sql('id_externo')}"
        )
        with _lectura(conn) as c:
            row = c.execute(sql).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def overview_para_hoy(
        self,
        filters: LicitacionesFilters,
        *,
        hoy_iso: str,
        limite_48h_iso: str,
        hace_24h_iso: str,
        p75: float | None = None,
        total_activas: int | None = None,
    ) -> ParaHoy:
        """Los cuatro contadores del bloque "para hoy", y el P75 con que se contó.

        Compartido por ``services/analytics/overview.py`` (que ignora
        ``total_activas``) y por ``services/analytics/resumen.py``
        (``/analytics/resumen/hoy``, que los usa los cuatro): son los mismos
        contadores sobre el mismo conjunto filtrado, así que duplicar el SQL
        sería duplicar también las convenciones de fecha y el P75.

        ``p75`` y ``total_activas`` son los dos valores globales que el
        precálculo de KPIs deja en ``kpi_snapshots``. Si llegan **y** el ámbito
        es la tabla entera, se sirve por :meth:`_para_hoy_fast`; en cualquier
        otro caso se calcula todo en vivo, que con filtros es la única opción
        correcta.

        ``vencen_48h`` cuenta solo las **abiertas**. Contaba cualquier
        expediente con el plazo en la ventana, así que una licitación anulada o
        ya adjudicada con plazo mañana salía en la cola roja del Resumen: algo
        que exige acción hoy y a lo que ya no se puede presentar nadie.

        ``importe_p75`` es el umbral con el que se contó ``calientes_hoy``: el
        del snapshot en el camino rápido y el de la CTE ``p75`` —el del ámbito
        filtrado— en el vivo. Sale para que el enlace de la tarjeta pueda cortar
        por el mismo umbral que produjo la cifra. ``None`` solo cuando el ámbito
        no tiene ningún importe.
        """
        if filters.is_empty() and p75 is not None and total_activas is not None:
            return self._para_hoy_fast(
                hoy_iso=hoy_iso,
                limite_48h_iso=limite_48h_iso,
                hace_24h_iso=hace_24h_iso,
                p75=p75,
                total_activas=total_activas,
            )
        where, params = _build_where(filters, presentacion=True)
        pub_guard = iso_guard("fecha_publicacion")
        lim_guard = iso_guard("fecha_limite")
        # `abierta_sql()` y no `estado IN ('PUB','EV')`: con la lista blanca,
        # `total_activas` daba 0 sobre datos donde el Radar listaba 12 — todos
        # en `ADM`, que no es terminal. Ver `shared/estados.py`.
        abierta = abierta_sql()
        # Proyección explícita y no `SELECT *`: `filtered` se referencia dos
        # veces (en `p75` y en el FROM final), así que Postgres la materializa
        # en lugar de inlinearla. Con `SELECT *` eso son 1,64 M filas completas
        # —los ~46 bytes de estas cuatro columnas frente a la fila entera— que
        # con `work_mem` a 2 MB se derraman a disco y se releen dos veces.
        # Medido en producción el 2026-08-10: 26,5 s de media antes, 20,1 s con
        # la proyección acotada. Las cuatro columnas son exactamente las que
        # usan los FILTER de abajo; el WHERE del CTE se evalúa contra
        # `licitaciones`, así que `_build_where` puede seguir citando cualquier
        # otra columna.
        sql = (
            "WITH filtered AS (SELECT importe, fecha_limite, fecha_publicacion, estado "
            "                  FROM licitaciones WHERE " + where + "), "
            "p75 AS (SELECT percentile_cont(0.75) WITHIN GROUP (ORDER BY importe) AS v "
            "        FROM filtered WHERE importe IS NOT NULL) "
            "SELECT "
            "  COUNT(*) FILTER ("
            f"    WHERE {abierta} "
            f"     AND {lim_guard} AND fecha_limite > %s "
            "      AND importe >= (SELECT v FROM p75)"
            "  ) AS calientes_hoy, "
            "  COUNT(*) FILTER ("
            f"    WHERE {abierta} "
            f"     AND {lim_guard} AND fecha_limite >= %s AND fecha_limite <= %s"
            "  ) AS vencen_48h, "
            f"  COUNT(*) FILTER (WHERE {pub_guard} AND fecha_publicacion >= %s) AS nuevas_24h, "
            f"  COUNT(*) FILTER (WHERE {abierta}) AS total_activas, "
            "  (SELECT v FROM p75) AS importe_p75 "
            "FROM filtered"
        )
        run_params = [*params, hoy_iso, hoy_iso, limite_48h_iso, hace_24h_iso]
        with connect_read() as c:
            row = c.execute(sql, run_params).fetchone()
        if row is None:
            return _para_hoy_vacio()
        calientes, vencen, nuevas, activas, umbral = row
        return {
            "calientes_hoy": int(calientes or 0),
            "vencen_48h": int(vencen or 0),
            "nuevas_24h": int(nuevas or 0),
            "total_activas": int(activas or 0),
            "importe_p75": float(umbral) if umbral is not None else None,
        }

    def _para_hoy_fast(
        self,
        *,
        hoy_iso: str,
        limite_48h_iso: str,
        hace_24h_iso: str,
        p75: float,
        total_activas: int,
    ) -> ParaHoy:
        """Los tres contadores con ventana, cada uno por su índice.

        Misma pregunta y mismos predicados que la rama con CTE, pero sin
        materializar ``filtered``: los tres acotan ventanas estrechas —plazo
        posterior a hoy, plazo dentro de 48 h, publicadas en 24 h— que
        ``idx_lic_fecha_limite`` e ``idx_fecha_pub`` resuelven por rango en vez
        de recorrer 1,64 M filas para contar unas pocas. ``total_activas`` no
        tiene ventana que acotar —es un recuento global por estado— así que
        viene del snapshot en lugar de calcularse aquí.

        Los ``iso_guard`` se conservan literalmente aunque el corte por fecha
        implique ya el extremo inferior: el techo ``< '3000'`` no lo implica, y
        repetirlos tal cual es lo que hace evidente que las dos ramas cuentan
        lo mismo. Como son rangos sobre la misma columna, Postgres los funde en
        un único recorrido del índice.
        """
        abierta = abierta_sql()
        pub_guard = iso_guard("fecha_publicacion")
        lim_guard = iso_guard("fecha_limite")
        sql = (
            "SELECT "
            "  (SELECT COUNT(*) FROM licitaciones "
            f"    WHERE {abierta} AND {lim_guard} AND fecha_limite > %s "
            "      AND importe >= %s) AS calientes_hoy, "
            "  (SELECT COUNT(*) FROM licitaciones "
            f"    WHERE {abierta} AND {lim_guard} AND fecha_limite >= %s AND fecha_limite <= %s) "
            "     AS vencen_48h, "
            "  (SELECT COUNT(*) FROM licitaciones "
            f"    WHERE {pub_guard} AND fecha_publicacion >= %s) AS nuevas_24h"
        )
        run_params: list[object] = [hoy_iso, p75, hoy_iso, limite_48h_iso, hace_24h_iso]
        with connect_read() as c:
            row = c.execute(sql, run_params).fetchone()
        if row is None:
            return _para_hoy_vacio()
        return {
            "calientes_hoy": int(row[0] or 0),
            "vencen_48h": int(row[1] or 0),
            "nuevas_24h": int(row[2] or 0),
            "total_activas": total_activas,
            "importe_p75": p75,
        }
