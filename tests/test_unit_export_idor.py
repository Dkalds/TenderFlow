"""Tests unitarios para IDOR fix en export jobs (issue #50).

Verifica que un usuario autenticado no puede acceder a exports de otro usuario.
Auto-marking: nombre test_unit_* → marker unit (conftest.py).
"""

from __future__ import annotations

import time

import pytest

from api.auth import AuthContext
from api.routes.exports import _store

# ── Fixtures ──────────────────────────────────────────────────────────────────

OWNER_HASH = "owner_hash_aaa"
OTHER_HASH = "other_hash_bbb"

JOB_ID = "test-job-idor-001"


@pytest.fixture(autouse=True)
def _clean_store():
    """Limpia el store antes y después de cada test."""
    _store.clear()
    yield
    _store.clear()


def _make_job(owner: str = OWNER_HASH, status: str = "pending") -> str:
    """Crea un job en el store con owner dado."""
    _store[JOB_ID] = {
        "status": status,
        "created_at": time.monotonic(),
        "pdf": b"%PDF-fake" if status == "done" else None,
        "error": None,
        "owner": owner,
        "n_rows": 1,
    }
    return JOB_ID


def _ctx(key_hash: str) -> AuthContext:
    return AuthContext(key_hash=key_hash, key_id=1, scopes=frozenset({"*"}))


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestExportOwnershipGet:
    """GET /exports/{id} debe validar ownership."""

    def test_owner_can_access_pending_job(self):

        from api.routes.exports import get_export

        _make_job(OWNER_HASH, status="pending")
        # Owner accede — no debe lanzar 403
        resp = get_export(JOB_ID, ctx=_ctx(OWNER_HASH))
        assert resp.status_code == 202  # pending → 202

    def test_owner_can_access_done_job(self):
        from api.routes.exports import get_export

        _make_job(OWNER_HASH, status="done")
        resp = get_export(JOB_ID, ctx=_ctx(OWNER_HASH))
        assert resp.status_code == 200

    def test_other_user_gets_403(self):
        from fastapi import HTTPException

        from api.routes.exports import get_export

        _make_job(OWNER_HASH)
        with pytest.raises(HTTPException) as exc_info:
            get_export(JOB_ID, ctx=_ctx(OTHER_HASH))
        assert exc_info.value.status_code == 403

    def test_nonexistent_job_gets_404(self):
        from fastapi import HTTPException

        from api.routes.exports import get_export

        with pytest.raises(HTTPException) as exc_info:
            get_export("nonexistent", ctx=_ctx(OWNER_HASH))
        assert exc_info.value.status_code == 404


class TestExportOwnershipDelete:
    """DELETE /exports/{id} debe validar ownership."""

    def test_owner_can_delete(self):
        from api.routes.exports import delete_export

        _make_job(OWNER_HASH)
        delete_export(JOB_ID, ctx=_ctx(OWNER_HASH))
        assert JOB_ID not in _store

    def test_other_user_cannot_delete(self):
        from fastapi import HTTPException

        from api.routes.exports import delete_export

        _make_job(OWNER_HASH)
        with pytest.raises(HTTPException) as exc_info:
            delete_export(JOB_ID, ctx=_ctx(OTHER_HASH))
        assert exc_info.value.status_code == 403
        assert JOB_ID in _store  # job still exists

    def test_delete_nonexistent_is_noop(self):
        from api.routes.exports import delete_export

        # Should not raise
        delete_export("nonexistent", ctx=_ctx(OWNER_HASH))


class TestExportOwnershipCreate:
    """POST /exports debe almacenar owner."""

    def test_create_stores_owner(self):
        from unittest.mock import MagicMock

        from api.routes.exports import create_export

        bg = MagicMock()
        result = create_export(
            background_tasks=bg,
            ccaa=None,
            estado=None,
            q=None,
            ctx=_ctx(OWNER_HASH),
        )
        job_id = result["id"]
        assert _store[job_id]["owner"] == OWNER_HASH
