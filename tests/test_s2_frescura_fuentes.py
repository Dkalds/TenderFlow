"""Frescura por fuente de ingesta (S2.3).

Hoy un conector puede llevar semanas muerto y el job sale verde: seis de los
siete corren con ``continue-on-error: true`` y el healthcheck solo miraba el
último ``extraction_run`` global, que el carril PLACSP mantiene fresco aunque
las demás fuentes estén paradas.

Sin BD: se inyecta el repositorio de salud.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

from scheduler.healthcheck import comprobar_frescura_fuentes
from scraper.connectors import REGISTERED_SOURCES, REGISTERED_SOURCES_BY_ID

AHORA = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


class _RepoFalso:
    """Repositorio de salud inyectable: solo necesita ``list_health``."""

    def __init__(self, filas: list[dict[str, Any]]) -> None:
        self._filas = filas

    def list_health(self) -> list[dict[str, Any]]:
        return self._filas


def _fila(source: str, *, horas: float | None, status: str = "success") -> dict[str, Any]:
    ultimo = None if horas is None else (AHORA - timedelta(hours=horas)).isoformat()
    return {"source": source, "status": status, "last_success_at": ultimo}


def _todas_frescas() -> list[dict[str, Any]]:
    return [_fila(s.source_id, horas=1) for s in REGISTERED_SOURCES]


# ---------------------------------------------------------------------------
# El inventario
# ---------------------------------------------------------------------------


def test_el_inventario_cubre_las_fuentes_vivas() -> None:
    assert set(REGISTERED_SOURCES_BY_ID) == {
        "placsp",
        "ted",
        "galicia_rss",
        "euskadi_rss",
        "pscp",
        "tacrc",
        "placsp_watched_company_awards",
    }


def test_placsp_tiene_el_umbral_del_carril_diario() -> None:
    """36 h = nueve ciclos de 4 h, el mismo número que ``--freshness-hours``."""
    assert REGISTERED_SOURCES_BY_ID["placsp"].max_lag_hours == 36


def test_las_fuentes_de_descubrimiento_tienen_umbral_semanal() -> None:
    for source_id in ("ted", "galicia_rss", "euskadi_rss", "tacrc"):
        assert REGISTERED_SOURCES_BY_ID[source_id].max_lag_hours == 168


def test_toda_fuente_declara_por_que_tiene_ese_umbral() -> None:
    """Un umbral sin motivo escrito se relaja hasta que deja de alertar."""
    for fuente in REGISTERED_SOURCES:
        assert fuente.motivo.strip()
        assert fuente.max_lag_hours > 0
        assert fuente.modulo.startswith("scraper.connectors.")


def test_las_fuentes_gateadas_por_variable_de_entorno_son_opcionales() -> None:
    assert REGISTERED_SOURCES_BY_ID["pscp"].opcional
    assert REGISTERED_SOURCES_BY_ID["tacrc"].opcional
    assert not REGISTERED_SOURCES_BY_ID["placsp"].opcional


# ---------------------------------------------------------------------------
# El chequeo
# ---------------------------------------------------------------------------


def test_todas_frescas_no_reporta_nada() -> None:
    resultado = comprobar_frescura_fuentes(_RepoFalso(_todas_frescas()), ahora=AHORA)

    assert resultado["atrasadas"] == []
    assert resultado["sin_registro"] == []
    assert resultado["apagadas"] == []
    assert resultado["fuentes"]["placsp"]["estado"] == "fresca"


def test_una_fuente_pasada_de_su_umbral_sale_atrasada() -> None:
    filas = _todas_frescas()
    filas[0] = _fila("placsp", horas=40)  # umbral 36

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["atrasadas"] == ["placsp"]
    assert resultado["fuentes"]["placsp"]["lag_hours"] == 40.0


def test_cada_fuente_se_mide_contra_su_propio_umbral() -> None:
    """40 h atrasan a PLACSP y no a Galicia: el punto del inventario."""
    filas = [
        _fila("placsp", horas=40),
        _fila("galicia_rss", horas=40),
        *[
            _fila(s.source_id, horas=1)
            for s in REGISTERED_SOURCES
            if s.source_id not in ("placsp", "galicia_rss")
        ],
    ]

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["atrasadas"] == ["placsp"]
    assert resultado["fuentes"]["galicia_rss"]["estado"] == "fresca"


def test_apagada_no_es_lo_mismo_que_muerta() -> None:
    """``disabled`` lo escribe el propio conector cuando le falta su variable.

    Es lo que S2.5 añade a PSCP y TACRC, y es la distinción que el
    ``continue-on-error: true`` del workflow borraba.
    """
    filas = _todas_frescas()
    filas = [f for f in filas if f["source"] != "pscp"]
    filas.append(_fila("pscp", horas=None, status="disabled"))

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["apagadas"] == ["pscp"]
    assert resultado["atrasadas"] == []
    assert resultado["fuentes"]["pscp"]["estado"] == "apagada"


def test_una_fuente_apagada_que_vuelve_a_correr_vuelve_a_medirse() -> None:
    filas = _todas_frescas()
    filas = [f for f in filas if f["source"] != "pscp"]
    filas.append(_fila("pscp", horas=100, status="success"))  # umbral 72

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["apagadas"] == []
    assert resultado["atrasadas"] == ["pscp"]


def test_una_fuente_obligatoria_sin_registro_alerta() -> None:
    filas = [f for f in _todas_frescas() if f["source"] != "placsp"]

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["sin_registro"] == ["placsp"]
    assert resultado["fuentes"]["placsp"]["estado"] == "sin_registro"


def test_una_fuente_opcional_sin_registro_no_alerta() -> None:
    """Repetir cada seis horas que algo nunca se configuró es el ruido que
    acaba con el check desactivado."""
    filas = [f for f in _todas_frescas() if f["source"] != "tacrc"]

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["sin_registro"] == []
    assert resultado["fuentes"]["tacrc"]["estado"] == "sin_registro"


def test_una_fila_sin_ningun_run_exitoso_cuenta_como_atrasada() -> None:
    """Hay registro (la fuente corrió) pero nunca terminó bien."""
    filas = [f for f in _todas_frescas() if f["source"] != "ted"]
    filas.append(_fila("ted", horas=None, status="failed"))

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["atrasadas"] == ["ted"]
    assert resultado["fuentes"]["ted"]["lag_hours"] is None


def test_una_fecha_ilegible_no_se_cuenta_como_fresca() -> None:
    filas = [f for f in _todas_frescas() if f["source"] != "ted"]
    filas.append({"source": "ted", "status": "success", "last_success_at": "ayer"})

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["atrasadas"] == ["ted"]


def test_las_fuentes_bulk_efimeras_se_ignoran() -> None:
    """``bulk_YYYYMM`` es una fuente por mes reprocesado: no tiene SLA."""
    filas = [*_todas_frescas(), _fila("bulk_202401", horas=9000)]

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["atrasadas"] == []
    assert "bulk_202401" not in resultado["fuentes"]


# ---------------------------------------------------------------------------
# Integración con el informe del healthcheck
# ---------------------------------------------------------------------------


def test_el_informe_incluye_la_frescura_y_avisa() -> None:
    from scheduler.healthcheck import _incorporar_frescura_fuentes

    checks: list[dict[str, object]] = []
    warnings: list[str] = []
    info: dict[str, object] = {}

    with (
        patch(
            "scheduler.healthcheck.comprobar_frescura_fuentes",
            return_value={
                "atrasadas": ["placsp"],
                "apagadas": ["pscp"],
                "sin_registro": ["ted"],
                "fuentes": {},
            },
        ),
        patch("scheduler.healthcheck.notify") as notificar,
    ):
        _incorporar_frescura_fuentes(checks, warnings, info)

    assert "fuente_atrasada:placsp" in warnings
    assert "fuente_sin_registro:ted" in warnings
    assert {"name": "fuentes_frescas", "ok": False} in checks
    assert info["fuentes_frescura"]["apagadas"] == ["pscp"]  # type: ignore[index]
    notificar.assert_called_once()


def test_no_poder_medir_la_frescura_no_tumba_el_informe() -> None:
    """Mismo criterio que el resto de checks secundarios del healthcheck."""
    from scheduler.healthcheck import _incorporar_frescura_fuentes

    checks: list[dict[str, object]] = []
    warnings: list[str] = []
    info: dict[str, object] = {}

    with patch(
        "scheduler.healthcheck.comprobar_frescura_fuentes",
        side_effect=RuntimeError("sin BD"),
    ):
        _incorporar_frescura_fuentes(checks, warnings, info)

    assert warnings == ["fuentes_frescura_no_medida"]
    assert checks == [{"name": "fuentes_frescas", "ok": True}]
    assert "fuentes_frescura_error" in info
