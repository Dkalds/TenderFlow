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

    # Jobs de export asíncronos: deprecados en favor de
    # GET /exports/download?format=pdf, porque su almacén vive en memoria del
    # proceso y no sobrevive ni a un reinicio ni a una segunda instancia.
    # Retirarlos sería breaking y requiere RFC, así que el flag es el contrato.
    assert on_disk["paths"]["/api/v1/exports"]["post"]["deprecated"] is True
    job_path = on_disk["paths"]["/api/v1/exports/{job_id}"]
    assert job_path["get"]["deprecated"] is True
    assert job_path["delete"]["deprecated"] is True


def test_export_openapi_is_deterministic(tmp_path):
    mod = _load_export_module()
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    mod.export_openapi(a)
    mod.export_openapi(b)
    assert a.read_bytes() == b.read_bytes()


# ── Ratchet del contrato (H2) ─────────────────────────────────────────────


def _load_contract_module():
    spec = importlib.util.spec_from_file_location(
        "check_openapi_contract", _REPO_ROOT / "scripts" / "check_openapi_contract.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_contract_ratchet_matches_current_spec(tmp_path):
    """La allowlist de operaciones opacas coincide con el schema exportado.

    Es la mitad del ratchet que no puede comprobar el gate de drift: ese
    verifica que `api.d.ts` está sincronizado, no que el contrato tenga
    contenido. Si alguien tipa una ruta y olvida encoger la allowlist, o
    añade una ruta con `dict[str, Any]`, este test lo dice.

    El schema se **genera** en vez de leerse de `api/openapi.json`: ese fichero
    está en `.gitignore`, así que en un checkout limpio no existe.
    """
    schema = _load_export_module().export_openapi(tmp_path / "openapi.json")
    mod = _load_contract_module()
    opaque = set(mod.find_opaque(schema))

    sin_tipar = sorted(opaque - mod.ALLOWED_OPAQUE)
    assert not sin_tipar, f"Operaciones nuevas con respuesta opaca: {sin_tipar}"

    ya_tipadas = sorted(mod.ALLOWED_OPAQUE - opaque)
    assert not ya_tipadas, (
        f"Ya tipadas pero aún en la allowlist (el ratchet solo encoge): {ya_tipadas}"
    )


def test_renovaciones_response_is_typed(tmp_path):
    """Regresión de la primera ola: /competitive/renovaciones no es opaca."""
    schema = _load_export_module().export_openapi(tmp_path / "openapi.json")
    for path in ("/api/v1/competitive/renovaciones", "/api/v1/competitive/renovaciones/resumen"):
        content = schema["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]
        assert "$ref" in content["schema"], f"{path} volvió a respuesta opaca"
