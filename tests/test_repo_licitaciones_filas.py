"""Las formas de fila (``db/repositories/licitaciones/filas.py``) frente a su SELECT.

``typed_rows`` no valida en runtime: el ``TypedDict`` es una aserción de forma
que mypy cree a ciegas. Si un alias del SELECT cambia y el ``TypedDict`` no, el
tipado sigue en verde y el consumidor lee una clave que no llega. Este test es
el contrapeso que ``typed_rows`` promete: cada consulta, contra Postgres,
devuelve exactamente las claves de su forma.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from db.repositories.licitaciones import LicitacionRepository, licitaciones_por_lote
from db.repositories.licitaciones import filas as f

_AHORA = "2026-10-01T00:00:00+00:00"
_ID = "L1"


def _sembrar(db_mod: Any) -> None:
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion, fuente, estado, "
            "fecha_publicacion, importe, ml_proba) "
            "VALUES (%s, 'Soporte SAP', %s, 'placsp', 'PRE', '2026-09-15', 100.0, 0.5)",
            (_ID, _AHORA),
        )
        c.execute(
            "INSERT INTO licitacion_tecnologia_score (licitacion_id, tecnologia, probabilidad, "
            "threshold_aplicado, computed_at) VALUES (%s, 'SAP', 0.9, 0.5, %s)",
            (_ID, _AHORA),
        )
        c.execute(
            "INSERT INTO licitaciones_history (id_externo, captured_at, source, snapshot_json, "
            "changed_fields) VALUES (%s, %s, 'placsp', '{}', '[]')",
            (_ID, _AHORA),
        )


_repo = LicitacionRepository()

_CONSULTAS: list[tuple[type[Any], Callable[[], list[Any]]]] = [
    (f.LicitacionResumenRow, lambda: _repo.get_by_ids([_ID])),
    (f.ProximaRow, lambda: _repo.proximas(estados=["PRE"])[0]),
    (f.TechScoreRow, lambda: _repo.tech_scores_for(_ID)),
    (f.CandidatoEtiquetadoRow, lambda: _repo.get_unlabelled_candidates()),
    (f.CandidatoEtiquetadoRow, lambda: _repo.get_unlabelled_random()),
    (f.ZonaIncertidumbreRow, lambda: _repo.load_uncertainty_zone(0.0, 1.0, 10)),
    (f.DriftRow, lambda: _repo.load_drift_window("2026-09-01", "2026-09-30")),
    (
        f.RecienteRow,
        lambda: _repo.fetch_recent(since_extraccion="2000", since_actualizacion="2000", limit=5),
    ),
    (f.ExportPdfRow, lambda: _repo.fetch_for_pdf()),
    (f.HistorialRow, lambda: _repo.get_history(_ID)),
    (f.LicitacionLoteRow, lambda: licitaciones_por_lote([_ID])),
]


@pytest.mark.parametrize(
    ("forma", "consulta"),
    _CONSULTAS,
    ids=[f"{forma.__name__}-{i}" for i, (forma, _) in enumerate(_CONSULTAS)],
)
def test_cada_consulta_devuelve_exactamente_las_claves_de_su_forma(
    tmp_db: Any, forma: type[Any], consulta: Callable[[], list[Any]]
) -> None:
    db_mod, _ = tmp_db
    _sembrar(db_mod)

    filas = consulta()

    assert filas, "la siembra no llegó a la consulta: el test no comprobaría nada"
    assert set(filas[0]) == forma.__required_keys__ | forma.__optional_keys__
