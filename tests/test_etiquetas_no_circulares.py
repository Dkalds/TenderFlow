"""Etiquetas de tecnología independientes del regex de keywords.

``LicitacionRepository.etiquetas_tecnologia_no_circulares`` es lo único que
rompe la circularidad del ``TechnologyClassifier``: sin ella el modelo entrena
contra ``licitaciones.tecnologia``, que escriben los conectores con
``matches_technology()`` sobre el mismo texto que ve el modelo.

Regresión que cubre esta suite: la mitad LLM de la query hacía
``JOIN licitaciones l ON l.id = p.licitacion_id`` y ``licitaciones`` no tiene
columna ``id`` —``licitacion_tecnologia_pliego.licitacion_id`` ES el
``id_externo``, así lo declara su propia FK—. Cada llamada lanzaba
``UndefinedColumn``; ``train_from_db`` lo capturaba y degradaba a etiquetas
circulares con un warning, así que el fallo nunca se vio como fallo, solo como
un clasificador que imitaba al regex. No había ningún test sobre esta función.
"""

from __future__ import annotations

import pytest

from db.repositories.licitaciones import LicitacionRepository
from db.repositories.tecnologia_pliego import TechSignal, TecnologiaPliegoRepository


@pytest.fixture()
def repos(tmp_db):
    _db_mod, _ = tmp_db
    return LicitacionRepository(), TecnologiaPliegoRepository()


def _insert_licitacion(id_externo: str) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, descripcion, fuente, fecha_publicacion, fecha_extraccion) "
            "VALUES (%s, %s, %s, 'placsp', '2026-06-01', CURRENT_TIMESTAMP)",
            (id_externo, f"Contrato {id_externo}", "Mantenimiento del ERP"),
        )


def _insert_feedback_humano(expediente: str, tecnologia: str | None) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO ml_feedback (expediente, relevante, tecnologia, source, created_at) "
            "VALUES (%s, 1, %s, 'human', CURRENT_TIMESTAMP)",
            (expediente, tecnologia),
        )


def test_la_query_no_revienta_contra_el_schema_real(repos) -> None:
    """La regresión desnuda: antes lanzaba UndefinedColumn en cada llamada."""
    lic_repo, _ = repos

    assert lic_repo.etiquetas_tecnologia_no_circulares() == {}


def test_la_señal_llm_se_indexa_por_id_externo(repos) -> None:
    lic_repo, tech_repo = repos
    _insert_licitacion("EXP-LLM")
    tech_repo.upsert_signals(
        "EXP-LLM",
        method="llm_metadata",
        signal_version="v1",
        scores={"SAP": TechSignal(score=0.91)},
    )

    externas = lic_repo.etiquetas_tecnologia_no_circulares()

    assert "EXP-LLM" in externas
    assert externas["EXP-LLM"]["tecnologia_llm"].startswith("SAP:")


def test_la_señal_de_keywords_no_cuenta_como_independiente(repos) -> None:
    """Es justo la fuente circular: si contara, el gate no serviría de nada."""
    lic_repo, tech_repo = repos
    _insert_licitacion("EXP-KW")
    tech_repo.upsert_signals(
        "EXP-KW",
        method="keywords",
        signal_version="v1",
        scores={"SAP": TechSignal(score=0.9)},
    )

    assert lic_repo.etiquetas_tecnologia_no_circulares() == {}


def test_el_feedback_humano_sin_tecnologia_es_un_pronunciamiento(repos) -> None:
    """Cadena vacía, no ausencia: el humano revisó y descartó, y eso es un
    negativo verdadero que el entrenamiento necesita."""
    lic_repo, _ = repos
    _insert_licitacion("EXP-H")
    _insert_feedback_humano("EXP-H", None)

    externas = lic_repo.etiquetas_tecnologia_no_circulares()

    assert externas["EXP-H"]["tecnologia_humana"] == ""


def test_las_dos_fuentes_conviven_en_la_misma_licitacion(repos) -> None:
    lic_repo, tech_repo = repos
    _insert_licitacion("EXP-2F")
    _insert_feedback_humano("EXP-2F", "ORACLE")
    tech_repo.upsert_signals(
        "EXP-2F",
        method="llm",
        signal_version="v1",
        scores={"SAP": TechSignal(score=0.8)},
    )

    fuentes = lic_repo.etiquetas_tecnologia_no_circulares()["EXP-2F"]

    assert fuentes["tecnologia_humana"] == "ORACLE"
    assert fuentes["tecnologia_llm"].startswith("SAP:")
