"""El expediente completo de una licitación, compuesto para consumo externo (MCP interno).

Reúne en un solo dict lo que la ficha del producto enseña repartido: el anuncio,
su canónica (si es una republicación), los lotes, las adjudicaciones, las
condiciones oficiales de CODICE (criterios, solvencia, garantías) y la ficha
extraída del pliego. No sustituye a ``GET /licitaciones/{id}``: esa ruta sigue
devolviendo su propio contrato tipado.
"""

from __future__ import annotations

from typing import Any

from db.repositories import dedupe
from db.repositories.adjudicaciones import AdjudicacionRepository
from db.repositories.condiciones_oficiales import CondicionesOficialesRepository
from db.repositories.identidad import resolver_id_licitacion
from db.repositories.licitaciones import lotes_de
from db.repositories.tender_fact_sheets import TenderFactSheetsRepository
from services.licitaciones import get_licitacion_detail

__all__ = ["expediente_completo"]

#: Columnas que no son datos del expediente: índices de búsqueda, trazas del
#: pipeline, `ml_proba` (no es señal sin modelo activo, D55) y la fecha duplicada.
_COLUMNAS_INTERNAS = frozenset(
    {
        "search_vector",
        "embedding",
        "raw_keywords",
        "filter_version",
        "classifier_model_version",
        "ml_proba",
        "fecha_pub_d",
    }
)


def _fila_del_anuncio(detalle: dict[str, object]) -> dict[str, object]:
    """La fila sin columnas internas ni las sombras ``<col>_ts`` de una fecha que ya va en texto."""
    return {
        k: v
        for k, v in detalle.items()
        if k not in _COLUMNAS_INTERNAS
        and not (k.endswith("_ts") and k.removesuffix("_ts") in detalle)
    }


def expediente_completo(id_externo: str) -> dict[str, Any] | None:
    """Expediente ``id_externo`` con todo lo que cuelga de él, o ``None`` si no existe.

    Claves: ``licitacion`` (la fila del anuncio sin columnas internas),
    ``canonica`` (``id_externo`` del
    anuncio original si este es una republicación, si no ``None``), ``lotes``,
    ``adjudicaciones``, ``criterios``, ``solvencia``, ``garantias`` (condiciones
    oficiales; listas vacías si el anuncio no las publicó) y ``ficha_pliego``
    (la ficha extraída de los pliegos, o ``None`` si aún no hay).
    """
    # Un id anterior a una re-key (`licitaciones_id_anterior`, v163) resuelve
    # a su fila vigente: el dict devuelto lleva el `id_externo` de hoy.
    resuelto = resolver_id_licitacion(id_externo)
    if resuelto is None:
        return None
    id_externo = resuelto.id_externo
    detalle = get_licitacion_detail(id_externo)
    if detalle is None:
        return None
    condiciones = CondicionesOficialesRepository().get(id_externo)
    return {
        "licitacion": _fila_del_anuncio(detalle),
        "canonica": dedupe.canonical_for(id_externo),
        "lotes": lotes_de(id_externo),
        "adjudicaciones": AdjudicacionRepository().list_for_licitacion(id_externo),
        "criterios": condiciones["criterios"],
        "solvencia": condiciones["solvencia"],
        "garantias": condiciones["garantias"],
        "ficha_pliego": TenderFactSheetsRepository().get(id_externo),
    }
