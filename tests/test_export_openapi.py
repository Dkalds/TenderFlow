"""Smoke test del export offline del schema OpenAPI (scripts/export_openapi.py).

Verifica que el export produce un JSON válido con paths no vacíos y que es
determinista (mismo contenido en dos exports consecutivos) — la propiedad de
la que depende el job CI ``codegen-drift``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_export_module():
    spec = importlib.util.spec_from_file_location(
        "export_openapi", _REPO_ROOT / "scripts" / "export_openapi.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_export_openapi_produces_nonempty_paths(tmp_path):
    mod = _load_export_module()
    dest = tmp_path / "openapi.json"
    schema = mod.export_openapi(dest)

    assert dest.exists()
    on_disk = json.loads(dest.read_text(encoding="utf-8"))
    assert on_disk == schema
    assert isinstance(on_disk["paths"], dict)
    assert len(on_disk["paths"]) > 0
    # Endpoints ancla que no deberían desaparecer sin migración consciente.
    assert "/api/v1/health" in on_disk["paths"]
    assert "/api/v1/licitaciones" in on_disk["paths"]
    # Endpoint huérfano (sin consumidor en web/) marcado deprecated en vez de
    # retirado — ver docs/IMPROVEMENT_BACKLOG.md (Cerrados, 2026-07-20).
    retendering_path = on_disk["paths"]["/api/v1/analytics/forecast/retendering"]
    assert retendering_path["get"]["deprecated"] is True


def test_export_openapi_is_deterministic(tmp_path):
    mod = _load_export_module()
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    mod.export_openapi(a)
    mod.export_openapi(b)
    assert a.read_bytes() == b.read_bytes()
