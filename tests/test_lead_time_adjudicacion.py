"""F4.4 — fecha prevista de adjudicación.

Lo que se prueba aquí es la **abstención**: sin fecha límite, sin histórico
suficiente o con datos malformados no hay estimación, y eso vale más que
acertar la fecha. Una fecha inventada en la pantalla donde se planifica un
equipo cuesta más que un hueco declarado.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest

from services.analytics.lead_time import estimar_adjudicacion
from shared.dto import ExpectedAward

#: Un órgano con lead-time conocido: mediana de 60 días, IQR de 45 a 90.
ORGANO_CONOCIDO: dict[str, Any] = {"n": 12, "p25": 45.0, "p50": 60.0, "p75": 90.0}


class TestEstimacion:
    def test_suma_la_mediana_a_la_fecha_limite(self) -> None:
        estimacion = estimar_adjudicacion("2026-10-01", ORGANO_CONOCIDO)
        assert estimacion is not None
        assert estimacion.fecha == date(2026, 11, 30)  # 1 oct + 60 días
        assert estimacion.metodo == "estimacion"

    def test_publica_el_intervalo_intercuartilico(self) -> None:
        estimacion = estimar_adjudicacion("2026-10-01", ORGANO_CONOCIDO)
        assert estimacion is not None
        assert estimacion.p25 == date(2026, 11, 15)  # +45
        assert estimacion.p75 == date(2026, 12, 30)  # +90
        assert estimacion.p25 <= estimacion.fecha <= estimacion.p75

    def test_publica_la_n_que_la_sostiene(self) -> None:
        """Una fecha sin `n` se lee como un compromiso, no como una estimación."""
        estimacion = estimar_adjudicacion("2026-10-01", ORGANO_CONOCIDO)
        assert estimacion is not None
        assert estimacion.n == 12

    def test_acepta_fecha_con_hora(self) -> None:
        """`fecha_limite` es TEXT y a veces trae la hora de cierre."""
        estimacion = estimar_adjudicacion("2026-10-01T13:00:00+02:00", ORGANO_CONOCIDO)
        assert estimacion is not None
        assert estimacion.fecha == date(2026, 11, 30)

    def test_acepta_date_y_datetime(self) -> None:
        por_date = estimar_adjudicacion(date(2026, 10, 1), ORGANO_CONOCIDO)
        por_datetime = estimar_adjudicacion(datetime(2026, 10, 1, 13, 0), ORGANO_CONOCIDO)
        assert por_date is not None and por_datetime is not None
        assert por_date.fecha == por_datetime.fecha == date(2026, 11, 30)

    def test_redondea_las_medianas_fraccionarias(self) -> None:
        """`percentile_cont` interpola, así que p50 llega con decimales."""
        estimacion = estimar_adjudicacion(
            "2026-10-01", {"n": 7, "p25": 10.4, "p50": 30.6, "p75": 60.5}
        )
        assert estimacion is not None
        assert estimacion.fecha == date(2026, 10, 1) + timedelta(days=31)


class TestAbstencion:
    def test_sin_historico_no_hay_estimacion(self) -> None:
        """El repositorio ya filtra por n mínimo: sin entrada, sin fecha."""
        assert estimar_adjudicacion("2026-10-01", None) is None

    def test_historico_vacio_no_hay_estimacion(self) -> None:
        assert estimar_adjudicacion("2026-10-01", {}) is None

    def test_sin_fecha_limite_no_hay_estimacion(self) -> None:
        assert estimar_adjudicacion(None, ORGANO_CONOCIDO) is None

    @pytest.mark.parametrize("basura", ["", "n/d", "01/10/2026", "2026-13", "  "])
    def test_fecha_malformada_no_hay_estimacion(self, basura: str) -> None:
        """Hay filas legacy con la fecha en DD/MM/YYYY (v59)."""
        assert estimar_adjudicacion(basura, ORGANO_CONOCIDO) is None

    def test_stats_incompletas_no_hay_estimacion(self) -> None:
        assert estimar_adjudicacion("2026-10-01", {"n": 9, "p50": 60.0}) is None

    def test_stats_con_n_cero(self) -> None:
        assert estimar_adjudicacion("2026-10-01", {"n": 0, "p25": 1, "p50": 2, "p75": 3}) is None

    def test_stats_no_numericas(self) -> None:
        assert (
            estimar_adjudicacion("2026-10-01", {"n": 9, "p25": "a", "p50": "b", "p75": "c"}) is None
        )


class TestContrato:
    def test_el_dto_admite_el_metodo_hito(self) -> None:
        """F2.1 sustituirá la estimación por el hito publicado sin tocar el
        contrato: el campo ya existe y la UI ya sabe distinguirlos."""
        hito = ExpectedAward(
            fecha=date(2026, 11, 30),
            p25=date(2026, 11, 30),
            p75=date(2026, 11, 30),
            n=0,
            metodo="hito",
        )
        assert hito.metodo == "hito"
        assert hito.p25 == hito.p75 == hito.fecha

    def test_el_dto_rechaza_un_metodo_inventado(self) -> None:
        with pytest.raises(ValueError):
            ExpectedAward(
                fecha=date(2026, 1, 1),
                p25=date(2026, 1, 1),
                p75=date(2026, 1, 1),
                metodo="adivinado",  # type: ignore[arg-type]  # es lo que se prueba
            )

    def test_pursuit_summary_nace_sin_estimacion(self) -> None:
        """Campo aditivo: una oportunidad sin órgano con histórico no cambia."""
        from shared.dto import PursuitSummary

        resumen = PursuitSummary(
            id=1,
            organization_id=1,
            licitacion_id="EXP-1",
            status="identified",
            decision="pending",
            outcome="pending",
            identified_at=datetime(2026, 9, 1),
            created_at=datetime(2026, 9, 1),
            updated_at=datetime(2026, 9, 1),
            version=1,
        )
        assert resumen.expected_award is None
        assert resumen.tender_organo is None
