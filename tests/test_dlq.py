"""Tests para db.dlq (Dead Letter Queue)."""

from __future__ import annotations


def test_record_and_list(tmp_db):
    from db import dlq

    dlq.record_failure(
        "run-1", "bulk_202601", ValueError("bad payload"), scope="parse", payload_ref="f1.xml"
    )
    items = dlq.list_unresolved()
    assert len(items) == 1
    assert items[0]["error_type"] == "ValueError"
    assert items[0]["fuente"] == "bulk_202601"


def test_mark_resolved_removes_from_unresolved(tmp_db):
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("x"))
    failure_id = dlq.list_unresolved()[0]["id"]
    dlq.mark_resolved(failure_id)
    assert dlq.list_unresolved() == []


def test_increment_retry(tmp_db):
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("x"))
    failure_id = dlq.list_unresolved()[0]["id"]
    dlq.increment_retry(failure_id)
    dlq.increment_retry(failure_id)
    items = dlq.list_unresolved()
    assert items[0]["retry_count"] == 2


def test_record_failure_truncates_long_message(tmp_db):
    from db import dlq

    long_msg = "x" * 3000
    dlq.record_failure(None, "src", RuntimeError(long_msg))
    items = dlq.list_unresolved()
    assert len(items[0]["error_message"]) == 2000


def test_record_failure_dedups_same_key_increments_retry(tmp_db):
    """Dos fallos con misma (fuente, scope, payload_ref) → un solo registro con retry=1."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", ValueError("primer error"),
                       scope="parse", payload_ref="f1.xml")
    dlq.record_failure("run-2", "bulk_202601", RuntimeError("segundo error"),
                       scope="parse", payload_ref="f1.xml")
    dlq.record_failure("run-3", "bulk_202601", RuntimeError("tercer error"),
                       scope="parse", payload_ref="f1.xml")

    items = dlq.list_unresolved()
    assert len(items) == 1
    assert items[0]["retry_count"] == 2  # 0 inicial + 2 incrementos
    # Mensaje y tipo actualizados al último error
    assert items[0]["error_type"] == "RuntimeError"
    assert items[0]["error_message"] == "tercer error"


def test_record_failure_dedups_with_null_payload_ref(tmp_db):
    """NULL payload_ref también dedupa (gracias a COALESCE en el índice)."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", ValueError("e1"), scope="download")
    dlq.record_failure("run-2", "bulk_202601", ValueError("e2"), scope="download")

    items = dlq.list_unresolved()
    assert len(items) == 1
    assert items[0]["retry_count"] == 1


def test_record_failure_distinct_keys_create_separate_rows(tmp_db):
    """Distintos (fuente, scope, payload_ref) → registros separados."""
    from db import dlq

    dlq.record_failure(None, "bulk_202601", ValueError("x"), scope="parse", payload_ref="a.xml")
    dlq.record_failure(None, "bulk_202601", ValueError("x"), scope="parse", payload_ref="b.xml")
    dlq.record_failure(None, "bulk_202602", ValueError("x"), scope="parse", payload_ref="a.xml")

    items = dlq.list_unresolved()
    assert len(items) == 3


def test_record_failure_resolved_does_not_block_new_entry(tmp_db):
    """Un fallo resuelto no bloquea la inserción de uno nuevo con la misma clave."""
    from db import dlq

    dlq.record_failure(None, "src", ValueError("x"), scope="parse", payload_ref="f.xml")
    failure_id = dlq.list_unresolved()[0]["id"]
    dlq.mark_resolved(failure_id)

    dlq.record_failure(None, "src", ValueError("y"), scope="parse", payload_ref="f.xml")
    items = dlq.list_unresolved()
    assert len(items) == 1
    assert items[0]["retry_count"] == 0  # nuevo registro, no incrementado
