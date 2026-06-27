"""Rutas /api/v1/watchlist/rules — reglas de watchlist por criterio.

CRUD de reglas (keyword/CPV/importe/CCAA + frecuencia) persistidas server-side y
preview de matches sobre el dataset completo. Sustituye el ``localStorage`` del
frontend de mi-watchlist (RFC ux-mi-watchlist; ADR-014 §2). El job de alertas por
frecuencia es un componente aparte (scheduler).
"""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from observability.logging import get_logger
from services.watchlist_rules import (
    Frequency,
    WatchlistRule,
    count_matches,
    create_rule,
    delete_rule,
    list_matches,
    list_rules,
    update_rule,
)

log = get_logger(__name__)

router = APIRouter(prefix="/watchlist/rules", tags=["watchlist"])


def _user_key(ctx: dict[str, Any]) -> str:
    """Clave opaca y estable por usuario (email de sesión o hash de API key)."""
    seed = str(ctx.get("email") or ctx.get("key_hash") or "anon")
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


class WatchlistRuleBody(BaseModel):
    """Cuerpo de creación/edición de una regla (sin id, con límites de tamaño)."""

    nombre: str | None = Field(default=None, max_length=120)
    keyword: str | None = Field(default=None, max_length=200)
    cpv: str | None = Field(default=None, max_length=20)
    min_importe: float | None = Field(default=None, ge=0)
    ccaa: str | None = Field(default=None, max_length=80)
    frequency: Frequency = "daily"
    active: bool = True

    def to_rule(self) -> WatchlistRule:
        return WatchlistRule(**self.model_dump())


class WatchlistRuleOut(WatchlistRule):
    """Regla devuelta al cliente, enriquecida con el conteo real de matches."""

    match_count: int = 0


def _rules_with_counts(user_key: str) -> list[WatchlistRuleOut]:
    """Lista las reglas del usuario con su conteo real de matches (no top-20)."""
    return [
        WatchlistRuleOut(**rule.model_dump(), match_count=count_matches(rule))
        for rule in list_rules(user_key)
    ]


def _matches_for(rule: WatchlistRule, limit: int) -> list[dict[str, Any]]:
    return list_matches(rule, limit=limit)


@router.get("", summary="Listar reglas del usuario (con conteo real de matches)")
async def get_rules(
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, list[WatchlistRuleOut]]:
    items = await run_db(_rules_with_counts, _user_key(ctx))
    return {"items": items}


@router.post("", status_code=status.HTTP_201_CREATED, summary="Crear una regla")
async def post_rule(
    body: WatchlistRuleBody,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, int]:
    rule_id = await run_db(create_rule, _user_key(ctx), body.to_rule())
    log.info("watchlist_rule_created", rule_id=rule_id)
    return {"id": rule_id}


@router.put("/{rule_id}", summary="Actualizar una regla propia")
async def put_rule(
    rule_id: int,
    body: WatchlistRuleBody,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, str]:
    ok = await run_db(update_rule, _user_key(ctx), rule_id, body.to_rule())
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regla no encontrada.")
    return {"status": "ok"}


@router.delete("/{rule_id}", summary="Eliminar una regla propia")
async def delete_rule_route(
    rule_id: int,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, str]:
    ok = await run_db(delete_rule, _user_key(ctx), rule_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regla no encontrada.")
    return {"status": "ok"}


@router.get("/{rule_id}/matches", summary="Licitaciones que coinciden con una regla")
async def get_rule_matches(
    rule_id: int,
    ctx: dict[str, Any] = Depends(require_any_auth),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    by_id = {r.id: r for r in await run_db(list_rules, _user_key(ctx))}
    rule = by_id.get(rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regla no encontrada.")
    items = await run_db(_matches_for, rule, limit)
    total = await run_db(count_matches, rule)
    return {"items": items, "total": total}


@router.post("/preview", summary="Conteo de matches de unos criterios sin guardar")
async def preview_matches(
    body: WatchlistRuleBody,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, int]:
    total = await run_db(count_matches, body.to_rule())
    return {"total": total}
