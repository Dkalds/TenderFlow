"""Puertas del verificador de la reingesta (``scripts/verificar_reingesta.py``).

Sin BD: ``evaluar_puertas`` es una función pura sobre las cifras, y ``main`` se
prueba con ``medir`` sustituido. Las cifras de «antes» son las de producción
del 2026-10-26 (MCP de solo lectura).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from scripts import verificar_reingesta
from scripts.verificar_reingesta import evaluar_puertas


def _cifras(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "desde": None,
        # Producción, 2026-10-26.
        "licitaciones": {
            "filas": 24562,
            "importe_tipo_desconocido": 17839,
            "importe_sin_iva": 6000,
            "importe_con_iva": 723,
            "con_base_sin_iva": 6723,
            "provincia_espana": 765,
            "fecha_publicacion_con_hora": 401,
        },
        "solvencia_economica": {
            "requisitos": 4046,
            "con_umbral": 5,
            "licitaciones": 3491,
            "licitaciones_con_umbral": 5,
        },
        "ceros": [
            {
                "grupo": "placsp",
                "adjudicaciones": 19288,
                "adjudicaciones_con_cero": 1408,
                "garantias": 3075,
                "garantias_con_cero": 161,
            },
            {
                "grupo": "placsp_watched_company_awards",
                "adjudicaciones": 598,
                "adjudicaciones_con_cero": 314,
                "garantias": 15,
                "garantias_con_cero": 0,
            },
        ],
        "sin_organo_ref": {"bulk_202501": 10},
        "conviven": 0,
        "colisiones": None,
    }
    base.update(over)
    return base


def _despues() -> dict[str, Any]:
    cifras = _cifras()
    cifras["licitaciones"] = {
        **cifras["licitaciones"],
        "importe_tipo_desconocido": 1200,
        "provincia_espana": 0,
        "fecha_publicacion_con_hora": 0,
    }
    cifras["ceros"][0] = {
        **cifras["ceros"][0],
        "adjudicaciones_con_cero": 0,
        "garantias_con_cero": 0,
    }
    return cifras


def _decisorias(cifras: dict[str, Any]) -> dict[str, bool]:
    return {p.nombre: p.pasa for p in evaluar_puertas(cifras) if p.pasa is not None}


def test_el_estado_de_hoy_no_pasa_ninguna_puerta_decisoria() -> None:
    assert not any(_decisorias(_cifras()).values())


def test_tras_la_reingesta_pasan_todas() -> None:
    assert all(_decisorias(_despues()).values())


def test_el_umbral_del_importe_es_estricto_al_diez_por_ciento() -> None:
    cifras = _despues()
    cifras["licitaciones"]["filas"] = 1000
    cifras["licitaciones"]["importe_tipo_desconocido"] = 100
    nombre = "importe_tipo desconocido o nulo (PLACSP)"
    assert _decisorias(cifras)[nombre] is False
    cifras["licitaciones"]["importe_tipo_desconocido"] = 99
    assert _decisorias(cifras)[nombre] is True


def test_sin_filas_la_puerta_del_importe_no_pasa() -> None:
    """Cero filas con --desde mal puesto no es «0 % desconocido»."""
    cifras = _despues()
    cifras["licitaciones"] = {k: 0 for k in cifras["licitaciones"]}
    assert _decisorias(cifras)["importe_tipo desconocido o nulo (PLACSP)"] is False


def test_las_empresas_vigiladas_son_informativas() -> None:
    """Sus ceros no los corrige la reingesta del feed: no deciden la puerta."""
    puertas = evaluar_puertas(_despues())
    vigiladas = [p for p in puertas if "placsp_watched_company_awards" in p.nombre]
    assert len(vigiladas) == 1
    assert vigiladas[0].pasa is None


@pytest.mark.parametrize(("cifras", "codigo"), [(_cifras(), 1), (_despues(), 0)])
def test_estricto_devuelve_1_si_falla_una_puerta(
    monkeypatch: pytest.MonkeyPatch, cifras: dict[str, Any], codigo: int
) -> None:
    monkeypatch.setattr(verificar_reingesta, "medir", lambda **_: cifras)
    assert verificar_reingesta.main(["--estricto", "--sin-historial"]) == codigo


def test_json_lleva_cifras_y_puertas(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(verificar_reingesta, "medir", lambda **_: _cifras())
    assert verificar_reingesta.main(["--json"]) == 0
    salida = json.loads(capsys.readouterr().out)
    assert salida["cifras"]["licitaciones"]["filas"] == 24562
    assert {"nombre", "valor", "objetivo", "pasa"} <= set(salida["puertas"][0])
