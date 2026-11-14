"""Limpieza del ruido de float4 en ``licitaciones_history`` (sin BD).

La decisión de qué fila es ruido (``es_ruido``), la lectura del importe de un
snapshot (``db.historial_ruido._numero``) y el recorrido del script con la capa
``db`` sustituida. El SQL se prueba contra Postgres en
``tests/test_ruido_importe_pg.py``.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from db.historial_ruido import CandidatoRuido, _numero
from scripts import limpiar_ruido_importe_historial as script


@pytest.mark.parametrize(
    ("antes", "despues", "esperado"),
    [
        pytest.param(12345.67, 12345.669921875, True, id="redondeo-float4"),
        pytest.param(1_000_004.0, 1_000_000.0, True, id="seis-cifras-al-leer"),
        pytest.param(1_000_000.0, 1_000_000.0, True, id="iguales-en-bits"),
        pytest.param(0.0, 0.0, True, id="cero"),
        pytest.param(1_000_000.0, 1_000_100.0, False, id="cambio-real-0.01pct"),
        pytest.param(100.0, 200.0, False, id="cambio-real"),
        pytest.param(None, 100.0, False, id="sin-antes"),
        pytest.param(100.0, None, False, id="sin-despues"),
        pytest.param(None, None, False, id="sin-ninguno"),
    ],
)
def test_es_ruido(antes: float | None, despues: float | None, esperado: bool) -> None:
    assert script.es_ruido(antes, despues) is esperado


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (None, None),
        ("null", None),
        ("12345.67", 12345.67),
        (" 1e+06", 1_000_000.0),
        ('"12.5"', 12.5),
        ("1234...(truncado)", None),
        (12345.669921875, 12345.669921875),
        (7, 7.0),
    ],
)
def test_numero_lee_el_importe_del_snapshot(valor: Any, esperado: float | None) -> None:
    assert _numero(valor) == esperado


def _candidato(history_id: int, antes: float | None, despues: float | None) -> CandidatoRuido:
    return CandidatoRuido(
        history_id=history_id, id_externo=f"x{history_id}", antes=antes, despues=despues
    )


_LOTE = [
    _candidato(10, 12345.67, 12345.669921875),  # ruido
    _candidato(11, 100.0, 200.0),  # cambio real
    _candidato(12, None, 5.0),  # snapshot truncado
    _candidato(13, 1_000_004.0, 1_000_000.0),  # ruido
]


_RESPALDO = {
    "licitaciones_history": [{"id": 10, "snapshot_json": '{"importe": 12345.67}'}],
    "contrato_eventos": [{"id": 7, "history_id": 10, "campo": "importe"}],
}


def _correr(tmp_path: Path, *extra: str) -> tuple[Any, Any, list[list[str]]]:
    salida = tmp_path / "ruido.csv"
    orden: list[str] = []
    with (
        patch.object(script, "candidatos_ruido_importe", side_effect=[_LOTE, []]) as candidatos,
        patch.object(
            script,
            "filas_a_borrar",
            side_effect=lambda ids: orden.append("respaldo") or _RESPALDO,
        ),
        patch.object(
            script,
            "borrar_ruido_importe",
            side_effect=lambda ids: orden.append("borrar") or (1, 2),
        ) as borrar,
        patch.object(script, "configure_logging"),
    ):
        assert script.main(["--csv", str(salida), "--desde-id", "5", *extra]) == 0
    with salida.open(encoding="utf-8") as f:
        filas = list(csv.reader(f))
    if borrar.called:
        assert orden == ["respaldo", "borrar"]  # el respaldo llega a disco antes de borrar
    return candidatos, borrar, filas


def test_sin_aplicar_no_borra_y_vuelca_el_plan(tmp_path: Path) -> None:
    candidatos, borrar, filas = _correr(tmp_path)

    borrar.assert_not_called()
    assert [f[0] for f in filas] == ["history_id", "10", "13"]
    # El segundo lote empieza tras el último id del primero.
    assert [c.args for c in candidatos.call_args_list] == [(5, 1000), (13, 1000)]


def test_aplicar_borra_solo_el_ruido(tmp_path: Path) -> None:
    _, borrar, filas = _correr(tmp_path, "--aplicar")

    borrar.assert_called_once_with([10, 13])
    assert [f[0] for f in filas] == ["history_id", "10", "13"]


def test_aplicar_respalda_las_filas_enteras(tmp_path: Path) -> None:
    _correr(tmp_path, "--aplicar")

    lineas = (tmp_path / "ruido.respaldo.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(linea) for linea in lineas] == [
        {"tabla": tabla, "fila": fila} for tabla, filas in _RESPALDO.items() for fila in filas
    ]


def test_sin_aplicar_no_escribe_respaldo(tmp_path: Path) -> None:
    _correr(tmp_path)

    assert not (tmp_path / "ruido.respaldo.jsonl").exists()
