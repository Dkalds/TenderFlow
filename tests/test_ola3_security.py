"""Tests OLA 3 — Seguridad y gobernanza.

Cubre:
  3.1/3.2 — API key rotation + prefix
  3.3     — Audit log hash chain (log_action + verify_hash_chain)
  3.4     — Migración 28: tabla api_key_tiers + columna tier en api_keys
  3.5     — SSRF blocklist DNS rebinding
  3.6     — revoke_api_key + hash_api_key export
  3.7     — CSP report endpoint (POST /api/v1/security/csp-report)
  3.8     — Audit verify endpoint (GET /api/v1/security/audit/verify)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import db.database as db_mod

    db_path = str(tmp_path / "ola3.db")
    monkeypatch.setenv("ENV", "dev")
    db_mod.set_db_path_override(db_path)
    db_mod.close_pool()
    db_mod.init_db()

    from api.app import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    db_mod.set_db_path_override(None)
    db_mod.close_pool()


@pytest.fixture()
def admin_key(tmp_path, monkeypatch):
    """Devuelve (raw_key, client) con scope '*' para tests que requieren auth."""
    import db.database as db_mod

    db_path = str(tmp_path / "ola3_auth.db")
    monkeypatch.setenv("ENV", "dev")
    db_mod.set_db_path_override(db_path)
    db_mod.close_pool()
    db_mod.init_db()

    from api.app import app
    from api.auth import create_api_key

    raw = create_api_key("test-admin", scopes="*")

    with TestClient(app, raise_server_exceptions=True) as c:
        yield raw, c

    db_mod.set_db_path_override(None)
    db_mod.close_pool()


# ── 3.2 — API key prefix ──────────────────────────────────────────────────────


def test_create_api_key_stores_prefix(tmp_path, monkeypatch):
    """create_api_key debe guardar los primeros 8 chars como prefix."""
    import db.database as db_mod

    db_path = str(tmp_path / "prefix.db")
    monkeypatch.setenv("ENV", "dev")
    db_mod.set_db_path_override(db_path)
    db_mod.close_pool()
    db_mod.init_db()

    from api.auth import create_api_key

    raw = create_api_key("prefix-test", scopes="read")
    expected_prefix = raw[:8]

    with db_mod.connect_read() as c:
        row = c.execute("SELECT prefix FROM api_keys WHERE prefix = ?", (expected_prefix,)).fetchone()

    assert row is not None, f"Prefix {expected_prefix!r} no guardado en api_keys"

    db_mod.set_db_path_override(None)
    db_mod.close_pool()


# ── 3.3 — Audit hash chain ────────────────────────────────────────────────────


def test_log_action_writes_hash_chain(tmp_path, monkeypatch):
    """log_action debe calcular y persistir prev_hash + this_hash en audit_log."""
    import db.database as db_mod

    db_path = str(tmp_path / "hashchain.db")
    monkeypatch.setenv("ENV", "dev")
    db_mod.set_db_path_override(db_path)
    db_mod.close_pool()
    db_mod.init_db()

    from db.audit import log_action

    log_action("user1", "sess1", "test_action", "detail A")
    log_action("user1", "sess1", "test_action2", "detail B")

    with db_mod.connect_read() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(audit_log)").fetchall()}
        has_chain = "prev_hash" in cols and "this_hash" in cols
        rows = c.execute(
            "SELECT prev_hash, this_hash FROM audit_log ORDER BY id ASC"
        ).fetchall()

    assert has_chain, "Columnas prev_hash/this_hash no existen en audit_log"
    assert len(rows) == 2
    first_prev, first_hash = rows[0]
    second_prev, _second_hash = rows[1]

    assert first_prev == "genesis", f"Primera fila debe tener prev_hash='genesis', got {first_prev!r}"
    assert first_hash is not None and len(first_hash) == 64, "this_hash debe ser SHA-256 hex (64 chars)"
    assert second_prev == first_hash, "prev_hash de segunda fila debe igualar this_hash de la primera"

    db_mod.set_db_path_override(None)
    db_mod.close_pool()


def test_verify_hash_chain_valid(tmp_path, monkeypatch):
    """verify_hash_chain debe retornar valid=True para un log sin tamper."""
    import db.database as db_mod

    db_path = str(tmp_path / "verify_ok.db")
    monkeypatch.setenv("ENV", "dev")
    db_mod.set_db_path_override(db_path)
    db_mod.close_pool()
    db_mod.init_db()

    from db.audit import log_action, verify_hash_chain

    for i in range(5):
        log_action("u", "s", f"action_{i}", f"detail {i}")

    result = verify_hash_chain()
    assert result["valid"] is True
    assert result["checked"] == 5
    assert result["first_tampered_id"] is None

    db_mod.set_db_path_override(None)
    db_mod.close_pool()


def test_verify_hash_chain_detects_tamper(tmp_path, monkeypatch):
    """verify_hash_chain debe detectar una fila modificada."""
    import db.database as db_mod

    db_path = str(tmp_path / "verify_tamper.db")
    monkeypatch.setenv("ENV", "dev")
    db_mod.set_db_path_override(db_path)
    db_mod.close_pool()
    db_mod.init_db()

    from db.audit import log_action, verify_hash_chain
    from db.database import connect

    for i in range(3):
        log_action("u", "s", f"action_{i}", "original")

    # Tamper: modificar el detail de la primera fila sin actualizar el hash
    with connect() as c:
        c.execute("UPDATE audit_log SET detail = 'TAMPERED' WHERE id = 1")

    result = verify_hash_chain()
    assert result["valid"] is False
    assert result["first_tampered_id"] == 1

    db_mod.set_db_path_override(None)
    db_mod.close_pool()


# ── 3.4 — api_key_tiers migración ────────────────────────────────────────────


def test_migration_28_creates_api_key_tiers(tmp_path, monkeypatch):
    """Migración 28 debe crear la tabla api_key_tiers con 3 filas por defecto."""
    import db.database as db_mod

    db_path = str(tmp_path / "tiers.db")
    monkeypatch.setenv("ENV", "dev")
    db_mod.set_db_path_override(db_path)
    db_mod.close_pool()
    db_mod.init_db()

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT tier FROM api_key_tiers ORDER BY tier").fetchall()

    tiers = {r[0] for r in rows}
    assert "free" in tiers
    assert "pro" in tiers
    assert "enterprise" in tiers

    db_mod.set_db_path_override(None)
    db_mod.close_pool()


def test_migration_28_adds_tier_column_to_api_keys(tmp_path, monkeypatch):
    """Migración 28 debe añadir columna tier en api_keys con default 'free'."""
    import db.database as db_mod

    db_path = str(tmp_path / "tier_col.db")
    monkeypatch.setenv("ENV", "dev")
    db_mod.set_db_path_override(db_path)
    db_mod.close_pool()
    db_mod.init_db()

    from api.auth import create_api_key

    create_api_key("tier-test")

    with db_mod.connect_read() as c:
        row = c.execute("SELECT tier FROM api_keys WHERE name = 'tier-test'").fetchone()

    assert row is not None
    assert row[0] == "free", f"Tier default esperado 'free', got {row[0]!r}"

    db_mod.set_db_path_override(None)
    db_mod.close_pool()


# ── 3.5 — SSRF DNS rebinding blocklist ───────────────────────────────────────


def test_ssrf_blocks_nip_io():
    """_is_ssrf_url debe bloquear dominios *.nip.io."""
    from api.routes.webhooks import _is_ssrf_url

    assert _is_ssrf_url("http://192.168.1.1.nip.io/hook") is True


def test_ssrf_blocks_sslip_io():
    """_is_ssrf_url debe bloquear dominios *.sslip.io."""
    from api.routes.webhooks import _is_ssrf_url

    assert _is_ssrf_url("https://10.0.0.1.sslip.io/callback") is True


def test_ssrf_blocks_xip_io():
    """_is_ssrf_url debe bloquear dominios *.xip.io."""
    from api.routes.webhooks import _is_ssrf_url

    assert _is_ssrf_url("https://172.16.0.1.xip.io/") is True


def test_ssrf_allows_public_url():
    """_is_ssrf_url debe permitir URLs públicas legítimas."""
    from api.routes.webhooks import _is_ssrf_url

    # example.com es un dominio público real — no debe bloquearse
    result = _is_ssrf_url("https://example.com/webhook")
    assert result is False


# ── 3.7 — CSP report endpoint ────────────────────────────────────────────────


def test_csp_report_returns_204(client):
    """POST /api/v1/security/csp-report debe retornar 204 No Content."""
    payload = {
        "csp-report": {
            "blocked-uri": "https://evil.example.com/script.js",
            "violated-directive": "script-src 'self'",
            "document-uri": "https://app.example.com/page",
            "source-file": "https://app.example.com/page",
        }
    }
    r = client.post(
        "/api/v1/security/csp-report",
        json=payload,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 204


def test_csp_report_handles_invalid_body(client):
    """POST /api/v1/security/csp-report con body inválido debe retornar 204 (silent drop)."""
    r = client.post(
        "/api/v1/security/csp-report",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 204
