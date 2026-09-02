"""Tests para scheduler/watchlist_alerts.py."""

from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import patch

# ---------------------------------------------------------------------------
# _user_key
# ---------------------------------------------------------------------------


def test_user_key_uses_password(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test_secret")

    from scheduler.watchlist_alerts import _user_key

    key = _user_key()
    expected = hashlib.sha256(b"test_secret").hexdigest()[:16]
    assert key == expected


def test_user_key_fallback_to_computername(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    monkeypatch.setenv("COMPUTERNAME", "MYHOST")

    from scheduler.watchlist_alerts import _user_key

    key = _user_key()
    expected = hashlib.sha256(b"MYHOST").hexdigest()[:16]
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
    _, _ = tmp_db
    import importlib

    from scheduler import watchlist_alerts

    importlib.reload(watchlist_alerts)

    result = watchlist_alerts._query_licitaciones_since("48", "2024-01-01")
    assert isinstance(result, list)
    assert result == []


# ---------------------------------------------------------------------------
# check_and_notify — empty watchlist
# ---------------------------------------------------------------------------


def test_check_and_notify_empty_watchlist_returns_zero(tmp_db):
    _, _ = tmp_db
    import importlib

    from scheduler import watchlist_alerts

    importlib.reload(watchlist_alerts)

    with patch("scheduler.watchlist_alerts.list_entries", return_value=[]):
        result = watchlist_alerts.check_and_notify()
    assert result == 0


# ---------------------------------------------------------------------------
# check_and_notify — entries without email (no notification sent)
# ---------------------------------------------------------------------------


def test_check_and_notify_no_email_no_notify(tmp_db, monkeypatch):
    _, _ = tmp_db

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
# check_and_notify - entry with email, has matches -> notify
# ---------------------------------------------------------------------------


def test_check_and_notify_with_matches_sends_alert(tmp_db):
    _, _ = tmp_db

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
        "frequency": "immediate",
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
        patch("scheduler.watchlist_alerts._query_licitaciones_batch", return_value={"48": [lic]}),
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
    _, _ = tmp_db

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


# ---------------------------------------------------------------------------
# _store_pending_digests
# ---------------------------------------------------------------------------


def test_store_pending_digests_inserts_rows(tmp_db):
    """_store_pending_digests persiste filas en pending_digests."""
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO watchlist_cpv (user_key, cpv_prefix, keyword, min_importe, ccaa, email, frequency, created_at) "
            "VALUES ('testkey', '48', NULL, NULL, NULL, 'u@example.com', 'daily', '2024-01-01')"
        )
        entry_id = c.execute("SELECT MAX(id) FROM watchlist_cpv").fetchone()[0]

    entry = {"id": entry_id, "cpv_prefix": "48", "keyword": None, "min_importe": None, "ccaa": None}
    lic = {"id_externo": "LIC-STORE-01", "titulo": "T"}

    from scheduler.watchlist_alerts import _store_pending_digests

    stored = _store_pending_digests(
        "testkey", "u@example.com", [(entry, [lic])], "daily", "2024-01-01T00:00:00"
    )
    assert stored == 1

    with connect() as c:
        row = c.execute(
            "SELECT licitacion_id FROM pending_digests WHERE licitacion_id = 'LIC-STORE-01'"
        ).fetchone()
    assert row is not None


def test_store_pending_digests_idempotent(tmp_db):
    """Insertar la misma fila dos veces → OR IGNORE, segunda no inserta."""
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO watchlist_cpv (user_key, cpv_prefix, keyword, min_importe, ccaa, email, frequency, created_at) "
            "VALUES ('testkey2', '48', NULL, NULL, NULL, 'u2@example.com', 'daily', '2024-01-01')"
        )
        entry_id = c.execute("SELECT MAX(id) FROM watchlist_cpv").fetchone()[0]

    entry = {"id": entry_id, "cpv_prefix": "48", "keyword": None, "min_importe": None, "ccaa": None}
    lic = {"id_externo": "LIC-DUP-01", "titulo": "T"}

    from scheduler.watchlist_alerts import _store_pending_digests

    first = _store_pending_digests(
        "testkey2", "u2@example.com", [(entry, [lic])], "daily", "2024-01-01"
    )
    assert first == 1


# ---------------------------------------------------------------------------
# send_pending_digests
# ---------------------------------------------------------------------------


def test_send_pending_digests_invalid_frequency(tmp_db):
    """Frecuencia no válida → ValueError."""
    import pytest

    from scheduler.watchlist_alerts import send_pending_digests

    with pytest.raises(ValueError):
        send_pending_digests("hourly")


def test_send_pending_digests_empty(tmp_db):
    """Sin pendientes → devuelve 0, no envía emails."""
    from scheduler.watchlist_alerts import send_pending_digests

    with patch("scheduler.watchlist_alerts.notify") as mock_notify:
        result = send_pending_digests("daily")
    assert result == 0
    mock_notify.assert_not_called()


def test_send_pending_digests_weekly_empty(tmp_db):
    """Frecuencia weekly vacía → devuelve 0."""
    from scheduler.watchlist_alerts import send_pending_digests

    with patch("scheduler.watchlist_alerts.notify") as mock_notify:
        result = send_pending_digests("weekly")
    assert result == 0
    mock_notify.assert_not_called()


def test_send_pending_digests_sends_and_marks_sent(tmp_db):
    """Con rows pendientes → envía email y marca sent=1."""
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO watchlist_cpv (user_key, cpv_prefix, keyword, min_importe, ccaa, email, frequency, created_at) "
            "VALUES ('uk1', '48', NULL, NULL, NULL, 'dest@example.com', 'daily', '2024-01-01')"
        )
        entry_id = c.execute("SELECT MAX(id) FROM watchlist_cpv").fetchone()[0]
        c.execute(
            "INSERT INTO pending_digests "
            "(user_key, recipient_email, entry_id, licitacion_id, frequency, matched_at) "
            "VALUES ('uk1', 'dest@example.com', %s, 'LIC-DIGEST-01', 'daily', '2024-01-01')",
            (entry_id,),
        )

    from scheduler.watchlist_alerts import send_pending_digests

    # Correo de producto (`enviar_email_transaccional`), no alerta de operación
    # (`notify`): el digest dejó de salir con la plantilla de monitorización.
    with (
        patch("scheduler.watchlist_alerts.enviar_email_transaccional", return_value=True) as envio,
        patch("scheduler.watchlist_alerts.notify") as mock_notify,
    ):
        result = send_pending_digests("daily")

    assert result == 1
    envio.assert_called_once()
    mock_notify.assert_not_called()
    kwargs = envio.call_args.kwargs
    assert kwargs["to_addr"] == "dest@example.com"
    assert "TenderFlow" in kwargs["subject"]
    assert "[INFO]" not in kwargs["subject"]
    assert "LIC-DIGEST-01" in kwargs["texto"]

    with connect() as c:
        row = c.execute(
            "SELECT sent FROM pending_digests WHERE licitacion_id = 'LIC-DIGEST-01'"
        ).fetchone()
    assert row[0] == 1


def test_send_pending_digests_multiple_recipients(tmp_db):
    """Múltiples destinatarios → un email por destinatario."""
    from db.database import connect

    with connect() as c:
        for i, email in enumerate(["a@x.com", "b@x.com"], start=1):
            c.execute(
                "INSERT INTO watchlist_cpv "
                "(user_key, cpv_prefix, keyword, min_importe, ccaa, email, frequency, created_at) "
                "VALUES (%s, '48', NULL, NULL, NULL, %s, 'daily', '2024-01-01')",
                (f"uk{i}", email),
            )
            entry_id = c.execute("SELECT MAX(id) FROM watchlist_cpv").fetchone()[0]
            c.execute(
                "INSERT INTO pending_digests "
                "(user_key, recipient_email, entry_id, licitacion_id, frequency, matched_at) "
                "VALUES (%s, %s, %s, %s, 'daily', '2024-01-01')",
                (f"uk{i}", email, entry_id, f"LIC-MULTI-{i:02d}"),
            )

    from scheduler.watchlist_alerts import send_pending_digests

    with patch("scheduler.watchlist_alerts.enviar_email_transaccional", return_value=True) as envio:
        result = send_pending_digests("daily")

    assert result == 2
    assert envio.call_count == 2
    assert {c.kwargs["to_addr"] for c in envio.call_args_list} == {"a@x.com", "b@x.com"}


def test_send_pending_digests_immediate_se_drena(tmp_db):
    """Las reglas «inmediatas» encolaban filas que ninguna frecuencia drenaba."""
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO pending_digests "
            "(user_key, recipient_email, entry_id, licitacion_id, frequency, matched_at) "
            "VALUES ('uk9', 'ya@example.com', 999, 'LIC-INMEDIATA-01', 'immediate', '2024-01-01')"
        )

    from scheduler.watchlist_alerts import send_pending_digests

    with patch("scheduler.watchlist_alerts.enviar_email_transaccional", return_value=True) as envio:
        result = send_pending_digests("immediate")

    assert result == 1
    envio.assert_called_once()
    with connect() as c:
        row = c.execute(
            "SELECT sent FROM pending_digests WHERE licitacion_id = 'LIC-INMEDIATA-01'"
        ).fetchone()
    assert row[0] == 1
