"""Resoluciones de recursos contractuales — TACRC (Fase 5.3, RFC 20260611-1).

El TACRC no produce licitaciones: produce resoluciones que afectan al ciclo
de vida de contratos ya ingeridos (suspensiones, anulaciones de adjudicación,
retroacciones). Este módulo gestiona su persistencia y su integración con la
Fase 4:

- Upsert idempotente sobre ``resoluciones_recurso``
  (``UNIQUE(tribunal, numero_resolucion)``).
- **Vinculación débil** a licitaciones por expediente + órgano normalizado
  (la misma normalización que el dedupe de 5.2). Sin match, la resolución se
  guarda igualmente con ``licitacion_id NULL`` — feed de jurisprudencia
  consultable por sí mismo.
- Una resolución vinculada con sentido ``estimado`` genera un evento
  ``recurso`` en ``contrato_eventos``, visible en la línea de tiempo.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from db.resoluciones import listar_resoluciones, upsert_resoluciones_lote, vincular_pendientes
from observability.logging import get_logger
from services.dedupe import natural_expediente, normalize_organo

log = get_logger(__name__)

SENTIDOS_VALIDOS = ("estimado", "desestimado", "inadmitido", "desistimiento")


@dataclass
class Resolucion:
    numero_resolucion: str
    tribunal: str = "tacrc"
    numero_recurso: str | None = None
    fecha: str | None = None
    expediente: str | None = None
    organo: str | None = None
    sentido: str | None = None  # estimado|desestimado|inadmitido|desistimiento
    url_pdf: str | None = None
    resumen: str | None = None
    licitacion_id: str | None = None


def upsert_resoluciones(items: list[Resolucion]) -> tuple[int, int]:
    """Inserta o actualiza resoluciones. Devuelve (nuevas, actualizadas).

    Idempotente: re-ejecutar con los mismos datos no duplica (invariante §3.2).
    El UPDATE no pisa ``licitacion_id`` ya asignado por la vinculación. El SQL,
    por lotes, vive en :mod:`db.resoluciones`.
    """
    return upsert_resoluciones_lote([asdict(res) for res in items])


def _emparejar(
    pendientes: Sequence[dict[str, Any]], licitaciones: Sequence[dict[str, Any]]
) -> Iterator[tuple[dict[str, Any], str]]:
    """Criterio de la vinculación débil: expediente natural + órgano normalizado.

    El expediente de la resolución debe coincidir con el expediente nacional de
    una licitación (id natural sin namespace). Si la resolución trae órgano,
    además debe coincidir normalizado; sin órgano se exige que el expediente
    sea unívoco. El SQL y la transacción están en
    :func:`db.resoluciones.vincular_pendientes`.
    """
    por_expediente: dict[str, list[dict[str, Any]]] = {}
    for lic in licitaciones:
        por_expediente.setdefault(natural_expediente(lic["id_externo"]), []).append(lic)
    for res in pendientes:
        candidatas = por_expediente.get(str(res["expediente"]).strip(), [])
        organo_res = normalize_organo(res.get("organo"))
        if organo_res:
            matches = [
                lic
                for lic in candidatas
                if normalize_organo(lic.get("organo_contratacion")) == organo_res
            ]
        else:
            matches = candidatas if len(candidatas) == 1 else []
        if len(matches) == 1:
            yield res, str(matches[0]["id_externo"])


def link_unlinked() -> dict[str, int]:
    """Vincula resoluciones sin ``licitacion_id`` por expediente + órgano.

    Matching débil: el expediente de la resolución debe coincidir con el
    expediente nacional de una licitación (id natural sin namespace). Si la
    resolución trae órgano, además debe coincidir normalizado; sin órgano se
    exige que el expediente sea unívoco. Devuelve contadores.
    """
    stats = vincular_pendientes(_emparejar)
    if stats["vinculadas"]:
        log.info("resoluciones_linked", **stats)
    return stats


def resoluciones(
    *,
    organo: str | None = None,
    sentido: str | None = None,
    desde: str | None = None,
    licitacion_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Listado filtrable de resoluciones (feed de jurisprudencia + detail panel)."""
    return listar_resoluciones(
        organo=organo, sentido=sentido, desde=desde, licitacion_id=licitacion_id, limit=limit
    )
