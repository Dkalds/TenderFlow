"""Rutas `/api/v1/follows` — seguir cualquier cosa desde un solo sitio (ADR-031).

Qué añade sobre lo que ya había
-------------------------------
Seguir estaba implementado tres veces —`/watchlist/items` (expedientes),
`/empresas/.../seguir` (empresas) y los descartes del radar—, y dos objetivos
que el producto pide desde hace meses no existían **porque habrían necesitado
una cuarta y una quinta tabla**: seguir un órgano de contratación y seguir un
CPV. Aquí son una fila.

Qué NO hace todavía
-------------------
No sustituye a los tres juegos de endpoints antiguos. Está en la fase aditiva
de ADR-031 §B: `follows` se mantiene al día por escritura doble desde las tres
tablas de origen, pero las pantallas de favoritos, empresas y radar siguen
leyendo de la suya. La sustitución llega cuando
`scripts/check_follows_paridad.py` dé cero diferencias contra producción, y la
retirada de los endpoints viejos va por RFC con fecha. Retirar antes de medir
convierte un bug de backfill en pérdida de datos del usuario.

Consecuencia práctica mientras dura la fase: seguir un expediente por
`POST /watchlist/items` aparece aquí, y seguir un **órgano** por este endpoint
no aparece en `/watchlist/items` — porque allí no cabe. No es una
inconsistencia, es el orden de la migración.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.tenancy import require_organization, resolve_organization_ctx
from db.repositories import follows as repo
from observability.logging import get_logger
from shared.dto import FollowItem, FollowsResult

log = get_logger(__name__)

router = APIRouter(prefix="/follows", tags=["follows"])

#: Patrón del tipo de objetivo, para que un valor inválido sea un 422 del DTO y
#: no un 500 del `CHECK` de la base. La lista canónica está en
#: `db/repositories/follows.py` y en la migración v130.
_TARGET_TYPE_RE = "^(licitacion|lote|empresa|organo|cpv)$"
_KIND_RE = "^(seguir|descartar)$"


def _user_key(ctx: dict[str, Any]) -> str:
    return str(ctx["user_key"])


def _user_id(ctx: dict[str, Any]) -> int | None:
    raw = ctx.get("user_id")
    return int(raw) if raw is not None else None


class FollowBody(BaseModel):
    """Alta de un seguimiento."""

    target_type: str = Field(pattern=_TARGET_TYPE_RE)
    # 200 caracteres porque un `id_externo` de PLACSP es largo y lleva barras
    # (`PA-S 2026/000058`); una empresa o un órgano caben de sobra.
    target_id: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="seguir", pattern=_KIND_RE)
    visibility: str = Field(default="private", pattern="^(private|organization)$")
    organization_id: int | None = Field(default=None, ge=1)
    # Caducidad del descarte pospuesto. Sólo tiene sentido con
    # `kind='descartar'`; con `seguir` el handler lo ignora en vez de
    # rechazarlo, porque un cliente que mande el campo de más no está pidiendo
    # nada incoherente — está pidiendo un seguimiento, que no caduca.
    hasta: str | None = Field(default=None, max_length=40)


@router.get("", summary="Listar lo que sigue el usuario")
async def get_follows(
    target_type: str | None = Query(default=None, pattern=_TARGET_TYPE_RE),
    kind: str = Query(default="seguir", pattern=_KIND_RE),
    vigentes: bool = Query(
        default=True,
        description=(
            "Excluir los seguimientos ya caducados (un descarte pospuesto que "
            "venció). La fila se conserva; sólo deja de contar."
        ),
    ),
    limit: int = Query(default=1000, ge=1, le=5000),
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_organization()),
) -> FollowsResult:
    items = await run_db(
        repo.listar,
        user_key=_user_key(ctx),
        user_id=_user_id(ctx),
        organization_id=ctx.get("organization_id"),
        target_type=target_type,
        kind=kind,
        vigentes=vigentes,
        limit=limit,
    )
    return FollowsResult(items=[FollowItem(**i) for i in items], total=len(items))


@router.post("", status_code=status.HTTP_201_CREATED, summary="Seguir algo")
async def post_follow(
    body: FollowBody,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> FollowItem:
    """Idempotente: seguir dos veces lo mismo devuelve la misma fila.

    No lleva `X-Idempotency-Key` como `/watchlist/items` y no es un olvido: el
    `ON CONFLICT` de `follows` ya hace que repetir la llamada sea inofensivo, y
    una clave de idempotencia sobre una operación que ya lo es sólo añade una
    tabla que mantener.
    """
    ctx = await resolve_organization_ctx(ctx, body.organization_id, write=True)
    fila = await run_db(
        repo.registrar,
        user_key=_user_key(ctx),
        user_id=_user_id(ctx),
        organization_id=ctx.get("organization_id"),
        target_type=body.target_type,
        target_id=body.target_id,
        kind=body.kind,
        visibility=body.visibility,
        hasta=body.hasta if body.kind == "descartar" else None,
    )
    if fila is None:
        # `registrar` traga sus errores porque también es escritura doble de
        # las tablas viejas (ver su docstring). Aquí es la operación principal,
        # así que un None sí tiene que verse.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo guardar el seguimiento. Volvé a intentarlo.",
        )
    log.info("follow_creado", target_type=body.target_type, kind=body.kind)
    return FollowItem(**fila)


@router.delete(
    # `:path` por lo mismo que en `/watchlist/items`: hay `id_externo` de PLACSP
    # con barras, y sin esto el DELETE devolvía 404 antes de llegar al handler.
    "/{target_type}/{target_id:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dejar de seguir",
)
async def delete_follow(
    target_type: str,
    target_id: str,
    kind: str = Query(default="seguir", pattern=_KIND_RE),
    ctx: dict[str, Any] = Depends(require_organization(write=True)),
) -> None:
    ok = await run_db(
        repo.olvidar,
        user_key=_user_key(ctx),
        user_id=_user_id(ctx),
        target_type=target_type,
        target_id=target_id,
        kind=kind,
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No seguías eso.")
