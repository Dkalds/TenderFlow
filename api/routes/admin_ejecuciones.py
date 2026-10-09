"""Admin — qué pasó con cada paso del cierre y con la cola de trabajo.

Desde S5.4 cada paso del cierre post-ingesta deja una fila en ``jobs`` con su
estado y su error, justo para que una pasada rota se lea paso a paso en la BD
en vez de reconstruirse del log de un runner efímero. Nadie la leía: en
septiembre de 2026 ``llm_tech_labeling`` falló 62 pasadas seguidas y
``ml_scoring`` 14, y en la consola no había dónde verlo. Esta ruta es esa
lectura.

Solo lectura y solo administradores de la plataforma: el cierre es de la
ingesta, común a todas las organizaciones, y ``error_detail`` es texto de
excepción sin filtrar.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_admin
from db.repositories.jobs import JobsRepository

router = APIRouter(prefix="/admin/ejecuciones", tags=["admin"])

#: Hasta dónde se busca la última ejecución de cada paso. Acota el recorrido de
#: ``jobs`` —la tabla solo crece— y es lo que el resumen puede afirmar: un paso
#: sin filas aquí «no ha corrido en 90 días», no «no ha corrido nunca».
HORIZONTE_DIAS = 90

#: Recorte de ``error_detail``. La columna admite 4.000 caracteres (un traceback
#: entero); en una fila de tabla basta con el tipo y el arranque del mensaje.
_MAX_ERROR = 500

EstadoPaso = Literal["ok", "error", "omitido", "omitido_por_dependencia", "sin_ejecuciones"]


class PasoEjecucion(BaseModel):
    """Un paso del cierre post-ingesta y su historia reciente."""

    paso: str
    #: ``bloqueante`` o ``advisory`` (``scheduler.pipeline_runs.STEP_TIER``).
    #: ``None`` = el paso ya no forma parte del cierre pero aún tiene filas.
    tier: str | None = None
    #: Resultado de la ejecución más reciente dentro del horizonte.
    ultimo_estado: EstadoPaso
    ultima_ejecucion: str | None = None
    ultima_ok: str | None = None
    ultimo_fallo: str | None = None
    ultimo_error: str | None = None
    #: Ejecuciones fallidas dentro de la ventana.
    fallos: int = Field(default=0, ge=0)
    #: Ejecuciones dentro de la ventana que corrieron (bien o mal); las omitidas
    #: por cadencia o por dependencia no cuentan.
    ejecuciones: int = Field(default=0, ge=0)


class TrabajoResumen(BaseModel):
    """Un tipo de trabajo a demanda (ficha del pliego, embeddings, export)."""

    tipo: str
    pendientes: int = Field(default=0, ge=0)
    en_curso: int = Field(default=0, ge=0)
    fallidos: int = Field(default=0, ge=0)
    hechos: int = Field(default=0, ge=0)
    ultimo_fallo: str | None = None
    ultimo_error: str | None = None


class EjecucionesResumen(BaseModel):
    ventana_dias: int
    horizonte_dias: int
    pasos: list[PasoEjecucion] = Field(default_factory=list)
    #: Pasos cuya última ejecución falló. Es el contador de la pestaña.
    pasos_en_error: int = Field(default=0, ge=0)
    trabajos: list[TrabajoResumen] = Field(default_factory=list)
    generado_at: str


def _iso(valor: Any) -> str | None:
    if valor is None:
        return None
    return valor.isoformat() if isinstance(valor, datetime) else str(valor)


def _recortar(error: Any) -> str | None:
    if error is None:
        return None
    texto = str(error)
    return texto if len(texto) <= _MAX_ERROR else texto[: _MAX_ERROR - 1] + "…"


def _estado_publico(estado: str, resultado: str) -> EstadoPaso:
    """Traduce el par (estado de la cola, estado del paso) a uno solo.

    Un ``done`` solo es ``ok`` si el paso dijo que lo fue (o no dijo nada). Lo
    que no se reconoce cae en ``omitido``: ante un valor nuevo es preferible
    «no consta que corriera» a afirmar un ``ok`` que nadie escribió.
    """
    if estado == "failed":
        return "error"
    if resultado in ("ok", ""):
        return "ok"
    if resultado == "skipped_por_dependencia":
        return "omitido_por_dependencia"
    return "omitido"


def componer_resumen(
    filas_pasos: Sequence[Mapping[str, Any]],
    filas_trabajos: Sequence[Mapping[str, Any]],
    *,
    pasos_canonicos: Sequence[str],
    tiers: Mapping[str, str],
    ventana_dias: int,
    horizonte_dias: int,
    ahora: datetime,
) -> EjecucionesResumen:
    """Ordena las filas como el cierre y rellena los pasos que no dejaron ninguna.

    El orden es el de ``CANONICAL_STEPS`` porque es el orden en que se leen las
    dependencias: el paso roto sale antes que los que arrastró. Un paso
    canónico sin filas se publica como ``sin_ejecuciones`` en vez de omitirse
    —«no salió en el informe» no puede significar «no pasó nada»—, y uno que ya
    no es canónico pero aún tiene filas va al final, sin tier.
    """
    por_paso = {str(f["paso"]): f for f in filas_pasos}
    retirados = sorted(p for p in por_paso if p not in set(pasos_canonicos))

    pasos: list[PasoEjecucion] = []
    for nombre in [*pasos_canonicos, *retirados]:
        fila = por_paso.get(nombre)
        if fila is None:
            pasos.append(
                PasoEjecucion(paso=nombre, tier=tiers.get(nombre), ultimo_estado="sin_ejecuciones")
            )
            continue
        pasos.append(
            PasoEjecucion(
                paso=nombre,
                tier=tiers.get(nombre),
                ultimo_estado=_estado_publico(str(fila["estado"]), str(fila["resultado"] or "")),
                ultima_ejecucion=_iso(fila.get("ultima_ejecucion")),
                ultima_ok=_iso(fila.get("ultima_ok")),
                ultimo_fallo=_iso(fila.get("ultimo_fallo")),
                ultimo_error=_recortar(fila.get("ultimo_error")),
                fallos=int(fila.get("fallos") or 0),
                ejecuciones=int(fila.get("ejecuciones") or 0),
            )
        )

    return EjecucionesResumen(
        ventana_dias=ventana_dias,
        horizonte_dias=horizonte_dias,
        pasos=pasos,
        pasos_en_error=sum(p.ultimo_estado == "error" for p in pasos),
        trabajos=[
            TrabajoResumen(
                tipo=str(f["tipo"]),
                pendientes=int(f.get("pendientes") or 0),
                en_curso=int(f.get("en_curso") or 0),
                fallidos=int(f.get("fallidos") or 0),
                hechos=int(f.get("hechos") or 0),
                ultimo_fallo=_iso(f.get("ultimo_fallo")),
                ultimo_error=_recortar(f.get("ultimo_error")),
            )
            for f in filas_trabajos
        ],
        generado_at=ahora.isoformat(),
    )


@router.get(
    "",
    response_model=EjecucionesResumen,
    summary="Pasos del cierre y cola de trabajo: última ejecución y fallos recientes",
)
async def resumen_ejecuciones(
    dias: int = Query(7, ge=1, le=30, description="Ventana del recuento de fallos, en días"),
    _admin: dict[str, Any] = Depends(require_admin),
) -> EjecucionesResumen:
    # Import diferido, como el resto de usos de `scheduler` desde la API: el
    # módulo declara el cierre entero y no hace falta al arrancar.
    from scheduler.pipeline_runs import CANONICAL_STEPS, STEP_TIER
    from shared.jobs import TIPO_PASO_PIPELINE

    ahora = datetime.now(UTC)
    desde = ahora - timedelta(days=dias)
    horizonte = ahora - timedelta(days=HORIZONTE_DIAS)

    def _leer() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        repo = JobsRepository()
        pasos = repo.resumen_por_paso(
            tipo=TIPO_PASO_PIPELINE,
            desde=desde,
            horizonte=horizonte,
            hasta=ahora,
            resultado_ok="ok",
            # Lo escribe `_cierre_por_cola` al descartar los restos de un
            # runner muerto: no es una ejecución del paso.
            ignorar_resultados=("descartado_pasada_anterior",),
        )
        trabajos = repo.resumen_por_tipo(
            excluir_tipo=TIPO_PASO_PIPELINE, desde=desde, horizonte=horizonte, hasta=ahora
        )
        return pasos, trabajos

    filas_pasos, filas_trabajos = await run_db(_leer)
    return componer_resumen(
        filas_pasos,
        filas_trabajos,
        pasos_canonicos=CANONICAL_STEPS,
        tiers=STEP_TIER,
        ventana_dias=dias,
        horizonte_dias=HORIZONTE_DIAS,
        ahora=ahora,
    )


__all__ = ["EjecucionesResumen", "PasoEjecucion", "TrabajoResumen", "componer_resumen", "router"]
