"""Tests para db/database.py — idempotencia del upsert y persistencia."""

from __future__ import annotations

import pytest

from db.database import (
    Adjudicacion,
    Licitacion,
)


@pytest.fixture()
def tmp_db(monkeypatch, tmp_path):
    """BD SQLite en directorio temporal; limpia entre tests."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("TURSO_DATABASE_URL", "")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "")

    # Recargar config con los nuevos env vars
    import importlib
    import sys

    importlib.import_module("config.settings")
    importlib.reload(sys.modules["config.settings"])
    import config as cfg

    importlib.reload(cfg)
    import db.database as db_mod

    importlib.reload(db_mod)

    db_mod.init_db()
    return db_mod, tmp_path


def _make_lic(id_externo: str = "TEST-001", titulo: str = "Test SAP") -> Licitacion:
    return Licitacion(id_externo=id_externo, titulo=titulo)


def _make_adj(lic_id: str = "TEST-001", nombre: str = "Empresa SA") -> Adjudicacion:
    return Adjudicacion(licitacion_id=lic_id, nombre=nombre, importe_adjudicado=50000.0)


class TestUpsertLicitaciones:
    def test_inserta_nueva(self, tmp_db):
        db_mod, _ = tmp_db
        nuevas, actualizadas = db_mod.upsert_licitaciones([_make_lic()])
        assert nuevas == 1
        assert actualizadas == 0

    def test_idempotente_segunda_vez(self, tmp_db):
        db_mod, _ = tmp_db
        db_mod.upsert_licitaciones([_make_lic()])
        nuevas, actualizadas = db_mod.upsert_licitaciones([_make_lic()])
        assert nuevas == 0
        assert actualizadas == 1

    def test_actualiza_titulo(self, tmp_db):
        db_mod, _ = tmp_db
        db_mod.upsert_licitaciones([_make_lic("ID-1", "Título original")])
        db_mod.upsert_licitaciones([_make_lic("ID-1", "Título actualizado")])
        with db_mod.connect() as c:
            row = c.execute(
                "SELECT titulo FROM licitaciones WHERE id_externo = ?", ["ID-1"]
            ).fetchone()
        assert row[0] == "Título actualizado"

    def test_lista_vacia_no_falla(self, tmp_db):
        db_mod, _ = tmp_db
        nuevas, actualizadas = db_mod.upsert_licitaciones([])
        assert nuevas == 0
        assert actualizadas == 0

    def test_multiples_licitaciones(self, tmp_db):
        db_mod, _ = tmp_db
        lics = [_make_lic(f"ID-{i}") for i in range(5)]
        nuevas, actualizadas = db_mod.upsert_licitaciones(lics)
        assert nuevas == 5
        assert actualizadas == 0


class TestReplaceAdjudicaciones:
    def test_inserta_adjudicacion(self, tmp_db):
        db_mod, _ = tmp_db
        db_mod.upsert_licitaciones([_make_lic()])
        n = db_mod.replace_adjudicaciones("TEST-001", [_make_adj()])
        assert n == 1

    def test_reemplaza_adjudicaciones_existentes(self, tmp_db):
        db_mod, _ = tmp_db
        db_mod.upsert_licitaciones([_make_lic()])
        db_mod.replace_adjudicaciones("TEST-001", [_make_adj(nombre="Empresa A")])
        n = db_mod.replace_adjudicaciones(
            "TEST-001", [_make_adj(nombre="Empresa B"), _make_adj(nombre="Empresa C")]
        )
        assert n == 2
        with db_mod.connect() as c:
            count = c.execute(
                "SELECT COUNT(*) FROM adjudicaciones WHERE licitacion_id = ?",
                ["TEST-001"],
            ).fetchone()[0]
        assert count == 2

    def test_idempotente(self, tmp_db):
        db_mod, _ = tmp_db
        db_mod.upsert_licitaciones([_make_lic()])
        adjs = [_make_adj()]
        db_mod.replace_adjudicaciones("TEST-001", adjs)
        db_mod.replace_adjudicaciones("TEST-001", adjs)
        with db_mod.connect() as c:
            count = c.execute(
                "SELECT COUNT(*) FROM adjudicaciones WHERE licitacion_id = ?",
                ["TEST-001"],
            ).fetchone()[0]
        assert count == 1

    def test_lista_vacia_elimina_adjudicaciones(self, tmp_db):
        db_mod, _ = tmp_db
        db_mod.upsert_licitaciones([_make_lic()])
        db_mod.replace_adjudicaciones("TEST-001", [_make_adj()])
        db_mod.replace_adjudicaciones("TEST-001", [])
        with db_mod.connect() as c:
            count = c.execute(
                "SELECT COUNT(*) FROM adjudicaciones WHERE licitacion_id = ?",
                ["TEST-001"],
            ).fetchone()[0]
        assert count == 0


# ─── Cursor helpers ──────────────────────────────────────────────────────────


class TestCursorHelpers:
    def test_get_cursor_returns_none_initially(self, tmp_db):
        db_mod, _ = tmp_db
        assert db_mod.get_cursor("test_source") is None

    def test_set_and_get_cursor(self, tmp_db):
        db_mod, _ = tmp_db
        db_mod.set_cursor(
            "test_source",
            last_seen_updated="2026-05-01T10:00:00Z",
            etag='"abc"',
        )
        cursor = db_mod.get_cursor("test_source")
        assert cursor is not None
        assert cursor["source"] == "test_source"
        assert cursor["last_seen_updated"] == "2026-05-01T10:00:00Z"
        assert cursor["etag"] == '"abc"'

    def test_set_cursor_upserts(self, tmp_db):
        db_mod, _ = tmp_db
        db_mod.set_cursor("src", last_seen_updated="2026-01-01T00:00:00Z")
        db_mod.set_cursor("src", last_seen_updated="2026-05-01T00:00:00Z")
        cursor = db_mod.get_cursor("src")
        assert cursor["last_seen_updated"] == "2026-05-01T00:00:00Z"


# ─── Upsert with history ────────────────────────────────────────────────────


class TestUpsertWithHistory:
    def test_insert_new_no_history(self, tmp_db):
        db_mod, _ = tmp_db
        result = db_mod.upsert_licitaciones_with_history([_make_lic("NEW-001")], source="test")
        assert result.nuevas == 1
        assert result.modified == []
        assert result.unchanged == []
        history = db_mod.get_history("NEW-001")
        assert len(history) == 0

    def test_same_data_no_history(self, tmp_db):
        db_mod, _ = tmp_db
        lic = _make_lic("SAME-001", "Titulo SAP")
        db_mod.upsert_licitaciones([lic])
        result = db_mod.upsert_licitaciones_with_history([lic], source="test")
        assert result.inserted == []
        assert result.modified == []
        assert result.unchanged == ["SAME-001"]
        assert len(db_mod.get_history("SAME-001")) == 0

    def test_changed_importe_creates_history(self, tmp_db):
        db_mod, _ = tmp_db
        lic1 = _make_lic("CHG-001")
        lic1.importe = 50000.0
        db_mod.upsert_licitaciones([lic1])

        lic2 = _make_lic("CHG-001")
        lic2.importe = 80000.0
        result = db_mod.upsert_licitaciones_with_history([lic2], source="daily")

        assert result.modified == ["CHG-001"]
        history = db_mod.get_history("CHG-001")
        assert len(history) == 1
        assert "importe" in history[0]["changed_fields"]
        assert history[0]["source"] == "daily"

    def test_changed_estado_creates_history(self, tmp_db):
        db_mod, _ = tmp_db
        lic1 = _make_lic("EST-001")
        lic1.estado = "EN PLAZO"
        db_mod.upsert_licitaciones([lic1])

        lic2 = _make_lic("EST-001")
        lic2.estado = "ADJUDICADA"
        result = db_mod.upsert_licitaciones_with_history([lic2], source="daily")

        assert result.modified == ["EST-001"]
        history = db_mod.get_history("EST-001")
        assert len(history) == 1
        assert "estado" in history[0]["changed_fields"]

    def test_multiple_changes_tracked(self, tmp_db):
        db_mod, _ = tmp_db
        lic1 = _make_lic("MULTI-001")
        lic1.importe = 10000.0
        lic1.estado = "EN PLAZO"
        db_mod.upsert_licitaciones([lic1])

        lic2 = _make_lic("MULTI-001")
        lic2.importe = 20000.0
        lic2.estado = "ADJUDICADA"
        db_mod.upsert_licitaciones_with_history([lic2], source="daily")

        history = db_mod.get_history("MULTI-001")
        assert len(history) == 1
        changed = history[0]["changed_fields"].split(",")
        assert "importe" in changed
        assert "estado" in changed

    def test_get_history_empty(self, tmp_db):
        db_mod, _ = tmp_db
        assert db_mod.get_history("NONEXISTENT") == []
