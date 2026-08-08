"""Tests para services/contract_events (derivación desde licitaciones_history)."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Fixtures y helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def upsert(db, lic_id="C-001", **kwargs):
    """Upsert con historial (mismo camino que la ingesta real)."""
    from db.upsert import Licitacion, upsert_licitaciones_with_history

    defaults = {
        "id_externo": lic_id,
        "titulo": "Mantenimiento SAP",
        "estado": "PUB",
        "importe": 100000.0,
        "fecha_publicacion": "2026-01-10",
    }
    defaults.update(kwargs)
    return upsert_licitaciones_with_history([Licitacion(**defaults)], source="test")


def eventos(db, lic_id="C-001"):
    from db.database import connect_read

    with connect_read() as c:
        return [
            dict(
                zip(
                    ("tipo", "campo", "valor_antes", "valor_despues", "importe_delta"),
                    r,
                    strict=False,
                )
            )
            for r in c.execute(
                "SELECT tipo, campo, valor_antes, valor_despues, importe_delta "
                "FROM contrato_eventos WHERE licitacion_id = %s ORDER BY id",
                (lic_id,),
            ).fetchall()
        ]


# ---------------------------------------------------------------------------
# Derivación de eventos por tipo de cambio
# ---------------------------------------------------------------------------


def test_cambio_estado_a_adj_genera_adjudicacion(db):
    from services.contract_events import derive_new_events

    upsert(db, estado="PUB")
    upsert(db, estado="ADJ")
    n = derive_new_events()

    assert n == 1
    evs = eventos(db)
    assert evs[0]["tipo"] == "adjudicacion"
    assert evs[0]["valor_antes"] == "PUB"
    assert evs[0]["valor_despues"] == "ADJ"


def test_cadena_estados_completa(db):
    from services.contract_events import derive_new_events

    upsert(db, estado="PUB")
    upsert(db, estado="ADJ")
    upsert(db, estado="RES")
    derive_new_events()

    tipos = [e["tipo"] for e in eventos(db)]
    assert tipos == ["adjudicacion", "formalizacion"]
    # El "después" del primer cambio sale del snapshot del segundo, no de la fila actual
    assert eventos(db)[0]["valor_despues"] == "ADJ"


def test_subida_de_importe_genera_modificacion_con_delta(db):
    from services.contract_events import derive_new_events

    upsert(db, importe=100000.0)
    upsert(db, importe=125000.0)
    derive_new_events()

    evs = eventos(db)
    assert evs[0]["tipo"] == "modificacion"
    assert evs[0]["importe_delta"] == 25000.0


def test_extension_fecha_fin_genera_prorroga(db):
    from services.contract_events import derive_new_events

    upsert(db, fecha_fin="2026-12-31")
    upsert(db, fecha_fin="2027-06-30")
    derive_new_events()

    evs = eventos(db)
    assert evs[0]["tipo"] == "prorroga"
    assert evs[0]["valor_despues"] == "2027-06-30"


def test_recorte_fecha_fin_es_modificacion(db):
    from services.contract_events import derive_new_events

    upsert(db, fecha_fin="2027-06-30")
    upsert(db, fecha_fin="2026-12-31")
    derive_new_events()

    assert eventos(db)[0]["tipo"] == "modificacion"


def test_anulacion(db):
    from services.contract_events import derive_new_events

    upsert(db, estado="PUB")
    upsert(db, estado="ANUL")
    derive_new_events()

    assert eventos(db)[0]["tipo"] == "anulacion"


def test_cambio_solo_titulo_no_genera_evento(db):
    from services.contract_events import derive_new_events

    upsert(db, titulo="Original")
    upsert(db, titulo="Corregido")
    assert derive_new_events() == 0
    assert eventos(db) == []


# ---------------------------------------------------------------------------
# Idempotencia y cursor
# ---------------------------------------------------------------------------


def test_derivacion_idempotente(db):
    from services.contract_events import derive_new_events

    upsert(db, estado="PUB")
    upsert(db, estado="ADJ")
    assert derive_new_events() == 1
    assert derive_new_events() == 0  # cursor avanzado, nada nuevo
    assert len(eventos(db)) == 1


def test_derive_all_procesa_en_lotes(db):
    from services.contract_events import derive_all_events

    for i in range(5):
        upsert(db, lic_id=f"C-{i:03d}", estado="PUB", importe=100000.0)
        upsert(db, lic_id=f"C-{i:03d}", estado="ADJ", importe=100000.0)

    total = derive_all_events(batch_size=2)
    assert total == 5


# ---------------------------------------------------------------------------
# Timeline y feed
# ---------------------------------------------------------------------------


def test_timeline_une_hitos_implicitos_y_eventos(db):
    from db.upsert import Adjudicacion, replace_adjudicaciones_batch
    from services.contract_events import derive_new_events, timeline

    upsert(db, estado="PUB", fecha_publicacion="2026-01-10")
    upsert(db, estado="ADJ")
    replace_adjudicaciones_batch(
        {
            "C-001": [
                Adjudicacion(
                    licitacion_id="C-001",
                    nombre="Ganadora SL",
                    importe_adjudicado=90000.0,
                    fecha_adjudicacion="2026-03-01",
                )
            ]
        }
    )
    derive_new_events()

    items = timeline("C-001")
    tipos = [i["tipo"] for i in items]
    assert tipos[0] == "publicacion"  # orden cronológico
    assert "adjudicacion" in tipos
    assert any("Ganadora SL" in (i.get("detalle") or "") for i in items)


def test_eventos_recientes_filtra_por_tipo(db):
    from services.contract_events import derive_new_events, eventos_recientes

    upsert(db, importe=100000.0, fecha_fin="2026-12-31")
    upsert(db, importe=150000.0, fecha_fin="2027-12-31")
    derive_new_events()

    todos = eventos_recientes(dias=365)
    prorrogas = eventos_recientes(tipos=("prorroga",), dias=365)
    assert len(todos) == 2
    assert len(prorrogas) == 1
    assert prorrogas[0]["tipo"] == "prorroga"
    assert prorrogas[0]["titulo"] == "Mantenimiento SAP"
