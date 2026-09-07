"""Capacidad de la organización: identidad fiscal, perfil y go/no-go (S2).

Tres superficies que responden a la misma pregunta —«¿qué puede acreditar esta
organización?»— y que por eso se leen juntas:

* ``/organizations/{id}/nifs`` — con qué NIFs concurre. Es lo que permite que
  el cierre de una oportunidad proponga ``won``/``lost`` en vez de pedir que
  alguien lo teclee, y que «contra quién» no cuente a la propia organización
  entre sus competidores.
* ``/organizations/{id}/capabilities`` — certificaciones, facturación,
  referencias y perfiles de equipo.
* ``/pursuits/{id}/checklist`` — el contraste de la ficha del pliego contra lo
  anterior. Vive aquí y no en ``api/routes/pursuits.py`` porque lo que decide
  su respuesta es el perfil de capacidad, no la oportunidad.

Vive aparte de ``api/routes/organization_settings.py`` porque aquello escribe
en ``organizations.settings_json`` y esto en tablas propias (decisión D11).
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from db.repositories.organization_capabilities import OrganizationCapabilitiesRepository
from db.repositories.organization_nifs import OrganizationNifRepository
from services.go_no_go import ChecklistNotFoundError, GoNoGoChecklist, build_checklist
from services.normalization import normalize_nif
from services.organizations import (
    OrganizationAccessError,
    OrganizationPermissionError,
    resolve_organization,
)
from shared.dto import (
    OrganizationCapabilities,
    OrganizationCapabilitiesOut,
    OrganizationCapabilityField,
    OrganizationNifOut,
    OrganizationNifsIn,
    OrganizationNifsOut,
)

router = APIRouter(tags=["pursuits"])

_nif_repo = OrganizationNifRepository()
_capabilities_repo = OrganizationCapabilitiesRepository()

# El mismo predicado que el CHECK de la tabla (v111). Se valida aquí para que
# un NIF mal escrito salga como 422 con su motivo y no como un error de
# integridad de Postgres convertido en 500.
_NIF_RE = re.compile(r"^[A-Z0-9]{4,32}$")

_ROLES_GESTORES = frozenset({"owner", "admin"})


def _require_manager(user_id: int, organization_id: int, *, write: bool) -> int:
    """Owner o admin. Devuelve la organización resuelta.

    ``write`` distingue las dos llamadas porque no significan lo mismo: la
    lectura de NIFs está restringida a gestores por lo que revela (con qué
    identidad concurre la casa), no porque escriba nada.
    """
    resolved_id, role = resolve_organization(user_id, organization_id, write=write)
    if role not in _ROLES_GESTORES:
        raise OrganizationPermissionError(
            "Solo owner o admin pueden gestionar la capacidad de la organización."
        )
    return resolved_id


def _normalizar_nifs(body: OrganizationNifsIn) -> list[dict[str, Any]]:
    """Normaliza, valida forma y unicidad, y comprueba que haya un principal.

    Se hace antes de tocar la BD porque el PUT reemplaza el conjunto entero:
    si la mitad de las filas fuera inválida, rechazar a medias dejaría a la
    organización con menos NIFs de los que tenía.
    """
    filas: list[dict[str, Any]] = []
    vistos: set[str] = set()
    principales = 0
    for entrada in body.nifs:
        normalizado = normalize_nif(entrada.nif)
        if normalizado is None or not _NIF_RE.match(normalizado):
            raise ValueError(f"NIF no válido: {entrada.nif!r}.")
        if normalizado in vistos:
            raise ValueError(f"NIF repetido: {normalizado}.")
        vistos.add(normalizado)
        principales += int(entrada.principal)
        filas.append(
            {
                "nif": normalizado,
                "razon_social": entrada.razon_social,
                "principal": entrada.principal,
            }
        )
    if principales > 1:
        raise ValueError("Solo puede haber un NIF principal.")
    return filas


def _campos_incompletos(
    capabilities: OrganizationCapabilities,
) -> list[OrganizationCapabilityField]:
    """Qué familias siguen vacías. La UI las marca; el checklist las sufre."""
    faltan: list[OrganizationCapabilityField] = []
    if not capabilities.certificaciones:
        faltan.append("certificaciones")
    if not capabilities.facturacion:
        faltan.append("facturacion")
    if not capabilities.referencias:
        faltan.append("referencias")
    if not capabilities.perfiles_equipo:
        faltan.append("perfiles_equipo")
    return faltan


def _capabilities_out(organization_id: int, raw: dict[str, Any]) -> OrganizationCapabilitiesOut:
    capabilities = OrganizationCapabilities.model_validate(raw)
    return OrganizationCapabilitiesOut(
        organization_id=organization_id,
        updated_at=raw.get("updated_at"),
        campos_incompletos=_campos_incompletos(capabilities),
        **capabilities.model_dump(),
    )


# ── Identidad fiscal ───────────────────────────────────────────────────────


def _leer_nifs(user_id: int, organization_id: int) -> OrganizationNifsOut:
    resolved_id = _require_manager(user_id, organization_id, write=False)
    return OrganizationNifsOut(
        organization_id=resolved_id,
        # El repositorio ya devuelve las claves con el nombre del DTO,
        # `empresa_id` incluido, así que la validación es directa.
        nifs=[
            OrganizationNifOut.model_validate(fila)
            for fila in _nif_repo.list_for_organization(resolved_id)
        ],
    )


def _escribir_nifs(
    user_id: int, organization_id: int, body: OrganizationNifsIn
) -> OrganizationNifsOut:
    resolved_id = _require_manager(user_id, organization_id, write=True)
    filas = _normalizar_nifs(body)
    guardadas = _nif_repo.replace_all(resolved_id, nifs=filas, actor_user_id=user_id)
    return OrganizationNifsOut(
        organization_id=resolved_id,
        nifs=[OrganizationNifOut.model_validate(fila) for fila in guardadas],
    )


@router.get(
    "/organizations/{organization_id}/nifs",
    response_model=OrganizationNifsOut,
    summary="NIFs con los que concurre la organización (owner/admin)",
)
async def get_organization_nifs(
    organization_id: int,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationNifsOut:
    """Identidad fiscal declarada, con su enlace al maestro de empresas."""
    try:
        return await run_db(_leer_nifs, int(ctx["user_id"]), organization_id)
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.put(
    "/organizations/{organization_id}/nifs",
    response_model=OrganizationNifsOut,
    summary="Declarar los NIFs de la organización (owner/admin)",
)
async def put_organization_nifs(
    organization_id: int,
    body: OrganizationNifsIn,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationNifsOut:
    """Reemplaza el conjunto completo de NIFs: manda la lista entera, no un alta."""
    try:
        return await run_db(_escribir_nifs, int(ctx["user_id"]), organization_id, body)
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── Perfil de capacidad ────────────────────────────────────────────────────


def _leer_capacidad(user_id: int, organization_id: int) -> OrganizationCapabilitiesOut:
    # Lectura para cualquier miembro activo, `viewer` incluido: el checklist de
    # una oportunidad se explica con estos datos y quien solo lee tiene que
    # poder entender por qué dice «desconocido».
    resolved_id, _ = resolve_organization(user_id, organization_id)
    return _capabilities_out(resolved_id, _capabilities_repo.get(resolved_id))


def _escribir_capacidad(
    user_id: int, organization_id: int, body: OrganizationCapabilities
) -> OrganizationCapabilitiesOut:
    resolved_id = _require_manager(user_id, organization_id, write=True)
    guardado = _capabilities_repo.replace(
        resolved_id,
        certificaciones=[item.model_dump() for item in body.certificaciones],
        facturacion=[item.model_dump() for item in body.facturacion],
        referencias=[item.model_dump() for item in body.referencias],
        perfiles_equipo=[item.model_dump() for item in body.perfiles_equipo],
    )
    return _capabilities_out(resolved_id, guardado)


@router.get(
    "/organizations/{organization_id}/capabilities",
    response_model=OrganizationCapabilitiesOut,
    summary="Perfil de capacidad de la organización",
)
async def get_organization_capabilities(
    organization_id: int,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationCapabilitiesOut:
    """Certificaciones, facturación, referencias y perfiles de equipo declarados.

    ``campos_incompletos`` enumera las familias vacías: son las que hacen que
    el checklist de una oportunidad conteste «desconocido».
    """
    try:
        return await run_db(_leer_capacidad, int(ctx["user_id"]), organization_id)
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.put(
    "/organizations/{organization_id}/capabilities",
    response_model=OrganizationCapabilitiesOut,
    summary="Declarar el perfil de capacidad (owner/admin)",
)
async def put_organization_capabilities(
    organization_id: int,
    body: OrganizationCapabilities,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationCapabilitiesOut:
    """Reemplaza el perfil completo. Es dato corporativo, no personal."""
    try:
        return await run_db(_escribir_capacidad, int(ctx["user_id"]), organization_id, body)
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


# ── Go/no-go ───────────────────────────────────────────────────────────────


@router.get(
    "/pursuits/{pursuit_id}/checklist",
    response_model=GoNoGoChecklist,
    summary="Contraste de la ficha del pliego con la capacidad declarada",
)
async def get_pursuit_checklist(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> GoNoGoChecklist:
    """Veredicto por requisito: ``cumple``, ``no_cumple`` o ``desconocido``.

    Ningún ``cumple`` se emite sin la cita del pliego que lo respalda, y
    ``desconocido`` es lo que se contesta cuando la ficha no extrajo el hecho o
    la organización no rellenó el campo. No decide el go/no-go: lo propone.
    """
    try:
        return await run_db(
            build_checklist,
            int(ctx["user_id"]),
            pursuit_id,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ChecklistNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
