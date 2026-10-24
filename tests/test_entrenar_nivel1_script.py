"""``scripts/entrenar_nivel1.py`` sin BD: la parte que no es E/S.

Fija que el acuerdo del LLM decide si sus etiquetas entran, que sin holdout no
se entrena nada y que el baseline de keywords es la puerta de reglas vigente.
Las etiquetas de abajo son sintéticas: prueban el código, no son golden.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

from services.ml.acuerdo_llm import RespuestaLlm
from services.ml.golden_ti import EjemploGoldenTi

_RUTA = Path(__file__).resolve().parents[1] / "scripts" / "entrenar_nivel1.py"
_spec = importlib.util.spec_from_file_location("entrenar_nivel1", _RUTA)
assert _spec is not None and _spec.loader is not None
_script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _script
_spec.loader.exec_module(_script)
ejecutar = _script.ejecutar
tiene_keyword_por_reglas = _script.tiene_keyword_por_reglas

_TI = ["desarrollo", "aplicación", "software", "plataforma", "licencias", "servidores", "hosting"]
_NO_TI = ["limpieza", "jardinería", "obras", "revista", "catering", "mobiliario", "vigilancia"]


def _titulo(rng: random.Random, es_ti: bool, keyword: bool) -> str:
    palabras = rng.sample(_TI if es_ti else _NO_TI, 3)
    return " ".join(palabras + (["kw"] if keyword else []))


def _golden(n: int, *, semilla: int, split: str, anio: int) -> list[EjemploGoldenTi]:
    rng = random.Random(semilla)
    tipos = [
        (True, True, "72000000"),
        (True, False, "72000000"),
        (False, True, "90900000"),
        (False, False, "72000000"),
    ]
    ejemplos = []
    for i in range(n):
        es_ti, keyword, cpv = tipos[i % 4]
        ejemplos.append(
            EjemploGoldenTi(
                id_externo=f"G{semilla}-{i}",
                fuente="pscp",
                fecha=f"{anio}-{1 + (i * 12) // n:02d}-01",
                titulo=_titulo(rng, es_ti, keyword) + f" {i}",
                descripcion="",
                cpv=cpv,
                es_ti=es_ti,
                familias=(),
                fabricantes=(),
                etiquetado_por="humano",
                etiquetado_at="2026-10-24",
                split=split,  # type: ignore[arg-type]  # literal de test
            )
        )
    return ejemplos


def _filas(n: int) -> list[dict]:
    rng = random.Random(99)
    filas = []
    for i in range(n):
        es_ti = i % 2 == 0
        filas.append(
            {
                "id_externo": f"F{i}",
                "fuente": "pscp",
                "fecha_publicacion": f"2024-{1 + (i * 12) // n:02d}-{1 + i % 28:02d}",
                # Vocabulario distinto del golden para que ninguna convocatoria
                # coincida con un ejemplo del golden.
                "titulo": _titulo(rng, es_ti, False) + " entrenamiento",
                "descripcion": None,
                "cpv": "72000000" if es_ti else "90900000",
                "tecnologia": None,
                "humano_es_ti": None,
                "llm_es_ti": es_ti,
            }
        )
    return filas


def _kw(titulo: str | None, cpv: str | None) -> bool:
    return "kw" in (titulo or "").split()


def test_con_llm_apto_entrena_y_decide() -> None:
    golden = _golden(80, semilla=1, split="tune", anio=2025) + _golden(
        80, semilla=2, split="holdout", anio=2026
    )
    respuestas = {e.id_externo: RespuestaLlm(e.es_ti, frozenset()) for e in golden}
    informe, modelos = ejecutar(
        golden, _filas(240), respuestas, candidatos=("A",), n_bootstrap=100, tiene_keyword=_kw
    )
    assert informe["acuerdo_llm"]["apto"] is True
    assert informe["dataset"]["n_llm"] == 240
    assert informe["veredicto"] == "APTO", informe["evaluacion"]["motivos"]
    assert set(modelos) == {"A"}


def test_con_llm_no_apto_sus_etiquetas_no_entrenan() -> None:
    golden = _golden(80, semilla=1, split="tune", anio=2025) + _golden(
        80, semilla=2, split="holdout", anio=2026
    )
    # El LLM dice lo contrario que el humano: acuerdo 0.
    respuestas = {e.id_externo: RespuestaLlm(not e.es_ti, frozenset()) for e in golden}
    informe, modelos = ejecutar(
        golden, _filas(240), respuestas, candidatos=("A",), n_bootstrap=100, tiene_keyword=_kw
    )
    assert informe["acuerdo_llm"]["apto"] is False
    assert informe["dataset"]["n_etiquetadas"] == 0
    assert modelos == {}
    assert informe["veredicto"] == "NO APTO"
    assert "A" in informe["evaluacion"]["sin_evaluar"]


def test_sin_holdout_no_entrena() -> None:
    golden = _golden(20, semilla=1, split="tune", anio=2025)
    informe, modelos = ejecutar(
        golden, _filas(240), {}, candidatos=("A",), n_bootstrap=10, tiene_keyword=_kw
    )
    assert informe["veredicto"].startswith("SIN HOLDOUT")
    assert modelos == {}


def test_el_baseline_de_keywords_es_la_puerta_de_reglas() -> None:
    assert tiene_keyword_por_reglas("Llicències SAP S/4HANA", "45221119")
    # Solo CPV 48/72, sin keyword: la puerta lo admite, pero no por keyword.
    assert not tiene_keyword_por_reglas("Servicio de mensajería", "72000000")
