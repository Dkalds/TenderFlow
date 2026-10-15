"""``expediente_completo`` contra Postgres (lee por ``DATABASE_URL``, no por el rol del MCP)."""

from __future__ import annotations

from typing import Any

import pytest

from db.repositories.tender_fact_sheets import TenderFactSheetsRepository
from db.upsert import (
    Adjudicacion,
    CondicionesCodice,
    CriterioAdjudicacion,
    GarantiaExigida,
    Licitacion,
    Lote,
    RequisitoSolvencia,
    replace_adjudicaciones,
    replace_lotes,
    upsert_licitaciones,
)
from services.expediente import expediente_completo

ID = "EXP-FICHA-1"


@pytest.fixture()
def licitacion_con_lote_y_adjudicacion(tmp_db: Any) -> str:
    """Expediente con un lote, una adjudicación, condiciones, ficha de pliego y una canónica."""
    db_mod, _ = tmp_db
    upsert_licitaciones(
        [
            Licitacion(
                id_externo=ID,
                titulo="Soporte SAP S/4HANA",
                descripcion="Mantenimiento evolutivo",
                organo_contratacion="Consejería de Hacienda",
                importe=640_000.0,
                estado="ADJ",
                ccaa="Madrid",
                fecha_publicacion="2026-03-01",
                tecnologia="SAP",
                condiciones=CondicionesCodice(
                    criterios=[
                        CriterioAdjudicacion(
                            orden=1, descripcion="Oferta económica", peso=60.0, peso_pct=60.0
                        )
                    ],
                    garantias=[GarantiaExigida(orden=1, tipo_codigo="2", porcentaje=5.0)],
                    solvencia=[
                        RequisitoSolvencia(
                            orden=1, clase="economica", descripcion="Volumen anual de negocios"
                        )
                    ],
                ),
            ),
            Licitacion(id_externo="EXP-ORIGINAL", titulo="Anuncio original", tecnologia="SAP"),
        ]
    )
    mapa = replace_lotes(ID, [Lote(licitacion_id=ID, numero="1", titulo="Lote uno", importe=1.0)])
    replace_adjudicaciones(
        ID,
        [
            Adjudicacion(
                licitacion_id=ID,
                nombre="ALFA CONSULTORÍA SA",
                nif="A10000001",
                importe_adjudicado=500_000.0,
                lote_id=mapa["1"],
            )
        ],
    )
    TenderFactSheetsRepository().upsert(
        licitacion_id=ID,
        status="extracted",
        extraction_version="t",
        model=None,
        facts={"plazo": "24 meses"},
        field_count=1,
        evidence_count=0,
    )
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, confianza, "
            "status, detectado_en) VALUES (%s, 'EXP-ORIGINAL', 1.0, 'confirmed', "
            "CURRENT_TIMESTAMP)",
            (ID,),
        )
    return ID


def test_expediente_completo_inexistente_es_none(tmp_db: Any) -> None:
    assert expediente_completo("NO-EXISTE") is None


def test_expediente_completo_trae_lotes_y_adjudicaciones(
    licitacion_con_lote_y_adjudicacion: str,
) -> None:
    exp = expediente_completo(licitacion_con_lote_y_adjudicacion)
    assert exp is not None
    assert set(exp) == {
        "licitacion",
        "canonica",
        "lotes",
        "adjudicaciones",
        "criterios",
        "solvencia",
        "garantias",
        "ficha_pliego",
    }
    assert exp["licitacion"]["titulo"] == "Soporte SAP S/4HANA"
    assert "search_vector" not in exp["licitacion"]
    assert exp["canonica"] == "EXP-ORIGINAL"
    assert [lote["numero"] for lote in exp["lotes"]] == ["1"]
    assert [a["nombre"] for a in exp["adjudicaciones"]] == ["ALFA CONSULTORÍA SA"]
    assert exp["adjudicaciones"][0]["lote_numero"] == "1"
    assert [c["descripcion"] for c in exp["criterios"]] == ["Oferta económica"]
    assert [s["clase"] for s in exp["solvencia"]] == ["economica"]
    assert len(exp["garantias"]) == 1
    assert exp["ficha_pliego"]["facts"] == {"plazo": "24 meses"}


def test_expediente_sin_extras_devuelve_vacios_no_claves_ausentes(tmp_db: Any) -> None:
    upsert_licitaciones([Licitacion(id_externo="SOLO", titulo="Solo anuncio")])
    exp = expediente_completo("SOLO")
    assert exp is not None
    assert exp["canonica"] is None
    assert exp["ficha_pliego"] is None
    assert exp["lotes"] == exp["adjudicaciones"] == exp["criterios"] == []
    assert exp["solvencia"] == exp["garantias"] == []
