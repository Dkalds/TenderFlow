"""Configuración de producto por organización.

Vive aparte de ``api/routes/pursuits.py`` —donde están el resto de rutas de
organizaciones— porque es la única superficie que escribe en
``organizations.settings_json`` y conviene que su contrato se lea entero en un
sitio.

Dos cosas, con dos almacenes distintos y a propósito:

- ``/organizations/{id}/settings`` — las familias del diccionario que vende la
  organización, en ``organizations.settings_json``.
- ``/organizations/{id}/report-schedule`` — cuándo sale el informe semanal
  (T6), en su propia tabla (``organization_report_schedules``, v132). No entra
  en ``settings_json`` porque el scheduler la consulta por día y hora en cada
  pasada: buscar dentro de un JSON de todas las organizaciones para saber a
  quién le toca el lunes sería un escaneo completo cada cuatro horas.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from db.audit import log_event
from services.informes import guardar_programacion, leer_programacion
from services.organizations import (
    OrganizationAccessError,
    OrganizationPermissionError,
    get_settings,
    update_settings,
)
from shared.audit_events import ORG_SETTINGS_UPDATED
from shared.dto import (
    OrganizationSettings,
    OrganizationSettingsOut,
    ReportSchedule,
    ReportScheduleOut,
)

router = APIRouter(tags=["pursuits"])


@router.get(
    "/organizations/{organization_id}/settings",
    response_model=OrganizationSettingsOut,
    summary="Configuración de la organización (familias tecnológicas)",
)
async def get_organization_settings(
    organization_id: int,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationSettingsOut:
    try:
        return await run_db(get_settings, int(ctx["user_id"]), organization_id)
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.put(
    "/organizations/{organization_id}/settings",
    response_model=OrganizationSettingsOut,
    summary="Cambiar la configuración de la organización (owner/admin)",
)
async def put_organization_settings(
    organization_id: int,
    body: OrganizationSettings,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationSettingsOut:
    try:
        guardados = await run_db(update_settings, int(ctx["user_id"]), organization_id, body)
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Qué claves se tocaron, no su contenido: el rastro dice «cambió la
    # estrategia» y la configuración vigente ya la sirve el GET.
    await run_db(
        log_event,
        event_type=ORG_SETTINGS_UPDATED,
        user_id=int(ctx["user_id"]),
        resource=f"org:{organization_id}",
        detail={"organization_id": organization_id, "campos": sorted(body.model_fields_set)},
    )
    return guardados


# ── Informe semanal programado (T6) ──────────────────────────────────────────


@router.get(
    "/organizations/{organization_id}/report-schedule",
    response_model=ReportScheduleOut,
    summary="Cuándo sale el informe semanal de esta organización",
)
async def get_report_schedule(
    organization_id: int,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> ReportScheduleOut:
    """Devuelve los valores por defecto cuando todavía no hay programación.

    No crea la fila: quien sólo abre la pantalla a mirar no debería dejar nada
    escrito.
    """
    try:
        fila = await run_db(leer_programacion, int(ctx["user_id"]), organization_id)
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OrganizationPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return ReportScheduleOut(**fila)


@router.put(
    "/organizations/{organization_id}/report-schedule",
    response_model=ReportScheduleOut,
    summary="Programar el informe semanal (owner/admin)",
    responses={403: {"description": "El informe lo programa quien puede ver Dirección"}},
)
async def put_report_schedule(
    organization_id: int,
    body: ReportSchedule,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> ReportScheduleOut:
    """Activa, cambia el día y la hora, o fija la lista de destinatarios.

    Cambiar la programación **no** reenvía el informe de esta semana: el
    repositorio no toca ``ultimo_envio_at``. Mover el informe del lunes al
    martes es cambiar de día, no pedir dos.
    """
    try:
        fila = await run_db(
            guardar_programacion,
            int(ctx["user_id"]),
            organization_id,
            activo=body.activo,
            dia_semana=body.dia_semana,
            hora_utc=body.hora_utc,
            destinatarios=[str(c) for c in (body.destinatarios or [])],
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OrganizationPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    # Qué se cambió, no a quién se le manda: la lista de destinatarios son
    # correos de personas y el rastro de auditoría no es sitio para copiarlos.
    await run_db(
        log_event,
        event_type=ORG_SETTINGS_UPDATED,
        user_id=int(ctx["user_id"]),
        resource=f"org:{fila['organization_id']}",
        detail={
            "organization_id": fila["organization_id"],
            "campos": ["report_schedule"],
            "activo": body.activo,
            "dia_semana": body.dia_semana,
            "hora_utc": body.hora_utc,
            "destinatarios": len(body.destinatarios or []),
        },
    )
    return ReportScheduleOut(**fila)
