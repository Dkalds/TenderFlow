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

**Tenencia.** Como el resto de ``api/routes/``, la organización se resuelve
pasando por ``api/tenancy.py`` y nunca llamando a ``resolve_organization`` a
mano (``tests/test_organization_sql_isolation.py`` explica por qué esa regla
existe). Las dos superficies de ``/organizations/{id}/…`` traen el id en la
**ruta** y no en la query, así que no encajan con la dependency
``require_organization`` —FastAPI no puede declarar el mismo nombre como path
y como query param— y usan ``resolve_organization_ctx`` directamente dentro
del handler, que es la puerta que el propio módulo de tenencia deja abierta
para los casos en que el id no viaja en la query.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.tenancy import resolve_organization_ctx
from db.repositories.organization_capabilities import OrganizationCapabilitiesRepository
from db.repositories.organization_nifs import OrganizationNifRepository
from services.go_no_go import ChecklistNotFoundError, GoNoGoChecklist, build_checklist
from services.normalization import normalize_nif
from services.organizations import OrganizationAccessError
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


async def _organizacion_gestionada(
    ctx: dict[str, Any], organization_id: int | None, *, write: bool
) -> int:
    """Organización resuelta por ``api/tenancy.py``, exigiendo owner o admin.

    La resolución NO se hace aquí: la hace ``resolve_organization_ctx``,
    incondicionalmente, que es el único punto de confianza de la tenencia
    (``tests/test_organization_sql_isolation.py`` impide que una ruta vuelva a
    resolverla por su cuenta). Esta función solo añade el escalón de rol que
    la capacidad de la organización exige por encima de la membresía.

    ``write`` distingue las dos llamadas porque no significan lo mismo: la
    lectura de NIFs está restringida a gestores por lo que revela (con qué
    identidad concurre la casa), no porque escriba nada.
    """
    resuelto = await resolve_organization_ctx(ctx, organization_id, write=write)
    if str(resuelto["organization_role"]) not in _ROLES_GESTORES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo owner o admin pueden gestionar la capacidad de la organización.",
        )
    return int(resuelto["organization_id"])


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


def _capabilities_out(
    organization_id: int, perfil: dict[str, Any], updated_at: datetime | None
) -> OrganizationCapabilitiesOut:
    """Compone la respuesta enumerando qué sale, no volcando lo que entró.

    El repositorio devuelve el perfil con las claves exactas del DTO y la
    marca por separado, así que aquí no hay nada que filtrar: cada campo de la
    respuesta se nombra una vez.
    """
    capabilities = OrganizationCapabilities.model_validate(perfil)
    return OrganizationCapabilitiesOut(
        organization_id=organization_id,
        updated_at=updated_at,
        campos_incompletos=_campos_incompletos(capabilities),
        certificaciones=capabilities.certificaciones,
        facturacion=capabilities.facturacion,
        referencias=capabilities.referencias,
        perfiles_equipo=capabilities.perfiles_equipo,
    )


# ── Identidad fiscal ───────────────────────────────────────────────────────


def _leer_nifs(organization_id: int) -> OrganizationNifsOut:
    """Lectura pura: la organización llega ya resuelta y autorizada."""
    return OrganizationNifsOut(
        organization_id=organization_id,
        # El repositorio selecciona exactamente los campos del DTO,
        # `empresa_id` incluido, así que la validación es directa.
        nifs=[
            OrganizationNifOut.model_validate(fila)
            for fila in _nif_repo.list_for_organization(organization_id)
        ],
    )


def _escribir_nifs(
    organization_id: int, body: OrganizationNifsIn, *, actor_user_id: int
) -> OrganizationNifsOut:
    filas = _normalizar_nifs(body)
    guardadas = _nif_repo.replace_all(organization_id, nifs=filas, actor_user_id=actor_user_id)
    return OrganizationNifsOut(
        organization_id=organization_id,
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
    resolved_id = await _organizacion_gestionada(ctx, organization_id, write=False)
    return await run_db(_leer_nifs, resolved_id)


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
    resolved_id = await _organizacion_gestionada(ctx, organization_id, write=True)
    try:
        return await run_db(_escribir_nifs, resolved_id, body, actor_user_id=int(ctx["user_id"]))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── Perfil de capacidad ────────────────────────────────────────────────────


def _leer_capacidad(organization_id: int) -> OrganizationCapabilitiesOut:
    perfil, updated_at = _capabilities_repo.get_with_updated_at(organization_id)
    return _capabilities_out(organization_id, perfil, updated_at)


def _escribir_capacidad(
    organization_id: int, body: OrganizationCapabilities
) -> OrganizationCapabilitiesOut:
    perfil, updated_at = _capabilities_repo.replace(
        organization_id,
        certificaciones=[item.model_dump() for item in body.certificaciones],
        facturacion=[item.model_dump() for item in body.facturacion],
        referencias=[item.model_dump() for item in body.referencias],
        perfiles_equipo=[item.model_dump() for item in body.perfiles_equipo],
    )
    return _capabilities_out(organization_id, perfil, updated_at)


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
    # Lectura para cualquier miembro activo, `viewer` incluido: el checklist de
    # una oportunidad se explica con estos datos y quien solo lee tiene que
    # poder entender por qué dice «desconocido». Por eso resuelve la tenencia
    # sin pasar por `_organizacion_gestionada`.
    resuelto = await resolve_organization_ctx(ctx, organization_id)
    return await run_db(_leer_capacidad, int(resuelto["organization_id"]))


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
    resolved_id = await _organizacion_gestionada(ctx, organization_id, write=True)
    return await run_db(_escribir_capacidad, resolved_id, body)


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
    # La organización se resuelve **siempre**, aunque el cliente omita el
    # parámetro: es la resolución la que decide contra qué perfil se contrasta
    # y en qué organización se busca la oportunidad. `build_checklist` la
    # vuelve a validar con el id ya explícito, como hace `services/pursuits.py`.
    resuelto = await resolve_organization_ctx(ctx, organization_id)
    try:
        return await run_db(
            build_checklist,
            int(ctx["user_id"]),
            pursuit_id,
            organization_id=int(resuelto["organization_id"]),
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ChecklistNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
