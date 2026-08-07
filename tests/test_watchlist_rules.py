"""Tests del CRUD de reglas de watchlist por criterio (services/watchlist_rules).

Cubre persistencia server-side, aislamiento por usuario y toggle activo/pausado.
El matching y el job de alertas se testean en increments posteriores.
"""

from __future__ import annotations

import pytest

from services.watchlist_rules import (
    WatchlistRule,
    count_matches,
    create_rule,
    delete_rule,
    list_matches,
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


# ── matching sobre el dataset ─────────────────────────────────────────────────


def _insert_lic(c, lic_id, *, titulo="Lic", descripcion=None, cpv=None, importe=None, ccaa=None):
    c.execute(
        "INSERT INTO licitaciones "
        "(id_externo, titulo, descripcion, cpv, importe, ccaa, fuente, "
        " fecha_publicacion, fecha_extraccion) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'placsp', '2026-01-01', CURRENT_TIMESTAMP)",
        (lic_id, titulo, descripcion, cpv, importe, ccaa),
    )


def _seed_licitaciones():
    from db.database import connect

    with connect() as c:
        _insert_lic(
            c,
            "L1",
            titulo="Implantación SAP S/4HANA",
            cpv="72000000",
            importe=100_000.0,
            ccaa="Madrid",
        )
        _insert_lic(
            c,
            "L2",
            titulo="Mantenimiento Oracle",
            cpv="72500000",
            importe=5_000.0,
            ccaa="Madrid",
        )
        _insert_lic(
            c,
            "L3",
            titulo="Obras varias",
            descripcion="incluye módulo SAP",
            cpv="45000000",
            importe=2_000_000.0,
            ccaa="Cataluña",
        )


def test_match_keyword_busca_titulo_y_descripcion(db):
    _seed_licitaciones()
    # "SAP" está en el título de L1 y en la descripción de L3.
    assert count_matches(WatchlistRule(keyword="SAP")) == 2


def test_match_aplica_cpv(db):
    _seed_licitaciones()
    # CPV deja de ser control muerto: prefijo "72" → L1 y L2 (no L3 con 45).
    assert count_matches(WatchlistRule(cpv="72")) == 2
    assert count_matches(WatchlistRule(cpv="45")) == 1


def test_match_aplica_min_importe(db):
    _seed_licitaciones()
    # min_importe no se pierde tras un top-20 cliente: 50k deja fuera a L2 (5k).
    assert count_matches(WatchlistRule(min_importe=50_000.0)) == 2


def test_match_aplica_ccaa(db):
    _seed_licitaciones()
    assert count_matches(WatchlistRule(ccaa="Cataluña")) == 1


def test_match_combina_todos_los_filtros(db):
    _seed_licitaciones()
    # keyword SAP + cpv 72 → solo L1 (L3 tiene SAP pero cpv 45).
    assert count_matches(WatchlistRule(keyword="SAP", cpv="72")) == 1


def test_list_matches_devuelve_campos(db):
    _seed_licitaciones()
    rows = list_matches(WatchlistRule(cpv="72"))
    assert {r["id_externo"] for r in rows} == {"L1", "L2"}
    assert "titulo" in rows[0]
    assert "importe" in rows[0]
