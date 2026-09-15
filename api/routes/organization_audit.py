"""Rastro de auditoría por organización (``GET /organizations/{id}/audit``).

Un cliente B2B espera poder llevarse el registro de lo que pasó en *su*
organización —quién entró, quién cambió un rol, quién exportó— sin pedirle
nada al operador. Hasta 2026-09 el ``audit_log`` solo se leía entero desde
administración (``GET /security/audit/verify`` y el panel de observabilidad)
o por usuario en el export GDPR; no había forma de acotarlo a un tenant.

Vive aparte de ``api/routes/pursuits.py`` —donde están las rutas de
organización que *escriben* esos eventos— porque es la única superficie que
lee ``audit_log`` en nombre de una organización, y conviene que su contrato
(quién puede, qué sale, cómo se pagina) se lea entero en un sitio.

**Tenencia.** Como ``organizations_capacidad.py``, el id viaja en la ruta y
no en la query, así que se pasa por ``resolve_organization_ctx`` dentro del
handler (``tests/test_organization_sql_isolation.py`` impide llamar a
``resolve_organization`` a mano). Por encima de la membresía se exige
owner/admin: el rastro nombra a otros miembros por id y un ``viewer`` no
tiene por qué verlo.

**Paginación.** Por cursor, como recomienda ``docs/api-design.md``: el
cursor es ``(created_at, id)`` de la última fila servida, opaco en base64.
El CSV usa la misma página y devuelve el cursor siguiente en
``X-Next-Cursor``; una exportación larga son varias páginas, no un fichero
sin techo.
"""

from __future__ import annotations

import base64
import csv
import io
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.tenancy import resolve_organization_ctx
from db.repositories.audit import AuditRepository
from shared.dto import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    AuditEntryOut,
    CursorPaginatedResponse,
)
from shared.export_safety import sanitize_spreadsheet_record

router = APIRouter(tags=["pursuits"])

_repo = AuditRepository()

_ROLES_AUDITORES = frozenset({"owner", "admin"})

#: Orden de columnas del CSV; es el mismo del DTO para que las dos formas
#: del mismo export se lean igual.
_COLUMNAS_CSV: tuple[str, ...] = (
    "id",
    "ts",
    "event_type",
    "actor_user_id",
    "outcome",
    "resource",
    "detail",
)


def _codificar_cursor(entrada: AuditEntryOut) -> str:
    raw = f"{entrada.ts}|{entrada.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decodificar_cursor(cursor: str) -> tuple[str, int]:
    """``(created_at, id)`` de la última fila vista; 400 si no es nuestro."""
    try:
        padding = "=" * (-len(cursor) % 4)
        ts, separador, id_texto = (
            base64.urlsafe_b64decode(cursor + padding).decode().rpartition("|")
        )
        if not separador or not ts or not id_texto.isdigit():
            raise ValueError("cursor sin forma (ts|id)")
        return ts, int(id_texto)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cursor inválido."
        ) from exc


def _csv(entradas: list[AuditEntryOut]) -> str:
    """Serializa la página como CSV neutralizando celdas activas.

    ``detail`` y ``resource`` los escribe el servidor, pero ``detail`` puede
    arrastrar texto del usuario (el nombre de una API key, por ejemplo): la
    misma sanitización que el resto de exports (``shared/export_safety.py``).
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_COLUMNAS_CSV)
    writer.writeheader()
    for entrada in entradas:
        writer.writerow(sanitize_spreadsheet_record(entrada.model_dump()))
    return buffer.getvalue()


@router.get(
    "/organizations/{organization_id}/audit",
    response_model=CursorPaginatedResponse[AuditEntryOut],
    summary="Rastro de auditoría de la organización (owner/admin)",
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": (
                "Página del rastro, del evento más reciente al más antiguo. Con "
                "`formato=csv` el mismo contenido como fichero; el cursor de la "
                "página siguiente viaja en `X-Next-Cursor`."
            ),
        },
        400: {"description": "Cursor inválido"},
        403: {"description": "No sos miembro, o no sos owner/admin"},
        422: {"description": "Rango de fechas invertido o límite fuera de rango"},
    },
)
async def get_organization_audit(
    organization_id: int,
    desde: date | None = Query(None, description="Primer día incluido (UTC)."),
    hasta: date | None = Query(None, description="Último día incluido (UTC)."),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    cursor: str | None = Query(
        None, max_length=512, description="`next_cursor` de la página anterior."
    ),
    formato: Literal["json", "csv"] = Query("json"),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> CursorPaginatedResponse[AuditEntryOut] | Response:
    """Eventos de la organización: pertenencia, invitaciones, configuración,
    capacidad y ciclo de vida (familia ``org.*`` de ``shared/audit_events.py``).

    El actor sale como ``actor_user_id`` y el ``detail`` lleva ids, nunca
    correos: el rastro sobrevive a un cambio de dirección y a una
    anonimización GDPR sin quedarse con dato personal (ADR-030 §D).
    """
    resuelto = await resolve_organization_ctx(ctx, organization_id)
    if str(resuelto["organization_role"]) not in _ROLES_AUDITORES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo owner o admin pueden leer el rastro de auditoría de la organización.",
        )
    if desde is not None and hasta is not None and hasta < desde:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="«hasta» es anterior a «desde».",
        )

    resolved_id = int(resuelto["organization_id"])
    # `created_at` es texto ISO en UTC: el día completo de `hasta` entra
    # pidiendo estrictamente menos que el día siguiente.
    filas = await run_db(
        _repo.list_for_organization,
        resolved_id,
        desde=desde.isoformat() if desde is not None else None,
        hasta=(hasta + timedelta(days=1)).isoformat() if hasta is not None else None,
        cursor=_decodificar_cursor(cursor) if cursor else None,
        # Una fila de más dice si hay página siguiente sin un COUNT(*).
        limit=limit + 1,
    )
    entradas = [AuditEntryOut.model_validate(fila) for fila in filas[:limit]]
    has_more = len(filas) > limit
    next_cursor = _codificar_cursor(entradas[-1]) if has_more and entradas else None

    if formato == "csv":
        headers = {
            "Content-Disposition": f'attachment; filename="auditoria-org-{resolved_id}.csv"',
        }
        if next_cursor:
            headers["X-Next-Cursor"] = next_cursor
        return Response(
            content=_csv(entradas), media_type="text/csv; charset=utf-8", headers=headers
        )

    return CursorPaginatedResponse[AuditEntryOut](
        items=entradas, next_cursor=next_cursor, has_more=has_more, limit=limit
    )
