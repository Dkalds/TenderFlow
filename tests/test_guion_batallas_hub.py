"""F2.6 (guion de oferta), F3.2 (batallas directas), F3.5 (cortes) y F6.5 (hub).

Dos criterios de aceptación cargan el peso aquí.

`TestContratoDeForma` convierte «solo esquema, nunca prosa» (D33) de una
instrucción al modelo —que a veces se ignora— en una propiedad comprobable de
la respuesta.

`TestQuePodemosAfirmar` fija el límite de lo que el producto puede decir sin
conocer el NIF propio: «nosotros perdimos» sí, «ellos ganaron contra nosotros»
no. Acusar a un competidor de haber ganado algo que ganó un tercero es un
error que un comercial detecta en la primera reunión, y con él se va la
confianza en el resto de la pantalla.
"""

from __future__ import annotations

from typing import Any

import pytest

from services.competitive.batallas import (
    MIN_POR_CELDA,
    TRAMOS_IMPORTE,
    construir_batallas,
    corte_por_procedimiento,
    corte_por_tramo,
    tramo_de,
)
from services.rag.guion_oferta import (
    MAX_FRASES_POR_PUNTO,
    GuionCriterio,
    GuionOferta,
    PuntoGuion,
    a_markdown,
    contar_frases,
    marcar_sin_base,
    validar_esquema,
)
from shared.tender_facts import EvidenceRef

_CITA = EvidenceRef(documento_id=1, page_number=3, quote="el licitador deberá acreditar")


def _guion(*textos: str, evidencia: list[EvidenceRef] | None = None) -> GuionOferta:
    return GuionOferta(
        licitacion_id="EXP-1",
        criterios=[
            GuionCriterio(
                criterio="Memoria técnica",
                peso_pct=40,
                puntos=[PuntoGuion(texto=t, evidencia=list(evidencia or [_CITA])) for t in textos],
            )
        ],
    )


# ── F2.6 ────────────────────────────────────────────────────────────────────


class TestContadorDeFrases:
    def test_una_frase(self) -> None:
        assert contar_frases("Describir la metodología de despliegue.") == 1

    def test_dos_frases(self) -> None:
        assert contar_frases("Describir el equipo. Incluir certificaciones.") == 2

    def test_sin_puntuacion_es_una(self) -> None:
        assert contar_frases("Plan de formación") == 1

    def test_vacio(self) -> None:
        assert contar_frases("   ") == 0


class TestContratoDeForma:
    def test_un_punto_de_dos_frases_pasa(self) -> None:
        assert validar_esquema(_guion("Describir el equipo. Incluir certificaciones.")) == []

    def test_un_parrafo_no_pasa(self) -> None:
        """D33: solo esquema. Tres frases ya es prosa."""
        largo = "Uno. Dos. Tres."
        infractores = validar_esquema(_guion(largo))
        assert infractores == [largo]

    def test_devuelve_los_textos_y_no_lanza(self) -> None:
        """El llamante decide si recorta, reintenta o rechaza."""
        infractores = validar_esquema(_guion("A. B. C. D.", "Correcto."))
        assert len(infractores) == 1

    def test_el_tope_es_dos(self) -> None:
        assert MAX_FRASES_POR_PUNTO == 2


class TestCitasVerificables:
    def test_una_cita_a_una_pagina_que_no_existe_no_es_una_cita(self) -> None:
        """Es una alucinación con formato de cita: peor que no citar, porque
        parece verificada."""
        marcado = marcar_sin_base(_guion("Describir el equipo."), paginas_validas=set())
        punto = marcado.criterios[0].puntos[0]
        assert punto.sin_base is True
        assert punto.evidencia == []

    def test_una_cita_valida_sobrevive(self) -> None:
        marcado = marcar_sin_base(_guion("Describir el equipo."), paginas_validas={(1, 3)})
        punto = marcado.criterios[0].puntos[0]
        assert punto.sin_base is False
        assert len(punto.evidencia) == 1

    def test_el_punto_sin_base_no_se_descarta(self) -> None:
        """Puede ser una buena idea; tiene que verse que es una propuesta."""
        marcado = marcar_sin_base(_guion("Proponer un piloto."), paginas_validas=set())
        assert len(marcado.criterios[0].puntos) == 1

    def test_no_muta_el_guion_original(self) -> None:
        original = _guion("Describir el equipo.")
        marcar_sin_base(original, paginas_validas=set())
        assert original.criterios[0].puntos[0].sin_base is False


class TestMarkdown:
    def test_incluye_el_criterio_y_su_peso(self) -> None:
        md = a_markdown(_guion("Describir el equipo."))
        assert "## Memoria técnica (40 puntos)" in md

    def test_la_cita_es_una_referencia_no_el_texto_citado(self) -> None:
        """Repetir el texto convertiría un esquema de una página en veinte."""
        md = a_markdown(_guion("Describir el equipo."))
        assert "doc 1 p. 3" in md
        assert "el licitador deberá acreditar" not in md

    def test_marca_los_puntos_sin_base(self) -> None:
        md = a_markdown(marcar_sin_base(_guion("Proponer un piloto."), paginas_validas=set()))
        assert "sin base en el pliego" in md

    def test_sin_guion_lo_dice(self) -> None:
        vacio = GuionOferta(licitacion_id="EXP-1", sin_guion="El pliego no publica criterios.")
        assert "no publica criterios" in a_markdown(vacio)


# ── F3.2 ────────────────────────────────────────────────────────────────────


def _cruce(**campos: Any) -> dict[str, Any]:
    base = {
        "licitacion_id": "EXP-1",
        "titulo": "Servicios SAP",
        "importe": 100_000.0,
        "offer_price_eur": 85_000.0,
        "importe_adjudicado": 80_000.0,
        "outcome": "lost",
        "adjudicatario_key": "rival",
    }
    return {**base, **campos}


class TestQuePodemosAfirmar:
    def test_ellos_ganaron_solo_si_el_adjudicatario_es_el_rival(self) -> None:
        resultado = construir_batallas("rival", [_cruce()])
        assert resultado.batallas[0].resultado == "ellos_ganaron"

    def test_si_gano_un_tercero_solo_decimos_que_perdimos(self) -> None:
        """Acusar a un competidor de algo que ganó otro cuesta la confianza."""
        resultado = construir_batallas("rival", [_cruce(adjudicatario_key="otra_empresa")])
        assert resultado.batallas[0].resultado == "perdimos"

    def test_sin_adjudicatario_observado_tampoco(self) -> None:
        resultado = construir_batallas("rival", [_cruce(adjudicatario_key=None)])
        assert resultado.batallas[0].resultado == "perdimos"

    def test_ganamos_lo_dice_nuestro_cierre(self) -> None:
        resultado = construir_batallas("rival", [_cruce(outcome="won")])
        assert resultado.batallas[0].resultado == "ganamos"

    def test_una_oportunidad_abierta_no_ha_terminado(self) -> None:
        resultado = construir_batallas("rival", [_cruce(outcome="pending")])
        assert resultado.batallas[0].resultado == "sin_resolver"

    def test_declara_que_no_conoce_el_nif_propio(self) -> None:
        """Sin decirlo, un historial lleno de «perdimos» parecería un rival
        invencible."""
        assert construir_batallas("rival", [_cruce()]).sin_nif_propio is True
        assert construir_batallas("rival", [_cruce()], nif_propio="A1").sin_nif_propio is False


class TestBajasDeLaBatalla:
    def test_calcula_las_dos_bajas(self) -> None:
        batalla = construir_batallas("rival", [_cruce()]).batallas[0]
        assert batalla.nuestra_baja == 0.15
        assert batalla.baja_ganadora == 0.2

    def test_sin_nuestro_precio_la_fila_lo_dice(self) -> None:
        """Se cuenta en `n` y se devuelve: esconderla mentiría sobre los cruces."""
        resultado = construir_batallas("rival", [_cruce(offer_price_eur=None)])
        assert resultado.n == 1
        assert resultado.batallas[0].nuestra_baja is None

    def test_sin_importe_no_hay_baja(self) -> None:
        batalla = construir_batallas("rival", [_cruce(importe=None)]).batallas[0]
        assert batalla.nuestra_baja is None

    def test_importe_cero_no_divide(self) -> None:
        batalla = construir_batallas("rival", [_cruce(importe=0)]).batallas[0]
        assert batalla.nuestra_baja is None


# ── F3.5 ────────────────────────────────────────────────────────────────────


class TestTramos:
    @pytest.mark.parametrize(
        ("importe", "esperado"),
        [
            (1_000, "< 15k"),
            (20_000, "15k-60k"),
            (100_000, "60k-140k"),
            (500_000, "140k-1M"),
            (5_000_000, "> 1M"),
        ],
    )
    def test_asigna_el_tramo(self, importe: float, esperado: str) -> None:
        assert tramo_de(importe) == esperado

    def test_los_limites_son_de_la_lcsp_no_potencias_de_diez(self) -> None:
        """Un tramo sin frontera legal detrás no explica por qué compite quien
        compite."""
        etiquetas = [t[0] for t in TRAMOS_IMPORTE]
        assert "< 15k" in etiquetas
        assert "15k-60k" in etiquetas

    def test_sin_importe_no_hay_tramo(self) -> None:
        assert tramo_de(None) is None
        assert tramo_de("n/d") is None

    def test_el_limite_inferior_es_inclusivo(self) -> None:
        assert tramo_de(15_000) == "15k-60k"


class TestCortes:
    def test_la_celda_escasa_no_publica_valor_pero_existe(self) -> None:
        filas = [_cruce(procedimiento="1") for _ in range(MIN_POR_CELDA - 1)]
        corte = corte_por_procedimiento(filas)
        assert corte[0].n == MIN_POR_CELDA - 1
        assert corte[0].baja_media is None

    def test_con_el_minimo_publica(self) -> None:
        filas = [_cruce(procedimiento="1") for _ in range(MIN_POR_CELDA)]
        corte = corte_por_procedimiento(filas)
        assert corte[0].baja_media == 0.2

    def test_la_etiqueta_no_es_el_codigo_crudo(self) -> None:
        """Un perfil que enseñe «procedimiento 9» no lo lee nadie."""
        filas = [_cruce(procedimiento="9") for _ in range(MIN_POR_CELDA)]
        assert corte_por_procedimiento(filas)[0].clave == "Abierto simplificado"

    def test_sin_procedimiento_la_fila_no_entra(self) -> None:
        filas = [_cruce(procedimiento=None) for _ in range(MIN_POR_CELDA)]
        assert corte_por_procedimiento(filas) == []

    def test_corte_por_tramo(self) -> None:
        filas = [_cruce(importe=500_000.0) for _ in range(MIN_POR_CELDA)]
        assert corte_por_tramo(filas)[0].clave == "140k-1M"

    def test_orden_determinista(self) -> None:
        filas = [_cruce(procedimiento="1") for _ in range(6)]
        filas += [_cruce(procedimiento="9") for _ in range(6)]
        assert [c.clave for c in corte_por_procedimiento(filas)] == [
            "Abierto",
            "Abierto simplificado",
        ]
