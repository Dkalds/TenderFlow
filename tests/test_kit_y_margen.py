"""F2.3 (kit de presentación) y F2.4 (margen implícito).

Los dos comparten la misma regla y aquí se prueba en los dos: **no se rellena
lo que el pliego no dijo**. El kit vacío lo declara en vez de proponer un DEUC
genérico, y el margen no se calcula con la mitad de los perfiles —que daría un
coste bajo y un margen alto, que es la dirección peligrosa—.
"""

from __future__ import annotations

import pytest

from services.kit_presentacion import ORDEN_SOBRES, clave_de, construir_kit
from services.ml.pricing_scenarios import coste_de_tarifas, margen_de
from shared.tender_facts import EvidenceRef, RateCardFact, RequiredDocumentFact

_CITA = EvidenceRef(documento_id=1, page_number=2, quote="deberá aportarse")


def _doc(nombre: str, sobre: str = "otro", **extra: object) -> RequiredDocumentFact:
    return RequiredDocumentFact(
        description=f"Documento: {nombre}",
        confidence=0.9,
        evidence=[_CITA],
        name=nombre,
        scope=sobre,  # type: ignore[arg-type]  # literal validado por el modelo
        **extra,  # type: ignore[arg-type]
    )


def _tarifa(role: str, rate: float | None, horas: float | None) -> RateCardFact:
    return RateCardFact(
        description=f"Tarifa de {role}",
        confidence=0.9,
        evidence=[_CITA],
        role=role,
        max_rate_eur_hour=rate,
        estimated_hours=horas,
    )


# ── F2.3 ────────────────────────────────────────────────────────────────────


class TestKitVacio:
    def test_sin_documentos_extraidos_lo_dice(self) -> None:
        """Nunca una lista genérica: el usuario la daría por leída del pliego."""
        kit = construir_kit("EXP-1", [])
        assert kit.sin_extraccion is True
        assert kit.items == []

    def test_con_documentos_no_marca_sin_extraccion(self) -> None:
        kit = construir_kit("EXP-1", [_doc("DEUC", "sobre_a")])
        assert kit.sin_extraccion is False
        assert len(kit.items) == 1


class TestOrdenDelKit:
    def test_por_sobre_y_no_alfabetico(self) -> None:
        """El sobre A se prepara una vez; el C se escribe cada vez."""
        kit = construir_kit(
            "EXP-1",
            [
                _doc("Memoria técnica", "sobre_c"),
                _doc("Anexo", "otro"),
                _doc("DEUC", "sobre_a"),
                _doc("Oferta económica", "sobre_b"),
            ],
        )
        assert [i.sobre for i in kit.items] == list(ORDEN_SOBRES)

    def test_el_orden_de_sobres_es_el_de_preparacion(self) -> None:
        assert ORDEN_SOBRES == ("sobre_a", "sobre_b", "sobre_c", "otro")


class TestClaveEstable:
    def test_lleva_indice_y_nombre(self) -> None:
        """Ninguno de los dos basta solo: el índice cambia al reordenar y el
        nombre se repite."""
        clave = clave_de(0, _doc("Declaración responsable"))
        assert clave.startswith("0:")
        assert "declaracion" in clave or "declaración" in clave

    def test_dos_documentos_con_el_mismo_nombre_no_colisionan(self) -> None:
        kit = construir_kit("EXP-1", [_doc("Certificado"), _doc("Certificado")])
        claves = [i.clave for i in kit.items]
        assert len(set(claves)) == 2

    def test_el_nombre_se_normaliza(self) -> None:
        assert clave_de(1, _doc("  DEUC   firmado ")) == "1:deuc-firmado"


class TestEstadoDelKit:
    def test_sin_oportunidad_nada_esta_marcado(self) -> None:
        """La ficha del expediente puede enseñar el kit sin pursuit abierto."""
        kit = construir_kit("EXP-1", [_doc("DEUC", "sobre_a")])
        assert kit.items[0].listo is False
        assert kit.items[0].marcado_por is None

    def test_el_contador_de_listos(self) -> None:
        kit = construir_kit("EXP-1", [_doc("A"), _doc("B")])
        assert kit.listos == 0

    def test_subsanable_viaja_cuando_el_pliego_lo_dice(self) -> None:
        kit = construir_kit("EXP-1", [_doc("DEUC", "sobre_a", subsanable=True)])
        assert kit.items[0].subsanable is True

    def test_subsanable_none_cuando_el_pliego_calla(self) -> None:
        """`None` es «no lo dice», que no es lo mismo que «no lo es»."""
        kit = construir_kit("EXP-1", [_doc("DEUC", "sobre_a")])
        assert kit.items[0].subsanable is None


# ── F2.4 ────────────────────────────────────────────────────────────────────


class TestCosteDeTarifas:
    def test_suma_tarifa_por_horas(self) -> None:
        """50 €/h × 1.000 h + 80 €/h × 500 h = 50.000 + 40.000 = 90.000 €."""
        calculado = coste_de_tarifas(
            [_tarifa("Analista", 50, 1000), _tarifa("Arquitecto", 80, 500)]
        )
        assert calculado == (90_000.0, 2)

    def test_sin_tarifas_no_hay_coste(self) -> None:
        assert coste_de_tarifas([]) is None

    def test_un_perfil_sin_horas_no_cuenta(self) -> None:
        calculado = coste_de_tarifas([_tarifa("Analista", 50, 1000), _tarifa("Jefe", 90, None)])
        assert calculado == (50_000.0, 1)

    def test_si_ninguno_esta_completo_no_hay_coste(self) -> None:
        """Sumar los completos e ignorar el resto daría un margen optimista."""
        assert coste_de_tarifas([_tarifa("Analista", 50, None)]) is None
        assert coste_de_tarifas([_tarifa("Analista", None, 1000)]) is None


class TestMargenImplicito:
    def test_margen_positivo(self) -> None:
        margen = margen_de(100_000, [_tarifa("Analista", 50, 1000)])
        assert margen is not None
        assert margen.coste_estimado_eur == 50_000.0
        assert margen.margen_eur == 50_000.0
        assert margen.margen_pct == 0.5

    def test_margen_negativo_se_publica(self) -> None:
        """Ofertar bajo coste es una decisión; esconderla no ayuda a tomarla."""
        margen = margen_de(40_000, [_tarifa("Analista", 50, 1000)])
        assert margen is not None
        assert margen.margen_eur == -10_000.0

    def test_sin_tarifas_no_hay_margen(self) -> None:
        assert margen_de(100_000, []) is None

    def test_declara_que_es_un_techo(self) -> None:
        """Las tarifas del pliego son máximos, no el coste real de la empresa."""
        margen = margen_de(100_000, [_tarifa("Analista", 50, 1000)])
        assert margen is not None
        assert "techo" in margen.fuente
        assert margen.perfiles == 1

    def test_precio_cero_no_divide(self) -> None:
        margen = margen_de(0, [_tarifa("Analista", 50, 1000)])
        assert margen is not None
        assert margen.margen_pct is None


class TestContratoDeLasFamilias:
    @pytest.mark.parametrize(
        "familia",
        ["price_formula", "required_documents", "rate_cards", "budget_breakdown"],
    )
    def test_las_cuatro_familias_nuevas_existen(self, familia: str) -> None:
        """La métrica de cierre del plan: 13 familias de ficha pasan a 17."""
        from shared.tender_facts import TenderFactSheet

        assert familia in TenderFactSheet.model_fields

    def test_diecisiete_familias(self) -> None:
        from shared.tender_facts import TenderFactSheet

        assert len(TenderFactSheet.model_fields) == 17

    def test_una_ficha_antigua_sigue_validando(self) -> None:
        """Aditivas: las familias nuevas nacen vacías, no rompen lo extraído."""
        from shared.tender_facts import TenderFactSheet

        ficha = TenderFactSheet()
        assert ficha.price_formula == []
        assert ficha.required_documents == []
        assert ficha.rate_cards == []
        assert ficha.budget_breakdown == []
