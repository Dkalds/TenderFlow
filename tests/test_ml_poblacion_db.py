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


def _feedback(
    expediente: str,
    *,
    source: str,
    tecnologia: str | None = None,
    secundarias: str | None = None,
    created_at: str = "2026-09-01T10:00:00+00:00",
) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO ml_feedback "
            "(expediente, relevante, tecnologia, tecnologias_secundarias, source, created_at) "
            "VALUES (%s, 1, %s, %s, %s, %s)",
            (expediente, tecnologia, secundarias, source, created_at),
        )


def test_una_fila_humana_solo_mete_la_licitacion_si_se_pronuncia(db) -> None:
    """Mismo criterio que ``etiqueta_humana``: una fila ``revision_ti`` se
    pronuncia siempre (sin tecnología, «ninguna familia»); una ``human``
    heredada, solo si nombra alguna tecnología, en ``tecnologia`` o en las
    secundarias. Si la heredada sin tecnología abriera la puerta, la fila de
    fuera de la población entraría sin etiqueta humana y caería a la de
    keywords. Lo admitido es justo lo que el lector etiqueta."""
    from db.repositories.feedback import FUENTE_LEGADO, FUENTE_REVISION_TI
    from db.repositories.licitaciones import LicitacionRepository

    for expediente in (
        "PSCP-LEGADO-SIN-TEC",
        "PSCP-LEGADO-CON-TEC",
        "PSCP-LEGADO-SECUNDARIA",
        "PSCP-REVISION-SIN-TEC",
    ):
        _insertar(expediente, universo="pscp_observed")
    _feedback("PSCP-LEGADO-SIN-TEC", source=FUENTE_LEGADO)
    _feedback("PSCP-LEGADO-CON-TEC", source=FUENTE_LEGADO, tecnologia="ORACLE")
    _feedback("PSCP-LEGADO-SECUNDARIA", source=FUENTE_LEGADO, secundarias='["SAP"]')
    _feedback("PSCP-REVISION-SIN-TEC", source=FUENTE_REVISION_TI)

    admitidas = _ids(filas_entrenamiento_tecnologia())

    assert admitidas == {"PSCP-LEGADO-CON-TEC", "PSCP-LEGADO-SECUNDARIA", "PSCP-REVISION-SIN-TEC"}
    etiquetas = LicitacionRepository().etiquetas_tecnologia_no_circulares()
    assert {
        expediente: valores["tecnologia_humana"]
        for expediente, valores in etiquetas.items()
        if valores.get("tecnologia_humana") is not None
    } == {
        "PSCP-LEGADO-CON-TEC": "ORACLE",
        "PSCP-LEGADO-SECUNDARIA": "SAP",
        "PSCP-REVISION-SIN-TEC": "",
    }


def test_manda_la_fila_humana_mas_reciente(db) -> None:
    """El lector se queda con la fila humana más reciente del expediente: si
    esa no se pronuncia, una anterior que sí lo hacía no cuenta, y la
    licitación tampoco entra por ella."""
    from db.repositories.feedback import FUENTE_LEGADO

    _insertar("PSCP-CORREGIDA", universo="pscp_observed")
    _feedback(
        "PSCP-CORREGIDA",
        source=FUENTE_LEGADO,
        tecnologia="SAP",
        created_at="2026-05-01T10:00:00+00:00",
    )
    _feedback("PSCP-CORREGIDA", source=FUENTE_LEGADO, created_at="2026-06-01T10:00:00+00:00")

    assert _ids(filas_entrenamiento_tecnologia()) == set()


def test_una_cita_inverificable_del_llm_no_mete_la_fila_en_el_dataset(db) -> None:
    """``__sin_evidencia__`` es «el LLM no se pronunció»: si abriera la puerta
    del dataset, la fila de fuera de la población entraría sin etiqueta y
    entrenaría como negativo. El «sin tecnología» sí es un pronunciamiento."""
    from db.repositories.tecnologia_pliego import TecnologiaPliegoRepository

    _insertar("PSCP-SIN-EVIDENCIA", universo="pscp_observed")
    _insertar("PSCP-SIN-TECNOLOGIA", universo="pscp_observed")
    repo = TecnologiaPliegoRepository()
    repo.upsert_signals(
        "PSCP-SIN-EVIDENCIA",
        method="llm_metadata",
        signal_version="v2",
        scores={},
        sin_evidencia=True,
    )
    repo.upsert_signals(
        "PSCP-SIN-TECNOLOGIA", method="llm_metadata", signal_version="v2", scores={}
    )

    assert _ids(filas_entrenamiento_tecnologia()) == {"PSCP-SIN-TECNOLOGIA"}


def _marcador_es_ti() -> dict[str, Any]:
    """La fila de nivel 1 tal como la escribe ``scheduler/jobs/llm_tech_labeling.py``."""
    from db.repositories.tecnologia_pliego import ES_TI_SENTINEL, TechSignal

    return {
        ES_TI_SENTINEL: TechSignal(
            score=0.0, evidence=[{"es_ti": True, "confianza": 0.9, "otros_fabricantes": []}]
        )
    }


def test_el_marcador_no_reabre_la_puerta_a_una_respuesta_sin_evidencia(db) -> None:
    """Forma v3: un «es TI» cuyas citas de familia no se sostuvieron escribe el
    marcador y ``__sin_evidencia__`` en la misma llamada. El lector de etiquetas
    descarta ese grupo entero; si el marcador abriera la puerta, la fila de
    fuera de la población entraría sin etiqueta y entrenaría como negativo de
    todas las familias. El marcador solo sí es una respuesta: «ninguna familia»."""
    from db.repositories.tecnologia_pliego import TecnologiaPliegoRepository

    _insertar("PSCP-ES-TI-SIN-EVIDENCIA", universo="pscp_observed")
    _insertar("PSCP-SOLO-MARCADOR", universo="pscp_observed")
    repo = TecnologiaPliegoRepository()
    repo.upsert_signals(
        "PSCP-ES-TI-SIN-EVIDENCIA",
        method="llm_metadata",
        signal_version="llm-meta-v3/m",
        scores=_marcador_es_ti(),
        sin_evidencia=True,
    )
    repo.upsert_signals(
        "PSCP-SOLO-MARCADOR",
        method="llm_metadata",
        signal_version="llm-meta-v3/m",
        scores=_marcador_es_ti(),
    )

    assert _ids(filas_entrenamiento_tecnologia()) == {"PSCP-SOLO-MARCADOR"}


def test_sin_evidencia_solo_cierra_su_propio_method(db) -> None:
    """El grupo es ``(licitación, method)``, como en el lector de etiquetas: un
    ``__sin_evidencia__`` de ``llm_metadata`` no tapa lo que dijo la ficha del
    pliego (``llm``) de la misma licitación."""
    from db.repositories.tecnologia_pliego import TechSignal, TecnologiaPliegoRepository

    _insertar("PSCP-DOS-CARRILES", universo="pscp_observed")
    repo = TecnologiaPliegoRepository()
    repo.upsert_signals(
        "PSCP-DOS-CARRILES",
        method="llm_metadata",
        signal_version="llm-meta-v3/m",
        scores=_marcador_es_ti(),
        sin_evidencia=True,
    )
    repo.upsert_signals(
        "PSCP-DOS-CARRILES",
        method="llm",
        signal_version="tender-facts-v2",
        scores={"SAP": TechSignal(score=0.9, evidence=[])},
    )

    assert _ids(filas_entrenamiento_tecnologia()) == {"PSCP-DOS-CARRILES"}


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
