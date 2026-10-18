"""La republicación tiene una regla, y es distinta por superficie (C4.2 / D23).

`detect_republicaciones` marca **siempre** `pending` y ADR-026 no decía qué
hacer con esas filas, así que cada superficie hacía una cosa distinta sin
haberlo decidido: el Radar mostraba el mismo contrato tantas veces como se
hubiera reemitido, y la ficha lo servía sin decir que lo era.

Estos tests fijan la asimetría, que es la parte que se rompe sola si alguien
"unifica" los dos fragmentos SQL por parecerse.

Desde 2026-10-17 la fila «listados» de D23 también se cumple: ``_base_filters``
(listado, cursor, export) y la rama FTS emiten siempre la exclusión de
presentación, y ``build_licitaciones_where`` la emite **solo cuando se le pide**
con ``presentacion=True``, que es como la llaman las superficies que encabezan
o abren una lista (overview, Resumen, calendario de vencimientos, Radar). Las
agregaciones de Mercado la llaman sin ese flag y siguen contando: son
métricas, y además leen de un índice que no incluye ``id_externo`` (v144). El
recorrido con Postgres está en ``tests/test_listado_esconde_duplicados.py``;
aquí se fija el SQL emitido y quién lo pide, sin base.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from db.sql_fragments import (
    exclude_duplicados_presentacion_sql,
    exclude_duplicados_sql,
)

ROOT = Path(__file__).resolve().parent.parent


class TestFragmentos:
    def test_la_analitica_solo_esconde_confirmed(self) -> None:
        """Retirar un contrato de la cuota de mercado exige evidencia confirmada."""
        sql = exclude_duplicados_sql("a.licitacion_id")
        assert "'confirmed'" in sql
        assert "pending" not in sql

    def test_la_presentacion_esconde_tambien_pending(self) -> None:
        """En una lista que alguien lee, esconder de más solo cuesta una fila."""
        sql = exclude_duplicados_presentacion_sql("l.id_externo")
        assert "'confirmed'" in sql
        assert "'pending'" in sql

    def test_los_dos_fragmentos_no_son_el_mismo(self) -> None:
        """Si alguien los unifica, uno de los dos lados queda mal.

        Unificar hacia `confirmed` devuelve el Radar duplicado; unificar hacia
        `pending` mete falsos positivos en el HHI para siempre.
        """
        assert exclude_duplicados_sql("x") != exclude_duplicados_presentacion_sql("x")

    def test_ambos_respetan_la_columna_que_se_les_pasa(self) -> None:
        for fn in (exclude_duplicados_sql, exclude_duplicados_presentacion_sql):
            assert fn("a.licitacion_id").startswith("a.licitacion_id NOT IN")


class TestSuperficies:
    """Quién usa cuál, verificado sobre el código."""

    def test_el_ambito_compartido_solo_esconde_cuando_se_le_pide(self) -> None:
        """`build_licitaciones_where` es métrica por defecto y presentación con el flag.

        El orden importa: la exclusión va pegada a la base, antes de cualquier
        filtro, para que una superficie de presentación sin filtros emita
        exactamente ``1 = 1 AND <anti-join>``.
        """
        from db.repositories.aggregates import LicitacionesFilters, build_licitaciones_where

        where, _ = build_licitaciones_where(LicitacionesFilters())
        assert where == "1 = 1"
        assert "licitaciones_duplicados" not in where

        where, _ = build_licitaciones_where(LicitacionesFilters(), presentacion=True)
        assert where == "1 = 1 AND " + exclude_duplicados_presentacion_sql("id_externo")
        where_alias, _ = build_licitaciones_where(
            LicitacionesFilters(), alias="l", presentacion=True
        )
        assert where_alias == "1 = 1 AND " + exclude_duplicados_presentacion_sql("l.id_externo")

    #: Encabezan o abren una lista: cuentan lo que la lista enseña.
    PRESENTACION = (
        "overview_kpis",
        "overview_por_estado",
        "overview_por_mes",
        "overview_top_organos",
        "overview_funnel",
        "overview_yoy_and_recent",
        "overview_concentracion_organos",
        "overview_concentracion_ccaa",
        "overview_ccaa_cubiertas",
        "overview_tasa_anulacion",
        "overview_para_hoy",
        "resumen_timeline_items",
        "resumen_novedades",
        "resumen_sankey",
        "resumen_top_licitaciones",
        "vencimientos_diarios",
        "vencimientos_kpis",
        "scoring_candidates",
        "pipeline_window",
    )

    #: Mercado y sus drill-downs: métricas que cuentan sobre el ámbito entero y
    #: leen de ``idx_lic_analitica`` (v144), que no incluye ``id_externo``.
    METRICA = (
        "trends_daily",
        "geography_by_ccaa",
        "tecnologias_entries",
        "cpv_top_por_count",
        "forecast_monthly",
        "tipos_contrato_breakdown",
        "_organos_where",
        "licitaciones_por_organo",
        "tecnologia_detalle_kpis",
    )

    @staticmethod
    def _cuerpo(metodo: str) -> str:
        fuente = (ROOT / "db" / "repositories" / "aggregates.py").read_text(encoding="utf-8")
        patron = rf"    def {re.escape(metodo)}\(.*?(?=\n    def |\n    # ──|\Z)"
        cuerpo = re.search(patron, fuente, re.S)
        assert cuerpo, f"no se encontró {metodo}"
        return cuerpo.group(0)

    @pytest.mark.parametrize("metodo", PRESENTACION)
    def test_las_superficies_de_presentacion_piden_la_exclusion(self, metodo: str) -> None:
        """Cada una pasa por `_build_where` con `presentacion=True`.

        Hasta 2026-10-17 el Radar añadía la cláusula a mano; si cualquiera de
        estas dejara de pedirla, su cifra volvería a contar la copia del DOUE
        que el listado al que enlaza ya no enseña.
        """
        cuerpo = self._cuerpo(metodo)
        assert "_build_where(" in cuerpo
        assert "presentacion=True" in cuerpo

    @pytest.mark.parametrize("metodo", METRICA)
    def test_las_metricas_de_mercado_no_la_piden(self, metodo: str) -> None:
        """«Métrica cuenta»: la agregación no esconde y el índice v144 la sigue sirviendo."""
        cuerpo = self._cuerpo(metodo)
        assert "_build_where(" in cuerpo
        assert "presentacion" not in cuerpo

    def test_el_listado_usa_la_variante_de_presentacion(self) -> None:
        """`_base_filters` es el universo del listado, el cursor y el export (D23)."""
        from sqlalchemy import and_, select

        from db.models import compile_query, licitaciones
        from db.repositories.licitaciones import LicitacionRepository

        clausulas = LicitacionRepository._base_filters(only_classified=False)
        sql, _ = compile_query(select(licitaciones.c.id_externo).where(and_(*clausulas)))
        assert exclude_duplicados_presentacion_sql("licitaciones.id_externo") in sql

    def test_la_busqueda_de_texto_escribe_la_misma_regla(self) -> None:
        """La rama FTS monta su `WHERE` a mano: la cláusula tiene que estar en su código."""
        fuente = (ROOT / "db" / "repositories" / "licitaciones.py").read_text(encoding="utf-8")
        cuerpo = re.search(r"def _list_fts\(.*?def list_cursor\(", fuente, re.S)
        assert cuerpo, "no se encontró _list_fts"
        assert 'exclude_duplicados_presentacion_sql("l.id_externo")' in cuerpo.group(0)

    def test_la_analitica_de_adjudicaciones_no_cambio(self) -> None:
        """Las métricas competitivas siguen contando los `pending`."""
        fuente = (ROOT / "db" / "repositories" / "adjudicaciones.py").read_text(encoding="utf-8")
        assert "exclude_duplicados_sql" in fuente
        assert "exclude_duplicados_presentacion_sql" not in fuente, (
            "una métrica competitiva no puede esconder un duplicado sin confirmar"
        )

    def test_la_ficha_declara_la_republicacion(self) -> None:
        from api.routes.licitaciones import LicitacionDetail

        campo = LicitacionDetail.model_fields.get("republicacion_de")
        assert campo is not None, "la ficha no puede servir una republicación en silencio"
        assert campo.default is None, "no ser una republicación es el caso normal"

    def test_la_regla_esta_en_el_adr(self) -> None:
        """ADR-026 es donde el plan pide que viva la decisión, no un comentario."""
        adr = (
            ROOT / "docs" / "adr" / "ADR-026-caminos-de-lectura-y-precedencia-tecnologica.md"
        ).read_text(encoding="utf-8")
        assert "D23" in adr
        assert "republicaci" in adr.lower()
        assert "exclude_duplicados_presentacion_sql" in adr
