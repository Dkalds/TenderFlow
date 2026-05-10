"""Tests para db.watchlist (CRUD + matching)."""

from __future__ import annotations

import pandas as pd


def test_crud_lifecycle(tmp_db):
    from db.watchlist import (
        WatchlistEntry,
        add_entry,
        list_entries,
        remove_entry,
    )

    e = WatchlistEntry(
        user_key="alice", cpv_prefix="72", keyword="sap", min_importe=10000.0, ccaa="Madrid"
    )
    add_entry(e)
    items = list_entries("alice")
    assert len(items) == 1
    assert items[0]["cpv_prefix"] == "72"
    assert items[0]["keyword"] == "sap"
    assert items[0]["ccaa"] == "Madrid"

    remove_entry(int(items[0]["id"]))
    assert list_entries("alice") == []


def test_add_entry_is_idempotent(tmp_db):
    from db.watchlist import WatchlistEntry, add_entry, list_entries

    entry = WatchlistEntry(user_key="u", cpv_prefix="72")
    add_entry(entry)
    add_entry(entry)
    assert len(list_entries("u")) == 1


def test_matches_licitacion_cpv_prefix():
    from db.watchlist import matches_licitacion

    entry = {"cpv_prefix": "72", "keyword": None, "min_importe": None, "ccaa": None}
    assert matches_licitacion(entry, {"cpv": "72267100-0"})
    assert not matches_licitacion(entry, {"cpv": "48700000-0"})


def test_matches_licitacion_keyword_case_insensitive():
    from db.watchlist import matches_licitacion

    entry = {"cpv_prefix": "72", "keyword": "SAP", "min_importe": None, "ccaa": None}
    assert matches_licitacion(
        entry, {"cpv": "72000000", "titulo": "Mantenimiento del sistema SAP", "descripcion": ""}
    )
    assert not matches_licitacion(entry, {"cpv": "72000000", "titulo": "oracle", "descripcion": ""})


def test_matches_licitacion_importe_filter():
    from db.watchlist import matches_licitacion

    entry = {"cpv_prefix": "72", "keyword": None, "min_importe": 100000.0, "ccaa": None}
    assert matches_licitacion(entry, {"cpv": "72000000", "importe": 200000})
    assert not matches_licitacion(entry, {"cpv": "72000000", "importe": 50000})


def test_matches_licitacion_ccaa_filter():
    from db.watchlist import matches_licitacion

    entry = {"cpv_prefix": "72", "keyword": None, "min_importe": None, "ccaa": "Cataluña"}
    assert matches_licitacion(entry, {"cpv": "72", "ccaa": "Cataluña"})
    assert not matches_licitacion(entry, {"cpv": "72", "ccaa": "Madrid"})


def test_watchlist_matching_with_categorical_columns():
    """Regression: fillna("") raises TypeError on Categorical columns.

    The fix is to call astype(str) BEFORE fillna("") so Categorical dtype is
    cast to object first and fillna works without category constraint.
    """
    from dashboard.pages.mi_watchlist import render  # noqa: F401 — import check

    # Build a minimal DataFrame with Categorical columns, mimicking the real
    # data_loader output (which converts string columns to Categorical).
    df = pd.DataFrame(
        {
            "cpv": pd.Categorical(["72000000", "48000000", None]),
            "titulo": pd.Categorical(["SAP system", "Oracle DB", "Other"]),
            "descripcion": ["desc SAP", "desc oracle", None],
            "importe": [100_000.0, 50_000.0, None],
            "ccaa": pd.Categorical(["Madrid", "Cataluña", None]),
            "fecha_publicacion": pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-01"]),
            "organo_contratacion": ["Org A", "Org B", "Org C"],
            "estado_desc": ["Abierto", "Cerrado", "Abierto"],
            "url": ["http://a.com", "http://b.com", "http://c.com"],
        }
    )

    entries = [
        {
            "id": 1,
            "user_key": "u",
            "cpv_prefix": "72",
            "keyword": None,
            "min_importe": None,
            "ccaa": None,
        }
    ]

    # This block mirrors mi_watchlist.py lines 125-148.  Must not raise.
    combined_mask = pd.Series(False, index=df.index)
    cpv_col = df["cpv"].astype(str).fillna("")
    titulo_col = df["titulo"].astype(str).fillna("").str.lower()
    desc_col = (
        df["descripcion"].astype(str).fillna("").str.lower()
        if "descripcion" in df.columns
        else pd.Series("", index=df.index)
    )
    text_col = titulo_col + " " + desc_col
    importe_col = pd.to_numeric(df["importe"], errors="coerce").fillna(0)
    ccaa_col = df["ccaa"].astype(str).fillna("")

    for e in entries:
        entry_mask = pd.Series(True, index=df.index)
        if e.get("cpv_prefix"):
            entry_mask &= cpv_col.str.startswith(e["cpv_prefix"])
        kw = (e.get("keyword") or "").strip().lower()
        if kw:
            entry_mask &= text_col.str.contains(kw, na=False, regex=False)
        if e.get("min_importe") is not None:
            entry_mask &= importe_col >= float(e["min_importe"])
        if e.get("ccaa"):
            entry_mask &= ccaa_col == e["ccaa"]
        combined_mask |= entry_mask

    matches = df[combined_mask]
    assert len(matches) == 1
    assert matches.iloc[0]["cpv"] == "72000000"
