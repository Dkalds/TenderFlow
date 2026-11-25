"""v191: identidad normalizada de cada adjudicación y su uso en el healthcheck.

Lo que se fija: la migración encadena con ``v190`` y añade dos columnas
anulables; el upsert las escribe con ``shared.normalization``; el backfill
rellena las que faltan y es idempotente; y el recuento «en revisión» del
healthcheck da lo mismo con las filas normalizadas (SQL) que sin normalizar
(Python).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from db.database import connect

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v191_adj_identidad_normalizada.py"
)


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v191_adj_identidad_normalizada", _RUTA)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_encadena_con_v190_y_anade_dos_columnas_anulables() -> None:
    modulo = _cargar()
    assert modulo.down_revision == "v190_mv_empresas_agregados"
    with patch.object(modulo, "op") as op_falso:
        op_falso.get_bind.return_value.dialect.name = "postgresql"
        modulo.upgrade()
    columnas = {c.args[1].name: c.args[1] for c in op_falso.add_column.call_args_list}
    assert set(columnas) == {"nombre_normalizado", "nif_normalizado"}
    assert all(c.nullable for c in columnas.values())


def _sembrar(nombre: str, nif: str | None) -> None:
    from db.upsert import (
        Adjudicacion,
        Licitacion,
        replace_adjudicaciones_batch,
        upsert_licitaciones,
    )

    lic_id = f"NORM-{nombre[:6]}"
    upsert_licitaciones([Licitacion(id_externo=lic_id, titulo="Contrato")])
    _, _, fallidas = replace_adjudicaciones_batch(
        {lic_id: [Adjudicacion(licitacion_id=lic_id, nombre=nombre, nif=nif)]}
    )
    assert fallidas == 0


@pytest.mark.usefixtures("tmp_db")
def test_el_upsert_escribe_la_identidad_normalizada() -> None:
    _sembrar("Acme Soluciones, S.L.", "b-1234567-4")

    with connect() as c:
        fila = c.execute(
            "SELECT nombre_normalizado, nif_normalizado FROM adjudicaciones"
        ).fetchone()

    from shared.normalization import normalize_company, normalize_nif

    assert tuple(fila) == (
        normalize_company("Acme Soluciones, S.L."),
        normalize_nif("b-1234567-4"),
    )


def _en_revision() -> int:
    """El recuento del healthcheck: SQL para lo normalizado, Python para el resto."""
    from scheduler.healthcheck import run_check

    resolucion = run_check()["info"]["empresa_resolution"]
    assert isinstance(resolucion, dict)
    return int(resolucion["en_revision"])


@pytest.mark.usefixtures("tmp_db")
def test_el_recuento_en_revision_no_cambia_con_el_backfill() -> None:
    from scripts.backfill_adj_normalizado import rellenar
    from shared.normalization import normalize_company

    _sembrar("Revisada Consultores SA", None)
    _sembrar("Otra Empresa SL", "B12345674")
    with connect() as c:
        c.execute(
            "INSERT INTO empresa_review_queue (alias_normalizado, nif, nombre_original, "
            "score, status, created_at) VALUES (%s, NULL, 'Revisada Consultores SA', 0.8, "
            "'pending', now()::text)",
            (normalize_company("Revisada Consultores SA"),),
        )
    normalizadas = _en_revision()

    # Como estaban antes de v191: sin identidad normalizada.
    with connect() as c:
        c.execute("UPDATE adjudicaciones SET nombre_normalizado = NULL, nif_normalizado = NULL")
    sin_normalizar = _en_revision()

    assert rellenar(lote=1) == 2
    assert rellenar() == 0  # idempotente
    assert normalizadas == sin_normalizar == _en_revision() == 1
