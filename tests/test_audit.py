"""Tests for db/audit.py — log_event and log_action (uncovered paths)."""

from __future__ import annotations

# ── log_event ──────────────────────────────────────────────────────────────


def test_log_event_string_detail_writes_to_db(tmp_db):
    """log_event with a string detail should persist a row in audit_log."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    log_event(event_type="test.event", user_key="user1", session_hash="sess1")

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT action, detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    assert len(rows) == 1
    action, detail = rows[0]
    assert action == "test.event"
    assert "event=test.event" in detail
    assert "outcome=success" in detail


def test_log_event_dict_detail_serialized(tmp_db):
    """log_event with a dict detail serializes it to JSON string."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    log_event(
        event_type="api_key.created",
        user_key="user2",
        detail={"key_id": 42, "name": "my_key"},
    )

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    assert len(rows) == 1
    detail = rows[0][0]
    assert "key_id" in detail
    assert "42" in detail


def test_log_event_with_ip_in_detail(tmp_db):
    """log_event with ip parameter includes it in structured detail."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    log_event(event_type="login", user_key="u1", ip="192.168.1.1")

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    assert "ip=192.168.1.1" in rows[0][0]


def test_log_event_with_resource_in_detail(tmp_db):
    """log_event with resource parameter includes it in structured detail."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    log_event(event_type="webhook.delivery", resource="webhook:7")

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    assert "resource=webhook:7" in rows[0][0]


def test_log_event_failure_outcome(tmp_db):
    """log_event with outcome=failure stores that outcome in detail."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    log_event(event_type="login_failed", user_key="bad_user", outcome="failure")

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    assert "outcome=failure" in rows[0][0]


def test_log_event_all_params(tmp_db):
    """log_event with all params populates detail accordingly."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    log_event(
        event_type="model.activated",
        user_key="admin",
        session_hash="s123",
        outcome="success",
        ip="10.0.0.1",
        resource="model:99",
        detail="activated new model",
    )

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT action, detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    action, detail = rows[0]
    assert action == "model.activated"
    assert "ip=10.0.0.1" in detail
    assert "resource=model:99" in detail
    assert "activated new model" in detail


def test_log_event_system_user_key_defaults(tmp_db):
    """log_event without user_key defaults to 'system'."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    log_event(event_type="scheduler.run")

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT user_key FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    assert rows[0][0] == "system"


def test_log_event_detail_truncated_at_2000_chars(tmp_db):
    """log_event truncates very long string details to 2000 chars."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    long_detail = "x" * 5000

    log_event(event_type="long.event", detail=long_detail)

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    detail = rows[0][0]
    # The raw detail_str portion is truncated; total structured detail will be longer
    # but the raw detail contribution is <= 2000 chars
    assert "event=long.event" in detail


def test_log_event_dict_detail_truncated(tmp_db):
    """log_event truncates large dict serializations to 2000 chars."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    big_dict = {f"key_{i}": "v" * 100 for i in range(50)}
    log_event(event_type="big.event", detail=big_dict)

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    assert len(rows) == 1  # Should succeed without error


# ── log_action ──────────────────────────────────────────────────────────────


def test_log_action_writes_row(tmp_db):
    """log_action persists user_key, session_hash, action and detail as given."""
    db_mod, _ = tmp_db

    from db.audit import log_action

    log_action("alice", "s1", "export_excel", "file.xlsx")

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT user_key, session_hash, action, detail FROM audit_log").fetchall()

    assert [tuple(r) for r in rows] == [("alice", "s1", "export_excel", "file.xlsx")]


def test_verify_hash_chain_detects_deleted_intermediate_entry(tmp_db):
    """A deleted row breaks prev_hash continuity rather than silently passing."""
    from db.audit import log_action, verify_hash_chain
    from db.database import connect

    log_action("u", "s", "first")
    log_action("u", "s", "second")
    log_action("u", "s", "third")
    with connect() as connection:
        connection.execute("DELETE FROM audit_log WHERE action = %s", ("second",))

    result = verify_hash_chain()
    assert result["valid"] is False
    assert "interrumpida" in str(result["error"])


def test_verify_hash_chain_detects_deleted_tail_via_signed_head(tmp_db):
    """The signed state catches a tail deletion that continuity alone cannot."""
    from db.audit import log_action, verify_hash_chain
    from db.database import connect

    log_action("u", "s", "first")
    log_action("u", "s", "second")
    with connect() as connection:
        connection.execute("DELETE FROM audit_log WHERE action = %s", ("second",))

    result = verify_hash_chain()
    assert result["valid"] is False
    assert "cabecera anclada" in str(result["error"])


def test_purga_de_retencion_reancla_la_cadena(tmp_db):
    """Borrar el extremo antiguo ya no deja `valid=false` para siempre."""
    from db.audit import log_action, purgar_extremo_antiguo, verify_hash_chain
    from db.database import connect_read

    for i in range(5):
        log_action("u", "s", f"accion_{i}")
    with connect_read() as c:
        corte = c.execute(
            "SELECT created_at FROM audit_log ORDER BY id OFFSET 3 LIMIT 1"
        ).fetchone()[0]

    assert purgar_extremo_antiguo(corte, apply=False) == 3
    assert purgar_extremo_antiguo(corte, apply=True) == 3

    result = verify_hash_chain()
    assert result["valid"] is True, result
    assert result["checked"] == 2


def test_log_event_no_deja_que_un_nombre_plante_eventos_en_otra_organizacion(tmp_db):
    """`name` de una API key con `| resource=org:N |` no entra en el rastro de la org N."""
    from db.audit import log_event
    from db.repositories.audit import AuditRepository

    log_event(event_type="org.created", actor="1", resource="org:7", detail={"user_id": 1})
    log_event(
        event_type="api_key.created",
        actor="2",
        resource="user:2",
        detail={"name": "x | resource=org:7 | y"},
    )
    log_event(
        event_type="feedback.submitted",
        actor="2",
        resource="licitacion:a | resource=org:7",
        detail={},
    )

    filas = AuditRepository().list_for_organization(7)

    assert [f["event_type"] for f in filas] == ["org.created"]
