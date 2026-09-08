"""Ruta ``/api/v1/tecnologias`` — el diccionario de tecnologías, editable (C5.6, D28).

Hasta 2026-09 el diccionario vivía sólo en ``config/keywords.py``: añadir una
keyword era un PR, una revisión, un merge y un despliegue. Y como el filtro
decide qué se **persiste** en varias fuentes, una keyword que faltaba no era una
etiqueta que faltaba, era un expediente que no estaba.

Lectura para cualquier usuario autenticado —saber qué se filtra no es
información sensible y ayuda a interpretar el corpus—; escritura sólo admin y
auditada, porque cambia el criterio con el que entra el dato de todo el mundo.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_admin, require_any_auth
from observability.logging import get_logger
from shared.dto import SafeStr

log = get_logger(__name__)

router = APIRouter(prefix="/tecnologias", tags=["tecnologias"])


class KeywordOut(BaseModel):
    """Una keyword del diccionario."""

    id: int | None = None
    tecnologia: str
    keyword: str
    activa: bool = True


class DiccionarioOut(BaseModel):
    """El diccionario vigente y de dónde sale."""

    #: `bd` o `semilla`. Un panel que deja editar sin decir que lo que se aplica
    #: es la semilla —porque la tabla está vacía— hace perder una tarde a quien
    #: no entiende por qué su cambio no hace nada.
    origen: str
    #: Huella del diccionario efectivo: el trozo de `filter_version` que cambia
    #: al editar. Comparar esto con el `filter_version` de una fila dice si se
    #: filtró con este diccionario o con otro.
    huella: str
    items: list[KeywordOut] = Field(default_factory=list)


class ImpactoOut(BaseModel):
    """«Esta keyword añadiría N expedientes de los últimos 90 días»."""

    keyword: str
    dias: int
    #: Expedientes sin tecnología que la keyword etiquetaría. Es la ganancia.
    nuevos: int = 0
    #: Los que ya tienen tecnología. No son ganancia: confirman que la keyword
    #: casa con lo que ya se detecta.
    ya_etiquetados: int = 0


class KeywordBody(BaseModel):
    """Alta o retirada de una keyword."""

    tecnologia: SafeStr = Field(min_length=1, max_length=60)
    keyword: SafeStr = Field(min_length=2, max_length=120)
    #: `False` retira sin borrar: una keyword retirada explica los expedientes
    #: que entraron por ella.
    activa: bool = True


@router.get("", summary="Diccionario de tecnologías vigente")
async def get_diccionario(
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> DiccionarioOut:
    """El diccionario que el filtro está aplicando ahora mismo."""
    from services.tech_dictionary import huella, origen, vigente

    def _leer() -> DiccionarioOut:
        efectivo = vigente(refrescar=True)
        return DiccionarioOut(
            origen=origen(),
            huella=huella(efectivo),
            items=[
                KeywordOut(tecnologia=tecnologia, keyword=palabra, activa=True)
                for tecnologia, palabras in sorted(efectivo.items())
                for palabra in palabras
            ],
        )

    return await run_db(_leer)


@router.get(
    "/impacto",
    summary="Qué añadiría una keyword antes de aplicarla",
    responses={401: {"description": "No autenticado"}},
)
async def get_impacto(
    keyword: str = Query(min_length=2, max_length=120),
    dias: int = Query(90, ge=1, le=730),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> ImpactoOut:
    """Vista previa de impacto (C5.6).

    Es la pregunta que hay que poder responder **antes** de aplicar el cambio.
    Sin ella, ampliar el diccionario es una apuesta, y la que sale mal —una
    keyword demasiado genérica— mete miles de filas de ruido en el corpus y no se
    nota hasta que alguien mira una gráfica rara.
    """
    from services.tech_dictionary import previsualizar

    def _medir() -> dict[str, Any]:
        return dict(previsualizar(keyword, dias=dias))

    return ImpactoOut(**await run_db(_medir))


@router.put(
    "/keywords",
    summary="Añadir o retirar una keyword (solo admin)",
    responses={
        403: {"description": "Requiere admin"},
        422: {"description": "Keyword vacía"},
    },
)
async def put_keyword(
    body: KeywordBody,
    admin: dict[str, Any] = Depends(require_admin),
) -> KeywordOut:
    """Cambia el diccionario **sin desplegar** y deja el impacto en `audit_log`.

    El registro guarda el delta de expedientes, no sólo qué se tocó: seis meses
    después, «se añadió *hcm cloud*» no explica nada y «se añadió *hcm cloud*,
    +38 expedientes en 90 días» sí.

    El cambio mueve `filter_version` para las filas nuevas, así que el linaje
    sigue separando lo filtrado con un criterio de lo filtrado con otro.
    """
    from services.tech_dictionary import guardar_keyword

    def _guardar() -> dict[str, Any]:
        return dict(
            guardar_keyword(
                tecnologia=body.tecnologia,
                keyword=body.keyword,
                activa=body.activa,
                user_id=admin.get("user_id"),
            )
        )

    try:
        fila = await run_db(_guardar)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    log.info(
        "tecnologia_keyword_actualizada",
        tecnologia=body.tecnologia,
        activa=body.activa,
    )
    return KeywordOut(
        id=fila.get("id"),
        tecnologia=str(fila["tecnologia"]),
        keyword=str(fila["keyword"]),
        activa=bool(fila["activa"]),
    )


__all__ = ["router"]
