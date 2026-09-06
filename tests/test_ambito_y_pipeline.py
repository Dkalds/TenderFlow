"""F6.1 (ámbito de mercado), F4.1 (valor ponderado) y F3.1 (motivos de pérdida).

Los tres comparten una idea que aquí se prueba explícitamente: **el supuesto
viaja con la cifra**. El ámbito dice de qué capa sale cada restricción, el
valor ponderado publica las probabilidades con las que se calculó, y el
reparto de pérdidas se abstiene por debajo del mínimo en vez de publicar un
porcentaje sobre tres casos.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from services.ambito_mercado import resolver_ambito
from services.pursuits import (
    MINIMO_PERDIDAS_POR_MOTIVO,
    MOTIVOS_PERDIDA,
    SIN_CODIFICAR,
    _perdidas_por_motivo,
    _trimestre,
    _valor_ponderado,
)
from shared.dto import PROBABILIDADES_ETAPA_DEFAULT, OrganizationSettings

# ── F6.1 ────────────────────────────────────────────────────────────────────


class TestPrecedenciaDelAmbito:
    def test_sin_nada_no_hay_restriccion(self) -> None:
        ambito = resolver_ambito(None, None)
        assert ambito.vacio
        assert ambito.nivel == "global"
        assert ambito.cpvs == []

    def test_solo_organizacion(self) -> None:
        ambito = resolver_ambito(None, OrganizationSettings(tecnologias=["SAP"], cpvs=["72"]))
        assert ambito.tecnologias == ["SAP"]
        assert ambito.cpvs == ["72"]
        assert ambito.nivel == "organizacion"

    def test_solo_perfil_personal(self) -> None:
        ambito = resolver_ambito({"cpvs": ["48"]}, None)
        assert ambito.cpvs == ["48"]
        assert ambito.nivel == "personal"

    def test_el_perfil_gana_a_la_organizacion(self) -> None:
        """La regla del plan, literal: personal → organización → global."""
        ambito = resolver_ambito({"cpvs": ["48"]}, OrganizationSettings(cpvs=["72"]))
        assert ambito.cpvs == ["48"]
        assert ambito.procedencia["cpvs"] == "personal"

    def test_la_precedencia_es_campo_a_campo(self) -> None:
        """No es «un bloque o el otro»: quien fija sus CPVs conserva el rango
        de importe del equipo sin tener que copiarlo a mano."""
        ambito = resolver_ambito(
            {"cpvs": ["48"]},
            OrganizationSettings(cpvs=["72"], importe_min=100_000),
        )
        assert ambito.cpvs == ["48"]
        assert ambito.importe_min == 100_000
        assert ambito.nivel == "mixto"

    def test_lista_vacia_del_perfil_no_anula_la_organizacion(self) -> None:
        """Vacío es «sin preferencia», no «ninguno»."""
        ambito = resolver_ambito({"cpvs": []}, OrganizationSettings(cpvs=["72"]))
        assert ambito.cpvs == ["72"]
        assert ambito.procedencia["cpvs"] == "organizacion"

    def test_un_cero_explicito_del_perfil_si_gana(self) -> None:
        """`importe_min = 0` es una decisión («me valen todos»), no un hueco."""
        ambito = resolver_ambito({"importe_min": 0}, OrganizationSettings(importe_min=500_000))
        assert ambito.importe_min == 0.0
        assert ambito.procedencia["importe_min"] == "personal"

    def test_la_procedencia_solo_lista_lo_que_restringe(self) -> None:
        ambito = resolver_ambito(None, OrganizationSettings(cpvs=["72"]))
        assert set(ambito.procedencia) == {"cpvs"}


class TestValidacionDeAjustes:
    def test_rango_de_importe_invertido(self) -> None:
        with pytest.raises(ValidationError, match="importe_max"):
            OrganizationSettings(importe_min=500_000, importe_max=100_000)

    def test_listas_sin_duplicados_ni_vacios(self) -> None:
        ajustes = OrganizationSettings(cpvs=["72", "72", "  ", "48"])
        assert ajustes.cpvs == ["72", "48"]

    def test_seis_conceptos_de_ambito(self) -> None:
        """La métrica de cierre del plan: de 1 campo de ámbito a 6 conceptos."""
        campos = set(OrganizationSettings.model_fields)
        assert {
            "tecnologias",
            "cpvs",
            "ccaas",
            "importe_min",
            "importe_max",
            "tipos_organo",
            "procedimientos_excluidos",
        } <= campos


# ── F4.1 ────────────────────────────────────────────────────────────────────


class TestProbabilidadesPorEtapa:
    def test_defaults_de_d34(self) -> None:
        ajustes = OrganizationSettings()
        assert ajustes.probabilidad_de("identified") == 10
        assert ajustes.probabilidad_de("submitted") == 60

    def test_la_organizacion_puede_editarlas(self) -> None:
        ajustes = OrganizationSettings(probabilidades_etapa={"submitted": 80})
        assert ajustes.probabilidad_de("submitted") == 80
        # Las que no toca conservan el default, no se pierden.
        assert ajustes.probabilidad_de("identified") == 10

    def test_una_etapa_terminal_no_puntua(self) -> None:
        """Contar lo ganado aquí lo sumaría dos veces: ya está en
        `awarded_amount_eur`."""
        assert OrganizationSettings().probabilidad_de("won") == 0
        assert OrganizationSettings().probabilidad_de("lost") == 0

    def test_etapa_inventada_se_rechaza(self) -> None:
        """Guardarla en silencio dejaría al admin creyendo que configuró algo."""
        with pytest.raises(ValidationError, match="Etapa desconocida"):
            OrganizationSettings(probabilidades_etapa={"vendida": 90})

    def test_porcentaje_fuera_de_rango(self) -> None:
        with pytest.raises(ValidationError, match="entre 0 y 100"):
            OrganizationSettings(probabilidades_etapa={"submitted": 150})


def _fila(status: str, importe: float | None, deadline: str | None = None) -> dict[str, Any]:
    return {"status": status, "tender_importe": importe, "tender_deadline": deadline}


class TestValorPonderado:
    def test_calculo_a_mano(self) -> None:
        """Fixture de ocho oportunidades con el valor calculado a mano.

        100k×10 % + 200k×20 % + 300k×30 % + 400k×50 % + 500k×60 %
        = 10k + 40k + 90k + 200k + 300k = 640.000 €.
        """
        rows = [
            _fila("identified", 100_000),
            _fila("qualifying", 200_000),
            _fila("go_no_go", 300_000),
            _fila("preparing", 400_000),
            _fila("submitted", 500_000),
            # Las tres terminales no son pipeline.
            _fila("won", 900_000),
            _fila("lost", 900_000),
            _fila("withdrawn", 900_000),
        ]
        valor, _prevision, sin_importe, _usadas = _valor_ponderado(rows, OrganizationSettings())
        assert valor == 640_000.0
        assert sin_importe == 0

    def test_publica_las_probabilidades_usadas(self) -> None:
        """Sin los supuestos, «640.000 € de pipeline» no es reproducible."""
        _valor, _prev, _sin, usadas = _valor_ponderado(
            [_fila("submitted", 100_000)], OrganizationSettings()
        )
        assert usadas == {"submitted": PROBABILIDADES_ETAPA_DEFAULT["submitted"]}

    def test_respeta_la_configuracion_de_la_organizacion(self) -> None:
        ajustes = OrganizationSettings(probabilidades_etapa={"submitted": 100})
        valor, _p, _s, usadas = _valor_ponderado([_fila("submitted", 100_000)], ajustes)
        assert valor == 100_000.0
        assert usadas == {"submitted": 100}

    def test_sin_importe_se_cuenta_aparte_y_no_como_cero(self) -> None:
        """Tratarlo como cero baja el pipeline en silencio."""
        valor, _p, sin_importe, _u = _valor_ponderado(
            [_fila("submitted", None), _fila("submitted", 100_000)], OrganizationSettings()
        )
        assert valor == 60_000.0
        assert sin_importe == 1

    def test_prevision_por_trimestre(self) -> None:
        valor, prevision, _s, _u = _valor_ponderado(
            [
                _fila("submitted", 100_000, "2026-11-15"),
                _fila("submitted", 200_000, "2027-02-01"),
            ],
            OrganizationSettings(),
        )
        assert prevision == {"2026-Q4": 60_000.0, "2027-Q1": 120_000.0}
        assert round(sum(prevision.values()), 2) == valor

    def test_sin_fecha_no_entra_en_la_prevision_pero_si_en_el_valor(self) -> None:
        """La oportunidad existe aunque no se sepa cuándo se resolverá."""
        valor, prevision, _s, _u = _valor_ponderado(
            [_fila("submitted", 100_000, None)], OrganizationSettings()
        )
        assert valor == 60_000.0
        assert prevision == {}

    def test_pipeline_vacio(self) -> None:
        assert _valor_ponderado([], OrganizationSettings()) == (0.0, {}, 0, {})

    @pytest.mark.parametrize(
        ("fecha", "esperado"),
        [
            ("2026-01-01", "2026-Q1"),
            ("2026-03-31", "2026-Q1"),
            ("2026-04-01", "2026-Q2"),
            ("2026-12-31", "2026-Q4"),
        ],
    )
    def test_limites_de_trimestre(self, fecha: str, esperado: str) -> None:
        assert _trimestre(fecha) == esperado

    def test_fecha_malformada_no_tiene_trimestre(self) -> None:
        assert _trimestre("01/10/2026") is None
        assert _trimestre(None) is None


# ── F3.1 ────────────────────────────────────────────────────────────────────


def _perdida(codigo: str | None) -> dict[str, Any]:
    return {"outcome": "lost", "outcome_reason_code": codigo}


class TestPerdidasPorMotivo:
    def test_se_abstiene_por_debajo_del_minimo(self) -> None:
        """«60 % por precio» sobre tres casos es ruido con forma de conclusión."""
        rows = [_perdida("precio")] * (MINIMO_PERDIDAS_POR_MOTIVO - 1)
        assert _perdidas_por_motivo(rows) == []

    def test_reparte_con_porcentaje(self) -> None:
        rows = [_perdida("precio")] * 3 + [_perdida("tecnica")] * 2
        reparto = _perdidas_por_motivo(rows)
        assert [(r.motivo, r.n) for r in reparto] == [("precio", 3), ("tecnica", 2)]
        assert reparto[0].pct == 0.6

    def test_los_sin_codigo_se_cuentan_aparte(self) -> None:
        """No se reparten entre los motivos: los inflarían."""
        rows = [_perdida("precio")] * 3 + [_perdida(None)] * 2
        motivos = {r.motivo for r in _perdidas_por_motivo(rows)}
        assert SIN_CODIFICAR in motivos

    def test_orden_determinista(self) -> None:
        """Dos consultas idénticas no pueden devolver órdenes distintos."""
        rows = [_perdida("tecnica")] * 2 + [_perdida("precio")] * 2 + [_perdida("plazo")]
        reparto = [r.motivo for r in _perdidas_por_motivo(rows)]
        assert reparto == ["precio", "tecnica", "plazo"]

    def test_las_ganadas_no_entran(self) -> None:
        rows = [_perdida("precio")] * 5 + [{"outcome": "won", "outcome_reason_code": None}] * 10
        reparto = _perdidas_por_motivo(rows)
        assert sum(r.n for r in reparto) == 5

    def test_los_motivos_salen_del_contrato(self) -> None:
        """Una lista paralela sería lo primero en quedarse vieja."""
        assert set(MOTIVOS_PERDIDA) == {
            "precio",
            "tecnica",
            "solvencia",
            "plazo",
            "desierto_o_anulado",
            "no_presentada",
            "otro",
        }
        assert SIN_CODIFICAR not in MOTIVOS_PERDIDA
