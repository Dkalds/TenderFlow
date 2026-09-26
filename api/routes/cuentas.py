"""Rutas /api/v1/cuentas y /api/v1/etiquetas — F1.5 y F1.6.

Dos superficies con el mismo modelo de tenencia: **organización**, no usuario.
Seguir un órgano y etiquetar una oportunidad son decisiones de equipo, y el
día que alguien se va no se puede ir con ellas.

CRUD sobre tablas de organización: las rutas llaman al servicio, que resuelve
la organización y el permiso de escritura (ADR-024). Aquí sólo se traduce
HTTP.

Una cuenta es un cliente con uno o varios órganos (v145). Las rutas fijas
(``/cuentas/resumen``, ``/cuentas/buscar-organos``) van **antes** que
``/cuentas/{cuenta_id}``: FastAPI prueba las rutas en orden, y ``resumen``
contra un ``cuenta_id: int`` sería un 422, no la ruta siguiente.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from observability.logging import get_logger
from services.cuentas import (
    CuentaNombreOcupadoError,
    EtiquetaLimiteError,
    OrganoEnOtraCuentaError,
    UltimoOrganoError,
    anadir_organos,
    aplicar_etiqueta,
    borrar_etiqueta,
    buscar_organos,
    crear_cuenta,
    crear_etiqueta,
    dejar_de_seguir,
    dejar_de_seguir_organo,
    editar_cuenta,
    etiquetas_de,
    ficha_cuenta,
    listar_cuentas,
    listar_etiquetas,
    quitar_etiqueta,
    quitar_organo,
    resumen_cuentas,
)
from services.organizations import OrganizationAccessError, OrganizationPermissionError
from shared.dto import (
    CuentaObjetivo,
    CuentaObjetivoCreate,
    CuentaObjetivoUpdate,
    CuentaOrganosAdd,
    CuentasResumen,
    Etiqueta,
    EtiquetaAplicacion,
    EtiquetaAplicada,
    EtiquetaCreate,
    FichaCuenta,
    ObjetoEtiquetable,
    OrganoCandidato,
    SafeStr,
)

log = get_logger(__name__)

router = APIRouter(tags=["cuentas"])

#: Los dos rechazos de ``resolve_organization``, que son hermanos y no padre e
#: hijo: no ser miembro (``OrganizationAccessError``) y serlo con un rol que no
#: escribe (``OrganizationPermissionError``, el viewer). Estas rutas sólo
#: capturaban el primero, y el viewer que pulsaba «Seguir» recibía un 500 en
#: vez del 403 que la ruta documenta. Un solo nombre para los nueve ``except``
#: es lo que impide que vuelva a faltar uno.
_RECHAZO_DE_ORGANIZACION = (OrganizationAccessError, OrganizationPermissionError)

#: Conflictos de una cuenta con el resto de la cartera: el órgano ya es de otra
#: cuenta, el nombre ya lo usa otra, o se quiere dejar una cuenta sin órganos.
#: Los tres son 409 con un mensaje que nombra el conflicto.
_CONFLICTO_DE_CUENTA = (OrganoEnOtraCuentaError, CuentaNombreOcupadoError, UltimoOrganoError)

_NO_EXISTE = "Esa cuenta no existe en tu organización."


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


@router.get("/cuentas", summary="Cuentas de la organización, con sus órganos")
async def get_cuentas(
    organization_id: int | None = Query(default=None, ge=1),
    organo: SafeStr | None = Query(
        default=None,
        min_length=1,
        max_length=500,
        description=(
            "Sólo la cuenta que contiene este órgano (cero o una). Se compara por "
            "el nombre plegado, así que la grafía del expediente encuentra la "
            "cuenta aunque el órgano se añadiera escrito de otra forma."
        ),
    ),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[CuentaObjetivo]:
    try:
        return await run_db(
            listar_cuentas, _user_id(ctx), organization_id=organization_id, organo=organo
        )
    except _RECHAZO_DE_ORGANIZACION as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post(
    "/cuentas",
    status_code=status.HTTP_201_CREATED,
    summary="Seguir un órgano, o crear una cuenta con varios órganos",
    responses={
        403: {"description": "Un viewer no puede seguir cuentas"},
        409: {"description": "Un órgano ya es de otra cuenta, o el nombre ya existe"},
    },
)
async def post_cuenta(
    body: CuentaObjetivoCreate,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> CuentaObjetivo:
    """Con ``organo``: idempotente, seguir dos veces el mismo órgano no crea dos
    cuentas. Con ``organos``: una cuenta nueva con todos, todo o nada.

    Devuelve 201 también cuando el órgano ya se seguía. Distinguirlo con un 200
    obligaría al cliente a tratar dos casos que para el usuario son el mismo
    —«ya lo sigo»— y el estado final es idéntico.
    """
    try:
        return await run_db(
            crear_cuenta,
            _user_id(ctx),
            organo=body.organo,
            organos=body.organos,
            nombre=body.nombre,
            nota=body.nota,
            organization_id=organization_id,
        )
    except _RECHAZO_DE_ORGANIZACION as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except _CONFLICTO_DE_CUENTA as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/cuentas/resumen", summary="Qué pasa hoy en cada cuenta, en cuatro números")
async def get_cuentas_resumen(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> CuentasResumen:
    """Abiertas hoy, última publicación, contratos que vencen y oportunidades
    activas de cada cuenta, con el universo y la ventana de cada cifra."""
    try:
        return await run_db(resumen_cuentas, _user_id(ctx), organization_id=organization_id)
    except _RECHAZO_DE_ORGANIZACION as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get(
    "/cuentas/buscar-organos",
    summary="Órganos para el alta de una cuenta, y de qué cuenta es ya cada uno",
)
async def get_buscar_organos(
    q: SafeStr = Query(max_length=200, description="Parte del nombre del órgano"),
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[OrganoCandidato]:
    """Un término de menos de tres caracteres devuelve lista vacía, no un 422:
    el campo pregunta en cada tecla, como la paleta de búsqueda."""
    try:
        return await run_db(buscar_organos, _user_id(ctx), q, organization_id=organization_id)
    except _RECHAZO_DE_ORGANIZACION as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.delete(
    "/cuentas/por-organo",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dejar de seguir un órgano: lo quita de su cuenta, o la cuenta si era el único",
    responses={404: {"description": "Ninguna cuenta de la organización tiene ese órgano"}},
)
async def delete_organo_seguido(
    organo: SafeStr = Query(min_length=1, max_length=500),
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> None:
    """La inversa de ``POST /cuentas`` con ``organo``: la estrella de Mercado.

    Por nombre y no por id porque el nombre del botón es la grafía del
    expediente, y casarla con el órgano de la cuenta exige plegar, que es cosa
    del servidor.
    """
    try:
        ok = await run_db(
            dejar_de_seguir_organo, _user_id(ctx), organo, organization_id=organization_id
        )
    except _RECHAZO_DE_ORGANIZACION as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Ninguna cuenta sigue ese órgano.")


@router.get(
    "/cuentas/{cuenta_id}",
    summary="Ficha de una cuenta: sus órganos, publicaciones, vencimientos y oportunidades",
    responses={404: {"description": "La cuenta no es de tu organización"}},
)
async def get_ficha_cuenta(
    cuenta_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> FichaCuenta:
    try:
        ficha = await run_db(
            ficha_cuenta, _user_id(ctx), cuenta_id, organization_id=organization_id
        )
    except _RECHAZO_DE_ORGANIZACION as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if ficha is None:
        raise HTTPException(status_code=404, detail=_NO_EXISTE)
    return ficha


@router.patch(
    "/cuentas/{cuenta_id}",
    summary="Renombrar una cuenta o cambiar su nota",
    responses={
        404: {"description": "La cuenta no es de tu organización"},
        409: {"description": "Otra cuenta ya se llama así"},
    },
)
async def patch_cuenta(
    cuenta_id: int,
    body: CuentaObjetivoUpdate,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> CuentaObjetivo:
    try:
        cuenta = await run_db(
            editar_cuenta,
            _user_id(ctx),
            cuenta_id,
            nombre=body.nombre,
            nota=body.nota,
            cambiar_nota="nota" in body.model_fields_set,
            organization_id=organization_id,
        )
    except _RECHAZO_DE_ORGANIZACION as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except _CONFLICTO_DE_CUENTA as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if cuenta is None:
        raise HTTPException(status_code=404, detail=_NO_EXISTE)
    return cuenta


@router.post(
    "/cuentas/{cuenta_id}/organos",
    summary="Añadir órganos a una cuenta",
    responses={
        404: {"description": "La cuenta no es de tu organización"},
        409: {"description": "Algún órgano ya es de otra cuenta"},
    },
)
async def post_organos_de_cuenta(
    cuenta_id: int,
    body: CuentaOrganosAdd,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> CuentaObjetivo:
    """Todo o nada, e idempotente para los órganos que ya eran de esta cuenta."""
    try:
        cuenta = await run_db(
            anadir_organos,
            _user_id(ctx),
            cuenta_id,
            organos=body.organos,
            organization_id=organization_id,
        )
    except _RECHAZO_DE_ORGANIZACION as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except _CONFLICTO_DE_CUENTA as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if cuenta is None:
        raise HTTPException(status_code=404, detail=_NO_EXISTE)
    return cuenta


@router.delete(
    "/cuentas/{cuenta_id}/organos/{cuenta_organo_id}",
    summary="Quitar un órgano de una cuenta",
    responses={
        404: {"description": "La cuenta o el órgano no son de tu organización"},
        409: {"description": "Es el único órgano de la cuenta"},
    },
)
async def delete_organo_de_cuenta(
    cuenta_id: int,
    cuenta_organo_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> CuentaObjetivo:
    """Devuelve la cuenta como queda. Quitar el último órgano es un 409: una
    cuenta sin órganos no avisaría de nada, y para eso se deja de seguir."""
    try:
        cuenta = await run_db(
            quitar_organo,
            _user_id(ctx),
            cuenta_id,
            cuenta_organo_id,
            organization_id=organization_id,
        )
    except _RECHAZO_DE_ORGANIZACION as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except _CONFLICTO_DE_CUENTA as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if cuenta is None:
        raise HTTPException(status_code=404, detail="Ese órgano no está en esa cuenta.")
    return cuenta


@router.delete(
    "/cuentas/{cuenta_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dejar de seguir una cuenta",
)
async def delete_cuenta(
    cuenta_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> None:
    """Se lleva sus órganos y las etiquetas aplicadas a la cuenta."""
    try:
        ok = await run_db(
            dejar_de_seguir, _user_id(ctx), cuenta_id, organization_id=organization_id
        )
    except _RECHAZO_DE_ORGANIZACION as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail=_NO_EXISTE)


# ── Etiquetas (F1.6) ────────────────────────────────────────────────────────


@router.get("/etiquetas", summary="Etiquetas de la organización")
async def get_etiquetas(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[Etiqueta]:
    try:
        return await run_db(listar_etiquetas, _user_id(ctx), organization_id=organization_id)
    except _RECHAZO_DE_ORGANIZACION as exc:
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
    except _RECHAZO_DE_ORGANIZACION as exc:
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
    except _RECHAZO_DE_ORGANIZACION as exc:
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
    except _RECHAZO_DE_ORGANIZACION as exc:
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
    except _RECHAZO_DE_ORGANIZACION as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return ResultadoEtiquetado(cambiado=quitada)


@router.post(
    "/etiquetas/por-objeto",
    summary="Etiquetas de varios objetos, para pintar una lista de una vez",
)
async def post_etiquetas_por_objeto(
    objeto_tipo: ObjetoEtiquetable = Body(embed=True),
    # ``SafeStr``: estos ids viajan al ``WHERE`` de la consulta. Con ``str`` a
    # secas, un byte NUL en el cuerpo llegaba a psycopg y salía como 500.
    objeto_ids: list[SafeStr] = Body(default_factory=list, embed=True, max_length=200),
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
    except _RECHAZO_DE_ORGANIZACION as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return EtiquetasPorObjeto(por_objeto=agrupado)
