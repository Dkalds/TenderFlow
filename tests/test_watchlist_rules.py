"""Tests del CRUD de reglas de watchlist por criterio (services/watchlist_rules).

Cubre persistencia server-side, aislamiento por usuario y toggle activo/pausado.
El matching y el job de alertas se testean en increments posteriores.
"""

from __future__ import annotations

import pytest

from services.watchlist_rules import (
    WatchlistRule,
    create_rule,
    delete_rule,
    list_rules,
    set_active,
    update_rule,
)


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def test_create_and_list_roundtrip(db):
    rid = create_rule("user-a", WatchlistRule(nombre="SAP Madrid", keyword="SAP", ccaa="Madrid"))
    assert rid > 0

    rules = list_rules("user-a")
    assert len(rules) == 1
    assert rules[0].id == rid
    assert rules[0].nombre == "SAP Madrid"
    assert rules[0].keyword == "SAP"
    assert rules[0].ccaa == "Madrid"
    assert rules[0].frequency == "daily"  # default
    assert rules[0].active is True


def test_list_aislado_por_usuario(db):
    create_rule("user-a", WatchlistRule(keyword="SAP"))
    create_rule("user-b", WatchlistRule(keyword="Oracle"))

    assert [r.keyword for r in list_rules("user-a")] == ["SAP"]
    assert [r.keyword for r in list_rules("user-b")] == ["Oracle"]


def test_update_modifica_campos(db):
    rid = create_rule("user-a", WatchlistRule(keyword="SAP", min_importe=1000.0))
    ok = update_rule(
        "user-a",
        rid,
        WatchlistRule(
            keyword="SAP S/4HANA",
            cpv="72000000",
            min_importe=5000.0,
            frequency="weekly",
        ),
    )
    assert ok is True

    rule = list_rules("user-a")[0]
    assert rule.keyword == "SAP S/4HANA"
    assert rule.cpv == "72000000"
    assert rule.min_importe == pytest.approx(5000.0)
    assert rule.frequency == "weekly"


def test_update_de_otro_usuario_no_aplica(db):
    rid = create_rule("user-a", WatchlistRule(keyword="SAP"))
    ok = update_rule("user-b", rid, WatchlistRule(keyword="HACKED"))
    assert ok is False
    assert list_rules("user-a")[0].keyword == "SAP"


def test_set_active_pausa_y_reactiva(db):
    rid = create_rule("user-a", WatchlistRule(keyword="SAP"))
    assert set_active("user-a", rid, active=False) is True
    assert list_rules("user-a")[0].active is False
    assert set_active("user-a", rid, active=True) is True
    assert list_rules("user-a")[0].active is True


def test_delete_remueve_solo_la_propia(db):
    rid = create_rule("user-a", WatchlistRule(keyword="SAP"))
    assert delete_rule("user-b", rid) is False  # no es del user-b
    assert len(list_rules("user-a")) == 1
    assert delete_rule("user-a", rid) is True
    assert list_rules("user-a") == []
