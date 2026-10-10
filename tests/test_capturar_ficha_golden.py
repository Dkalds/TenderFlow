"""Captura de un pliego real como caso del golden de la ficha.

Con repositorios falsos: lo que se fija aquí es lo que el script escribe y,
sobre todo, lo que se niega a pisar. Recapturar un caso ya revisado borraría
horas de etiquetado sin avisar.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from scripts import capturar_ficha_golden
from scripts.capturar_ficha_golden import CasoYaExiste, capturar, main
from services.rag.ficha_golden import leer_caso, sin_revisar

_HOY = date(2026, 10, 11)
_TEXTO = "El criterio precio tendrá una ponderación del 60 por ciento."


class _Documentos:
    def list_pages_by_licitacion(self, licitacion_id: str) -> list[dict[str, Any]]:
        return [
            {
                "documento_id": 7,
                "page_number": 1,
                "tipo": "legal",
                "filename": "pcap.pdf",
                "texto": _TEXTO,
                "start_offset": 0,
                "end_offset": len(_TEXTO),
                "ocr": False,
                "uri": "https://contrataciondelestado.es/doc?token=secreto",
            }
        ]


class _Fichas:
    def get(self, licitacion_id: str) -> dict[str, Any] | None:
        return {
            "licitacion_id": licitacion_id,
            "status": "extracted",
            "extraction_version": "tender-facts-v6",
            "model": "modelo-x",
            "facts": {
                "award_criteria": [
                    {
                        "name": "Precio",
                        "description": "Criterio económico",
                        "weight_pct": 60,
                        "criterion_type": "price",
                        "confidence": 0.9,
                        "evidence": [
                            {"documento_id": 7, "page_number": 1, "quote": "ponderación del 60"}
                        ],
                    }
                ]
            },
        }

    def list_candidatas_golden(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return [
            {
                "licitacion_id": "EXP-1",
                "fuente": "placsp",
                "documentos": 1,
                "paginas": 1,
                "paginas_ocr": 0,
                "status": "extracted",
                "extraction_version": "tender-facts-v6",
                "field_count": 1,
                "lotes": 0,
                "formulas": 0,
            }
        ]


def _capturar(carpeta: Path, *, forzar: bool = False, completo: bool = False) -> int:
    return capturar(
        "EXP-1",
        carpeta,
        completo=completo,
        forzar=forzar,
        documentos=_Documentos(),
        fichas=_Fichas(),
        hoy=_HOY,
    )


@pytest.fixture
def repos_falsos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capturar_ficha_golden, "DocumentosRepository", _Documentos)
    monkeypatch.setattr(capturar_ficha_golden, "TenderFactSheetsRepository", _Fichas)


def test_captura_escribe_paginas_sin_uri_y_golden_sin_veredictos(tmp_path: Path) -> None:
    carpeta = tmp_path / "caso-a"

    escritos = _capturar(carpeta, completo=True)

    crudo = (carpeta / "paginas.jsonl").read_text(encoding="utf-8")
    assert escritos == len(crudo.encode("utf-8"))
    assert "uri" not in json.loads(crudo.splitlines()[0])
    caso = leer_caso(carpeta)
    assert caso.golden.licitacion_id == "EXP-1"
    assert caso.golden.completo is True
    assert caso.golden.capturado_el == _HOY
    assert caso.golden.status_origen == "extracted"
    assert sin_revisar(caso.golden) == 1


def test_no_pisa_un_caso_que_ya_existe(tmp_path: Path) -> None:
    carpeta = tmp_path / "caso-a"
    _capturar(carpeta)
    revisado = (
        (carpeta / "golden.json").read_text(encoding="utf-8").replace("null", '"correcto"', 1)
    )
    (carpeta / "golden.json").write_text(revisado, encoding="utf-8")
    antes = (carpeta / "golden.json").read_bytes()

    with pytest.raises(CasoYaExiste):
        _capturar(carpeta)

    assert (carpeta / "golden.json").read_bytes() == antes


def test_con_forzar_si_lo_reescribe(tmp_path: Path) -> None:
    carpeta = tmp_path / "caso-a"
    _capturar(carpeta)
    (carpeta / "golden.json").write_text("{}", encoding="utf-8")

    _capturar(carpeta, forzar=True)

    assert leer_caso(carpeta).golden.licitacion_id == "EXP-1"


def test_main_devuelve_1_y_no_lanza_si_el_caso_existe(
    tmp_path: Path, repos_falsos: None, capsys: pytest.CaptureFixture[str]
) -> None:
    argumentos = ["EXP-1", "--caso", "caso-a", "--raiz", str(tmp_path)]

    assert main(argumentos) == 0
    assert main(argumentos) == 1
    assert "--forzar" in capsys.readouterr().err
    assert main([*argumentos, "--forzar"]) == 0


def test_main_sin_caso_devuelve_2(tmp_path: Path, repos_falsos: None) -> None:
    assert main(["EXP-1", "--raiz", str(tmp_path)]) == 2
    assert list(tmp_path.iterdir()) == []


def test_listar_imprime_los_candidatos(
    tmp_path: Path, repos_falsos: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--listar", "--raiz", str(tmp_path)]) == 0

    salida = capsys.readouterr().out
    assert "EXP-1" in salida and "placsp" in salida and "extracted" in salida


def test_avisa_si_las_paginas_pasan_de_un_mega(
    tmp_path: Path,
    repos_falsos: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(capturar_ficha_golden, "AVISO_TAMANO_BYTES", 10)

    assert main(["EXP-1", "--caso", "caso-a", "--raiz", str(tmp_path)]) == 0

    assert "1 MB" in capsys.readouterr().err
