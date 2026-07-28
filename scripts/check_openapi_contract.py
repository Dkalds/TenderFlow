"""Gate del contrato API↔web: ninguna operación nueva con respuesta opaca.

El job *Codegen Drift Check* de CI compara el ``api.d.ts`` regenerado contra el
commiteado: verifica que el artefacto está **sincronizado**, no que el contrato
**diga algo**. Una ruta que devuelve ``dict[str, Any]`` pasa ese gate
perfectamente y produce, en el cliente generado::

    content: { "application/json": { [key: string]: unknown } }

…lo que obliga al frontend a reescribir la forma a mano (p. ej.
``interface Renovacion`` en ``renovaciones/page.tsx``). El resultado es
confianza falsa: el tablero está verde sobre un contrato que, para esas
operaciones, no describe nada, y cualquier renombre de campo en el backend
rompe el frontend en runtime sin que mypy ni tsc se enteren.

Este script cierra ese hueco con el mismo patrón que el ratchet TID251 de
``pyproject.toml``: una allowlist explícita que **sólo puede encoger**.

Uso:
    python scripts/check_openapi_contract.py            # falla si hay opacas fuera de la allowlist
    python scripts/check_openapi_contract.py --list     # imprime las opacas actuales
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = _ROOT / "api" / "openapi.json"

# ── RATCHET: operaciones con respuesta 2xx sin schema ────────────────────────
# Para quitar una línea: dale a la ruta un `response_model` (o un tipo de
# retorno Pydantic) y borra su entrada de aquí.
# **Añadir líneas está prohibido.** Una ruta nueva nace tipada.
ALLOWED_OPAQUE: frozenset[str] = frozenset(
    {
        "DELETE /api/v1/auth/totp",
        "DELETE /api/v1/competitive/watchlist/{empresa_id}",
        "DELETE /api/v1/me",
        "DELETE /api/v1/me/profile",
        "DELETE /api/v1/saved-filters/{filter_id}",
        "DELETE /api/v1/watchlist/rules/{rule_id}",
        "GET /api/v1/auth/oauth/google/authorize",
        "GET /api/v1/auth/oauth/google/callback",
        "GET /api/v1/competitive/bajas",
        "GET /api/v1/competitive/bajas/referencia",
        "GET /api/v1/competitive/cuota",
        "GET /api/v1/competitive/hhi",
        "GET /api/v1/competitive/watchlist",
        "GET /api/v1/empresas",
        "GET /api/v1/empresas/reviews",
        "GET /api/v1/empresas/stats",
        "GET /api/v1/empresas/{empresa_id}",
        "GET /api/v1/exports/calendario.ics",
        "GET /api/v1/exports/download",
        "GET /api/v1/exports/{job_id}",
        "GET /api/v1/feedback/model-info",
        "GET /api/v1/feedback/queue",
        "GET /api/v1/feedback/stats",
        "GET /api/v1/health/live",
        "GET /api/v1/licitaciones/{id_externo}/documentos",
        "GET /api/v1/licitaciones/{id_externo}/explain",
        "GET /api/v1/licitaciones/{id_externo}/tech-scores",
        "GET /api/v1/licitaciones/{licitacion_id}/eventos",
        "GET /api/v1/licitaciones/{licitacion_id}/prediccion-baja",
        "GET /api/v1/me/data",
        "GET /api/v1/meta/filters",
        "GET /api/v1/meta/last-extraction",
        "GET /api/v1/models/{name}",
        "GET /api/v1/resoluciones",
        "GET /api/v1/saved-filters",
        "GET /api/v1/security/audit/verify",
        "GET /api/v1/watchlist/feed.xml",
        "GET /api/v1/watchlist/items",
        "GET /api/v1/watchlist/rules",
        "GET /api/v1/watchlist/rules/{rule_id}/matches",
        "GET /api/v1/webhooks/{webhook_id}",
        "PATCH /api/v1/webhooks/{webhook_id}",
        "POST /api/v1/admin/users/{user_id}/deactivate",
        "POST /api/v1/auth/logout",
        "POST /api/v1/auth/logout-all",
        "POST /api/v1/auth/totp/confirm",
        "POST /api/v1/auth/totp/setup",
        "POST /api/v1/auth/totp/verify",
        "POST /api/v1/competitive/watchlist",
        "POST /api/v1/empresas/reviews/{review_id}",
        "POST /api/v1/exports",
        "POST /api/v1/licitaciones/bulk-get",
        "POST /api/v1/me/keys/rotate",
        "POST /api/v1/models/{name}/activate/{version}",
        "POST /api/v1/notifications/alerts/read",
        "POST /api/v1/notifications/read",
        "POST /api/v1/saved-filters",
        "POST /api/v1/watchlist/items",
        "POST /api/v1/watchlist/rules",
        "POST /api/v1/watchlist/rules/preview",
        "POST /api/v1/webhooks/{webhook_id}/ping",
        "PUT /api/v1/admin/users/{user_id}/admin",
        "PUT /api/v1/feature-flags",
        "PUT /api/v1/me/profile",
        "PUT /api/v1/watchlist/rules/{rule_id}",
    }
)


_SUCCESS_CODES = ("200", "201", "202")


def _is_opaque(schema: dict[str, Any]) -> bool:
    """True si el schema es un objeto sin forma declarada.

    ``{"type": "object"}`` a secas es lo que FastAPI emite para
    ``-> dict[str, Any]``: openapi-typescript lo traduce a
    ``{ [key: string]: unknown }``.
    """
    if not schema:
        return True
    if "$ref" in schema or "allOf" in schema or "anyOf" in schema or "oneOf" in schema:
        return False
    return schema.get("type") == "object" and "properties" not in schema


def find_opaque(spec: dict[str, Any]) -> list[str]:
    """Devuelve ``"METHOD /path"`` de cada operación con respuesta 2xx opaca."""
    opaque: list[str] = []
    for path, operations in spec.get("paths", {}).items():
        for method, op in operations.items():
            if not isinstance(op, dict) or "responses" not in op:
                continue
            response = next(
                (op["responses"][c] for c in _SUCCESS_CODES if c in op["responses"]), None
            )
            if not response:
                continue
            content = (response.get("content") or {}).get("application/json")
            if not content:
                continue
            if _is_opaque(content.get("schema", {})):
                opaque.append(f"{method.upper()} {path}")
    return sorted(opaque)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="Imprime las opacas y sale")
    parser.add_argument("--spec", type=Path, default=_SPEC)
    args = parser.parse_args()

    if not args.spec.exists():
        print(f"[ERROR] No existe {args.spec}. Ejecutá `make openapi` primero.")
        sys.exit(2)

    spec = json.loads(args.spec.read_text())
    opaque = find_opaque(spec)

    if args.list:
        for entry in opaque:
            print(entry)
        sys.exit(0)

    nuevas = sorted(set(opaque) - ALLOWED_OPAQUE)
    resueltas = sorted(ALLOWED_OPAQUE - set(opaque))

    print()
    print("─── Contrato API↔web: operaciones con respuesta opaca ─────────")
    print(f"  Opacas ahora      : {len(opaque)}")
    print(f"  Allowlist         : {len(ALLOWED_OPAQUE)}")

    if resueltas:
        print(f"\n[ACCIÓN] {len(resueltas)} operación(es) ya tipada(s) siguen en la allowlist.")
        print("Borralas de ALLOWED_OPAQUE — el ratchet sólo puede encoger:")
        for entry in resueltas:
            print(f"    {entry}")
        sys.exit(1)

    if nuevas:
        print(f"\n[FAIL] {len(nuevas)} operación(es) nueva(s) con respuesta opaca:")
        for entry in nuevas:
            print(f"    {entry}")
        print(
            "\nUna ruta nueva nace tipada: declará un `response_model` (o un tipo de\n"
            "retorno Pydantic) en vez de `dict[str, Any]`. Añadir entradas a\n"
            "ALLOWED_OPAQUE está prohibido."
        )
        sys.exit(1)

    print("\n[OK] Sin operaciones opacas fuera de la allowlist. ✅")
    sys.exit(0)


if __name__ == "__main__":
    main()
