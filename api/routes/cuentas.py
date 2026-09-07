"""Rutas /api/v1/cuentas y /api/v1/etiquetas — F1.5 y F1.6.

Dos superficies con el mismo modelo de tenencia: **organización**, no usuario.
Seguir un órgano y etiquetar una oportunidad son decisiones de equipo, y el
día que alguien se va no se puede ir con ellas.

CRUD sobre tablas de organización: las rutas llaman al servicio, que resuelve
la organización y el permiso de escritura (ADR-024). Aquí sólo se traduce
HTTP.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from observability.logging import get_logger
from services.cuentas import (
    EtiquetaLimiteError,
    aplicar_etiqueta,
    borrar_etiqueta,
    crear_etiqueta,
    dejar_de_seguir,
    etiquetas_de,
    listar_cuentas,
    listar_etiquetas,
    quitar_etiqueta,
    seguir_organo,
)
from services.organizations import OrganizationAccessError
from shared.dto import (
    CuentaObjetivo,
    CuentaObjetivoCreate,
    Etiqueta,
    EtiquetaAplicacion,
    EtiquetaAplicada,
    EtiquetaCreate,
    ObjetoEtiquetable,
)

log = get_logger(__name__)

router = APIRouter(tags=["cuentas"])


class ResultadoEtiquetado(BaseModel):
    """Si la operación cambió algo.

    Tipado y no `dict[str, bool]`: el cliente TS se genera de aquí, y un
    diccionario abierto obliga al frontend a redeclarar la forma a mano
    (invariante 5).
    """

    model_config = ConfigDict(extra="forbid")

    #: `False` puede ser «ya estaba así» o «la etiqueta no es de tu
    #: organización». Las dos se ven igual en pantalla —la etiqueta no está—,
    #: y distinguirlas costaría una consulta extra que nadie usaría.
    cambiado: bool


class EtiquetasPorObjeto(BaseModel):
    """Las etiquetas de varios objetos, indexadas por objeto."""

    model_config = ConfigDict(extra="forbid")

    #: Sólo aparecen los objetos **con** etiquetas: un mapa con doscientas
    #: listas vacías es doscientas veces más grande sin decir nada más.
    por_objeto: dict[str, list[EtiquetaAplicada]] = Field(default_factory=dict)


def _user_id(ctx: dict[str, Any]) -> int:
    return int(ctx["user_id"])


# ── Cuentas objetivo (F1.5) ─────────────────────────────────────────────────


@router.get("/cuentas", summary="Órganos que la organización sigue como cuenta")
async def get_cuentas(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[CuentaObjetivo]:
    try:
        return await run_db(listar_cuentas, _user_id(ctx), organization_id=organization_id)
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post(
    "/cuentas",
    status_code=status.HTTP_201_CREATED,
    summary="Seguir un órgano como cuenta objetivo",
    responses={403: {"description": "Un viewer no puede seguir cuentas"}},
)
async def post_cuenta(
    body: CuentaObjetivoCreate,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> CuentaObjetivo:
    """Idempotente: seguir dos veces el mismo órgano no crea dos cuentas.

    Devuelve 201 también cuando ya se seguía. Distinguirlo con un 200 obligaría
    al cliente a tratar dos casos que para el usuario son el mismo —«ya lo
    sigo»— y el estado final es idéntico.
    """
    try:
        return await run_db(
            seguir_organo,
            _user_id(ctx),
            organo=body.organo,
            nota=body.nota,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.delete(
    "/cuentas/{cuenta_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dejar de seguir un órgano",
)
async def delete_cuenta(
    cuenta_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> None:
    try:
        ok = await run_db(
            dejar_de_seguir, _user_id(ctx), cuenta_id, organization_id=organization_id
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Esa cuenta no existe en tu organización.")


# ── Etiquetas (F1.6) ────────────────────────────────────────────────────────


@router.get("/etiquetas", summary="Etiquetas de la organización")
async def get_etiquetas(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[Etiqueta]:
    try:
        return await run_db(listar_etiquetas, _user_id(ctx), organization_id=organization_id)
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post(
    "/etiquetas",
    status_code=status.HTTP_201_CREATED,
    summary="Crear una etiqueta",
    responses={409: {"description": "La organización llegó al máximo de etiquetas"}},
)
async def post_etiqueta(
    body: EtiquetaCreate,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> Etiqueta:
    """Crear una etiqueta que ya existe devuelve la existente, no un error.

    Dos personas etiquetando a la vez «Q4» quieren la misma etiqueta; un
    conflicto obligaría a una de las dos a resolver algo que no es un problema.
    """
    try:
        etiqueta, _creada = await run_db(
            crear_etiqueta,
            _user_id(ctx),
            nombre=body.nombre,
            color=body.color,
            organization_id=organization_id,
        )
    except EtiquetaLimiteError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return etiqueta


@router.delete(
    "/etiquetas/{etiqueta_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar una etiqueta y todas sus aplicaciones",
)
async def delete_etiqueta(
    etiqueta_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> None:
    try:
        ok = await run_db(
            borrar_etiqueta, _user_id(ctx), etiqueta_id, organization_id=organization_id
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Esa etiqueta no existe en tu organización.")


@router.post(
    "/etiquetas/aplicar",
    summary="Aplicar una etiqueta a un favorito, una oportunidad o una cuenta",
    responses={404: {"description": "La etiqueta no es de tu organización"}},
)
async def post_aplicar_etiqueta(
    body: EtiquetaAplicacion,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> ResultadoEtiquetado:
    try:
        aplicada = await run_db(
            aplicar_etiqueta,
            _user_id(ctx),
            etiqueta_id=body.etiqueta_id,
            objeto_tipo=body.objeto_tipo,
            objeto_id=body.objeto_id,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return ResultadoEtiquetado(cambiado=aplicada)


@router.post(
    "/etiquetas/quitar",
    summary="Quitar una etiqueta de un objeto",
)
async def post_quitar_etiqueta(
    body: EtiquetaAplicacion,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> ResultadoEtiquetado:
    try:
        quitada = await run_db(
            quitar_etiqueta,
            _user_id(ctx),
            etiqueta_id=body.etiqueta_id,
            objeto_tipo=body.objeto_tipo,
            objeto_id=body.objeto_id,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return ResultadoEtiquetado(cambiado=quitada)


@router.post(
    "/etiquetas/por-objeto",
    summary="Etiquetas de varios objetos, para pintar una lista de una vez",
)
async def post_etiquetas_por_objeto(
    objeto_tipo: ObjetoEtiquetable = Body(embed=True),
    objeto_ids: list[str] = Body(default_factory=list, embed=True, max_length=200),
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> EtiquetasPorObjeto:
    """POST y no GET porque la lista de ids puede ser larga.

    Doscientos `id_externo` de PLACSP no caben cómodamente en una query
    string, y meterlos ahí además los dejaría en los logs de acceso.
    """
    try:
        agrupado = await run_db(
            etiquetas_de,
            _user_id(ctx),
            objeto_tipo=objeto_tipo,
            objeto_ids=list(objeto_ids),
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return EtiquetasPorObjeto(por_objeto=agrupado)
