"""La población del clasificador contra el schema real (S6.1).

Los tests de ``test_ml_poblacion_entrenamiento.py`` fijan la **decisión** sobre
strings; estos comprueban que el SQL que la implementa hace lo que dice contra
Postgres: que las filas de PSCP quedan fuera del dataset, que los scores
heredados de fuera de la población se borran, y que la medición del criterio de
aceptación cuenta lo que tiene que contar.
"""

from __future__ import annotations

from typing import Any

import pytest

from db.repositories.ml_dataset import (
    distribucion_ml_proba,
    filas_entrenamiento_sap,
    filas_entrenamiento_tecnologia,
    filas_pendientes_ml_proba,
    guardar_ml_proba,
    limpiar_ml_proba_fuera_de_poblacion,
)


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _insertar(
    id_externo: str,
    *,
    universo: str | None,
    tecnologia: str | None = None,
    ml_proba: float | None = None,
) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, descripcion, fuente, analysis_universe, tecnologia, "
            " ml_proba, fecha_publicacion, fecha_extraccion) "
            "VALUES (%s, %s, %s, 'test', %s, %s, %s, '2026-06-01', CURRENT_TIMESTAMP)",
            (
                id_externo,
                f"Contrato {id_externo}",
                "Mantenimiento del ERP corporativo",
                universo,
                tecnologia,
                ml_proba,
            ),
        )


def _ids(filas: list[dict[str, Any]]) -> set[str]:
    return {str(f["id_externo"]) for f in filas}


def test_el_dataset_excluye_pscp_e_incluye_las_fuentes_filtradas(db) -> None:
    _insertar("PLACSP-1", universo="technology_observed")
    _insertar("SEED-1", universo=None)  # negativos de seed_negatives
    _insertar("GAL-1", universo="galicia_rss_recent_technology_observed")
    # Con `tecnologia` puesta: aun así no entra. Es la fila que
    # `universo_tecnologico_sql` sí admitiría, y por la que el dataset acabaría
    # con la fuente decidiendo la clase.
    _insertar("PSCP-1", universo="pscp_observed", tecnologia="SAP")

    assert _ids(filas_entrenamiento_sap()) == {"PLACSP-1", "SEED-1", "GAL-1"}
    assert _ids(filas_entrenamiento_tecnologia()) == {"PLACSP-1", "SEED-1", "GAL-1"}


def test_una_etiqueta_humana_entra_aunque_su_fuente_quede_fuera(db) -> None:
    """El corte no puede tirar etiquetas independientes: son exactamente lo
    que el gate de publicación exige y lo que produce la campaña de etiquetado.
    """
    from db.database import connect

    _insertar("PSCP-ETIQUETADA", universo="pscp_observed")
    _insertar("PSCP-SIN-ETIQUETA", universo="pscp_observed", tecnologia="SAP")
    with connect() as c:
        c.execute(
            "INSERT INTO ml_feedback (expediente, relevante, tecnologia, source, created_at) "
            "VALUES ('PSCP-ETIQUETADA', 1, 'ORACLE', 'human', CURRENT_TIMESTAMP)"
        )

    # El multi-tecnología la necesita; el binario se queda con su población.
    assert _ids(filas_entrenamiento_tecnologia()) == {"PSCP-ETIQUETADA"}
    assert _ids(filas_entrenamiento_sap()) == set()


def test_el_scoring_sirve_la_misma_poblacion_que_el_entrenamiento(db) -> None:
    _insertar("PLACSP-1", universo="technology_observed")
    _insertar("PSCP-1", universo="pscp_observed")

    assert _ids(filas_pendientes_ml_proba()) == {"PLACSP-1"}


def test_solo_las_filas_sin_score_salvo_force(db) -> None:
    _insertar("CON-SCORE", universo="technology_observed", ml_proba=0.9)
    _insertar("SIN-SCORE", universo="technology_observed")

    assert _ids(filas_pendientes_ml_proba()) == {"SIN-SCORE"}
    assert _ids(filas_pendientes_ml_proba(force=True)) == {"CON-SCORE", "SIN-SCORE"}


def test_guardar_ml_proba_persiste_el_score(db) -> None:
    _insertar("PLACSP-1", universo="technology_observed")

    assert guardar_ml_proba([(0.42, "PLACSP-1")]) == 1
    medicion = distribucion_ml_proba(0.1)
    assert medicion["puntuadas"] == 1
    assert medicion["por_encima"] == 1


def test_limpia_los_scores_heredados_de_fuera_de_la_poblacion(db) -> None:
    """El 90,64% del corpus por encima del umbral eran estas filas."""
    _insertar("PSCP-1", universo="pscp_observed", ml_proba=0.95)
    _insertar("PSCP-2", universo="pscp_observed", ml_proba=0.91)
    _insertar("PLACSP-1", universo="technology_observed", ml_proba=0.80)

    assert limpiar_ml_proba_fuera_de_poblacion() == 2
    # Idempotente: la segunda pasada no encuentra nada.
    assert limpiar_ml_proba_fuera_de_poblacion() == 0

    medicion = distribucion_ml_proba(0.7)
    assert medicion["fuera_poblacion"]["puntuadas"] == 0
    assert medicion["dentro_poblacion"]["puntuadas"] == 1


def test_la_medicion_separa_al_modelo_de_la_superficie(db) -> None:
    """``pct_puntuadas`` describe al clasificador; ``pct_corpus``, la superficie.

    Con la población acotada las dos divergen, y confundirlas haría pasar por
    mejora lo que solo es dejar de puntuar filas.
    """
    _insertar("PLACSP-1", universo="technology_observed", ml_proba=0.95)
    _insertar("PLACSP-2", universo="technology_observed", ml_proba=0.10)
    for i in range(8):
        _insertar(f"PSCP-{i}", universo="pscp_observed")

    medicion = distribucion_ml_proba(0.7)
    assert medicion["total_corpus"] == 10
    assert medicion["puntuadas"] == 2
    assert medicion["por_encima"] == 1
    assert medicion["pct_puntuadas_por_encima"] == 50.0
    assert medicion["pct_corpus_por_encima"] == 10.0


def test_sin_filas_puntuadas_el_porcentaje_es_none(db) -> None:
    _insertar("PLACSP-1", universo="technology_observed")

    medicion = distribucion_ml_proba(0.7)
    assert medicion["pct_puntuadas_por_encima"] is None
