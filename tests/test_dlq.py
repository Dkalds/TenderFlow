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


def test_list_unresolved_excludes_fuente_prefix(tmp_db):
    """El filtro por prefijo va en SQL, antes del LIMIT."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("x"))
    dlq.record_failure("run-1", "bulk_202602", RuntimeError("x"))
    dlq.record_failure("run-1", "place_live_atom", RuntimeError("x"))

    assert len(dlq.list_unresolved()) == 3
    sin_bulk = dlq.list_unresolved(exclude_fuente_prefix="bulk_")
    assert [f["fuente"] for f in sin_bulk] == ["place_live_atom"]


def test_list_unresolved_prefix_filter_survives_a_tight_limit(tmp_db):
    """Con LIMIT 1 y bulk delante, el filtro tiene que dejar pasar la otra fila."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("x"))
    dlq.record_failure("run-1", "bulk_202602", RuntimeError("x"))
    dlq.record_failure("run-1", "place_live_atom", RuntimeError("x"))

    filas = dlq.list_unresolved(limit=1, exclude_fuente_prefix="bulk_")
    assert [f["fuente"] for f in filas] == ["place_live_atom"]


def test_mark_resolved_removes_from_unresolved(tmp_db):
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("x"))
    failure_id = dlq.list_unresolved()[0]["id"]
    dlq.mark_resolved(failure_id)
    assert dlq.list_unresolved() == []


def test_count_unresolved_matches_list(tmp_db):
    """count_unresolved cuenta exactamente los fallos abiertos (no resueltos)."""
    from db import dlq

    assert dlq.count_unresolved() == 0
    dlq.record_failure("run-1", "src", RuntimeError("a"), payload_ref="p1")
    dlq.record_failure("run-1", "src", RuntimeError("b"), payload_ref="p2")
    assert dlq.count_unresolved() == 2
    # Al resolver uno, el conteo baja y sigue casando con list_unresolved.
    dlq.mark_resolved(dlq.list_unresolved()[0]["id"])
    assert dlq.count_unresolved() == 1
    assert dlq.count_unresolved() == len(dlq.list_unresolved())


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

    dlq.record_failure(
        "run-1", "bulk_202601", ValueError("primer error"), scope="parse", payload_ref="f1.xml"
    )
    dlq.record_failure(
        "run-2", "bulk_202601", RuntimeError("segundo error"), scope="parse", payload_ref="f1.xml"
    )
    dlq.record_failure(
        "run-3", "bulk_202601", RuntimeError("tercer error"), scope="parse", payload_ref="f1.xml"
    )

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


def test_unresolved_summary_groups_by_source_and_scope(tmp_db):
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", ValueError("a"), scope="parse", payload_ref="a")
    dlq.record_failure("run-2", "bulk_202601", ValueError("b"), scope="parse", payload_ref="b")
    dlq.record_failure("run-3", "bulk_202601", ValueError("c"), scope="download")

    summary = dlq.unresolved_summary()
    parse = next(row for row in summary if row["scope"] == "parse")
    assert parse["fuente"] == "bulk_202601"
    assert parse["n"] == 2


def test_mark_matching_resolved_resolves_group(tmp_db):
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", ValueError("a"), scope="parse", payload_ref="a")
    dlq.record_failure("run-2", "bulk_202601", ValueError("b"), scope="parse", payload_ref="b")
    dlq.record_failure("run-3", "bulk_202601", ValueError("c"), scope="download")

    n = dlq.mark_matching_resolved("bulk_202601", "parse")
    assert n == 2
    remaining = dlq.list_unresolved()
    assert len(remaining) == 1
    assert remaining[0]["scope"] == "download"
