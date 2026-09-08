"""El importe dice de qué base es (C1.1, ADR-032, D21).

`scraper/codice_parser.py` tomaba `cbc:TaxExclusiveAmount` y, si faltaba, caía a
`cbc:TotalAmount`. El primero es la base **sin** IVA; el segundo lo **incluye**.
La fila guardaba un número y **no guardaba cuál de los dos fue**.

No es un error de precisión sino de significado: `bajas` calcula
`(importe - adjudicado) / importe` sobre una población en la que unas filas
llevan IVA y otras no, así que una baja del 21 % puede ser exactamente el
impuesto. Y `cbc:EstimatedOverallContractAmount` —el número con el que la Ley
9/2017 determina el procedimiento— no se extraía en absoluto.
"""

from __future__ import annotations

from lxml import etree

from scraper.codice_parser import (
    NS,
    TIPO_CON_IVA,
    TIPO_SIN_IVA,
    _importes_del_proyecto,
)

_PROJECT_XP = "./cac:ProcurementProject"


def _proyecto(*, sin_iva: str | None, con_iva: str | None, estimado: str | None) -> etree._Element:
    """Un `ProcurementProject` con los importes que se le pidan."""
    partes = []
    if sin_iva is not None:
        partes.append(
            f'<cbc:TaxExclusiveAmount currencyID="EUR">{sin_iva}</cbc:TaxExclusiveAmount>'
        )
    if con_iva is not None:
        partes.append(f'<cbc:TotalAmount currencyID="EUR">{con_iva}</cbc:TotalAmount>')
    if estimado is not None:
        partes.append(
            f'<cbc:EstimatedOverallContractAmount currencyID="EUR">{estimado}'
            "</cbc:EstimatedOverallContractAmount>"
        )
    xmlns = " ".join(f'xmlns:{p}="{u}"' for p, u in NS.items())
    xml = (
        f"<root {xmlns}><cac:ProcurementProject><cac:BudgetAmount>"
        + "".join(partes)
        + "</cac:BudgetAmount></cac:ProcurementProject></root>"
    )
    return etree.fromstring(xml.encode("utf-8"))


class TestExtraccion:
    def test_los_tres_importes_por_separado(self) -> None:
        """El fixture del criterio de aceptación: los tres presentes."""
        entry = _proyecto(sin_iva="100000.00", con_iva="121000.00", estimado="200000.00")
        importes = _importes_del_proyecto(entry, _PROJECT_XP)

        assert importes.base_sin_iva == 100_000.0
        assert importes.con_iva == 121_000.0
        assert importes.valor_estimado == 200_000.0
        assert importes.tipo == TIPO_SIN_IVA
        # `importe` es el alias de la base sin IVA: los consumidores existentes
        # (frontend, exports, scoring, vistas materializadas) no cambian.
        assert importes.importe == 100_000.0

    def test_sin_base_sin_iva_cae_a_con_iva_y_lo_dice(self) -> None:
        """El fallback se conserva; lo que cambia es que deja de ser invisible.

        Una fila con importe con IVA es más útil que una sin importe. Lo que no
        puede es entrar en un cálculo de baja como si fuera comparable.
        """
        entry = _proyecto(sin_iva=None, con_iva="121000.00", estimado=None)
        importes = _importes_del_proyecto(entry, _PROJECT_XP)

        assert importes.base_sin_iva is None
        assert importes.con_iva == 121_000.0
        assert importes.importe == 121_000.0
        assert importes.tipo == TIPO_CON_IVA

    def test_sin_ningun_importe_no_hay_tipo(self) -> None:
        """`None` (la fuente no publicó importe) es distinto de `desconocido`."""
        entry = _proyecto(sin_iva=None, con_iva=None, estimado=None)
        importes = _importes_del_proyecto(entry, _PROJECT_XP)

        assert importes.importe is None
        assert importes.tipo is None

    def test_el_valor_estimado_se_extrae_aunque_falte_el_presupuesto(self) -> None:
        """Es el número que determina el procedimiento; no depende del otro."""
        entry = _proyecto(sin_iva=None, con_iva=None, estimado="500000.00")
        importes = _importes_del_proyecto(entry, _PROJECT_XP)

        assert importes.valor_estimado == 500_000.0
        assert importes.importe is None


class TestParidadDeBase:
    """Ningún cálculo de baja mezcla tipos (criterio de aceptación de C1.1)."""

    @staticmethod
    def _baja(presupuesto: float, adjudicado: float) -> float:
        return (presupuesto - adjudicado) / presupuesto * 100

    def test_mezclar_bases_inventa_una_baja_del_iva(self) -> None:
        """Por qué el ítem existe, en aritmética.

        El mismo contrato: 100.000 sin IVA, 121.000 con IVA, adjudicado en
        100.000 sin IVA. Comparado contra su propia base, la baja es 0 —se
        adjudicó por el presupuesto—. Comparado contra el importe con IVA da
        17,4 %, que es una baja inventada por el impuesto.
        """
        assert self._baja(100_000, 100_000) == 0.0
        baja_falsa = self._baja(121_000, 100_000)
        assert 17.0 < baja_falsa < 18.0

    def test_el_fragmento_prefiere_la_base_sin_iva(self) -> None:
        from services.sql_fragments import BASE_COMPARABLE_SQL

        # El lote manda primero (su importe ya es base sin IVA del lote), luego
        # la base declarada, y solo entonces el histórico.
        assert BASE_COMPARABLE_SQL.index("lo.importe") < BASE_COMPARABLE_SQL.index(
            "l.importe_base_sin_iva"
        )
        assert BASE_COMPARABLE_SQL.index("l.importe_base_sin_iva") < BASE_COMPARABLE_SQL.index(
            "l.importe)"
        )

    def test_lo_que_lleva_iva_queda_fuera(self) -> None:
        from services.sql_fragments import SIN_IVA_CONOCIDO_SQL

        assert "'con_iva'" in SIN_IVA_CONOCIDO_SQL
        # `desconocido` sigue entrando: excluirlo hoy vaciaría el endpoint, y
        # decirlo en `base` es más honesto que devolver una tabla vacía.
        assert "desconocido" in SIN_IVA_CONOCIDO_SQL

    def test_el_modo_estricto_solo_admite_base_declarada(self) -> None:
        from services.sql_fragments import BASE_DECLARADA_SQL

        assert "'sin_iva'" in BASE_DECLARADA_SQL
        assert "importe_base_sin_iva IS NOT NULL" in BASE_DECLARADA_SQL


class TestContrato:
    """Las respuestas comparativas declaran su base."""

    def test_bajas_declara_base(self) -> None:
        from api.routes.competitive import BajaReferencia, BajasResult

        assert "base" in BajasResult.model_fields
        assert "base" in BajaReferencia.model_fields

    def test_escenarios_precio_declara_base(self) -> None:
        from services.ml.pricing_scenarios import PriceScenariosResult

        assert "base" in PriceScenariosResult.model_fields

    def test_el_modo_por_defecto_no_miente(self) -> None:
        """Por defecto la población es mixta, y el campo lo dice.

        Devolver `base: "sin_iva"` sobre una población que incluye el histórico
        `desconocido` sería la misma mentira que el ítem vino a quitar, con otra
        etiqueta.
        """
        from services.competitive.bajas import _filtro_de_base
        from services.sql_fragments import BASE_MIXTA, BASE_SIN_IVA

        _, base_defecto = _filtro_de_base(False)
        _, base_estricta = _filtro_de_base(True)
        assert base_defecto == BASE_MIXTA
        assert base_estricta == BASE_SIN_IVA


class TestModelo:
    def test_la_licitacion_lleva_los_cuatro_campos(self) -> None:
        from dataclasses import fields

        from db.upsert import Licitacion

        nombres = {f.name for f in fields(Licitacion)}
        assert {
            "importe",
            "importe_base_sin_iva",
            "importe_con_iva",
            "valor_estimado",
            "importe_tipo",
        } <= nombres

    def test_el_upsert_los_persiste(self) -> None:
        """Las columnas del INSERT salen de los campos del dataclass."""
        from db.upsert import _LIC_KEYS

        for campo in ("importe_base_sin_iva", "importe_con_iva", "valor_estimado", "importe_tipo"):
            assert campo in _LIC_KEYS
