"""Eval determinista de la ficha del pliego: integridad de los casos y selector.

Sin LLM, sin base de datos y sin red: es la mitad del eval de la ficha que sí
puede vivir en el gate de CI. La otra mitad —precisión y cobertura de la
extracción— llama al modelo y se ejecuta a mano con ``make eval-ficha``
(``docs/plans/2026-10-eval-ficha-pliego.md``).

Qué protege
-----------
1. **Los casos no se pudren.** Cada ``golden.json`` encaja en su esquema, no
   tiene veredictos pendientes, y la cita de cada hecho cierto sigue estando
   literalmente en su página.
2. **El selector de páginas no pierde lo que importa.** Lo que no entra en el
   contexto del modelo no se puede extraer, por bueno que sea el prompt. De
   cada hecho cierto del golden se comprueba que alguna de sus páginas citadas
   entra en ``_select_pages``. El mínimo es un ratchet: el valor medido al
   fijar la base (``minimos.json``), que solo sube.

Mientras no haya casos
----------------------
Los dos tests de datos se saltan con el motivo escrito. En cuanto existe
``minimos.json`` dejan de poder saltarse: un control que se salta en silencio
cuando ya debería morder no cuenta como verde.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from services.rag.fact_sheet import _select_pages, _validated_evidence
from services.rag.ficha_eval import cobertura_selector
from services.rag.ficha_golden import (
    FAMILIAS,
    Caso,
    CasoGolden,
    escribir_golden,
    escribir_paginas,
    leer_caso,
    leer_pendientes,
    listar_casos,
    positivos,
    sin_revisar,
)

_RAIZ = Path(__file__).parent / "fixtures" / "fichas"
_MINIMOS = "minimos.json"
_SIN_CASOS = "aún no hay casos capturados (docs/plans/2026-10-eval-ficha-pliego.md §8)"


def _publicar(texto: str) -> None:
    """Imprime y, en GitHub Actions, añade al resumen del job (como ``test_eval_rag``)."""
    print(texto)
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if not destino:
        return
    try:
        with open(destino, "a", encoding="utf-8") as resumen:
            resumen.write(f"```\n{texto.strip()}\n```\n")
    except OSError:
        pass


def _casos_o_skip(raiz: Path) -> list[Caso]:
    """Los casos de ``raiz``; sin ninguno, se salta o falla según haya mínimos."""
    carpetas = listar_casos(raiz)
    if carpetas:
        return [leer_caso(carpeta) for carpeta in carpetas]
    if (raiz / _MINIMOS).is_file():
        pytest.fail(
            f"Hay {_MINIMOS} en {raiz} pero ningún caso: los mínimos se midieron sobre "
            "casos que ya no están. Recupéralos; no borres los mínimos para que esto pase."
        )
    pytest.skip(_SIN_CASOS)


def _problemas_de_integridad(caso: Caso, pendientes: int = 0) -> list[str]:
    """Lo que impide medir contra un caso. Lista vacía si está sano."""
    problemas: list[str] = []
    if faltan := sin_revisar(caso.golden) + pendientes:
        problemas.append(f"{caso.nombre}: {faltan} hechos sin veredicto")
    indice = {(int(p["documento_id"]), int(p["page_number"])): p for p in caso.paginas}
    for familia, hechos in positivos(caso.golden).items():
        for hecho in hechos:
            # Sobre una copia: `_validated_evidence` corrige la página en sitio.
            if not any(
                _validated_evidence(cita.model_copy(), indice) is not None
                for cita in hecho.evidence
            ):
                problemas.append(
                    f"{caso.nombre}: un hecho cierto de {familia} no tiene ninguna cita "
                    f"literal en sus páginas («{hecho.description[:60]}»)"
                )
    return problemas


def _cobertura(casos: list[Caso]) -> dict[str, tuple[int, int]]:
    """Cobertura del selector sumada por familia sobre todos los casos."""
    suma: dict[str, tuple[int, int]] = {}
    for caso in casos:
        for familia, (cubiertos, total) in cobertura_selector(
            caso, _select_pages(caso.paginas)
        ).items():
            previos = suma.get(familia, (0, 0))
            suma[familia] = (previos[0] + cubiertos, previos[1] + total)
    return suma


# ── La política y las comprobaciones, sobre casos sintéticos ────────────────

_CITA = "El criterio precio tendrá una ponderación del 60 por ciento del total"


def _caso_sintetico(
    raiz: Path,
    nombre: str = "caso",
    *,
    cita: str = _CITA,
    pagina_citada: int = 1,
    veredicto: str | None = "correcto",
    paginas: list[dict[str, Any]] | None = None,
) -> Caso:
    golden = CasoGolden.model_validate(
        {
            "licitacion_id": "EXP-1",
            "completo": True,
            "capturado_el": date(2026, 10, 11).isoformat(),
            "extraction_version": "tender-facts-v6",
            "model": "modelo-x",
            "status_origen": "extracted",
            "hechos": {
                "award_criteria": [
                    {
                        "veredicto": veredicto,
                        "hecho": {
                            "name": "Precio",
                            "description": "Criterio económico",
                            "weight_pct": 60,
                            "confidence": 0.9,
                            "evidence": [
                                {"documento_id": 7, "page_number": pagina_citada, "quote": cita}
                            ],
                        },
                    }
                ]
            },
        }
    )
    escribir_golden(raiz / nombre, golden)
    escribir_paginas(
        raiz / nombre,
        paginas or [{"documento_id": 7, "page_number": 1, "tipo": "legal", "texto": f"{_CITA}."}],
    )
    return leer_caso(raiz / nombre)


def test_sin_casos_ni_minimos_se_salta(tmp_path: Path) -> None:
    with pytest.raises(pytest.skip.Exception, match="aún no hay casos"):
        _casos_o_skip(tmp_path)


def test_con_minimos_y_sin_casos_falla(tmp_path: Path) -> None:
    (tmp_path / _MINIMOS).write_text("{}", encoding="utf-8")

    with pytest.raises(pytest.fail.Exception, match="ningún caso"):
        _casos_o_skip(tmp_path)


def test_con_casos_se_devuelven_haya_o_no_minimos(tmp_path: Path) -> None:
    _caso_sintetico(tmp_path, "b")
    _caso_sintetico(tmp_path, "a")

    assert [caso.nombre for caso in _casos_o_skip(tmp_path)] == ["a", "b"]


def test_un_caso_sano_no_tiene_problemas_de_integridad(tmp_path: Path) -> None:
    assert _problemas_de_integridad(_caso_sintetico(tmp_path)) == []


def test_una_cita_que_ya_no_esta_en_la_pagina_es_un_problema(tmp_path: Path) -> None:
    caso = _caso_sintetico(tmp_path, cita="Esta frase nunca estuvo en el pliego capturado")

    (problema,) = _problemas_de_integridad(caso)

    assert "award_criteria" in problema and "cita" in problema


def test_un_veredicto_o_un_pendiente_sin_resolver_es_un_problema(tmp_path: Path) -> None:
    sin_veredicto = _caso_sintetico(tmp_path, "a", veredicto=None)
    revisado = _caso_sintetico(tmp_path, "b")

    assert len(_problemas_de_integridad(sin_veredicto)) == 1
    assert len(_problemas_de_integridad(revisado, pendientes=2)) == 1


def test_la_cobertura_cuenta_el_hecho_cuya_pagina_no_cabe_en_el_contexto(tmp_path: Path) -> None:
    # Cuarenta y una páginas densas: el selector se queda con cuarenta, y la
    # que cita el hecho —sin un solo término puntuable— es la que se cae.
    densa = "criterios de adjudicación solvencia garantía penalidades " * 20
    paginas = [
        {"documento_id": 7, "page_number": n, "tipo": "additional", "texto": densa}
        for n in range(1, 42)
    ]
    paginas.append(
        {"documento_id": 7, "page_number": 99, "tipo": "additional", "texto": "Lorem ipsum dolor."}
    )
    fuera = _caso_sintetico(
        tmp_path, "fuera", cita="Lorem ipsum dolor", pagina_citada=99, paginas=paginas
    )
    dentro = _caso_sintetico(tmp_path, "dentro")

    assert _cobertura([fuera]) == {"award_criteria": (0, 1)}
    assert _cobertura([fuera, dentro]) == {"award_criteria": (1, 2)}


# ── Los casos reales ────────────────────────────────────────────────────────


def test_integridad_de_los_casos() -> None:
    casos = _casos_o_skip(_RAIZ)

    problemas = [
        problema
        for caso in casos
        for problema in _problemas_de_integridad(caso, len(leer_pendientes(_RAIZ / caso.nombre)))
    ]

    assert problemas == []


def test_cobertura_del_selector() -> None:
    casos = _casos_o_skip(_RAIZ)
    ruta_minimos = _RAIZ / _MINIMOS
    if not ruta_minimos.is_file():
        pytest.skip(
            "hay casos pero aún no se ha fijado la base "
            "(python scripts/eval_ficha.py --fijar-minimos)"
        )
    minimo = json.loads(ruta_minimos.read_text(encoding="utf-8"))["minimos"]["selector_cobertura"]

    por_familia = _cobertura(casos)
    cubiertos = sum(c for c, _ in por_familia.values())
    total = sum(t for _, t in por_familia.values())
    lineas = [f"Selector de la ficha: {cubiertos}/{total} positivos con su página en contexto"]
    lineas += [
        f"  {familia:20} {por_familia[familia][0]:>4} / {por_familia[familia][1]}"
        for familia in FAMILIAS
        if familia in por_familia
    ]
    _publicar("\n".join(lineas))

    assert total > 0, "ningún caso tiene hechos ciertos: no hay nada que medir"
    assert cubiertos / total >= minimo, (
        f"El selector cubre {cubiertos}/{total} = {cubiertos / total:.4f}, por debajo del "
        f"mínimo {minimo}. Si el cambio es una mejora medida, sube el mínimo en el mismo "
        "cambio; no lo bajes para que pase."
    )
