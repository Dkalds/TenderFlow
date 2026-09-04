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
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.tenancy import require_organization, resolve_organization_ctx
from db.repositories.watchlist_rules import list_rules_rows, set_rule_email
from observability.logging import get_logger
from services.organizations import claim_legacy_scope
from services.watchlist_rules import (
    Frequency,
    WatchlistRule,
    count_matches,
    count_matches_bounded,
    create_rule,
    delete_rule,
    list_matches,
    list_rules,
    update_rule,
)
from shared.dto import (
    CreatedId,
    StatusOk,
    TotalCount,
    WatchlistRuleMatch,
    WatchlistRuleMatchesResult,
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
    """Regla devuelta al cliente, enriquecida con el conteo real de matches.

    Sin defaults (nota de modelado del backlog de contrato): una regla listada
    siempre trae ``id``, su conteo y el email de entrega (posiblemente null).
    """

    id: int
    # Conteo ACOTADO (ver ``count_matches_bounded``): saturado en
    # ``MATCH_COUNT_CAP``. El listado no puede permitirse un COUNT(*) exacto por
    # regla, así que este número significa «al menos tantas» cuando llega al
    # tope, y la UI lo pinta como «999+». El exacto vive en el detalle
    # (``/{rule_id}/matches``), que se pide de una regla cada vez.
    match_count: int
    email: str | None  # email de entrega, si lo tiene


class WatchlistRulesResult(BaseModel):
    """Listado de reglas del usuario (contrato tipado del GET)."""

    items: list[WatchlistRuleOut]


def _rules_with_counts(user_key: str, organization_id: int) -> list[WatchlistRuleOut]:
    """Lista las reglas del usuario con su conteo real de matches y email de entrega."""
    rows_raw = list_rules_rows(user_key, organization_id)

    rules = [
        WatchlistRule(
            id=r.get("id"),
            nombre=r.get("nombre"),
            keyword=r.get("keyword"),
            cpv=r.get("cpv"),
            min_importe=r.get("min_importe"),
            ccaa=r.get("ccaa"),
            frequency=r.get("frequency") or "daily",
            active=bool(r.get("active", 1)),
        )
        for r in rows_raw
    ]
    # Un único viaje para TODAS las reglas y con techo. Antes esto era un
    # ``count_matches(rule)`` dentro del bucle: N escaneos secuenciales sobre
    # ~1,6M filas y N conexiones del pool en una sola petición, con 30 s de
    # ``statement_timeout`` para todo el conjunto.
    counts = count_matches_bounded(rules)
    return [
        WatchlistRuleOut(**rule.model_dump(), match_count=count, email=r.get("email"))
        for rule, count, r in zip(rules, counts, rows_raw, strict=True)
    ]


def _matches_for(rule: WatchlistRule, limit: int) -> list[dict[str, Any]]:
    return list_matches(rule, limit=limit)


@router.get("", summary="Listar reglas del usuario (con conteo real de matches)")
async def get_rules(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_organization()),
) -> WatchlistRulesResult:
    if organization_id is not None:
        await run_db(claim_legacy_scope, int(ctx["user_id"]), _user_key(ctx))
    items = await run_db(_rules_with_counts, _user_key(ctx), ctx["organization_id"])
    return WatchlistRulesResult(items=items)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Crear una regla")
async def post_rule(
    body: WatchlistRuleBody,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> CreatedId:
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
            set_rule_email(user_key, rule_id, email)
        return rule_id

    rule_id = await run_db(_create)
    log.info("watchlist_rule_created", rule_id=rule_id, has_email=email is not None)
    return CreatedId(id=rule_id)


@router.put("/{rule_id}", summary="Actualizar una regla propia")
async def put_rule(
    rule_id: int,
    body: WatchlistRuleBody,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> StatusOk:
    ctx = await resolve_organization_ctx(ctx, body.organization_id, write=True)
    user_key = _user_key(ctx)
    email = _ctx_email(ctx)
    organization_id = ctx["organization_id"]

    def _update() -> bool:
        ok = update_rule(user_key, rule_id, body.to_rule(), organization_id)
        if ok and email is not None:
            set_rule_email(user_key, rule_id, email)
        return ok

    ok = await run_db(_update)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regla no encontrada.")
    return StatusOk(status="ok")


@router.delete("/{rule_id}", summary="Eliminar una regla propia")
async def delete_rule_route(
    rule_id: int,
    ctx: dict[str, Any] = Depends(require_organization(write=True)),
) -> StatusOk:
    ok = await run_db(delete_rule, _user_key(ctx), rule_id, ctx["organization_id"])
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regla no encontrada.")
    return StatusOk(status="ok")


@router.get("/{rule_id}/matches", summary="Licitaciones que coinciden con una regla")
async def get_rule_matches(
    rule_id: int,
    ctx: dict[str, Any] = Depends(require_organization()),
    limit: int = Query(default=50, ge=1, le=200),
) -> WatchlistRuleMatchesResult:
    by_id = {r.id: r for r in await run_db(list_rules, _user_key(ctx), ctx["organization_id"])}
    rule = by_id.get(rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regla no encontrada.")
    items = await run_db(_matches_for, rule, limit)
    total = await run_db(count_matches, rule)
    return WatchlistRuleMatchesResult(
        items=[WatchlistRuleMatch(**item) for item in items], total=total
    )


@router.post("/preview", summary="Conteo de matches de unos criterios sin guardar")
async def preview_matches(
    body: WatchlistRuleBody,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> TotalCount:
    total = await run_db(count_matches, body.to_rule())
    return TotalCount(total=total)


# ── Baja desde el correo ────────────────────────────────────────────────────


@router.get(
    "/baja",
    response_model=StatusOk,
    summary="Pausar todas las reglas desde el enlace del pie de un digest",
    responses={
        303: {"description": "Redirige a Mi Watchlist con las reglas ya pausadas"},
        403: {"description": "Firma inválida"},
    },
)
async def baja_alertas(
    k: str = Query(..., min_length=8, max_length=64, description="user_key firmado"),
    t: str = Query(..., min_length=8, max_length=200, description="Firma HMAC (kid.sig)"),
) -> Any:
    """Pausa las reglas de quien pulsa el enlace de baja del digest.

    Sin sesión a propósito: quien quiere dejar de recibir correo no quiere
    antes hacer login. Lo que autoriza es la firma del ``user_key`` (ver
    ``services/email_digest.py``). No borra nada —las reglas quedan en pausa
    y se reactivan desde Mi Watchlist— y por eso, cuando se conoce el sitio,
    responde con una redirección a esa pantalla en vez de con JSON.
    """

    def _pausar() -> tuple[bool, int, str | None]:
        """Verificación, pausa y destino en un solo salto al threadpool.

        La verificación de la firma es HMAC (CPU) y la pausa es una escritura:
        las dos fuera de ``run_db`` correrían en el event loop. Devuelve
        ``(firma_valida, reglas_pausadas, destino)`` en vez de lanzar, porque
        ``HTTPException`` pertenece al handler y no al trabajo despachado.
        """
        from services.app_urls import url_absoluta
        from services.email_digest import verificar_token_de_baja
        from services.watchlist_rules import deactivate_all_for_user

        if not verificar_token_de_baja(k, t):
            return False, 0, None
        pausadas = deactivate_all_for_user(k)
        return True, pausadas, url_absoluta(f"/mi-watchlist?baja={pausadas}")

    valida, pausadas, destino = await run_db(_pausar)
    if not valida:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Enlace no válido.")
    log.info("watchlist_rules_baja", user_key=k[:8], pausadas=pausadas)
    if destino:
        return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)
    return StatusOk(status="ok")
