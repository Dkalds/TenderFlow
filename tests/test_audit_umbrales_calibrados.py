"""Los umbrales de la auditoría de verdad del dato están calibrados (C4.5).

Antes de este ítem `MAX_PCT_SIN_FECHA_LIMITE` valía 60 % y **todas** las fuentes
con volumen lo superaban: PSCP 96,6 %, PLACSP 93,1 %, TED 65,6 %, los backfills
mensuales 100 % (medido contra producción el 2026-09-06). Un gate que no puede
estar verde no mide nada — o el cron llevaba meses en rojo, o no corría.

Lo que estos tests fijan es la propiedad que hace útil un umbral calibrado: que
el límite salga del valor medido y no de un número escrito a mano, y que quien
lo lea dentro de seis meses pueda saber contra qué se comparó y cuándo.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from scripts.audit_domain_truth import (
    TODOS_LOS_UMBRALES,
    UMBRAL_DELTA_BAJA,
    UMBRAL_FECHA_LIMITE_POR_DEFECTO,
    UMBRAL_FECHAS_IMPOSIBLES,
    UMBRAL_UTE,
    UMBRALES_FECHA_LIMITE,
    Umbral,
    evaluar,
)


@pytest.mark.parametrize("umbral", TODOS_LOS_UMBRALES, ids=lambda u: u.nombre)
def test_cada_umbral_declara_su_procedencia(umbral: Umbral) -> None:
    """Valor medido, fecha y motivo. Sin los tres no se puede recalibrar."""
    assert umbral.medido >= 0
    assert umbral.fecha, f"{umbral.nombre} no dice cuándo se midió"
    assert len(umbral.fecha) == 10 and umbral.fecha[4] == "-", (
        f"{umbral.nombre}: la fecha debe ser ISO (YYYY-MM-DD), no {umbral.fecha!r}"
    )
    assert umbral.motivo, f"{umbral.nombre} no dice qué mide ni por qué ese valor"
    assert umbral.unidad


def test_el_limite_se_deriva_del_valor_medido() -> None:
    """No se escribe a mano: recalibrar es cambiar `medido`, no `limite`."""
    u = Umbral("prueba", 50.0, "2026-09-06", "%", "test", margen_pct=10.0)
    assert u.limite == 55.0
    assert u.supera(55.1)
    assert not u.supera(55.0)
    assert not u.supera(50.0)


def test_el_tope_recorta_los_porcentajes() -> None:
    """Un porcentaje con margen no puede pasar de 100.

    Sin el tope, PSCP al 96,6 % daría un límite de 106,3 %: imposible de
    superar, o sea un control desactivado sin decirlo.
    """
    u = Umbral("prueba", 96.6, "2026-09-06", "%", "test", tope=100.0)
    assert u.limite == 100.0


def test_margen_cero_significa_que_no_puede_crecer() -> None:
    """Las fechas imposibles se cortan en el origen: el histórico no crece."""
    assert UMBRAL_FECHAS_IMPOSIBLES.margen_pct == 0.0
    assert UMBRAL_FECHAS_IMPOSIBLES.limite == UMBRAL_FECHAS_IMPOSIBLES.medido
    assert UMBRAL_FECHAS_IMPOSIBLES.supera(UMBRAL_FECHAS_IMPOSIBLES.medido + 1)


def test_las_fuentes_medidas_estan_calibradas() -> None:
    """Las tres fuentes con volumen real tienen umbral propio.

    Uno global obligaría a elegir entre no detectar nada (al 100 %, el de los
    backfills) o alertar siempre (al 65 %, el de TED).
    """
    assert set(UMBRALES_FECHA_LIMITE) == {"pscp", "placsp", "ted"}


def test_una_fuente_sin_calibrar_no_alerta() -> None:
    """Un `bulk_YYYYMM` nuevo no puede poner el cron en rojo el día que aparece."""
    assert UMBRAL_FECHA_LIMITE_POR_DEFECTO.limite == 100.0
    assert not UMBRAL_FECHA_LIMITE_POR_DEFECTO.supera(100.0)


class TestEvaluar:
    """`evaluar` sobre las cifras reales de producción del 2026-09-06."""

    #: Copiadas de la medición; son el caso que el umbral anterior suspendía.
    MEDICION_REAL: ClassVar[dict[str, Any]] = {
        "fecha_limite": {
            "por_fuente": [
                {
                    "fuente": "pscp",
                    "total": 684_374,
                    "sin_fecha_limite": 661_211,
                    "pct_sin_fecha_limite": 96.6,
                },
                {
                    "fuente": "placsp",
                    "total": 6_853,
                    "sin_fecha_limite": 6_382,
                    "pct_sin_fecha_limite": 93.1,
                },
                {
                    "fuente": "ted",
                    "total": 2_015,
                    "sin_fecha_limite": 1_321,
                    "pct_sin_fecha_limite": 65.6,
                },
                {
                    "fuente": "bulk_202512",
                    "total": 1_269,
                    "sin_fecha_limite": 1_269,
                    "pct_sin_fecha_limite": 100.0,
                },
            ]
        },
        "fechas_imposibles": {"antes_de_1990": 50, "corte": "1990-01-01", "por_fuente": []},
    }

    def test_la_realidad_de_hoy_no_dispara_nada(self) -> None:
        assert evaluar(dict(self.MEDICION_REAL)) == []

    def test_una_regresion_si_dispara(self) -> None:
        """TED al 80 % (calibrado en 65,6, límite 72,16) tiene que saltar."""
        datos = {
            "fecha_limite": {
                "por_fuente": [
                    {
                        "fuente": "ted",
                        "total": 2_015,
                        "sin_fecha_limite": 1_612,
                        "pct_sin_fecha_limite": 80.0,
                    }
                ]
            }
        }
        violaciones = evaluar(datos)
        assert len(violaciones) == 1
        assert "ted" in violaciones[0]
        assert "72.16" in violaciones[0]

    def test_una_fuente_pequena_no_dispara(self) -> None:
        """3 de 4 sin plazo es 75 % y no significa nada."""
        datos = {
            "fecha_limite": {
                "por_fuente": [
                    {
                        "fuente": "ted",
                        "total": 4,
                        "sin_fecha_limite": 3,
                        "pct_sin_fecha_limite": 75.0,
                    }
                ]
            }
        }
        assert evaluar(datos) == []

    def test_mas_fechas_imposibles_disparan(self) -> None:
        """El conector las corta en el origen: si crecen, entran por otro camino."""
        datos = {"fechas_imposibles": {"antes_de_1990": 51, "corte": "1990-01-01"}}
        violaciones = evaluar(datos)
        assert len(violaciones) == 1
        assert "1990" in violaciones[0]

    def test_ute_y_baja_siguen_evaluandose(self) -> None:
        datos = {
            "ute": {
                "pct_filas_afectadas": UMBRAL_UTE.limite + 1,
                "filas_afectadas": 1,
                "total_filas": 10,
            },
            "baja": {"delta_puntos": UMBRAL_DELTA_BAJA.limite + 1},
        }
        assert len(evaluar(datos)) == 2
