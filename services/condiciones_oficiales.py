"""Condiciones oficiales de PLACSP de un expediente, agrupadas por ámbito (v148).

Lo que el anuncio CODICE publica en ``cac:TenderingTerms`` —criterios de
adjudicación, garantías y solvencia— lo guarda la ingesta en tres tablas
(``db/upsert.py``). Este módulo lo compone para servirlo: un ámbito por
expediente y por lote, con el título del lote y la procedencia declarada.

Es la **fuente primaria** de esos datos. La ficha LLM del pliego
(``services/rag/fact_sheet.py``) los complementa o los cubre cuando faltan,
pero no se mezclan: cada pantalla y cada regla dice de cuál de las dos sale lo
que enseña.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from db.repositories.condiciones_oficiales import CondicionesOficialesRepository
from shared.dto import (
    CondicionesAmbito,
    CondicionesOficiales,
    CriterioOficial,
    GarantiaOficial,
    RequisitoSolvenciaOficial,
)

_repo = CondicionesOficialesRepository()


def _clave_lote(lote_numero: str | None) -> tuple[int, int, str]:
    """Expediente primero; los lotes numéricos por número ("2" antes que "10")."""
    if lote_numero is None:
        return (0, 0, "")
    if lote_numero.isdigit():
        return (1, int(lote_numero), "")
    return (2, 0, lote_numero)


def construir_condiciones(licitacion_id: str, datos: Mapping[str, Any]) -> CondicionesOficiales:
    """Agrupa las filas del repositorio por ámbito. Pura: ni lee ni escribe BD.

    ``datos`` es lo que devuelve ``CondicionesOficialesRepository.get``. Solo
    aparecen los ámbitos con alguna fila: un lote sin condiciones publicadas no
    sale vacío, porque «sin condiciones» ya lo dice su ausencia.
    """
    titulos: Mapping[str, str | None] = datos.get("lotes") or {}
    ambitos: dict[str | None, CondicionesAmbito] = {}

    def ambito(lote_numero: str | None) -> CondicionesAmbito:
        if lote_numero not in ambitos:
            ambitos[lote_numero] = CondicionesAmbito(
                lote_numero=lote_numero,
                lote_titulo=titulos.get(lote_numero) if lote_numero is not None else None,
            )
        return ambitos[lote_numero]

    def campos(fila: Mapping[str, Any], modelo: type[Any]) -> dict[str, Any]:
        return {k: v for k, v in fila.items() if k in modelo.model_fields}

    for fila in datos.get("criterios") or []:
        ambito(fila.get("lote_numero")).criterios.append(
            CriterioOficial.model_validate(campos(fila, CriterioOficial))
        )
    for fila in datos.get("garantias") or []:
        ambito(fila.get("lote_numero")).garantias.append(
            GarantiaOficial.model_validate(campos(fila, GarantiaOficial))
        )
    for fila in datos.get("solvencia") or []:
        ambito(fila.get("lote_numero")).solvencia.append(
            RequisitoSolvenciaOficial.model_validate(campos(fila, RequisitoSolvenciaOficial))
        )

    return CondicionesOficiales(
        licitacion_id=licitacion_id,
        url_publicacion=datos.get("url"),
        actualizado=datos.get("actualizado"),
        ambitos=[ambitos[clave] for clave in sorted(ambitos, key=_clave_lote)],
    )


def condiciones_oficiales(licitacion_id: str) -> CondicionesOficiales | None:
    """Las condiciones oficiales de un expediente, o ``None`` si no existe.

    Una republicación confirmada no tiene anuncio CODICE propio —TED reenvía un
    expediente que el órgano publicó en PLACSP—, así que se leen las del
    original (``services.dedupe.expediente_del_pliego``, la misma regla que la
    ficha del pliego) y el ``licitacion_id`` de la respuesta lo dice.
    """
    from services.dedupe import expediente_del_pliego

    original = expediente_del_pliego(licitacion_id)
    datos = _repo.get(original)
    if not datos["existe"] and original != licitacion_id:
        original = licitacion_id
        datos = _repo.get(licitacion_id)
    if not datos["existe"]:
        return None
    return construir_condiciones(original, datos)
