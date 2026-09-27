"""El golden set real de «¿es TI?» y familias (plan de tres niveles, F2).

Sustituye a los 27 ejemplos de `golden_set.jsonl` como gate del binario: sale
de la revisión humana (`ml_feedback`, `source='revision_ti'`), lleva fuente y
fecha, y su holdout es el 50 % más reciente, fijo.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from services.ml import golden_ti
from services.ml.golden_ti import (
    EjemploGoldenTi,
    a_linea,
    asignar_splits,
    cargar_golden_ti,
    ejemplo_desde_fila,
)


def _ejemplo(id_: str, fecha: str, **cambios: object) -> EjemploGoldenTi:
    base = EjemploGoldenTi(
        id_externo=id_,
        fuente="pscp",
        fecha=fecha,
        titulo="t",
        descripcion="",
        cpv=None,
        es_ti=True,
        familias=(),
        fabricantes=(),
        etiquetado_por="humano",
        etiquetado_at="2026-09-28T00:00:00+00:00",
        split="tune",
    )
    return replace(base, **cambios)  # type: ignore[arg-type]  # cambios de test


def test_el_holdout_es_la_mitad_mas_reciente() -> None:
    ejemplos = [_ejemplo(f"E{i}", f"2026-0{i}-01") for i in range(1, 5)]
    splits = {e.id_externo: e.split for e in asignar_splits(ejemplos)}
    assert splits == {"E1": "tune", "E2": "tune", "E3": "holdout", "E4": "holdout"}


def test_una_fila_de_revision_separa_familias_de_fabricantes() -> None:
    fila = {
        "expediente": "EXP-1",
        "fuente": "placsp",
        "fecha_publicacion": "2026-09-01",
        "titulo": "Implantación de SAP S/4HANA",
        "descripcion": None,
        "cpv": "72000000",
        "relevante": 1,
        "tecnologia": "ERP",
        "tecnologias_secundarias": '["SAP"]',
        "created_at": "2026-09-28T10:00:00+00:00",
    }
    ejemplo = ejemplo_desde_fila(fila)
    assert ejemplo.es_ti is True
    assert ejemplo.familias == ("ERP",)
    assert ejemplo.fabricantes == ("SAP",)
    assert ejemplo.descripcion == ""


def test_una_tecnologia_desconocida_se_descarta_con_aviso(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una tecnología que no está en TECH_LABEL_TIPO no se cuela como negativo
    silencioso: se descarta (no entra en familias ni en fabricantes) y queda
    rastro -- un aviso estructurado con el expediente y el valor malo -- para
    que un label retirado o un dato legacy corrupto no desaparezca sin dejar
    huella, tal y como ya exige `cargar_golden_ti` para el fichero."""
    log = MagicMock()
    monkeypatch.setattr(golden_ti, "log", log)
    fila = {
        "expediente": "EXP-9",
        "fuente": "placsp",
        "fecha_publicacion": "2026-09-01",
        "titulo": "t",
        "descripcion": "",
        "cpv": None,
        "relevante": 1,
        "tecnologia": "NO_EXISTE",
        "tecnologias_secundarias": '["SAP"]',
        "created_at": "2026-09-28T10:00:00+00:00",
    }

    ejemplo = ejemplo_desde_fila(fila)

    assert ejemplo.familias == ()
    assert ejemplo.fabricantes == ("SAP",)  # la conocida se conserva
    assert log.warning.call_args.args[0] == "golden_ti.tecnologia_desconocida"
    assert log.warning.call_args.kwargs["expediente"] == "EXP-9"
    assert log.warning.call_args.kwargs["tecnologia"] == "NO_EXISTE"


def test_un_campo_obligatorio_ausente_es_un_error_claro(tmp_path: Path) -> None:
    ruta = tmp_path / "golden.jsonl"
    incompleto = json.loads(a_linea(_ejemplo("E1", "2026-09-01")))
    del incompleto["titulo"]
    ruta.write_text(json.dumps(incompleto), encoding="utf-8")
    with pytest.raises(ValueError, match="titulo"):
        cargar_golden_ti(ruta)


def test_ida_y_vuelta_por_el_fichero(tmp_path: Path) -> None:
    ruta = tmp_path / "golden.jsonl"
    ejemplo = _ejemplo("E1", "2026-09-01", familias=("ERP",), split="holdout")
    ruta.write_text("# cabecera\n\n" + a_linea(ejemplo) + "\n", encoding="utf-8")
    assert cargar_golden_ti(ruta) == [ejemplo]


def test_una_etiqueta_fuera_del_vocabulario_es_un_error(tmp_path: Path) -> None:
    ruta = tmp_path / "golden.jsonl"
    ruta.write_text(
        a_linea(_ejemplo("E1", "2026-09-01", familias=("NO_EXISTE",))), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="NO_EXISTE"):
        cargar_golden_ti(ruta)


def test_el_fichero_del_repo_carga() -> None:
    """Hoy solo tiene la cabecera: vacío es válido, roto no."""
    assert isinstance(cargar_golden_ti(), list)
