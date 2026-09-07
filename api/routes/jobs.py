"""Ruta /api/v1/jobs — consulta del trabajo encolado (plan 2026-09 v2, S5.2).

Solo lectura por id. **No hay endpoint genérico para encolar**, y es
deliberado: cada tipo de job se pide desde la ruta del recurso que lo produce
(``…/ficha-pliego/extract-async``, ``…/embeddings-async``,
``/exports/download``), que es donde vive la autorización de ese recurso. Un
``POST /jobs`` con el tipo en el body sería una superficie por la que pedir
trabajo saltándose esas comprobaciones.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, status

from api.concurrency import run_db
from api.tenancy import require_organization
from shared.dto import JobEstadoDTO, JobResultado
from shared.jobs import Job

router = APIRouter(prefix="/jobs", tags=["jobs"])


def a_dto(job: Job) -> JobEstadoDTO:
    """Traduce el job de dominio a su forma publicada.

    Vive aquí y no en ``shared/jobs.py`` para que la capa de dominio no dependa
    del contrato HTTP: la cola la consume también el worker, que no publica
    nada.
    """
    return JobEstadoDTO(
        id=job.id,
        tipo=job.tipo,
        estado=job.estado,
        intentos=job.intentos,
        run_after=job.run_after,
        created_at=job.created_at,
        updated_at=job.updated_at,
        resultado=None if job.resultado is None else JobResultado(**job.resultado),
        error_detail=job.error_detail,
    )


@router.get(
    "/{job_id}",
    response_model=JobEstadoDTO,
    summary="Estado de un trabajo encolado",
    responses={
        401: {"description": "Autenticación inválida"},
        404: {"description": "El trabajo no existe o no es de esta organización"},
    },
)
async def get_job(
    job_id: int = Path(ge=1, description="Identificador devuelto por el 202 que lo encoló"),
    ctx: dict[str, Any] = Depends(require_organization()),
) -> JobEstadoDTO:
    """Devuelve el estado del trabajo: si sigue en cola, si falló o su resultado.

    El trabajo de otra organización responde **404 y no 403**: un 403 confirma
    que ese id existe, y con ids correlativos eso convierte la ruta en un
    contador del trabajo ajeno. Lo mismo vale para el trabajo del sistema (los
    pasos del cierre de la pasada, sin organización): no se sirve a nadie por
    aquí.
    """
    from shared.jobs import obtener

    job = await run_db(obtener, job_id)
    if job is None or job.organization_id != int(ctx["organization_id"]):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trabajo {job_id} no encontrado.",
        )
    return a_dto(job)


__all__ = ["a_dto", "router"]
