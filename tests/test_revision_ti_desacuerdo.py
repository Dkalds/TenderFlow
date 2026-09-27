"""Candidatos de la revisión por desacuerdo contra el schema real (F1).

``db.repositories.revision_ti.candidatos_desacuerdo`` cruza tres fuentes que
se escriben por caminos distintos: las reglas (``licitaciones.tecnologia`` y el
CPV), el LLM (el marcador de es_ti y las familias, filas de
``licitacion_tecnologia_pliego`` con ``method='llm_metadata'``) y el modelo
(``ml_proba``). Por eso las señales del LLM se siembran con
``upsert_signals``, el mismo escritor que usa el job: si el marcador cambia de
forma al escribirse, esta suite lo ve.
"""

from __future__ import annotations

from typing import Any

import pytest

from db.repositories.feedback import FUENTE_REVISION_TI
from db.repositories.revision_ti import candidatos_desacuerdo
from db.repositories.tecnologia_pliego import (
    ES_TI_SENTINEL,
    NO_ES_TI_SENTINEL,
    TechSignal,
    TecnologiaPliegoRepository,
)

_VERSION = "llm-meta-v3/m"


@pytest.fixture()
def tech_repo(tmp_db) -> TecnologiaPliegoRepository:
    _db_mod, _ = tmp_db
    return TecnologiaPliegoRepository()


def _insert_licitacion(
    id_externo: str, *, tecnologia: str | None = None, cpv: str | None = None
) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, cpv, tecnologia, fuente, fecha_publicacion, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s, 'placsp', '2026-09-01', CURRENT_TIMESTAMP)",
            (id_externo, f"Contrato {id_externo}", cpv, tecnologia),
        )


def _insert_feedback(expediente: str, *, source: str) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO ml_feedback (expediente, relevante, source, created_at) "
            "VALUES (%s, 1, %s, CURRENT_TIMESTAMP)",
            (expediente, source),
        )


def _marcador(es_ti: bool, confianza: float) -> dict[str, TechSignal]:
    """La fila de nivel 1 tal como la escribe ``scheduler/jobs/llm_tech_labeling.py``."""
    return {
        (ES_TI_SENTINEL if es_ti else NO_ES_TI_SENTINEL): TechSignal(
            score=0.0,
            evidence=[{"es_ti": es_ti, "confianza": confianza, "otros_fabricantes": []}],
        )
    }


def _senal_llm(
    repo: TecnologiaPliegoRepository, licitacion_id: str, scores: dict[str, TechSignal]
) -> None:
    repo.upsert_signals(
        licitacion_id, method="llm_metadata", signal_version=_VERSION, scores=scores
    )


def _por_id(filas: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(f["id_externo"]): f for f in filas}


def test_ordena_por_la_gravedad_del_desacuerdo_y_excluye_lo_revisado(
    tech_repo: TecnologiaPliegoRepository,
) -> None:
    # A: las reglas ven ERP; el LLM dice que no es TI.
    _insert_licitacion("EXP-A", tecnologia="ERP")
    _senal_llm(tech_repo, "EXP-A", _marcador(False, 0.8))
    # B: el LLM dice que es TI; ni las reglas ni el CPV (79, servicios) lo ven.
    _insert_licitacion("EXP-B", cpv="79000000-4")
    _senal_llm(tech_repo, "EXP-B", _marcador(True, 0.9))
    # C: el CPV es de informática (72); el LLM dice que no es TI.
    _insert_licitacion("EXP-C", cpv="72000000-5")
    _senal_llm(tech_repo, "EXP-C", _marcador(False, 0.6))
    # D: las reglas ven SAP; el LLM, es TI pero con otra familia.
    _insert_licitacion("EXP-D", tecnologia="SAP")
    _senal_llm(tech_repo, "EXP-D", {"ORACLE": TechSignal(score=0.9), **_marcador(True, 0.95)})
    # E: como A, pero ya revisada con `revision_ti` (y con una fila heredada).
    _insert_licitacion("EXP-E", tecnologia="ERP")
    _senal_llm(tech_repo, "EXP-E", _marcador(False, 0.8))
    _insert_feedback("EXP-E", source="human")
    _insert_feedback("EXP-E", source=FUENTE_REVISION_TI)

    filas = candidatos_desacuerdo(10)

    assert [f["id_externo"] for f in filas] == ["EXP-A", "EXP-B", "EXP-C", "EXP-D"]
    assert [f["motivo"] for f in filas] == [
        "llm_no_reglas_si",
        "llm_si_reglas_no",
        "llm_no_cpv_si",
        "familias_distintas",
    ]
    por_id = _por_id(filas)
    # La propuesta del LLM llega descodificada: el marcador como bool, la
    # confianza desde su evidencia y las familias sin sentinels.
    assert por_id["EXP-A"]["llm_es_ti"] is False
    assert por_id["EXP-A"]["llm_confianza_es_ti"] == pytest.approx(0.8)
    assert por_id["EXP-A"]["llm_familias"] == []
    assert por_id["EXP-D"]["llm_es_ti"] is True
    assert por_id["EXP-D"]["llm_confianza_es_ti"] == pytest.approx(0.95)
    assert por_id["EXP-D"]["llm_familias"] == ["ORACLE"]
    assert "marcador" not in por_id["EXP-D"]
    assert "llm_evidencia" not in por_id["EXP-D"]


def test_una_fila_heredada_sola_no_saca_la_licitacion_de_la_cola(
    tech_repo: TecnologiaPliegoRepository,
) -> None:
    """Las filas ``human`` anteriores al plan significaban «es SAP», no «es TI»:
    esas licitaciones se vuelven a revisar, así que solo ``revision_ti`` las
    saca de la cola."""
    _insert_licitacion("EXP-H", tecnologia="ERP")
    _senal_llm(tech_repo, "EXP-H", _marcador(False, 0.8))
    _insert_feedback("EXP-H", source="human")

    assert [f["id_externo"] for f in candidatos_desacuerdo(10)] == ["EXP-H"]


def test_sin_desacuerdo_no_hay_candidato(tech_repo: TecnologiaPliegoRepository) -> None:
    """Reglas y LLM de acuerdo, y sin ``ml_proba`` en la zona dudosa: nada
    que preguntar a una persona."""
    _insert_licitacion("EXP-OK", tecnologia="SAP", cpv="72000000-5")
    _senal_llm(tech_repo, "EXP-OK", {"SAP": TechSignal(score=0.9), **_marcador(True, 0.9)})

    assert candidatos_desacuerdo(10) == []
