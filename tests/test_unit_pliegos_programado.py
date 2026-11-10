"""El lote de pliegos en el plano de cron de la API (ADR-033).

El plano da por bueno cualquier retorno sin excepción: lo que el workflow
decía con su rojo, ``run_programado`` tiene que decirlo con un correo.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from scheduler.jobs import build_default_registry, documentos_embeddings
from scheduler.jobs.documentos_embeddings import run_programado


def _resumen(**fases: dict[str, Any]) -> dict[str, Any]:
    base: dict[str, dict[str, Any]] = {
        "fetch": {"extracted": 3, "error": 0},
        "embed": {"documentos_procesados": 3, "sin_motor": 0},
        "facts": {"procesadas": 2, "error": 0},
        "tech_signal": {},
        "resumen_pregen": {},
    }
    return {**base, **fases}


def _correr(resumen: dict[str, Any]) -> list[str]:
    """Títulos de los avisos que manda ``run_programado`` para ese resumen."""
    with (
        patch.object(documentos_embeddings, "run", return_value=resumen),
        patch("observability.alerts.notify") as notify,
    ):
        assert run_programado() is resumen
    return [llamada.args[1] for llamada in notify.call_args_list]


def test_el_plano_registra_la_entrada_que_avisa() -> None:
    """Con ``run`` a secas, una credencial rechazada saldría en verde cada noche."""
    job = next(j for j in build_default_registry() if j.name == "documentos_embeddings")
    assert job.fn is run_programado
    assert job.plane == "render"


def test_un_lote_sano_no_manda_ningun_correo() -> None:
    assert _correr(_resumen()) == []


def test_avisa_si_el_lote_entero_de_descarga_falla() -> None:
    avisos = _correr(_resumen(fetch={"extracted": 0, "error": 300}))
    assert avisos == ["Pliegos: el lote entero de descarga falló"]


@pytest.mark.parametrize("procesado", ["extracted", "unsupported", "sin_texto"])
def test_un_lote_con_algo_procesado_no_es_un_fallo(procesado: str) -> None:
    """Formatos que no se leen o escaneados son cobertura que falta, no un fallo."""
    assert _correr(_resumen(fetch={"error": 5, procesado: 1})) == []


def test_avisa_si_no_hay_motor_de_embeddings() -> None:
    """Un build sin el modelo ONNX deja la fase saltándose con el job en verde."""
    avisos = _correr(_resumen(embed={"documentos_procesados": 0, "sin_motor": 1}))
    assert avisos == ["Pliegos: no hay motor de embeddings"]


def test_avisa_si_el_llm_rechaza_la_credencial() -> None:
    """El incidente de las once noches de 401 en verde (2026-09)."""
    avisos = _correr(_resumen(facts={"procesadas": 4, "credencial_rechazada": "401"}))
    assert avisos == ["Pliegos: fallo sistémico en la fase de fichas"]


def test_dos_fases_rotas_mandan_dos_avisos() -> None:
    avisos = _correr(
        _resumen(fetch={"error": 9}, facts={"error": 7, "procesadas": 0}),
    )
    assert avisos == [
        "Pliegos: el lote entero de descarga falló",
        "Pliegos: fallo sistémico en la fase de fichas",
    ]


def test_no_lanza_aunque_todo_falle() -> None:
    """Una excepción haría que el backoff del plano multiplicara un intervalo de un día."""
    _correr(_resumen(fetch={"error": 9}, embed={"sin_motor": 1}, facts={"error": 1}))
