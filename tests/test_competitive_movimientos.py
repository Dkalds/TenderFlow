"""Competidores — filtros de ámbito en bajas y señales de la watchlist (RFC #1, #4).

- ``bajas_agregadas`` honra fechas de adjudicación, presupuesto mínimo y varias
  CCAA, con la misma semántica que el resto de la página de Competidores.
- ``construir_movimientos`` clasifica en señales explicables (nueva CCAA, nuevo
  CPV, racha) lo que devuelve ``movimientos_vigiladas``.

Los tests de clasificación son puros; los de SQL necesitan ``tmp_db``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from services.competitive.movimientos import (
    MAX_SENALES,
    UMBRAL_RACHA,
    construir_movimientos,
)

# ---------------------------------------------------------------------------
# Clasificación de señales (sin BD)
# ---------------------------------------------------------------------------


def _adj(**kw: Any) -> dict[str, Any]:
    base = {
        "empresa_id": 1,
        "nombre": "Rival SL",
        "licitacion_id": "L-1",
        "titulo": "Mantenimiento SAP",
        "cpv": "72267100",
        "ccaa": "Galicia",
        "importe_adjudicado": 1000.0,
        "fecha_adjudicacion": "2026-09-10T00:00:00",
        "ccaa_nueva": False,
        "cpv_nuevo": False,
    }
    base.update(kw)
    return base


def test_senales_de_territorio_y_cpv_nuevos_una_por_novedad():
    datos = {
        "resumen": [{"empresa_id": 1, "nombre": "Rival SL", "adjudicaciones": 2, "importe": 3000}],
        "adjudicaciones": [
            _adj(licitacion_id="L-1", ccaa_nueva=True, cpv_nuevo=True),
            # Segunda adjudicación en la misma CCAA nueva: la novedad es una.
            _adj(licitacion_id="L-2", ccaa_nueva=True, cpv="72267200"),
        ],
    }
    res = construir_movimientos(datos, dias=30, desde="2026-08-20")

    tipos = [(s.tipo, s.licitacion_id) for s in res.senales]
    assert tipos == [("nueva_ccaa", "L-1"), ("nuevo_cpv", "L-1")]
    assert res.senales[0].titulo == "Rival SL entra en Galicia"
    assert res.senales[0].fecha == "2026-09-10"
    assert res.senales[1].titulo.endswith("familia CPV 72")
    assert res.senales_truncadas is False


def test_racha_a_partir_del_umbral_y_empresas_quietas_con_cero():
    datos = {
        "resumen": [
            {"empresa_id": 1, "nombre": "Activa", "adjudicaciones": UMBRAL_RACHA, "importe": 9},
            {"empresa_id": 2, "nombre": "Quieta", "adjudicaciones": 0, "importe": 0},
        ],
        "adjudicaciones": [],
    }
    res = construir_movimientos(datos, dias=15, desde="2026-09-04")

    assert [s.tipo for s in res.senales] == ["racha"]
    assert res.senales[0].empresa == "Activa"
    assert "15 días" in res.senales[0].detalle
    # La quieta sigue en la lista: «no se mueve» también es una respuesta.
    assert [(e.nombre, e.adjudicaciones) for e in res.empresas] == [("Activa", 3), ("Quieta", 0)]


def test_senales_se_recortan_y_lo_declaran():
    adjudicaciones = [
        _adj(empresa_id=i, nombre=f"E{i}", licitacion_id=f"L-{i}", ccaa_nueva=True)
        for i in range(MAX_SENALES + 5)
    ]
    res = construir_movimientos(
        {"resumen": [], "adjudicaciones": adjudicaciones}, dias=30, desde="2026-08-20"
    )
    assert len(res.senales) == MAX_SENALES
    assert res.senales_truncadas is True


# ---------------------------------------------------------------------------
# SQL (con BD)
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def test_bajas_filtran_por_fecha_de_adjudicacion_e_importe(db):
    from services.competitive.bajas import bajas_agregadas
    from tests.test_competitive import insert_contract, resolve

    insert_contract(db, "F-1", "Antigua SL", fecha_adjudicacion="2024-03-01", importe=100000)
    insert_contract(db, "F-2", "Reciente SL", fecha_adjudicacion="2026-03-01", importe=100000)
    # Con hora: `fecha_hasta` la incluye aunque el texto sea mayor que el día.
    insert_contract(
        db,
        "F-3",
        "Reciente SL",
        fecha_adjudicacion="2026-03-31T10:00:00",
        importe=5000,
        adjudicado=4000,
    )
    resolve(db)

    items, _ = bajas_agregadas(
        min_contratos=1, fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 3, 31)
    )
    assert {i["grupo"] for i in items} == {"Reciente SL"}
    assert items[0]["contratos"] == 2

    items, _ = bajas_agregadas(min_contratos=1, fecha_desde=date(2026, 1, 1), importe_min=50000)
    assert items[0]["contratos"] == 1


def test_bajas_aceptan_varias_ccaa(db):
    from services.competitive.bajas import bajas_agregadas
    from tests.test_competitive import insert_contract, resolve

    insert_contract(db, "C-1", "Norte SL", ccaa="Galicia")
    insert_contract(db, "C-2", "Centro SL", ccaa="Madrid")
    insert_contract(db, "C-3", "Sur SL", ccaa="Andalucía")
    resolve(db)

    items, _ = bajas_agregadas(min_contratos=1, ccaa="Galicia,Madrid")
    assert {i["grupo"] for i in items} == {"Norte SL", "Centro SL"}


def test_movimientos_vigiladas_marca_territorio_nuevo(db):
    from db.watchlist_empresas import WatchlistEmpresaEntry, add_entry, movimientos_vigiladas
    from tests.test_competitive import (
        _organizacion_de_pruebas,
        insert_contract,
        resolve,
    )

    hace = (datetime.now(UTC) - timedelta(days=5)).strftime("%Y-%m-%d")
    insert_contract(db, "M-1", "Vigilada SL", nif="B11111111", fecha_adjudicacion="2025-01-10")
    insert_contract(
        db, "M-2", "Vigilada SL", nif="B11111111", fecha_adjudicacion=hace, ccaa="Galicia"
    )
    insert_contract(db, "M-3", "Vigilada SL", nif="B11111111", fecha_adjudicacion=hace)
    resolve(db)

    from db.connection import connect

    with connect() as c:
        row = c.execute(
            "SELECT empresa_id FROM adjudicaciones WHERE licitacion_id = 'M-1'"
        ).fetchone()
    empresa_id = int(row[0])
    org = _organizacion_de_pruebas("movimientos-equipo")
    add_entry(WatchlistEmpresaEntry(user_key="u1", empresa_id=empresa_id, organization_id=org))

    desde = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")
    datos = movimientos_vigiladas("u1", org, desde_iso=desde)

    assert datos["resumen"][0]["adjudicaciones"] == 2
    por_lic = {f["licitacion_id"]: f for f in datos["adjudicaciones"]}
    assert set(por_lic) == {"M-2", "M-3"}
    assert por_lic["M-2"]["ccaa_nueva"] is True  # Galicia: primera vez
    assert por_lic["M-3"]["ccaa_nueva"] is False  # Madrid: ya tenía historial

    # Otra organización no ve la watchlist ajena.
    otra = _organizacion_de_pruebas("movimientos-otro")
    assert movimientos_vigiladas("u1", otra, desde_iso=desde) == {
        "resumen": [],
        "adjudicaciones": [],
    }
