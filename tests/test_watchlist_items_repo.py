"""Tests del repositorio de watchlist_items (favoritos de licitaciones).

Cubre db/repositories/watchlist.py: list_items/add_item/remove_item y el
export/anonymize GDPR asociado. Ver tests/test_watchlist_rules.py para el
equivalente de reglas por criterio.
"""

from __future__ import annotations

import pytest

from db.repositories.watchlist import WatchlistRepository


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


@pytest.fixture()
def repo() -> WatchlistRepository:
    return WatchlistRepository()


def _seed_licitacion(lic_id: str = "L1", *, titulo="Implantación SAP", importe=100_000.0) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, importe, estado, fuente, "
            " fecha_publicacion, fecha_extraccion) "
            "VALUES (?, ?, ?, 'ABIERTO', 'placsp', '2026-01-01', CURRENT_TIMESTAMP)",
            (lic_id, titulo, importe),
        )


def test_add_and_list_roundtrip(db, repo):
    _seed_licitacion()
    item = repo.add_item("user-a", None, "L1")
    assert item["id_externo"] == "L1"

    items = repo.list_items("user-a")
    assert len(items) == 1
    assert items[0]["id_externo"] == "L1"
    assert items[0]["titulo"] == "Implantación SAP"
    assert items[0]["importe"] == 100_000.0
    assert items[0]["estado"] == "ABIERTO"
    assert items[0]["fecha_publicacion"] == "2026-01-01"


def test_add_item_is_idempotent(db, repo):
    _seed_licitacion()
    first = repo.add_item("user-a", None, "L1")
    second = repo.add_item("user-a", None, "L1")
    assert first["id"] == second["id"]
    assert len(repo.list_items("user-a")) == 1


def test_list_aislado_por_usuario(db, repo):
    _seed_licitacion("L1")
    _seed_licitacion("L2", titulo="Mantenimiento Oracle", importe=5_000.0)
    repo.add_item("user-a", None, "L1")
    repo.add_item("user-b", None, "L2")

    assert [it["id_externo"] for it in repo.list_items("user-a")] == ["L1"]
    assert [it["id_externo"] for it in repo.list_items("user-b")] == ["L2"]


def test_remove_item_solo_lo_propio(db, repo):
    _seed_licitacion()
    repo.add_item("user-a", None, "L1")

    assert repo.remove_item("user-b", "L1") is False
    assert len(repo.list_items("user-a")) == 1
    assert repo.remove_item("user-a", "L1") is True
    assert repo.list_items("user-a") == []


def test_remove_item_inexistente_devuelve_false(db, repo):
    assert repo.remove_item("user-a", "NOPE") is False


def test_export_items_by_user_key(db, repo):
    _seed_licitacion()
    repo.add_item("user-a", None, "L1")

    exported = repo.export_items_by_user_key("user-a")
    assert len(exported) == 1
    assert exported[0]["id_externo"] == "L1"
    assert repo.export_items_by_user_key("user-b") == []


def test_anonymize_items_by_user_key(db, repo):
    _seed_licitacion()
    repo.add_item("user-a", None, "L1")

    repo.anonymize_items_by_user_key("user-a")
    assert repo.list_items("user-a") == []
    assert repo.export_items_by_user_key("user-a") == []
