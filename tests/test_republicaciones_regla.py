"""La republicación tiene una regla, y es distinta por superficie (C4.2 / D23).

`detect_republicaciones` marca **siempre** `pending` y ADR-026 no decía qué
hacer con esas filas, así que cada superficie hacía una cosa distinta sin
haberlo decidido: el Radar mostraba el mismo contrato tantas veces como se
hubiera reemitido, y la ficha lo servía sin decir que lo era.

Estos tests fijan la asimetría, que es la parte que se rompe sola si alguien
"unifica" los dos fragmentos SQL por parecerse.
"""

from __future__ import annotations

import re
from pathlib import Path

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

    def test_el_radar_usa_la_variante_de_presentacion(self) -> None:
        """`scoring_candidates` es el universo del Radar y no excluía nada."""
        fuente = (ROOT / "db" / "repositories" / "aggregates.py").read_text(encoding="utf-8")
        cuerpo = re.search(r"def scoring_candidates\(.*?return rows_to_dicts", fuente, re.S)
        assert cuerpo, "no se encontró scoring_candidates"
        assert "exclude_duplicados_presentacion_sql" in cuerpo.group(0), (
            "el universo del Radar volvería a mostrar el mismo contrato N veces"
        )

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
