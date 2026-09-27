"""``FeedbackRepository.filas_revision_ti`` contra el schema real (Postgres).

Cubre lo que ningún test unitario puede: que el ``DISTINCT ON`` se queda con
la revisión más reciente por expediente (no la primera insertada) y que el
JOIN con ``licitaciones`` trae las columnas que ``services.ml.golden_ti``
necesita (``fuente``, ``fecha_publicacion``, ``titulo``, ``descripcion``,
``cpv``). Una fila ``human`` (no ``revision_ti``) del mismo expediente
comprueba que el filtro ``source`` la excluye.
"""

from __future__ import annotations

import pytest

from db.repositories.feedback import FUENTE_REVISION_TI, FeedbackRepository


@pytest.fixture()
def repo(tmp_db):
    _db_mod, _ = tmp_db
    return FeedbackRepository()


def _insert_licitacion(id_externo: str) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, descripcion, fuente, fecha_publicacion, cpv, fecha_extraccion) "
            "VALUES (%s, %s, %s, 'placsp', '2026-09-01', %s, CURRENT_TIMESTAMP)",
            (id_externo, f"Contrato {id_externo}", "Implantación de ERP", "72000000"),
        )


def _insert_feedback(
    expediente: str,
    *,
    relevante: int,
    tecnologia: str | None,
    created_at: str,
    source: str = FUENTE_REVISION_TI,
) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO ml_feedback (expediente, relevante, tecnologia, source, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (expediente, relevante, tecnologia, source, created_at),
        )


def test_filas_revision_ti_devuelve_la_mas_reciente_por_expediente(repo) -> None:
    """Dos revisiones `revision_ti` del mismo expediente + una `human` vieja.

    Solo debe volver una fila: la `revision_ti` más nueva por `created_at`,
    con las columnas de `licitaciones` unidas. La `human` no cuenta -- ni
    aunque sea la más reciente de las tres -- porque el filtro es por
    `source`, no por fecha.
    """
    _insert_licitacion("EXP-1")
    _insert_feedback(
        "EXP-1",
        relevante=0,
        tecnologia=None,
        created_at="2026-09-01T10:00:00+00:00",
    )
    _insert_feedback(
        "EXP-1",
        relevante=1,
        tecnologia="ERP",
        created_at="2026-09-20T10:00:00+00:00",
    )
    _insert_feedback(
        "EXP-1",
        relevante=1,
        tecnologia="SAP",
        created_at="2026-09-25T10:00:00+00:00",
        source="human",
    )

    filas = repo.filas_revision_ti()

    assert len(filas) == 1
    fila = filas[0]
    assert fila["expediente"] == "EXP-1"
    assert fila["relevante"] == 1
    assert fila["tecnologia"] == "ERP"
    assert fila["created_at"] == "2026-09-20T10:00:00+00:00"
    assert fila["fuente"] == "placsp"
    assert fila["fecha_publicacion"] == "2026-09-01"
    assert fila["titulo"] == "Contrato EXP-1"
    assert fila["descripcion"] == "Implantación de ERP"
    assert fila["cpv"] == "72000000"


def test_filas_revision_ti_separa_expedientes_distintos(repo) -> None:
    _insert_licitacion("EXP-A")
    _insert_licitacion("EXP-B")
    _insert_feedback("EXP-A", relevante=1, tecnologia="ERP", created_at="2026-09-01T00:00:00+00:00")
    _insert_feedback("EXP-B", relevante=0, tecnologia=None, created_at="2026-09-02T00:00:00+00:00")

    filas = {fila["expediente"]: fila for fila in repo.filas_revision_ti()}

    assert set(filas) == {"EXP-A", "EXP-B"}
    assert filas["EXP-A"]["relevante"] == 1
    assert filas["EXP-B"]["relevante"] == 0
