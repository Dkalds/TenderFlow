"""Revisión a teclado de los casos del golden de la ficha.

El teclado se sustituye por una lista de respuestas. Lo que se fija es lo que
queda en disco después de cada una: la revisión se hace a ratos, y un corte a
media sesión no puede costar lo ya etiquetado.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from scripts.revisar_ficha_golden import anadir, estado, revisar
from services.rag.ficha_golden import (
    CasoGolden,
    escribir_golden,
    escribir_paginas,
    escribir_pendientes,
    leer_caso,
    leer_pendientes,
)

_TEXTO = (
    "El criterio precio tendrá una ponderación del 60 por ciento. "
    "La calidad técnica se valorará con hasta 40 puntos sobre el total."
)
_CITA = "criterio precio tendrá una ponderación del 60 por ciento"


def _respuestas(*valores: str) -> Callable[[str], str]:
    """Un ``input()`` de mentira: al acabarse las respuestas, EOF (Ctrl-D)."""
    pendientes = iter(valores)

    def leer(_pregunta: str) -> str:
        try:
            return next(pendientes)
        except StopIteration:
            raise EOFError from None

    return leer


def _criterio(peso: float | None, nombre: str = "Precio") -> dict[str, Any]:
    return {
        "name": nombre,
        "description": "Criterio de adjudicación",
        "weight_pct": peso,
        "criterion_type": "price",
        "confidence": 0.9,
        "evidence": [{"documento_id": 7, "page_number": 1, "quote": _CITA}],
    }


def _solvencia() -> dict[str, Any]:
    return {
        "description": "Tres trabajos similares en los últimos tres años",
        "confidence": 0.8,
        "evidence": [{"documento_id": 7, "page_number": 1, "quote": _CITA}],
    }


def _crear(
    carpeta: Path,
    hechos: dict[str, list[dict[str, Any]]],
    *,
    completo: bool = False,
    veredicto: str | None = None,
) -> Path:
    golden = CasoGolden.model_validate(
        {
            "licitacion_id": "EXP-1",
            "completo": completo,
            "capturado_el": date(2026, 10, 11).isoformat(),
            "extraction_version": "tender-facts-v6",
            "model": "modelo-x",
            "status_origen": "extracted",
            "hechos": {
                familia: [{"veredicto": veredicto, "hecho": h} for h in items]
                for familia, items in hechos.items()
            },
        }
    )
    escribir_golden(carpeta, golden)
    escribir_paginas(
        carpeta,
        [
            {
                "documento_id": 7,
                "page_number": 1,
                "tipo": "legal",
                "filename": "pcap.pdf",
                "texto": _TEXTO,
            }
        ],
    )
    return carpeta


def _veredictos(carpeta: Path, familia: str = "award_criteria") -> list[str | None]:
    return [h.veredicto for h in leer_caso(carpeta).golden.hechos.get(familia, [])]


def test_guarda_cada_veredicto_y_retoma_donde_iba(tmp_path: Path) -> None:
    caso = _crear(
        tmp_path / "caso",
        {"award_criteria": [_criterio(60), _criterio(40, "Calidad"), _criterio(5)]},
    )

    assert revisar(caso, leer=_respuestas("c", "i", "q")) == 2
    assert _veredictos(caso) == ["correcto", "incorrecto", None]

    assert revisar(caso, leer=_respuestas("c")) == 1
    assert _veredictos(caso) == ["correcto", "incorrecto", "correcto"]


def test_saltar_deja_el_hecho_sin_veredicto(tmp_path: Path) -> None:
    caso = _crear(tmp_path / "caso", {"award_criteria": [_criterio(60), _criterio(40, "Calidad")]})

    assert revisar(caso, leer=_respuestas("s", "c")) == 1
    assert _veredictos(caso) == [None, "correcto"]


def test_corregir_guarda_el_valor_bueno_y_el_original(tmp_path: Path) -> None:
    caso = _crear(tmp_path / "caso", {"award_criteria": [_criterio(40)]})

    assert revisar(caso, leer=_respuestas("v", "60", "")) == 1

    (hecho,) = leer_caso(caso).golden.hechos["award_criteria"]
    assert hecho.veredicto == "corregido"
    assert hecho.hecho["weight_pct"] == 60
    assert hecho.hecho["name"] == "Precio"
    assert hecho.valor_extraido == {"weight_pct": 40}


def test_un_valor_que_no_valida_se_vuelve_a_pedir(tmp_path: Path) -> None:
    caso = _crear(tmp_path / "caso", {"award_criteria": [_criterio(40)]})

    assert revisar(caso, leer=_respuestas("v", "abc", "60", "")) == 1

    (hecho,) = leer_caso(caso).golden.hechos["award_criteria"]
    assert (hecho.veredicto, hecho.hecho["weight_pct"]) == ("corregido", 60)


def test_corregir_sin_cambiar_nada_no_cuenta_como_corregido(tmp_path: Path) -> None:
    caso = _crear(tmp_path / "caso", {"award_criteria": [_criterio(40)]})

    assert revisar(caso, leer=_respuestas("v", "", "", "c")) == 1

    (hecho,) = leer_caso(caso).golden.hechos["award_criteria"]
    assert (hecho.veredicto, hecho.valor_extraido) == ("correcto", None)


def test_una_familia_sin_campos_clave_no_ofrece_corregir(tmp_path: Path) -> None:
    caso = _crear(tmp_path / "caso", {"technical_solvency": [_solvencia()]})

    assert revisar(caso, leer=_respuestas("v", "c")) == 1
    assert _veredictos(caso, "technical_solvency") == ["correcto"]


def test_eof_a_media_revision_deja_un_golden_valido(tmp_path: Path) -> None:
    caso = _crear(tmp_path / "caso", {"award_criteria": [_criterio(60), _criterio(40, "Calidad")]})

    assert revisar(caso, leer=_respuestas("c")) == 1

    assert _veredictos(caso) == ["correcto", None]
    assert sorted(p.name for p in caso.iterdir()) == ["golden.json", "paginas.jsonl"]


def test_eof_a_media_correccion_no_deja_el_hecho_a_medias(tmp_path: Path) -> None:
    caso = _crear(tmp_path / "caso", {"award_criteria": [_criterio(40)]})

    assert revisar(caso, leer=_respuestas("v", "60")) == 0

    (hecho,) = leer_caso(caso).golden.hechos["award_criteria"]
    assert (hecho.veredicto, hecho.hecho["weight_pct"]) == (None, 40)


def test_los_pendientes_pasan_al_golden_y_el_fichero_desaparece(tmp_path: Path) -> None:
    caso = _crear(tmp_path / "caso", {"award_criteria": [_criterio(60)]}, veredicto="correcto")
    escribir_pendientes(
        caso, [("award_criteria", _criterio(40, "Calidad")), ("technical_solvency", _solvencia())]
    )

    assert revisar(caso, leer=_respuestas("c", "i")) == 2

    assert _veredictos(caso) == ["correcto", "correcto"]
    assert _veredictos(caso, "technical_solvency") == ["incorrecto"]
    assert leer_pendientes(caso) == []
    assert not (caso / "pendientes.json").exists()


def test_un_pendiente_saltado_sigue_pendiente(tmp_path: Path) -> None:
    caso = _crear(tmp_path / "caso", {}, veredicto="correcto")
    escribir_pendientes(caso, [("award_criteria", _criterio(40, "Calidad"))])

    assert revisar(caso, leer=_respuestas("s")) == 0

    assert len(leer_pendientes(caso)) == 1
    assert _veredictos(caso) == []


def test_anadir_rechaza_una_cita_que_no_esta_en_la_pagina(tmp_path: Path) -> None:
    caso = _crear(tmp_path / "caso", {}, completo=True)
    respuestas = _respuestas(
        "award_criteria",
        "7",
        "1",
        "esta frase no aparece en ninguna página del pliego",
        "calidad técnica se valorará con hasta 40 puntos",
        "40",
        "Calidad técnica",
        "",
        "",
    )

    assert anadir(caso, leer=respuestas) == 1

    (hecho,) = leer_caso(caso).golden.hechos["award_criteria"]
    assert hecho.veredicto == "añadido"
    assert (hecho.hecho["weight_pct"], hecho.hecho["name"]) == (40, "Calidad técnica")
    assert hecho.hecho["confidence"] == 1.0
    assert hecho.hecho["evidence"][0]["page_number"] == 1
    assert hecho.hecho["description"] == "calidad técnica se valorará con hasta 40 puntos"


def test_anadir_se_niega_en_un_caso_parcial(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    caso = _crear(tmp_path / "caso", {}, completo=False)

    assert anadir(caso, leer=_respuestas("award_criteria")) == 0

    assert leer_caso(caso).golden.hechos == {}
    assert "completo" in capsys.readouterr().err


def _diez_casos(raiz: Path, *, completos: int, veredicto: str | None = "correcto") -> None:
    for n in range(10):
        _crear(
            raiz / f"caso-{n:02d}",
            {"award_criteria": [_criterio(60)]},
            completo=n < completos,
            veredicto=veredicto,
        )


def test_estado_cumple_con_diez_casos_tres_completos_y_todo_revisado(tmp_path: Path) -> None:
    _diez_casos(tmp_path, completos=3)

    assert estado(tmp_path) is True


def test_estado_es_falso_con_nueve_casos(tmp_path: Path) -> None:
    for n in range(9):
        _crear(
            tmp_path / f"caso-{n}",
            {"award_criteria": [_criterio(60)]},
            completo=n < 3,
            veredicto="correcto",
        )

    assert estado(tmp_path) is False


def test_estado_es_falso_con_dos_completos_o_con_hechos_sin_revisar(tmp_path: Path) -> None:
    _diez_casos(tmp_path / "pocos-completos", completos=2)
    _diez_casos(tmp_path / "sin-revisar", completos=3, veredicto=None)

    assert estado(tmp_path / "pocos-completos") is False
    assert estado(tmp_path / "sin-revisar") is False
