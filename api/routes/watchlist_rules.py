"""Rutas /api/v1/watchlist/rules — reglas de watchlist por criterio.

CRUD de reglas (keyword/CPV/importe/CCAA + frecuencia) persistidas server-side y
preview de matches sobre el dataset completo. Sustituye el ``localStorage`` del
frontend de mi-watchlist (RFC ux-mi-watchlist; ADR-014 §2). El job de alertas por
frecuencia es un componente aparte (scheduler).

Feature A: el email de entrega de la regla se toma del ctx de sesion OAuth al
crear/editar. Contextos API-key sin email quedan con email=NULL (solo in-app).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.tenancy import require_organization, resolve_organization_ctx
from observability.logging import get_logger
from services.organizations import claim_legacy_scope
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
    """Clave opaca y estable por usuario.

    ``require_any_auth`` (sesión o API key) siempre adjunta ``user_key`` al
    contexto vía ``shared.identity.user_key_from_email`` — es la única
    derivación canónica. Antes esta función tenía un fallback local con una
    fórmula distinta (sin ``.strip().lower()``, usando ``key_hash`` en vez de
    ``user_id`` como semilla alternativa) que nunca se ejercitaba en la
    práctica pero podía divergir silenciosamente si algún día lo hiciera.
    """
    return str(ctx["user_key"])


def _ctx_email(ctx: dict[str, Any]) -> str | None:
    """Email del usuario de sesion OAuth; None para API-key (sin email recuperable)."""
    email = ctx.get("email")
    return str(email) if email else None


class WatchlistRuleBody(BaseModel):
    """Cuerpo de creacion/edicion de una regla (sin id, con limites de tamano)."""

    nombre: str | None = Field(default=None, max_length=120)
    keyword: str | None = Field(default=None, max_length=200)
    cpv: str | None = Field(default=None, max_length=20)
    min_importe: float | None = Field(default=None, ge=0)
    ccaa: str | None = Field(default=None, max_length=80)
    frequency: Frequency = "daily"
    active: bool = True
    organization_id: int | None = Field(default=None, ge=1)
    visibility: str = Field(default="private", pattern="^(private|organization)$")

    def to_rule(self) -> WatchlistRule:
        return WatchlistRule(**self.model_dump())


class WatchlistRuleOut(WatchlistRule):
    """Regla devuelta al cliente, enriquecida con el conteo real de matches."""

    match_count: int = 0
    email: str | None = None  # email de entrega, si lo tiene


def _rules_with_counts(user_key: str, organization_id: int | None = None) -> list[WatchlistRuleOut]:
    """Lista las reglas del usuario con su conteo real de matches y email de entrega."""
    from db.database import connect_read

    # Intentar obtener las reglas con la columna email (v47).
    # Si la columna no existe todavia (BD legacy / tests sin migrate), fallback
    # a la query sin email (tolerancia a schema viejo).
    try:
        with connect_read() as c:
            where = (
                "user_key = ?"
                if organization_id is None
                else "organization_id = ? AND (visibility = 'organization' OR user_key = ?)"
            )
            params = (user_key,) if organization_id is None else (organization_id, user_key)
            cur = c.execute(
                "SELECT id, user_key, nombre, keyword, cpv, min_importe, ccaa, "
                "frequency, active, last_notified_at, email, organization_id, visibility "
                "FROM watchlist_rules WHERE " + where + " ORDER BY id",
                params,
            )
            cols = [d[0] for d in cur.description]
            rows_raw = [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
    except Exception:
        # Fallback: columna email no disponible (BD sin migrar)
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, user_key, nombre, keyword, cpv, min_importe, ccaa, "
                "frequency, active, last_notified_at "
                "FROM watchlist_rules WHERE user_key = ? ORDER BY id",
                (user_key,),
            )
            cols = [d[0] for d in cur.description]
            rows_raw = [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    result: list[WatchlistRuleOut] = []
    for r in rows_raw:
        rule = WatchlistRule(
            id=r.get("id"),
            nombre=r.get("nombre"),
            keyword=r.get("keyword"),
            cpv=r.get("cpv"),
            min_importe=r.get("min_importe"),
            ccaa=r.get("ccaa"),
            frequency=r.get("frequency") or "daily",
            active=bool(r.get("active", 1)),
        )
        result.append(
            WatchlistRuleOut(
                **rule.model_dump(),
                match_count=count_matches(rule),
                email=r.get("email"),
            )
        )
    return result


def _matches_for(rule: WatchlistRule, limit: int) -> list[dict[str, Any]]:
    return list_matches(rule, limit=limit)


@router.get("", summary="Listar reglas del usuario (con conteo real de matches)")
async def get_rules(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_organization()),
) -> dict[str, list[WatchlistRuleOut]]:
    if organization_id is not None:
        await run_db(claim_legacy_scope, int(ctx["user_id"]), _user_key(ctx))
    items = await run_db(_rules_with_counts, _user_key(ctx), ctx["organization_id"])
    return {"items": items}


@router.post("", status_code=status.HTTP_201_CREATED, summary="Crear una regla")
async def post_rule(
    body: WatchlistRuleBody,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, int]:
    from db.database import connect

    ctx = await resolve_organization_ctx(ctx, body.organization_id, write=True)
    user_key = _user_key(ctx)
    email = _ctx_email(ctx)
    rule = body.to_rule()
    organization_id = ctx["organization_id"]

    def _create() -> int:
        rule_id = create_rule(
            user_key,
            rule,
            user_id=int(ctx["user_id"]),
            organization_id=organization_id,
            visibility=body.visibility,
        )
        if email is not None:
            with connect() as c:
                c.execute(
                    "UPDATE watchlist_rules SET email = ? WHERE id = ? AND user_key = ?",
                    (email, rule_id, user_key),
                )
        return rule_id

    rule_id = await run_db(_create)
    log.info("watchlist_rule_created", rule_id=rule_id, has_email=email is not None)
    return {"id": rule_id}


@router.put("/{rule_id}", summary="Actualizar una regla propia")
async def put_rule(
    rule_id: int,
    body: WatchlistRuleBody,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, str]:
    from db.database import connect

    ctx = await resolve_organization_ctx(ctx, body.organization_id, write=True)
    user_key = _user_key(ctx)
    email = _ctx_email(ctx)
    organization_id = ctx["organization_id"]

    def _update() -> bool:
        ok = update_rule(user_key, rule_id, body.to_rule(), organization_id)
        if ok and email is not None:
            with connect() as c:
                c.execute(
                    "UPDATE watchlist_rules SET email = ? WHERE id = ? AND user_key = ?",
                    (email, rule_id, user_key),
                )
        return ok

    ok = await run_db(_update)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regla no encontrada.")
    return {"status": "ok"}


@router.delete("/{rule_id}", summary="Eliminar una regla propia")
async def delete_rule_route(
    rule_id: int,
    ctx: dict[str, Any] = Depends(require_organization(write=True)),
) -> dict[str, str]:
    ok = await run_db(delete_rule, _user_key(ctx), rule_id, ctx["organization_id"])
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regla no encontrada.")
    return {"status": "ok"}


@router.get("/{rule_id}/matches", summary="Licitaciones que coinciden con una regla")
async def get_rule_matches(
    rule_id: int,
    ctx: dict[str, Any] = Depends(require_organization()),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    by_id = {r.id: r for r in await run_db(list_rules, _user_key(ctx), ctx["organization_id"])}
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
