"""``scripts/sample_golden_candidates.py --desde``: muestrear desde un export.

El muestreo nació leyendo la BD, y en la máquina del dueño no hay BD: el paso
humano llevaba meses bloqueado por eso. Lo que se fija aquí es que el export
se lee como lo leería la BD (vacíos como ausencia, sinónimos de columna) y que
la ``ml_proba`` del export sustituye a puntuar con un modelo local.
"""

from __future__ import annotations

import csv
import json

import pytest

from scripts import sample_golden_candidates as sgc

_COLUMNAS = ["id_externo", "titulo", "descripcion", "cpv", "importe", "organo_contratacion"]


def _csv(ruta, filas, columnas=_COLUMNAS):
    with ruta.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columnas)
        w.writeheader()
        w.writerows(filas)


def _fila(i: int, **extra: object) -> dict[str, object]:
    return {
        "id_externo": f"exp-{i}",
        "titulo": f"Servicio de mantenimiento {i}",
        "descripcion": "",
        "cpv": "50000000",
        "importe": "1000.5" if i % 2 else "",
        "organo_contratacion": f"Órgano {i}",
        **extra,
    }


@pytest.fixture
def sin_modelo(monkeypatch):
    """Si el muestreo intentara puntuar con `ml_proba` en el export, falla."""

    def _no(_candidatos):
        raise AssertionError("no debía puntuar: el export trae ml_proba")

    monkeypatch.setattr(sgc, "_puntuar", _no)


def test_lee_el_csv_normalizando_vacios_e_importe(tmp_path):
    ruta = tmp_path / "export.csv"
    _csv(ruta, [_fila(1), _fila(2)])

    filas = sgc._leer_export(ruta, pool=10)
    assert [f["id_externo"] for f in filas] == ["exp-1", "exp-2"]
    assert filas[0]["importe"] == 1000.5
    assert filas[1]["importe"] is None
    assert filas[1]["descripcion"] is None


def test_acepta_un_jsonl_con_los_nombres_del_golden(tmp_path):
    ruta = tmp_path / "export.jsonl"
    ruta.write_text(
        "# comentario\n" + json.dumps({"id": "x", "titulo": "T", "organo": "O", "importe": 5}),
        encoding="utf-8",
    )
    (fila,) = sgc._leer_export(ruta, pool=10)
    assert fila["id_externo"] == "x"
    assert fila["organo_contratacion"] == "O"
    assert fila["importe"] == 5.0


def test_descarta_filas_sin_id_o_sin_titulo(tmp_path):
    ruta = tmp_path / "export.csv"
    _csv(ruta, [_fila(1), {**_fila(2), "titulo": ""}, {**_fila(3), "id_externo": ""}])
    assert [f["id_externo"] for f in sgc._leer_export(ruta, pool=10)] == ["exp-1"]


def test_respeta_el_pool(tmp_path):
    ruta = tmp_path / "export.csv"
    _csv(ruta, [_fila(i) for i in range(10)])
    assert len(sgc._leer_export(ruta, pool=3)) == 3


def test_muestrea_desde_el_export_con_su_ml_proba(tmp_path, sin_modelo):
    ruta = tmp_path / "export.csv"
    columnas = [*_COLUMNAS, "ml_proba"]
    _csv(ruta, [_fila(i, ml_proba=f"{(i % 10) / 10:.1f}") for i in range(40)], columnas)

    salida = sgc.muestrear(n=12, pool=100, seed=1, desde=ruta)
    assert len(salida) == 12
    assert all(f["label"] is None for f in salida)
    assert all(str(f["organo"]).startswith("Órgano") for f in salida)
    assert all("ml_proba=" in f["note"] for f in salida)
    assert len({f["id"] for f in salida}) == 12


def test_ml_proba_parcial_se_ignora_y_se_puntua(tmp_path, monkeypatch):
    """Mezclar filas con y sin probabilidad desequilibraría los estratos."""
    ruta = tmp_path / "export.csv"
    columnas = [*_COLUMNAS, "ml_proba"]
    _csv(ruta, [_fila(1, ml_proba="0.9"), _fila(2, ml_proba="")], columnas)
    llamadas: list[int] = []

    def _puntuar(candidatos):
        llamadas.append(len(candidatos))
        return [None] * len(candidatos)

    monkeypatch.setattr(sgc, "_puntuar", _puntuar)
    sgc.muestrear(n=2, pool=10, seed=1, desde=ruta)
    assert llamadas == [2]


def test_main_escribe_el_fichero_desde_el_export(tmp_path, sin_modelo):
    ruta = tmp_path / "export.csv"
    _csv(ruta, [_fila(i, ml_proba="0.5") for i in range(5)], [*_COLUMNAS, "ml_proba"])
    out = tmp_path / "cand.jsonl"

    assert sgc.main(["--desde", str(ruta), "--n", "5", "--out", str(out)]) == 0
    lineas = [ln for ln in out.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
    assert len(lineas) == 5


def test_un_export_vacio_falla_con_codigo_1(tmp_path):
    ruta = tmp_path / "export.csv"
    _csv(ruta, [])
    assert sgc.main(["--desde", str(ruta), "--out", str(tmp_path / "o.jsonl")]) == 1
