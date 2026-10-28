"""Admin — revisión humana del dato: duplicados, órganos y verdad del dominio.

Dos colas se llenaban solas y nadie podía vaciarlas desde el producto:

- **Duplicados** (ADR-026). El detector marca ``pending`` el par que no puede
  confirmar (mismo órgano y expediente, CPV distinto; una republicación TED
  sin referencia explícita). Un ``pending`` se esconde de los listados pero
  cuenta en las métricas: hasta que alguien decide, el mismo contrato pesa dos
  veces en la cuota de mercado o desaparece de un listado sin ser duplicado.
- **Órganos** (ADR-032 §C). El resolver encola la grafía que se parece a un
  órgano del maestro pero no lo bastante para fusionarla sola; sus
  licitaciones se quedan sin ``organo_id`` mientras tanto.

Y un panel, ``GET /admin/revision/verdad``: lo que mide cada noche
``scripts/audit_domain_truth.py`` contra sus umbrales calibrados, que hasta
ahora solo llegaba por correo y como artefacto de GitHub Actions.

Sólo administradores de la plataforma, como ``/admin/dlq``: el dato de
licitaciones es común a todas las organizaciones, y no hay «owner» que pueda
decidir por las demás si dos expedientes son el mismo. Cada decisión queda en
``audit_log`` (``dedupe.review_resolved``, ``organo.review_resolved``) con el
id del administrador, nunca su correo (ADR-030 §D).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.identidad import id_vigente
from api.routes.dual_auth import require_admin
from db.audit import log_event
from db.repositories.dedupe import pendientes_count, pendientes_de_revision, resolver_pendiente
from db.repositories.organos import listar_pendientes, revision_pendiente_count
from observability.logging import get_logger
from services.organos import decidir_revision
from services.verdad_dominio import EstadoSeccion, evaluar, medir_bd, resumir
from shared.audit_events import DEDUPE_REVIEW_RESOLVED, ORGANO_REVIEW_RESOLVED
from shared.cache import cache_response, get_cache

log = get_logger(__name__)

router = APIRouter(prefix="/admin/revision", tags=["admin"])

#: La auditoría hace una docena de agregados sobre las tablas núcleo. El dato
#: cambia con cada ingesta (cada 4 h), y nadie decide nada mirando el minuto a
#: minuto: una hora de caché compartida entre administradores basta.
VERDAD_CACHE_TTL_S = 3600


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class DuplicadoPendiente(BaseModel):
    """Un par sin decidir: la fila que se escondería y la canónica que se queda."""

    licitacion_id: str = Field(description="La fila marcada como duplicada.")
    canonical_id: str = Field(description="La fila canónica que se queda.")
    clave_match: str | None = None
    confianza: float
    detectado_en: str | None = None
    titulo: str | None = None
    fuente: str | None = None
    organo: str | None = None
    fecha_publicacion: str | None = None
    importe: float | None = None
    titulo_canonica: str | None = None
    fuente_canonica: str | None = None
    organo_canonica: str | None = None
    fecha_publicacion_canonica: str | None = None
    importe_canonica: float | None = None


class DuplicadosPendientes(BaseModel):
    items: list[DuplicadoPendiente] = Field(default_factory=list)
    total: int = Field(description="Pares pendientes en toda la cola, no solo en esta página.")


class OrganoPendiente(BaseModel):
    """Una grafía que se parece a un órgano del maestro, a la espera de decisión."""

    id: int
    nombre_original: str
    alias_normalizado: str
    dir3: str | None = None
    candidato_organo_id: int | None = None
    candidato_nombre: str | None = None
    score: float = 0.0
    created_at: str | None = None


class OrganosPendientes(BaseModel):
    items: list[OrganoPendiente] = Field(default_factory=list)
    total: int = Field(description="Grafías pendientes en toda la cola, no solo en esta página.")


class RevisionDecision(BaseModel):
    aceptar: bool = Field(
        ...,
        description=(
            "Duplicados: true confirma el par (la fila se esconde de listados y "
            "métricas), false lo rechaza (vuelve a contar). Órganos: true fusiona "
            "la grafía con el candidato, false crea un órgano propio."
        ),
    )


class DuplicadoResuelto(BaseModel):
    licitacion_id: str
    estado: Literal["confirmed", "rejected"]
    detalle: str


class OrganoResuelto(BaseModel):
    id: int
    estado: Literal["accepted", "rejected"]
    organo_id: int
    organo_nuevo: bool = Field(description="True si la grafía quedó como órgano propio.")
    filas_asignadas: int = Field(description="Licitaciones que recibieron el órgano.")
    detalle: str


class VerdadMetrica(BaseModel):
    etiqueta: str
    valor: float | None = None
    unidad: str
    limite: float | None = Field(
        default=None, description="Umbral calibrado; null si el número se informa sin evaluar."
    )
    supera: bool = False
    detalle: str | None = None


class VerdadSeccion(BaseModel):
    clave: str
    titulo: str
    estado: EstadoSeccion
    metricas: list[VerdadMetrica] = Field(default_factory=list)
    error: str | None = None


class VerdadDominio(BaseModel):
    """Lo que mide la auditoría nocturna de verdad del dato, contra sus umbrales."""

    medido_en: str
    secciones: list[VerdadSeccion] = Field(default_factory=list)
    violaciones: list[str] = Field(
        default_factory=list, description="Las mismas frases que manda el correo del cron."
    )


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------


def _txt(valor: Any) -> str | None:
    return None if valor is None else str(valor)


def _num(valor: Any) -> float | None:
    return None if valor is None else float(valor)


def _actor(admin: dict[str, Any]) -> str:
    """Quién decide, como id de usuario (ADR-030 §D). Una API key sin dueño: ``api``."""
    return str(admin.get("user_id") or "api")


def _user_id(admin: dict[str, Any]) -> int | None:
    return int(admin["user_id"]) if admin.get("user_id") is not None else None


#: Nombre del handler de ``GET /analytics/quality`` (``api/routes/analytics.py``):
#: ``cache_response`` usa el nombre de la función como prefijo de la clave.
_FUNCION_CALIDAD = "quality"


def _invalidar_calidad() -> None:
    """Tira la copia cacheada de ``/analytics/quality`` (10 min, compartida).

    Publica el tamaño de las dos colas. Sin esto, quien acaba de vaciar una
    seguiría viendo el número de antes hasta que caducara la caché, y no
    sabría si su decisión se aplicó.
    """
    cache = get_cache("analytics")
    for clave in cache.keys(f"{_FUNCION_CALIDAD}|*"):
        cache.delete(clave)


# ---------------------------------------------------------------------------
# Duplicados
# ---------------------------------------------------------------------------


@router.get(
    "/duplicados", response_model=DuplicadosPendientes, summary="Pares de duplicados sin decidir"
)
async def listar_duplicados(
    limit: int = Query(50, ge=1, le=500),
    _admin: dict[str, Any] = Depends(require_admin),
) -> DuplicadosPendientes:
    def _trabajo() -> DuplicadosPendientes:
        return DuplicadosPendientes(
            items=[
                DuplicadoPendiente(
                    licitacion_id=str(f["licitacion_id"]),
                    canonical_id=str(f["canonical_id"]),
                    clave_match=_txt(f.get("clave_match")),
                    confianza=float(f.get("confianza") or 0.0),
                    detectado_en=_txt(f.get("detectado_en")),
                    titulo=_txt(f.get("titulo")),
                    fuente=_txt(f.get("fuente")),
                    organo=_txt(f.get("organo")),
                    fecha_publicacion=_txt(f.get("fecha_publicacion")),
                    importe=_num(f.get("importe")),
                    titulo_canonica=_txt(f.get("titulo_canonica")),
                    fuente_canonica=_txt(f.get("fuente_canonica")),
                    organo_canonica=_txt(f.get("organo_canonica")),
                    fecha_publicacion_canonica=_txt(f.get("fecha_publicacion_canonica")),
                    importe_canonica=_num(f.get("importe_canonica")),
                )
                for f in pendientes_de_revision(limit)
            ],
            total=pendientes_count(),
        )

    return await run_db(_trabajo)


_DETALLE_DUPLICADO = {
    "confirmed": "Confirmado: la fila sale de listados y métricas; su ficha sigue respondiendo.",
    "rejected": "Rechazado: no es el mismo contrato, y la fila vuelve a contar en todo.",
}


@router.post(
    "/duplicados/{id_externo:path}/resolver",
    response_model=DuplicadoResuelto,
    summary="Confirmar o rechazar un par de duplicados",
    responses={404: {"description": "El par no existe o ya estaba resuelto"}},
)
async def resolver_duplicado(
    body: RevisionDecision,
    response: Response,
    id_externo: str = Path(
        min_length=1, max_length=512, description="La fila marcada como duplicada."
    ),
    admin: dict[str, Any] = Depends(require_admin),
) -> DuplicadoResuelto:
    # `{id_externo:path}`, como el resto de rutas que direccionan un expediente
    # (`tests/test_licitaciones_identificador.py`): un id de PLACSP lleva barras.
    # Un id anterior a la re-key (RFC de identidad PLACSP) resuelve a la fila
    # vigente, después de la autenticación.
    licitacion_id = await id_vigente(id_externo, response)
    actor = _actor(admin)
    cambiado = await run_db(
        resolver_pendiente, licitacion_id, accept=body.aceptar, resolved_by=actor
    )
    if not cambiado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Par inexistente o ya resuelto.",
        )
    estado: Literal["confirmed", "rejected"] = "confirmed" if body.aceptar else "rejected"
    await run_db(
        log_event,
        event_type=DEDUPE_REVIEW_RESOLVED,
        actor=actor,
        user_id=_user_id(admin),
        resource=f"licitacion_duplicada:{licitacion_id}",
        detail=f"estado={estado}",
    )
    await run_db(_invalidar_calidad)
    log.info("dedupe_review_resolved", licitacion_id=licitacion_id, estado=estado)
    return DuplicadoResuelto(
        licitacion_id=licitacion_id, estado=estado, detalle=_DETALLE_DUPLICADO[estado]
    )


# ---------------------------------------------------------------------------
# Órganos
# ---------------------------------------------------------------------------


@router.get(
    "/organos", response_model=OrganosPendientes, summary="Fusiones dudosas de órganos sin decidir"
)
async def listar_organos(
    limit: int = Query(50, ge=1, le=500),
    _admin: dict[str, Any] = Depends(require_admin),
) -> OrganosPendientes:
    def _trabajo() -> OrganosPendientes:
        return OrganosPendientes(
            items=[
                OrganoPendiente(
                    id=int(f["id"]),
                    nombre_original=str(f.get("nombre_original") or ""),
                    alias_normalizado=str(f.get("alias_normalizado") or ""),
                    dir3=_txt(f.get("dir3")),
                    candidato_organo_id=(
                        int(f["candidato_organo_id"])
                        if f.get("candidato_organo_id") is not None
                        else None
                    ),
                    candidato_nombre=_txt(f.get("candidato_nombre")),
                    score=float(f.get("score") or 0.0),
                    created_at=_txt(f.get("created_at")),
                )
                for f in listar_pendientes(limit=limit)
            ],
            total=revision_pendiente_count(),
        )

    return await run_db(_trabajo)


@router.post(
    "/organos/{revision_id}/resolver",
    response_model=OrganoResuelto,
    summary="Fusionar una grafía con su candidato o separarla como órgano propio",
    responses={404: {"description": "La revisión no existe o ya estaba resuelta"}},
)
async def resolver_organo(
    body: RevisionDecision,
    revision_id: int = Path(ge=1),
    admin: dict[str, Any] = Depends(require_admin),
) -> OrganoResuelto:
    actor = _actor(admin)
    decision = await run_db(decidir_revision, revision_id, aceptar=body.aceptar, resolved_by=actor)
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Revisión inexistente o ya resuelta.",
        )
    estado: Literal["accepted", "rejected"] = "accepted" if body.aceptar else "rejected"
    await run_db(
        log_event,
        event_type=ORGANO_REVIEW_RESOLVED,
        actor=actor,
        user_id=_user_id(admin),
        resource=f"organo_review:{revision_id}",
        detail=(f"estado={estado} organo_id={decision.organo_id} filas={decision.filas_asignadas}"),
    )
    await run_db(_invalidar_calidad)
    accion = (
        "Queda como órgano propio" if decision.organo_nuevo else "Fusionada con el órgano candidato"
    )
    return OrganoResuelto(
        id=revision_id,
        estado=estado,
        organo_id=decision.organo_id,
        organo_nuevo=decision.organo_nuevo,
        filas_asignadas=decision.filas_asignadas,
        detalle=f"{accion}; {decision.filas_asignadas} licitaciones asignadas.",
    )


# ---------------------------------------------------------------------------
# Verdad del dato
# ---------------------------------------------------------------------------


def medir_verdad() -> VerdadDominio:
    """Mide, evalúa y resume. Síncrono: corre en el hilo de la caché."""
    datos = medir_bd()
    return VerdadDominio(
        medido_en=datetime.now(UTC).isoformat(timespec="seconds"),
        secciones=[
            VerdadSeccion(
                clave=s.clave,
                titulo=s.titulo,
                estado=s.estado,
                metricas=[
                    VerdadMetrica(
                        etiqueta=m.etiqueta,
                        valor=m.valor,
                        unidad=m.unidad,
                        limite=m.limite,
                        supera=m.supera,
                        detalle=m.detalle,
                    )
                    for m in s.metricas
                ],
                error=s.error,
            )
            for s in resumir(datos)
        ],
        violaciones=evaluar(datos),
    )


@router.get(
    "/verdad",
    response_model=VerdadDominio,
    summary="Auditoría de verdad del dato contra sus umbrales calibrados",
)
@cache_response(ttl=VERDAD_CACHE_TTL_S, namespace="admin", user_scoped=False)
def verdad_dominio(_admin: dict[str, Any] = Depends(require_admin)) -> VerdadDominio:
    """Las secciones de BD de ``scripts/audit_domain_truth.py``, cacheadas una hora.

    La (b), multi-lote, no está: lee ZIP en disco que el servidor de la API no
    tiene. Una sección que no pudo medirse sale con ``estado="error"`` y no
    tumba las demás.
    """
    return medir_verdad()
