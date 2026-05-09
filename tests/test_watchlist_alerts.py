"""Tests para scheduler/watchlist_alerts.py."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# _user_key
# ---------------------------------------------------------------------------


def test_user_key_uses_password(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test_secret")
    import importlib

    import config
    importlib.reload(config)

    from scheduler.watchlist_alerts import _user_key

    key = _user_key()
    expected = hashlib.sha256("test_secret".encode()).hexdigest()[:16]
    assert key == expected


def test_user_key_fallback_to_computername(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    monkeypatch.setenv("COMPUTERNAME", "MYHOST")
    import importlib

    import config
    importlib.reload(config)

    from scheduler.watchlist_alerts import _user_key

    key = _user_key()
    expected = hashlib.sha256("MYHOST".encode()).hexdigest()[:16]
    assert key == expected


# ---------------------------------------------------------------------------
# _build_body
# ---------------------------------------------------------------------------


def _make_entry(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"cpv_prefix": "48", "keyword": None, "min_importe": None, "ccaa": None}
    base.update(kwargs)
    return base


def _make_lic(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "titulo": "Sistema ERP",
        "organo_contratacion": "Junta de Andalucía",
        "importe": 100000.0,
        "url": "https://example.com/123",
        "fecha_publicacion": "2024-01-15",
    }
    base.update(kwargs)
    return base


def test_build_body_contains_count():
    from scheduler.watchlist_alerts import _build_body

    entry = _make_entry()
    lics = [_make_lic(), _make_lic()]
    body = _build_body([(entry, lics)])
    assert "2" in body


def test_build_body_with_keyword_and_importe():
    from scheduler.watchlist_alerts import _build_body

    entry = _make_entry(keyword="SAP", min_importe=50000.0, ccaa="AND")
    lics = [_make_lic()]
    body = _build_body([(entry, lics)])
    assert "SAP" in body
    assert "50.000" in body or "50,000" in body
    assert "AND" in body


def test_build_body_truncates_at_10():
    from scheduler.watchlist_alerts import _build_body

    entry = _make_entry()
    lics = [_make_lic(titulo=f"Lic {i}") for i in range(15)]
    body = _build_body([(entry, lics)])
    assert "5 más" in body


def test_build_body_no_importe_shows_dash():
    from scheduler.watchlist_alerts import _build_body

    entry = _make_entry()
    lic = _make_lic(importe=None)
    body = _build_body([(entry, [lic])])
    assert "—" in body


# ---------------------------------------------------------------------------
# _query_licitaciones_since
# ---------------------------------------------------------------------------


def test_query_licitaciones_since_empty_db(tmp_db):
    db_mod, _ = tmp_db
    from scheduler import watchlist_alerts

    import importlib
    importlib.reload(watchlist_alerts)

    result = watchlist_alerts._query_licitaciones_since("48", "2024-01-01")
    assert isinstance(result, list)
    assert result == []


# ---------------------------------------------------------------------------
# check_and_notify — empty watchlist
# ---------------------------------------------------------------------------


def test_check_and_notify_empty_watchlist_returns_zero(tmp_db):
    db_mod, _ = tmp_db
    from scheduler import watchlist_alerts

    import importlib
    importlib.reload(watchlist_alerts)

    with patch("scheduler.watchlist_alerts.list_entries", return_value=[]):
        result = watchlist_alerts.check_and_notify()
    assert result == 0


# ---------------------------------------------------------------------------
# check_and_notify — entries without email (no notification sent)
# ---------------------------------------------------------------------------


def test_check_and_notify_no_email_no_notify(tmp_db, monkeypatch):
    db_mod, _ = tmp_db

    import importlib
    from scheduler import watchlist_alerts
    importlib.reload(watchlist_alerts)

    entry = {
        "id": 1,
        "cpv_prefix": "48",
        "keyword": None,
        "min_importe": None,
        "ccaa": None,
        "email": None,
        "last_notified_at": None,
    }

    with (
        patch("scheduler.watchlist_alerts.list_entries", return_value=[entry]),
        patch("scheduler.watchlist_alerts._query_licitaciones_since", return_value=[]),
        patch("scheduler.watchlist_alerts.update_last_notified") as mock_update,
        patch("scheduler.watchlist_alerts.notify") as mock_notify,
    ):
        result = watchlist_alerts.check_and_notify()

    assert result == 0
    mock_notify.assert_not_called()
    mock_update.assert_called_once()


# ---------------------------------------------------------------------------
# check_and_notify — entry with email, has matches → notify
# ---------------------------------------------------------------------------


def test_check_and_notify_with_matches_sends_alert(tmp_db):
    db_mod, _ = tmp_db

    import importlib
    from scheduler import watchlist_alerts
    importlib.reload(watchlist_alerts)

    entry = {
        "id": 2,
        "cpv_prefix": "48",
        "keyword": "SAP",
        "min_importe": None,
        "ccaa": None,
        "email": "test@example.com",
        "last_notified_at": "2024-01-01",
    }
    lic = {
        "id_externo": "LIC-001",
        "titulo": "Sistema SAP",
        "descripcion": "SAP ABAP",
        "organo_contratacion": "Ayuntamiento",
        "cpv": "48000000",
        "importe": 200000.0,
        "ccaa": "AND",
        "estado": "EV",
        "fecha_publicacion": "2024-02-01",
        "url": "https://example.com/1",
    }

    with (
        patch("scheduler.watchlist_alerts.list_entries", return_value=[entry]),
        patch("scheduler.watchlist_alerts._query_licitaciones_since", return_value=[lic]),
        patch("scheduler.watchlist_alerts.matches_licitacion", return_value=True),
        patch("scheduler.watchlist_alerts.update_last_notified"),
        patch("scheduler.watchlist_alerts.notify") as mock_notify,
    ):
        result = watchlist_alerts.check_and_notify()

    assert result == 1
    mock_notify.assert_called_once()
    call_args = mock_notify.call_args
    assert call_args[1]["to_addr"] == "test@example.com"


def test_check_and_notify_with_email_no_matches_no_notify(tmp_db):
    db_mod, _ = tmp_db

    import importlib
    from scheduler import watchlist_alerts
    importlib.reload(watchlist_alerts)

    entry = {
        "id": 3,
        "cpv_prefix": "48",
        "keyword": None,
        "min_importe": None,
        "ccaa": None,
        "email": "user@example.com",
        "last_notified_at": None,
    }

    with (
        patch("scheduler.watchlist_alerts.list_entries", return_value=[entry]),
        patch("scheduler.watchlist_alerts._query_licitaciones_since", return_value=[]),
        patch("scheduler.watchlist_alerts.update_last_notified"),
        patch("scheduler.watchlist_alerts.notify") as mock_notify,
    ):
        result = watchlist_alerts.check_and_notify()

    assert result == 0
    mock_notify.assert_not_called()
