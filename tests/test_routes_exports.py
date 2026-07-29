"""Tests para api/routes/exports.py — job store PDF (crear/consultar/borrar)."""

from __future__ import annotations

import time
from unittest.mock import patch


class TestExportsGcStore:
    """Cover _gc_store deleting expired keys (line 44)."""

    def test_gc_store_removes_expired(self):
        from api.routes.exports import _TTL_SECONDS, _gc_store, _store

        _store["old-job"] = {
            "status": "done",
            "created_at": time.monotonic() - _TTL_SECONDS - 10,
        }
        _store["fresh-job"] = {
            "status": "pending",
            "created_at": time.monotonic(),
        }
        _gc_store()
        assert "old-job" not in _store
        assert "fresh-job" in _store
        # cleanup
        _store.pop("fresh-job", None)


class TestBuildPdf:
    """Cover _build_pdf lines 52-108."""

    def test_build_pdf_empty_rows(self):
        from api.routes.exports import _build_pdf

        result = _build_pdf([], "Test Title")
        assert isinstance(result, bytes)
        assert len(result) > 0
        assert result[:5] == b"%PDF-"

    def test_build_pdf_with_rows(self):
        from api.routes.exports import _build_pdf

        rows = [
            {"col_a": "value1", "col_b": "value2"},
            {"col_a": "value3", "col_b": "value4"},
        ]
        result = _build_pdf(rows, "Test Export")
        assert result[:5] == b"%PDF-"


class TestRunExport:
    """Cover _run_export lines 116-138."""

    @patch("api.routes.exports._build_pdf", return_value=b"%PDF-fake")
    @patch("services.licitaciones.fetch_for_pdf", return_value=[{"a": 1}])
    def test_run_export_success(self, mock_fetch, mock_pdf):
        from api.routes.exports import _run_export, _store

        _store["j1"] = {"status": "pending", "created_at": time.monotonic()}
        _run_export("j1", {"ccaa": "Madrid"})
        assert _store["j1"]["status"] == "done"
        assert _store["j1"]["pdf"] == b"%PDF-fake"
        assert _store["j1"]["n_rows"] == 1
        _store.pop("j1", None)

    @patch("services.licitaciones.fetch_for_pdf", side_effect=RuntimeError("boom"))
    def test_run_export_error(self, mock_fetch):
        from api.routes.exports import _run_export, _store

        _store["j2"] = {"status": "pending", "created_at": time.monotonic()}
        _run_export("j2", {})
        assert _store["j2"]["status"] == "error"
        assert "boom" in _store["j2"]["error"]
        _store.pop("j2", None)


class TestExportsEndpoints:
    """Cover GET/DELETE export endpoints including error status (lines 193-194)."""

    def test_get_export_error_status(self, client, auth):
        # Create a job with error status, owned by the authenticated user
        # First, find the key_hash from auth context
        from api.auth import hash_api_key
        from api.routes.exports import _store

        key_hash = hash_api_key(auth["X-API-Key"])
        job_id = "err-job-123"
        _store[job_id] = {
            "status": "error",
            "error": "something broke",
            "created_at": time.monotonic(),
            "pdf": None,
            "owner": key_hash,
        }
        resp = client.get(f"/api/v1/exports/{job_id}", headers=auth)
        assert resp.status_code == 500
        _store.pop(job_id, None)

    def test_get_export_done_returns_pdf(self, client, auth):
        from api.auth import hash_api_key
        from api.routes.exports import _store

        key_hash = hash_api_key(auth["X-API-Key"])
        job_id = "done-job-123"
        _store[job_id] = {
            "status": "done",
            "pdf": b"%PDF-test",
            "created_at": time.monotonic(),
            "owner": key_hash,
            "n_rows": 5,
        }
        resp = client.get(f"/api/v1/exports/{job_id}", headers=auth)
        assert resp.status_code == 200
        assert resp.content == b"%PDF-test"
        assert resp.headers["content-type"] == "application/pdf"
        _store.pop(job_id, None)

    def test_get_export_pending_returns_202(self, client, auth):
        from api.auth import hash_api_key
        from api.routes.exports import _store

        key_hash = hash_api_key(auth["X-API-Key"])
        job_id = "pending-job-123"
        _store[job_id] = {
            "status": "pending",
            "pdf": None,
            "created_at": time.monotonic(),
            "owner": key_hash,
        }
        resp = client.get(f"/api/v1/exports/{job_id}", headers=auth)
        assert resp.status_code == 202
        assert resp.json()["status"] == "pending"
        _store.pop(job_id, None)

    def test_get_export_not_found(self, client, auth):
        resp = client.get("/api/v1/exports/nonexistent", headers=auth)
        assert resp.status_code == 404

    def test_get_export_forbidden(self, client, auth):
        from api.routes.exports import _store

        _store["other-job"] = {
            "status": "pending",
            "pdf": None,
            "created_at": time.monotonic(),
            "owner": "different-owner-hash",
        }
        resp = client.get("/api/v1/exports/other-job", headers=auth)
        assert resp.status_code == 403
        _store.pop("other-job", None)

    def test_create_export(self, client, auth):
        resp = client.post("/api/v1/exports", headers=auth)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "pending"
        assert "id" in data
        # cleanup
        from api.routes.exports import _store

        _store.pop(data["id"], None)

    def test_delete_export(self, client, auth):
        from api.auth import hash_api_key
        from api.routes.exports import _store

        key_hash = hash_api_key(auth["X-API-Key"])
        _store["del-job"] = {
            "status": "done",
            "pdf": b"x",
            "created_at": time.monotonic(),
            "owner": key_hash,
        }
        resp = client.delete("/api/v1/exports/del-job", headers=auth)
        assert resp.status_code == 204
        assert "del-job" not in _store

    def test_delete_export_not_found(self, client, auth):
        resp = client.delete("/api/v1/exports/no-such-job", headers=auth)
        assert resp.status_code == 204

    def test_delete_export_forbidden(self, client, auth):
        from api.routes.exports import _store

        _store["other-del"] = {
            "status": "done",
            "pdf": b"x",
            "created_at": time.monotonic(),
            "owner": "someone-else",
        }
        resp = client.delete("/api/v1/exports/other-del", headers=auth)
        assert resp.status_code == 403
        _store.pop("other-del", None)
