"""Proyectos por familia y módulo, tipos de contrato, CPV y listas controladas."""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, TypedDict

from db.database import connect_read
from db.repositories.aggregates.filtros import (
    LicitacionesFilters,
    _AgregadosBase,
    _build_where,
)
from db.repositories.base import rows_to_dicts, typed_rows
from db.sql_fragments import (
    iso_guard,
    tecnologia_en_csv_sql,
)


class TipoContratoFila(TypedDict):
    tipo_contrato: str
    count: int
    importe: float


class TipoEstadoConteoFila(TypedDict):
    tipo_contrato: str
    estado: str
    n: int


class CpvConteoFila(TypedDict):
    cpv: str
    count: int
    importe: float


class ProyectosMixin(_AgregadosBase):
    """Proyectos por familia y módulo, tipos de contrato, CPV y listas controladas."""

    # ── Proyectos por familia (2026-10) ──────────────────────────────────
    #
    # Una familia es un conjunto de códigos de ``tecnologia`` (su categoría y
    # sus fabricantes, ``config.keywords.codigos_de_familia``): pertenecer es
    # solapar el CSV de la fila con ese conjunto, la misma expresión que el
    # filtro del ámbito (:func:`db.sql_fragments.tecnologia_en_csv_sql`). El
    # ``WHERE`` lleva ``_CON_TECNOLOGIA`` para que el plan recorra solo las
    # filas etiquetadas por su índice, no la tabla entera.

    def proyectos_familias_stats(
        self,
        filters: LicitacionesFilters,
        *,
        codigos_por_familia: dict[str, list[str]],
    ) -> tuple[dict[str, tuple[int, float]], int, float]:
        """Conteo/importe por familia + (licitaciones con alguna familia, su importe).

        Una licitación con códigos de dos familias cuenta en las dos; el par
        final la cuenta una vez, con su importe una vez.
        """
        todos = [codigo for codigos in codigos_por_familia.values() for codigo in codigos]
        if not todos:
            return {}, 0, 0.0
        where, params = _build_where(filters)
        selects: list[str] = []
        run_params: list[object] = []
        for codigos in [*codigos_por_familia.values(), todos]:
            pertenece = tecnologia_en_csv_sql("tecnologia", n=len(codigos))
            selects.append(f"COUNT(*) FILTER (WHERE {pertenece})")
            selects.append(f"COALESCE(SUM(importe) FILTER (WHERE {pertenece}), 0)")
            run_params.extend([*codigos, *codigos])
        sql = (
            "SELECT " + ", ".join(selects) + " FROM licitaciones "
            f"WHERE {where} AND {self._CON_TECNOLOGIA}"
        )
        with connect_read() as c:
            row = c.execute(sql, [*run_params, *params]).fetchone()
        if row is None:
            return {}, 0, 0.0
        por_familia: dict[str, tuple[int, float]] = {}
        for i, familia in enumerate(codigos_por_familia):
            count = int(row[i * 2] or 0)
            if count:
                por_familia[familia] = (count, float(row[i * 2 + 1] or 0.0))
        return por_familia, int(row[-2] or 0), float(row[-1] or 0.0)

    def proyectos_familias_yoy(
        self,
        filters: LicitacionesFilters,
        *,
        codigos_por_familia: dict[str, list[str]],
        hace_365d_iso: str,
        hace_730d_iso: str,
    ) -> dict[str, tuple[int, int]]:
        """{familia: (n_act, n_prev)} en ventanas de 12 meses consecutivas."""
        if not codigos_por_familia:
            return {}
        where, params = _build_where(filters)
        col = "fecha_publicacion"
        guard = iso_guard(col)
        selects: list[str] = []
        run_params: list[object] = []
        for codigos in codigos_por_familia.values():
            pertenece = tecnologia_en_csv_sql("tecnologia", n=len(codigos))
            selects.append(f"COUNT(*) FILTER (WHERE {pertenece} AND {guard} AND {col} >= %s)")
            selects.append(
                f"COUNT(*) FILTER (WHERE {pertenece} AND {guard} AND {col} < %s AND {col} >= %s)"
            )
            run_params.extend([*codigos, hace_365d_iso, *codigos, hace_365d_iso, hace_730d_iso])
        sql = (
            "SELECT " + ", ".join(selects) + " FROM licitaciones "
            f"WHERE {where} AND {self._CON_TECNOLOGIA}"
        )
        with connect_read() as c:
            row = c.execute(sql, [*run_params, *params]).fetchone()
        if row is None:
            return {}
        return {
            familia: (int(row[i * 2] or 0), int(row[i * 2 + 1] or 0))
            for i, familia in enumerate(codigos_por_familia)
        }

    # ── Proyectos & módulos (detección regex en el motor) ────────────────

    @staticmethod
    def _where_modulos(
        filters: LicitacionesFilters, solo_codigos: list[str] | None
    ) -> tuple[str, list[object]]:
        """El ``WHERE`` del ámbito, acotado a las filas con alguno de ``solo_codigos``.

        Desde 2026-10 los módulos SAP son el desglose de la familia ERP, así que
        se buscan solo en lo etiquetado como SAP: «financiero» es keyword de
        SAP FI y casaba con cualquier asesoramiento financiero.
        """
        where, params = _build_where(filters)
        if solo_codigos:
            where = f"{where} AND {tecnologia_en_csv_sql('tecnologia', n=len(solo_codigos))}"
            params = [*params, *solo_codigos]
        return where, params

    def proyectos_modulos_stats(
        self,
        filters: LicitacionesFilters,
        *,
        module_patterns: dict[str, str],
        all_pattern: str,
        solo_codigos: list[str] | None = None,
    ) -> tuple[dict[str, tuple[int, float]], int, float, int]:
        """Conteo/importe por módulo + (clasificadas, importe distinct, filas del ámbito).

        Los patrones llegan como regex POSIX (mismas alternancias escapadas que
        compilaba el servicio con ``re.IGNORECASE``); ``~* %s`` los evalúa en el
        motor sobre ``titulo`` — la columna de texto disponible en la
        proyección de stats (la detección pandas usaba titulo+descripcion solo
        si descripcion existía, y en stats no existe). El último elemento es el
        denominador del desglose: las filas del ámbito acotado por
        ``solo_codigos`` (con SAP, las licitaciones SAP).
        """
        where, params = self._where_modulos(filters, solo_codigos)
        selects: list[str] = []
        run_params: list[object] = []
        for pattern in module_patterns.values():
            selects.append("COUNT(*) FILTER (WHERE titulo ~* %s)")
            selects.append("COALESCE(SUM(importe) FILTER (WHERE titulo ~* %s), 0)")
            run_params.extend([pattern, pattern])
        selects.append("COUNT(*) FILTER (WHERE titulo ~* %s)")
        selects.append("COALESCE(SUM(importe) FILTER (WHERE titulo ~* %s), 0)")
        run_params.extend([all_pattern, all_pattern])
        selects.append("COUNT(*)")
        sql = "SELECT " + ", ".join(selects) + " FROM licitaciones WHERE " + where
        with connect_read() as c:
            row = c.execute(sql, [*run_params, *params]).fetchone()
        if row is None:
            return {}, 0, 0.0, 0
        por_modulo: dict[str, tuple[int, float]] = {}
        for i, mod in enumerate(module_patterns):
            count = int(row[i * 2] or 0)
            if count:
                por_modulo[mod] = (count, float(row[i * 2 + 1] or 0.0))
        total_clasificados = int(row[-3] or 0)
        importe_distinct = float(row[-2] or 0.0)
        return por_modulo, total_clasificados, importe_distinct, int(row[-1] or 0)

    def proyectos_modulos_yoy(
        self,
        filters: LicitacionesFilters,
        *,
        module_patterns: dict[str, str],
        hace_365d_iso: str,
        hace_730d_iso: str,
        solo_codigos: list[str] | None = None,
    ) -> dict[str, tuple[int, int]]:
        """{módulo: (n_act, n_prev)} en ventanas de 12 meses consecutivas."""
        where, params = self._where_modulos(filters, solo_codigos)
        col = "fecha_publicacion"
        guard = iso_guard(col)
        selects: list[str] = []
        run_params: list[object] = []
        for pattern in module_patterns.values():
            selects.append(f"COUNT(*) FILTER (WHERE titulo ~* %s AND {guard} AND {col} >= %s)")
            selects.append(
                f"COUNT(*) FILTER (WHERE titulo ~* %s AND {guard} AND {col} < %s AND {col} >= %s)"
            )
            run_params.extend([pattern, hace_365d_iso, pattern, hace_365d_iso, hace_730d_iso])
        sql = "SELECT " + ", ".join(selects) + " FROM licitaciones WHERE " + where
        with connect_read() as c:
            row = c.execute(sql, [*run_params, *params]).fetchone()
        if row is None:
            return {}
        return {
            mod: (int(row[i * 2] or 0), int(row[i * 2 + 1] or 0))
            for i, mod in enumerate(module_patterns)
        }

    def tipos_contrato_breakdown(self, filters: LicitacionesFilters) -> list[TipoContratoFila]:
        """(tipo_contrato, count, importe) — NULL/'' excluidos, count DESC."""
        where, params = _build_where(filters)
        sql = (
            "SELECT tipo_contrato, COUNT(*) AS count, COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            "WHERE " + where + " AND tipo_contrato IS NOT NULL AND trim(tipo_contrato) != '' "
            "GROUP BY tipo_contrato ORDER BY count DESC, tipo_contrato"
        )
        with connect_read() as c:
            return typed_rows(TipoContratoFila, rows_to_dicts(c.execute(sql, params)))

    def tipo_estado_crosstab(self, filters: LicitacionesFilters) -> list[TipoEstadoConteoFila]:
        """(tipo_contrato, estado, n) — tipo NULL/'' y estado NULL excluidos.

        Paridad con el ``groupby(["tipo","estado"])`` de pandas, que descartaba
        los NaN de ambas columnas.
        """
        where, params = _build_where(filters)
        sql = (
            "SELECT tipo_contrato, estado, COUNT(*) AS n FROM licitaciones "
            "WHERE " + where + " AND tipo_contrato IS NOT NULL AND trim(tipo_contrato) != '' "
            "AND estado IS NOT NULL "
            "GROUP BY tipo_contrato, estado ORDER BY tipo_contrato, estado"
        )
        with connect_read() as c:
            return typed_rows(TipoEstadoConteoFila, rows_to_dicts(c.execute(sql, params)))

    def cpv_top_por_count(self, filters: LicitacionesFilters, *, n: int) -> list[CpvConteoFila]:
        """(cpv, count, importe) top-N por count — cpv NULL/'' excluido."""
        where, params = _build_where(filters)
        sql = (
            "SELECT cpv, COUNT(*) AS count, COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            "WHERE " + where + " AND cpv IS NOT NULL AND trim(cpv) != '' "
            "GROUP BY cpv ORDER BY count DESC, cpv LIMIT %s"
        )
        with connect_read() as c:
            return typed_rows(CpvConteoFila, rows_to_dicts(c.execute(sql, [*params, n])))

    # Columnas de lista controlada CODICE. La familia (la clave) es la que
    # entiende `shared/procedimientos.py`; el valor, la columna que la guarda.
    _CODELIST_COLS: Final = MappingProxyType(
        {
            "procedimiento": "procedimiento",
            "tramitacion": "tramitacion",
            "tipo_contrato": "tipo_contrato",
        }
    )

    def codigos_codelist(self) -> dict[str, dict[str, int]]:
        """``{familia: {código crudo: nº de expedientes}}`` para las tres
        columnas de lista controlada.

        Devuelve los códigos **sin juzgarlos**: qué códigos existen es un hecho
        de la tabla y por tanto de `db/`; cuáles de ellos tienen etiqueta es
        una regla de dominio y vive en `services/analytics/quality.py` con el
        catálogo delante. Partirlo así evita que el SQL tenga que incrustar la
        lista de códigos conocidos y quedarse desincronizado del catálogo.

        Se normaliza en SQL lo mismo que normaliza el catálogo (trim y ceros a
        la izquierda) para que ``01`` y ``1`` no se cuenten como dos códigos.
        """
        resultado: dict[str, dict[str, int]] = {}
        with connect_read() as c:
            for familia, col in self._CODELIST_COLS.items():
                # `ltrim(x, '0')` deja '' para un '0' o '000' literales, que no
                # es ningún código; `NULLIF` + `COALESCE` lo devuelve a '0'.
                normalizado = f"COALESCE(NULLIF(ltrim(trim({col}), '0'), ''), '0')"
                sql = (
                    f"SELECT {normalizado} AS codigo, COUNT(*) AS n "
                    "FROM licitaciones "
                    f"WHERE {col} IS NOT NULL AND trim({col}) != '' "
                    "GROUP BY 1 ORDER BY n DESC"
                )
                resultado[familia] = {
                    str(fila["codigo"]): int(fila["n"]) for fila in rows_to_dicts(c.execute(sql))
                }
        return resultado
