"""Ruta /api/v1/tecnologias/keywords — el diccionario editable (C5.6, D28).

Añadir «SAP BTP» exigía commit, revisión, merge y despliegue. Ahora es una
petición, con **preview de impacto antes de aplicar** y rastro en `audit_log`.

Solo admin: el diccionario decide qué entra en el universo tecnológico, o sea
qué ve el producto entero. Una keyword demasiado laxa —«cloud»— no rompe nada
visiblemente: mete miles de expedientes irrelevantes y degrada el radar de todo
el mundo a la vez, que es el fallo más caro de detectar.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_admin, require_any_auth
from db.audit import log_event
from db.repositories.tecnologias_keywords import (
    VENTANA_IMPACTO_DIAS,
    TecnologiasKeywordsRepository,
)
from observability.logging import get_logger
from services.tecnologias_diccionario import invalidar, sembrar_desde_semilla, vigente
from shared.dto import SafeStr, StatusOk

log = get_logger(__name__)

router = APIRouter(prefix="/tecnologias/keywords", tags=["tecnologias"])

_repo = TecnologiasKeywordsRepository()


class KeywordOut(BaseModel):
    tecnologia: str
    keyword: str
    activa: bool
    origen: str
    updated_at: str | None = None


class DiccionarioOut(BaseModel):
    """El diccionario vigente y de dónde sale."""

    version: str = Field(description="Hash del contenido; es el `filter_version` del linaje")
    fuente: str = Field(description="`tabla` o `semilla`")
    tecnologias: int
    keywords: int
    items: list[KeywordOut]


class KeywordIn(BaseModel):
    tecnologia: SafeStr
    keyword: SafeStr = Field(min_length=2, max_length=120)


class ImpactoOut(BaseModel):
    keyword: str
    dias: int
    expedientes_nuevos: int


@router.get("", response_model=DiccionarioOut)
async def get_keywords(
    incluir_inactivas: bool = Query(default=False),
    _user: dict[str, Any] = Depends(require_any_auth),
) -> DiccionarioOut:
    """Diccionario vigente, con su versión.

    `fuente` no es cosmético: dice si lo que gobierna el filtro es la tabla o la
    semilla de respaldo. Sin ese campo, un entorno con la tabla vacía se vería
    idéntico a uno configurado, y nadie sabría que sus ediciones no están
    aplicándose porque nunca se sembró.
    """
    diccionario, version = await run_db(vigente)
    filas = await run_db(_repo.listar, incluir_inactivas=incluir_inactivas)
    return DiccionarioOut(
        version=version,
        fuente=("tabla" if filas else "semilla"),
        tecnologias=len(diccionario),
        keywords=sum(len(v) for v in diccionario.values()),
        items=[
            KeywordOut(
                tecnologia=str(f["tecnologia"]),
                keyword=str(f["keyword"]),
                activa=bool(f["activa"]),
                origen=str(f["origen"]),
                updated_at=(str(f["updated_at"]) if f.get("updated_at") else None),
            )
            for f in filas
        ],
    )


@router.get("/impacto", response_model=ImpactoOut)
async def get_impacto(
    keyword: str = Query(min_length=2, max_length=120),
    dias: int = Query(default=VENTANA_IMPACTO_DIAS, ge=1, le=365),
    _admin: dict[str, Any] = Depends(require_admin),
) -> ImpactoOut:
    """«Esta keyword añadiría N expedientes de los últimos 90 días» (D28).

    Cuenta solo los que **aún no tienen tecnología**: lo que importa es qué
    *añade*, no cuántos la mencionan. «SAP» aparece en miles de expedientes que
    ya están dentro, y ese número no ayudaría a decidir nada.
    """
    return ImpactoOut(**await run_db(_repo.impacto, keyword, dias=dias))


@router.put("", response_model=DiccionarioOut)
async def put_keyword(
    body: KeywordIn,
    admin: dict[str, Any] = Depends(require_admin),
) -> DiccionarioOut:
    """Añade (o reactiva) una keyword. Queda auditada **con su impacto**.

    El impacto se mide **antes** de escribir: después, los expedientes ya
    tendrían tecnología asignada en cuanto pasara la siguiente ingesta y el
    número dejaría de ser reconstruible. Es el dato que convierte el registro de
    auditoría en algo revisable — «se añadió `cloud` y trajo 4.200 expedientes»
    explica por sí solo una degradación posterior del radar.
    """
    impacto = await run_db(_repo.impacto, body.keyword)
    version_antes = (await run_db(vigente))[1]
    await run_db(
        _repo.upsert,
        tecnologia=str(body.tecnologia),
        keyword=str(body.keyword),
        activa=True,
        origen="manual",
        user_id=admin.get("user_id"),
    )
    invalidar()
    _diccionario, version_despues = await run_db(vigente, forzar=True)
    await run_db(
        log_event,
        event_type="tecnologias_keyword.added",
        user_key=str(admin.get("user_id", "")),
        resource=f"tecnologia:{body.tecnologia}",
        detail={
            "keyword": str(body.keyword),
            "expedientes_nuevos_estimados": impacto["expedientes_nuevos"],
            "dias": impacto["dias"],
            "filter_version_antes": version_antes,
            "filter_version_despues": version_despues,
        },
    )
    return await get_keywords(incluir_inactivas=False, _user=admin)


@router.delete("", response_model=DiccionarioOut)
async def delete_keyword(
    tecnologia: str = Query(min_length=1, max_length=80),
    keyword: str = Query(min_length=2, max_length=120),
    admin: dict[str, Any] = Depends(require_admin),
) -> DiccionarioOut:
    """Retira una keyword. **Desactiva, no borra**: la decisión es revisable."""
    version_antes = (await run_db(vigente))[1]
    if not await run_db(_repo.desactivar, tecnologia=tecnologia, keyword=keyword):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Esa keyword no está activa en esa tecnología.",
        )
    invalidar()
    _diccionario, version_despues = await run_db(vigente, forzar=True)
    await run_db(
        log_event,
        event_type="tecnologias_keyword.removed",
        user_key=str(admin.get("user_id", "")),
        resource=f"tecnologia:{tecnologia}",
        detail={
            "keyword": keyword,
            "filter_version_antes": version_antes,
            "filter_version_despues": version_despues,
        },
    )
    return await get_keywords(incluir_inactivas=False, _user=admin)


@router.post("/sembrar", response_model=StatusOk)
async def post_sembrar(
    admin: dict[str, Any] = Depends(require_admin),
) -> StatusOk:
    """Vuelca en la tabla las keywords de la semilla que falten. Idempotente.

    **No reactiva** lo que alguien desactivó a mano: si lo hiciera, cada
    resiembra desharía en silencio una decisión del equipo y la tabla dejaría de
    gobernar de verdad.
    """
    insertadas = await run_db(sembrar_desde_semilla)
    await run_db(
        log_event,
        event_type="tecnologias_keyword.seeded",
        user_key=str(admin.get("user_id", "")),
        resource="tecnologias_keywords",
        detail={"insertadas": insertadas},
    )
    return StatusOk(status="ok")
