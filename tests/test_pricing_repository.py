"""Tests para db/repositories/pricing.py — presupuesto efectivo por lote."""

from __future__ import annotations

import pytest


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def test_load_history_uses_lote_budget_when_present(db):
    """Regresión: antes de v65_lotes, importe_licitacion era siempre el del
    expediente completo, así que un lote cuyo adjudicado superaba ese total
    (aritméticamente posible si el lote es una fracción del expediente) se
    descartaba como outlier en vez de compararse contra su propio presupuesto."""
    from db.repositories.pricing import PricingRepository
    from db.upsert import (
        Adjudicacion,
        Licitacion,
        Lote,
        replace_adjudicaciones_batch,
        replace_lotes,
    )
    from db.upsert import upsert_licitaciones as _upsert_licitaciones

    lic_id = "PRICE-LOTE-001"
    _upsert_licitaciones(
        [
            Licitacion(
                id_externo=lic_id,
                titulo="Expediente con lote",
                importe=100_000.0,
                organo_contratacion="Ministerio X",
                cpv="72000000",
                fecha_publicacion="2025-05-01",
                analysis_universe="technology_observed",
            )
        ]
    )
    lote_ids = replace_lotes(lic_id, [Lote(licitacion_id=lic_id, numero="1", importe=20_000.0)])
    adj = Adjudicacion(
        licitacion_id=lic_id,
        nombre="Empresa Lote SL",
        importe_adjudicado=18_000.0,
        fecha_adjudicacion="2025-06-01",
        lote_id=lote_ids["1"],
    )
    _total, _dropped, failed = replace_adjudicaciones_batch({lic_id: [adj]})
    assert failed == 0

    rows = PricingRepository().load_history()
    row = next(r for r in rows if r["licitacion_id"] == lic_id)
    assert row["importe_licitacion"] == pytest.approx(20_000.0)
    assert row["importe_adjudicado"] == pytest.approx(18_000.0)


def test_load_history_falls_back_to_expediente_budget_without_lote(db):
    from db.repositories.pricing import PricingRepository
    from db.upsert import Adjudicacion, Licitacion, replace_adjudicaciones_batch
    from db.upsert import upsert_licitaciones as _upsert_licitaciones

    lic_id = "PRICE-NOLOTE-001"
    _upsert_licitaciones(
        [
            Licitacion(
                id_externo=lic_id,
                titulo="Expediente sin lotes",
                importe=50_000.0,
                organo_contratacion="Ministerio X",
                cpv="72000000",
                fecha_publicacion="2025-05-01",
                analysis_universe="technology_observed",
            )
        ]
    )
    adj = Adjudicacion(
        licitacion_id=lic_id,
        nombre="Empresa Sin Lote SL",
        importe_adjudicado=40_000.0,
        fecha_adjudicacion="2025-06-01",
    )
    _total, _dropped, failed = replace_adjudicaciones_batch({lic_id: [adj]})
    assert failed == 0

    rows = PricingRepository().load_history()
    row = next(r for r in rows if r["licitacion_id"] == lic_id)
    assert row["importe_licitacion"] == pytest.approx(50_000.0)
