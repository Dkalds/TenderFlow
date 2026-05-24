"""Tests unitarios para services/watchlist.py — Bloque 4 Phase 2."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

# ── query_licitaciones_since ──────────────────────────────────────────────────


def _make_cursor(rows: list[tuple[Any, ...]], cols: list[str]) -> MagicMock:
    cur = MagicMock()
    cur.description = [(c,) for c in cols]
    cur.fetchall.return_value = rows
    return cur


_LIC_COLS = [
    "id_externo",
    "titulo",
    "descripcion",
    "organo_contratacion",
    "cpv",
    "importe",
    "ccaa",
    "estado",
    "fecha_publicacion",
    "url",
]


def test_query_licitaciones_since_returns_dicts():
    """query_licitaciones_since devuelve lista de dicts con las columnas correctas."""
    from services.watchlist import query_licitaciones_since

    row = (
        "LIC-001",
        "Título SAP",
        "Desc",
        "Órgano",
        "72210000",
        50000.0,
        "Madrid",
        "PUB",
        "2026-01-01",
        "https://example.com",
    )
    cur = _make_cursor([row], _LIC_COLS)
    conn_mock = MagicMock()
    conn_mock.__enter__ = MagicMock(return_value=conn_mock)
    conn_mock.__exit__ = MagicMock(return_value=False)
    conn_mock.execute.return_value = cur

    with patch("services.watchlist.connect_read", return_value=conn_mock):
        results = query_licitaciones_since("72210000", "2026-01-01")

    assert len(results) == 1
    assert results[0]["id_externo"] == "LIC-001"
    assert results[0]["titulo"] == "Título SAP"


def test_query_licitaciones_since_empty():
    """query_licitaciones_since devuelve lista vacía cuando no hay resultados."""
    from services.watchlist import query_licitaciones_since

    cur = _make_cursor([], _LIC_COLS)
    conn_mock = MagicMock()
    conn_mock.__enter__ = MagicMock(return_value=conn_mock)
    conn_mock.__exit__ = MagicMock(return_value=False)
    conn_mock.execute.return_value = cur

    with patch("services.watchlist.connect_read", return_value=conn_mock):
        results = query_licitaciones_since("99999999", "2026-01-01")

    assert results == []


# ── query_licitaciones_batch ──────────────────────────────────────────────────


def test_query_licitaciones_batch_groups_by_prefix():
    """query_licitaciones_batch devuelve dict keyed por cpv_prefix."""
    from services.watchlist import query_licitaciones_batch

    entries = [
        {"cpv_prefix": "7221", "last_notified_at": "2026-01-01"},
        {"cpv_prefix": "4800", "last_notified_at": "2026-01-01"},
    ]
    rows = [
        ("L1", "Tit1", None, "Org", "72210000", 1000.0, None, "PUB", "2026-02-01", None),
        ("L2", "Tit2", None, "Org", "48000000", 2000.0, None, "PUB", "2026-02-02", None),
    ]
    cur = _make_cursor(rows, _LIC_COLS)
    conn_mock = MagicMock()
    conn_mock.__enter__ = MagicMock(return_value=conn_mock)
    conn_mock.__exit__ = MagicMock(return_value=False)
    conn_mock.execute.return_value = cur

    with patch("services.watchlist.connect_read", return_value=conn_mock):
        result = query_licitaciones_batch(entries, default_since="2026-01-01")

    assert "7221" in result
    assert "4800" in result
    assert result["7221"][0]["id_externo"] == "L1"
    assert result["4800"][0]["id_externo"] == "L2"


def test_query_licitaciones_batch_empty_entries():
    """query_licitaciones_batch con lista vacía devuelve dict vacío."""
    from services.watchlist import query_licitaciones_batch

    result = query_licitaciones_batch([], default_since="2026-01-01")
    assert result == {}


# ── mark_digests_sent ─────────────────────────────────────────────────────────


def test_mark_digests_sent_executes_update():
    """mark_digests_sent ejecuta UPDATE con los ids correctos."""
    from services.watchlist import mark_digests_sent

    conn_mock = MagicMock()
    conn_mock.__enter__ = MagicMock(return_value=conn_mock)
    conn_mock.__exit__ = MagicMock(return_value=False)

    with patch("services.watchlist.connect", return_value=conn_mock):
        mark_digests_sent([1, 2, 3])

    call_args = conn_mock.execute.call_args
    sql, params = call_args[0]
    assert "UPDATE pending_digests SET sent = 1" in sql
    assert "IN (?,?,?)" in sql
    assert params == [1, 2, 3]


def test_mark_digests_sent_noop_for_empty_list():
    """mark_digests_sent no ejecuta nada si la lista está vacía."""
    from services.watchlist import mark_digests_sent

    with patch("services.watchlist.connect") as mock_connect:
        mark_digests_sent([])

    mock_connect.assert_not_called()


# ── store_pending_digest ──────────────────────────────────────────────────────


def test_store_pending_digest_returns_true_on_success():
    """store_pending_digest devuelve True cuando la inserción funciona."""
    from services.watchlist import store_pending_digest

    conn_mock = MagicMock()
    conn_mock.__enter__ = MagicMock(return_value=conn_mock)
    conn_mock.__exit__ = MagicMock(return_value=False)

    with patch("services.watchlist.connect", return_value=conn_mock):
        result = store_pending_digest(
            "user_key_1", "test@example.com", 1, "LIC-001", "daily", "2026-01-01"
        )

    assert result is True


def test_store_pending_digest_returns_false_on_exception():
    """store_pending_digest devuelve False cuando la DB lanza excepción."""
    from services.watchlist import store_pending_digest

    with patch("services.watchlist.connect", side_effect=Exception("DB error")):
        result = store_pending_digest("key", "email", 1, "lic", "daily", "2026-01-01")

    assert result is False


# ── generate_atom_feed ────────────────────────────────────────────────────────


def test_generate_atom_feed_empty_watchlist_returns_valid_xml():
    """generate_atom_feed sin entradas devuelve XML Atom válido con feed vacío."""
    from services.watchlist import generate_atom_feed

    with patch("services.watchlist.query_licitaciones_batch", return_value={}):
        with patch("db.watchlist.list_entries", return_value=[]):
            xml = generate_atom_feed("user_key_test")

    assert '<?xml version="1.0"' in xml
    assert "<feed" in xml
    assert "sin entradas" in xml


def test_generate_atom_feed_with_licitaciones_returns_entries():
    """generate_atom_feed con resultados incluye <entry> en el feed."""
    from services.watchlist import generate_atom_feed

    lic = {
        "id_externo": "LIC-001",
        "titulo": "SAP S/4HANA",
        "descripcion": "Implantación",
        "organo_contratacion": "AEAT",
        "importe": 100000.0,
        "ccaa": "Madrid",
        "estado": "PUB",
        "fecha_publicacion": "2026-01-15T00:00:00",
        "url": "https://example.com/lic-001",
        "cpv": "72210000",
    }
    watchlist_entries = [{"cpv_prefix": "7221", "last_notified_at": None}]

    with patch("db.watchlist.list_entries", return_value=watchlist_entries):
        with patch("services.watchlist.query_licitaciones_batch", return_value={"7221": [lic]}):
            xml = generate_atom_feed("user_key_test")

    assert "<entry>" in xml
    assert "LIC-001" in xml
    assert "SAP S/4HANA" in xml
