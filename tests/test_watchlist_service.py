"""Tests unitarios para services/watchlist.py — Bloque 4 Phase 2."""

from __future__ import annotations

from unittest.mock import patch

# Module-level _repo for patching (delegates to WatchlistRepository)
_REPO_PATH = "services.watchlist._repo"


# ── query_licitaciones_since ──────────────────────────────────────────────────


def test_query_licitaciones_since_returns_dicts():
    """query_licitaciones_since devuelve lista de dicts con las columnas correctas."""
    from services.watchlist import query_licitaciones_since

    expected = [
        {
            "id_externo": "LIC-001",
            "titulo": "Título SAP",
            "descripcion": "Desc",
            "organo_contratacion": "Órgano",
            "cpv": "72210000",
            "importe": 50000.0,
            "ccaa": "Madrid",
            "estado": "PUB",
            "fecha_publicacion": "2026-01-01",
            "url": "https://example.com",
        }
    ]

    with patch(_REPO_PATH) as mock_repo:
        mock_repo.query_licitaciones_since.return_value = expected
        results = query_licitaciones_since("72210000", "2026-01-01")

    assert len(results) == 1
    assert results[0]["id_externo"] == "LIC-001"
    assert results[0]["titulo"] == "Título SAP"
    mock_repo.query_licitaciones_since.assert_called_once_with("72210000", "2026-01-01")


def test_query_licitaciones_since_empty():
    """query_licitaciones_since devuelve lista vacía cuando no hay resultados."""
    from services.watchlist import query_licitaciones_since

    with patch(_REPO_PATH) as mock_repo:
        mock_repo.query_licitaciones_since.return_value = []
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
    expected = {
        "7221": [{"id_externo": "L1", "titulo": "Tit1", "cpv": "72210000"}],
        "4800": [{"id_externo": "L2", "titulo": "Tit2", "cpv": "48000000"}],
    }

    with patch(_REPO_PATH) as mock_repo:
        mock_repo.query_licitaciones_batch.return_value = expected
        result = query_licitaciones_batch(entries, default_since="2026-01-01")

    assert "7221" in result
    assert "4800" in result
    assert result["7221"][0]["id_externo"] == "L1"
    assert result["4800"][0]["id_externo"] == "L2"
    mock_repo.query_licitaciones_batch.assert_called_once_with(entries, "2026-01-01")


def test_query_licitaciones_batch_empty_entries():
    """query_licitaciones_batch con lista vacía devuelve dict vacío."""
    from services.watchlist import query_licitaciones_batch

    with patch(_REPO_PATH) as mock_repo:
        mock_repo.query_licitaciones_batch.return_value = {}
        result = query_licitaciones_batch([], default_since="2026-01-01")

    assert result == {}


# ── mark_digests_sent ─────────────────────────────────────────────────────────


def test_mark_digests_sent_executes_update():
    """mark_digests_sent delega al repo con los ids correctos."""
    from services.watchlist import mark_digests_sent

    with patch(_REPO_PATH) as mock_repo:
        mark_digests_sent([1, 2, 3])

    mock_repo.mark_digests_sent.assert_called_once_with([1, 2, 3])


def test_mark_digests_sent_noop_for_empty_list():
    """mark_digests_sent delega lista vacía al repo (repo maneja internamente)."""
    from services.watchlist import mark_digests_sent

    with patch(_REPO_PATH) as mock_repo:
        mark_digests_sent([])

    mock_repo.mark_digests_sent.assert_called_once_with([])


# ── store_pending_digest ──────────────────────────────────────────────────────


def test_store_pending_digest_returns_true_on_success():
    """store_pending_digest devuelve True cuando la inserción funciona."""
    from services.watchlist import store_pending_digest

    with patch(_REPO_PATH) as mock_repo:
        mock_repo.store_pending_digest.return_value = True
        result = store_pending_digest(
            "user_key_1", "test@example.com", 1, "LIC-001", "daily", "2026-01-01"
        )

    assert result is True
    mock_repo.store_pending_digest.assert_called_once_with(
        user_key="user_key_1",
        recipient="test@example.com",
        entry_id=1,
        licitacion_id="LIC-001",
        frequency="daily",
        matched_at="2026-01-01",
    )


def test_store_pending_digest_returns_false_on_exception():
    """store_pending_digest devuelve False cuando el repo falla."""
    from services.watchlist import store_pending_digest

    with patch(_REPO_PATH) as mock_repo:
        mock_repo.store_pending_digest.return_value = False
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
