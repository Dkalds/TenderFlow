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


def _sembrar(lic_id: str, adjudicados: list[float], *, fuente: str = "placsp") -> None:
    from db.upsert import Adjudicacion, Licitacion, replace_adjudicaciones_batch
    from db.upsert import upsert_licitaciones as _upsert_licitaciones

    _upsert_licitaciones(
        [
            Licitacion(
                id_externo=lic_id,
                titulo=f"Expediente {lic_id}",
                importe=90_000.0,
                organo_contratacion="Ministerio X",
                cpv="72000000",
                fecha_publicacion="2025-05-01",
                analysis_universe="technology_observed",
                fuente=fuente,
            )
        ]
    )
    adjs = [
        Adjudicacion(
            licitacion_id=lic_id,
            nombre=f"Empresa {i} SL",
            nif=f"B0000000{i}",
            importe_adjudicado=importe,
            fecha_adjudicacion="2025-06-01",
        )
        for i, importe in enumerate(adjudicados)
    ]
    _total, _dropped, failed = replace_adjudicaciones_batch({lic_id: adjs})
    assert failed == 0


def test_load_history_excluye_duplicados_confirmados(db):
    """Un contrato llegado por dos fuentes no pesa doble en la cohorte de bajas."""
    from db.database import connect, now_utc_iso
    from db.repositories.pricing import PricingRepository

    _sembrar("PRICE-CANON", [80_000.0])
    _sembrar("PRICE-DUP", [80_000.0])
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, confianza, "
            "status, detectado_en) VALUES ('PRICE-DUP', 'PRICE-CANON', 1.0, 'confirmed', %s)",
            (now_utc_iso(),),
        )

    ids = {r["licitacion_id"] for r in PricingRepository().load_history()}
    assert "PRICE-CANON" in ids
    assert "PRICE-DUP" not in ids


def test_load_history_excluye_ted(db):
    """TED no publica presupuesto base: su baja sale inflada o 0 por construcción."""
    from db.repositories.pricing import PricingRepository

    _sembrar("ted:PRICE-1", [80_000.0], fuente="ted")

    ids = {r["licitacion_id"] for r in PricingRepository().load_history()}
    assert "ted:PRICE-1" not in ids


def test_load_history_una_fila_por_expediente_sin_lote(db):
    """Tres adjudicaciones sin lote del mismo expediente son UN precio, no tres bajas.

    Fila a fila, cada tercio del presupuesto se leía como una baja del 67 %.
    """
    from db.repositories.pricing import PricingRepository

    _sembrar("PRICE-MULTI", [29_000.0, 29_000.0, 29_000.0])

    rows = [r for r in PricingRepository().load_history() if r["licitacion_id"] == "PRICE-MULTI"]
    assert len(rows) == 1
    assert rows[0]["importe_adjudicado"] == pytest.approx(87_000.0)
    assert rows[0]["importe_licitacion"] == pytest.approx(90_000.0)
