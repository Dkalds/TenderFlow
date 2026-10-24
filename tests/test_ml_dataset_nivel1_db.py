"""``filas_etiquetadas_nivel1`` contra el schema real (Postgres).

Lo que ningún test unitario cubre: que la revisión humana vigente es la
``revision_ti`` más reciente (y no una ``human`` heredada), que el LLM se lee
de su versión vigente con la regla de ``__sin_evidencia__``, que una fila sin
ninguna etiqueta no sale y que los duplicados confirmados quedan fuera.
"""

from __future__ import annotations

import pytest

from db.repositories.feedback import FUENTE_REVISION_TI
from db.repositories.tecnologia_pliego import (
    ES_TI_SENTINEL,
    NO_ES_TI_SENTINEL,
    SIN_EVIDENCIA_SENTINEL,
)


@pytest.fixture()
def db(tmp_db):
    return tmp_db


def _licitacion(id_externo: str, *, tecnologia: str | None = None) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, descripcion, fuente, fecha_publicacion, cpv, tecnologia, "
            "fecha_extraccion) "
            "VALUES (%s, %s, NULL, 'pscp', '2026-09-01', '72000000', %s, CURRENT_TIMESTAMP)",
            (id_externo, f"Contrato {id_externo}", tecnologia),
        )


def _feedback(expediente: str, relevante: int, created_at: str, source: str) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO ml_feedback (expediente, relevante, source, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (expediente, relevante, source, created_at),
        )


def _senal(licitacion_id: str, tecnologia: str, version: str, computed_at: str) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitacion_tecnologia_pliego "
            "(licitacion_id, tecnologia, method, score, matched_terms, evidence_json, "
            "signal_version, computed_at) "
            "VALUES (%s, %s, 'llm_metadata', 0.0, NULL, NULL, %s, %s)",
            (licitacion_id, tecnologia, version, computed_at),
        )


def test_filas_etiquetadas_nivel1(db) -> None:
    from db.database import connect
    from db.repositories.ml_dataset import filas_etiquetadas_nivel1

    for id_ in ("H", "L", "S", "N", "D"):
        _licitacion(id_, tecnologia="ERP" if id_ == "H" else None)
    # H: humano, la revisión más reciente manda; la `human` heredada no cuenta.
    _feedback("H", 0, "2026-09-01T00:00:00+00:00", FUENTE_REVISION_TI)
    _feedback("H", 1, "2026-09-10T00:00:00+00:00", FUENTE_REVISION_TI)
    _feedback("H", 0, "2026-09-20T00:00:00+00:00", "human")
    # L: el LLM dijo «sí» en v2 y «no» en v3, la vigente.
    _senal("L", ES_TI_SENTINEL, "llm-meta-v2/m", "2026-09-01T00:00:00+00:00")
    _senal("L", NO_ES_TI_SENTINEL, "llm-meta-v3/m", "2026-09-10T00:00:00+00:00")
    # S: marcador con `__sin_evidencia__` en la misma versión: no se pronunció.
    _senal("S", ES_TI_SENTINEL, "llm-meta-v3/m", "2026-09-10T00:00:00+00:00")
    _senal("S", SIN_EVIDENCIA_SENTINEL, "llm-meta-v3/m", "2026-09-10T00:00:00+00:00")
    # D: con etiqueta, pero duplicado confirmado.
    _feedback("D", 1, "2026-09-10T00:00:00+00:00", FUENTE_REVISION_TI)
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones_duplicados "
            "(licitacion_id, canonical_id, confianza, status, clave_match) "
            "VALUES ('D', 'H', 1.0, 'confirmed', 'test')"
        )

    filas = {f["id_externo"]: f for f in filas_etiquetadas_nivel1()}

    assert set(filas) == {"H", "L", "S"}  # N sin etiqueta, D duplicado
    assert filas["H"]["humano_es_ti"] == 1
    assert filas["H"]["llm_es_ti"] is None
    assert filas["H"]["tecnologia"] == "ERP"
    assert filas["L"]["humano_es_ti"] is None
    assert filas["L"]["llm_es_ti"] is False
    assert filas["S"]["llm_es_ti"] is None
