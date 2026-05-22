"""Tests para db/upsert.py — upsert idempotente, historial y FTS."""

from __future__ import annotations

import json

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    """Devuelve el módulo db tras inicializar la BD."""
    db_mod, _ = tmp_db
    return db_mod


# ---------------------------------------------------------------------------
# upsert_licitaciones
# ---------------------------------------------------------------------------


def make_licitacion(**kwargs):
    from db.upsert import Licitacion

    defaults = {
        "id_externo": "TEST-001",
        "titulo": "Sistema ERP SAP",
        "descripcion": "Implantación SAP S/4HANA",
        "organo_contratacion": "Ministerio de Hacienda",
        "importe": 500000.0,
        "estado": "PUB",
        "fecha_publicacion": "2024-01-15",
        "tecnologia": "SAP",
        "ccaa": "Madrid",
    }
    defaults.update(kwargs)
    return Licitacion(**defaults)


def test_upsert_inserts_new(db):
    from db.upsert import upsert_licitaciones

    lic = make_licitacion()
    nuevas, actualizadas = upsert_licitaciones([lic])
    assert nuevas == 1
    assert actualizadas == 0


def test_upsert_idempotent(db):
    """Segunda inserción del mismo ID actualiza, no duplica."""
    from db.upsert import upsert_licitaciones

    lic = make_licitacion()
    upsert_licitaciones([lic])
    nuevas, actualizadas = upsert_licitaciones([lic])
    assert nuevas == 0
    assert actualizadas == 1


def test_upsert_updates_field(db):
    """Un upsert actualiza un campo existente."""
    from db.database import connect
    from db.upsert import upsert_licitaciones

    lic = make_licitacion(importe=100.0)
    upsert_licitaciones([lic])

    lic2 = make_licitacion(importe=200.0)
    upsert_licitaciones([lic2])

    with connect() as c:
        row = c.execute(
            "SELECT importe FROM licitaciones WHERE id_externo = ?", ["TEST-001"]
        ).fetchone()
    assert row[0] == pytest.approx(200.0)


def test_upsert_empty_list(db):
    from db.upsert import upsert_licitaciones

    nuevas, actualizadas = upsert_licitaciones([])
    assert nuevas == 0
    assert actualizadas == 0


def test_upsert_multiple_items(db):
    from db.upsert import upsert_licitaciones

    lics = [make_licitacion(id_externo=f"TEST-{i:03d}", titulo=f"Título {i}") for i in range(5)]
    nuevas, actualizadas = upsert_licitaciones(lics)
    assert nuevas == 5
    assert actualizadas == 0


def test_upsert_chunked_large_batch(db):
    """Batches > 500 items se procesan en chunks sin error."""
    from db.upsert import upsert_licitaciones

    lics = [make_licitacion(id_externo=f"BULK-{i:04d}", titulo=f"Lic {i}") for i in range(600)]
    nuevas, _actualizadas = upsert_licitaciones(lics)
    assert nuevas == 600


def test_count_licitaciones(db):
    from db.upsert import count_licitaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion(), make_licitacion(id_externo="TEST-002", titulo="Otro")])
    assert count_licitaciones() >= 2


# ---------------------------------------------------------------------------
# replace_adjudicaciones
# ---------------------------------------------------------------------------


def test_replace_adjudicaciones_inserts(db):
    from db.upsert import Adjudicacion, replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion()])
    adj = Adjudicacion(licitacion_id="TEST-001", nombre="Empresa SA", nif="B12345678")
    n = replace_adjudicaciones("TEST-001", [adj])
    assert n == 1


def test_replace_adjudicaciones_replaces(db):
    """Segunda llamada elimina las anteriores e inserta las nuevas."""
    from db.database import connect
    from db.upsert import Adjudicacion, replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion()])
    adj1 = Adjudicacion(licitacion_id="TEST-001", nombre="Empresa A")
    replace_adjudicaciones("TEST-001", [adj1])

    adj2 = Adjudicacion(licitacion_id="TEST-001", nombre="Empresa B")
    replace_adjudicaciones("TEST-001", [adj2])

    with connect() as c:
        rows = c.execute(
            "SELECT nombre FROM adjudicaciones WHERE licitacion_id = ?", ["TEST-001"]
        ).fetchall()
    names = [r[0] for r in rows]
    assert "Empresa B" in names
    assert "Empresa A" not in names


def test_replace_adjudicaciones_empty_clears(db):
    from db.database import connect
    from db.upsert import Adjudicacion, replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion()])
    replace_adjudicaciones("TEST-001", [Adjudicacion(licitacion_id="TEST-001", nombre="X")])
    replace_adjudicaciones("TEST-001", [])

    with connect() as c:
        count = c.execute(
            "SELECT COUNT(*) FROM adjudicaciones WHERE licitacion_id = ?", ["TEST-001"]
        ).fetchone()[0]
    assert count == 0


# ---------------------------------------------------------------------------
# upsert_licitaciones_with_history
# ---------------------------------------------------------------------------


def test_upsert_with_history_inserts(db):
    from db.upsert import upsert_licitaciones_with_history

    lic = make_licitacion()
    result = upsert_licitaciones_with_history([lic], source="test")
    assert lic.id_externo in result.inserted
    assert result.nuevas == 1


def test_upsert_with_history_tracks_changes(db):
    """Cambiar un campo rastreado genera entrada en licitaciones_history."""
    from db.database import connect
    from db.upsert import upsert_licitaciones_with_history

    lic = make_licitacion(importe=100.0)
    upsert_licitaciones_with_history([lic], source="initial")

    lic2 = make_licitacion(importe=999.0)
    result = upsert_licitaciones_with_history([lic2], source="update")
    assert lic2.id_externo in result.modified

    with connect() as c:
        rows = c.execute(
            "SELECT snapshot_json, changed_fields FROM licitaciones_history WHERE id_externo = ?",
            ["TEST-001"],
        ).fetchall()
    assert len(rows) == 1
    snapshot = json.loads(rows[0][0])
    assert snapshot["importe"] == pytest.approx(100.0)


def test_upsert_with_history_unchanged(db):
    """Re-insertar sin cambios marca como unchanged."""
    from db.upsert import upsert_licitaciones_with_history

    lic = make_licitacion()
    upsert_licitaciones_with_history([lic], source="a")
    result = upsert_licitaciones_with_history([lic], source="b")
    assert lic.id_externo in result.unchanged


def test_upsert_result_properties(db):
    from db.upsert import upsert_licitaciones_with_history

    lics = [make_licitacion(id_externo=f"H-{i}", titulo=f"T{i}") for i in range(3)]
    result = upsert_licitaciones_with_history(lics, source="test")
    assert result.nuevas == 3
    assert result.actualizadas == 0


# ---------------------------------------------------------------------------
# cursor helpers
# ---------------------------------------------------------------------------


def test_set_and_get_cursor(db):
    from db.upsert import get_cursor, set_cursor

    set_cursor("test_source", last_seen_updated="2024-01-01T00:00:00Z", etag="abc123")
    cursor = get_cursor("test_source")
    assert cursor is not None
    assert cursor["source"] == "test_source"
    assert cursor["etag"] == "abc123"
    assert cursor["last_seen_updated"] == "2024-01-01T00:00:00Z"


def test_get_cursor_nonexistent(db):
    from db.upsert import get_cursor

    assert get_cursor("nonexistent_source") is None


def test_set_cursor_upserts(db):
    """Llamar a set_cursor dos veces actualiza en lugar de insertar duplicado."""
    from db.upsert import get_cursor, set_cursor

    set_cursor("src", etag="v1")
    set_cursor("src", etag="v2")
    cursor = get_cursor("src")
    assert cursor["etag"] == "v2"


# ---------------------------------------------------------------------------
# log_extraccion
# ---------------------------------------------------------------------------


def test_log_extraccion(db):
    from db.database import connect
    from db.upsert import log_extraccion

    log_extraccion("test_fuente", nuevas=5, actualizadas=3, total=8, notas="ok")
    with connect() as c:
        row = c.execute(
            "SELECT fuente, nuevas, actualizadas FROM extracciones WHERE fuente = ?",
            ["test_fuente"],
        ).fetchone()
    assert row is not None
    assert row[1] == 5
    assert row[2] == 3


# ---------------------------------------------------------------------------
# FTS
# ---------------------------------------------------------------------------


def test_fts_available(db):
    from db.upsert import fts_available

    # FTS puede o no estar disponible según las migraciones del tmp_db
    result = fts_available()
    assert isinstance(result, bool)


def test_search_fts_empty_query(db):
    from db.upsert import search_fts

    rows, total = search_fts("")
    assert rows == []
    assert total == 0


def test_get_history_empty(db):
    from db.upsert import get_history, upsert_licitaciones

    upsert_licitaciones([make_licitacion()])
    history = get_history("TEST-001")
    assert isinstance(history, list)
    # Sin cambios registrados, historial vacío
    assert len(history) == 0


def test_get_history_with_changes(db):
    from db.upsert import get_history, upsert_licitaciones_with_history

    lic1 = make_licitacion(importe=1.0)
    lic2 = make_licitacion(importe=2.0)
    upsert_licitaciones_with_history([lic1], source="src")
    upsert_licitaciones_with_history([lic2], source="src")

    history = get_history("TEST-001")
    assert len(history) == 1
    assert "snapshot_json" in history[0]
