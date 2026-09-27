"""Las dos fases de ``candidatos_desacuerdo``, sin BD (plan de tres niveles, F1).

Una sola pasada recorría ``licitaciones`` entera, ~6 s en producción: el heap
sigue en 872 MB tras la purga. Ahora la fase A (los cuatro motivos del LLM)
parte de las filas del LLM, y la fase B (``modelo_dudoso``) solo corre si A no
llena el cupo y solo mira lo reciente. El SQL de cada fase se prueba contra
Postgres en ``tests/test_revision_ti_desacuerdo.py``; aquí, qué se le pide a la
BD en cada fase y cómo se juntan las respuestas.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from db.repositories import revision_ti
from db.repositories.tecnologia_pliego import ES_TI_SENTINEL

_COLUMNAS = (
    "id_externo",
    "titulo",
    "descripcion",
    "cpv",
    "importe",
    "organo_contratacion",
    "ccaa",
    "fecha_publicacion",
    "url",
    "tecnologia",
    "ml_tecnologias",
    "ml_proba_max",
    "ml_tech_principal",
    "ml_proba",
    "marcador",
    "llm_evidencia",
    "llm_familias",
    "motivo",
)


def _fila(id_externo: str, motivo: str, **campos: Any) -> tuple[Any, ...]:
    valores: dict[str, Any] = dict.fromkeys(_COLUMNAS)
    valores.update(id_externo=id_externo, titulo=f"Contrato {id_externo}", motivo=motivo)
    valores.update(campos)
    return tuple(valores[c] for c in _COLUMNAS)


class _BD:
    """Conexión falsa: cada ``execute`` devuelve la siguiente tanda de filas."""

    def __init__(self, tandas: list[list[tuple[Any, ...]]]) -> None:
        self._tandas = tandas
        self.parametros: list[dict[str, Any]] = []

    def execute(self, sql: str, params: dict[str, Any]) -> SimpleNamespace:
        self.parametros.append(params)
        filas = self._tandas.pop(0)
        return SimpleNamespace(description=[(c,) for c in _COLUMNAS], fetchall=lambda: filas)


def _conectar(monkeypatch: pytest.MonkeyPatch, *tandas: list[tuple[Any, ...]]) -> _BD:
    bd = _BD(list(tandas))

    @contextlib.contextmanager
    def _conexion() -> Iterator[_BD]:
        yield bd

    monkeypatch.setattr(revision_ti, "connect_read", _conexion)
    return bd


def _desde() -> str:
    hace = datetime.now(UTC) - timedelta(days=revision_ti.VENTANA_DUDOSO_DIAS)
    return hace.date().isoformat()


def test_si_la_fase_a_llena_el_cupo_no_se_mira_la_zona_dudosa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bd = _conectar(monkeypatch, [_fila("A", "llm_no_reglas_si"), _fila("B", "llm_si_reglas_no")])

    filas = revision_ti.candidatos_desacuerdo(2)

    assert [f["id_externo"] for f in filas] == ["A", "B"]
    assert len(bd.parametros) == 1
    assert bd.parametros[0]["limit"] == 2


def test_la_zona_dudosa_rellena_solo_lo_que_falta_sin_repetir_y_reciente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bd = _conectar(
        monkeypatch,
        [_fila("A", "llm_no_reglas_si")],
        [_fila("F", "modelo_dudoso", ml_proba=0.5)],
    )

    antes = _desde()
    filas = revision_ti.candidatos_desacuerdo(5)
    despues = _desde()

    assert [(f["id_externo"], f["motivo"]) for f in filas] == [
        ("A", "llm_no_reglas_si"),
        ("F", "modelo_dudoso"),
    ]
    fase_b = bd.parametros[1]
    assert fase_b["faltan"] == 4
    assert fase_b["excluir"] == ["A"]
    # Fecha ISO, que es como `licitaciones.fecha_publicacion` se compara y
    # ordena; `antes`/`despues` cubren un cambio de día a mitad de la llamada.
    assert fase_b["desde"] in {antes, despues}


def test_la_zona_dudosa_trae_tambien_la_propuesta_del_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una licitación en la que reglas y LLM coinciden solo entra por la fase B,
    pero su propuesta del LLM sigue sirviendo para aceptarla de un clic."""
    evidencia = json.dumps([{"es_ti": True, "confianza": 0.9, "otros_fabricantes": []}])
    _conectar(
        monkeypatch,
        [],
        [
            _fila(
                "F",
                "modelo_dudoso",
                marcador=ES_TI_SENTINEL,
                llm_evidencia=evidencia,
                llm_familias=["SAP"],
            )
        ],
    )

    (fila,) = revision_ti.candidatos_desacuerdo(5)

    assert fila["llm_es_ti"] is True
    assert fila["llm_confianza_es_ti"] == pytest.approx(0.9)
    assert fila["llm_familias"] == ["SAP"]
    assert "marcador" not in fila
    assert "llm_evidencia" not in fila
