"""La ficha del pliego y el checklist de cada licitación del resumen diario (B3).

El correo diario (``services/email_digest.py``) enseña, por licitación, hasta
tres requisitos de solvencia y el veredicto del checklist frente a la
capacidad de la organización. Este módulo los calcula y se los entrega ya
hechos en la clave ``pliego`` de cada licitación; las funciones de formato
siguen siendo puras.

No hay una segunda implementación del contraste: el veredicto sale de
:func:`services.go_no_go.evaluate`, la misma función pura que responde en la
pestaña Decisión de la oportunidad, con las mismas reglas —ningún ``cumple``
sin evidencia, la publicación oficial de PLACSP manda sobre la ficha LLM en su
familia—. Lo único que cambia es cómo se cargan los datos: en lote, con una
consulta por tabla para todas las licitaciones del correo
(``TenderFactSheetsRepository.get_many``,
``CondicionesOficialesRepository.solvencia_de``), y solo para las que el
correo va a enseñar (:func:`services.email_digest.visibles_por_bloque`).

Dos diferencias con la pestaña, deliberadas:

- **Sin lote.** Una regla avisa del expediente, no de un lote: los requisitos
  de cada lote salen con su número delante, como en el checklist sin lote.
- **Sin seguir republicaciones.** La ficha y las condiciones se leen por el
  ``id_externo`` de la licitación avisada; si es una republicación de TED sin
  ficha propia, el correo no enseña requisitos y la pestaña sí lo hará.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from pydantic import ValidationError

from db.repositories.condiciones_oficiales import CondicionesOficialesRepository
from db.repositories.organization_capabilities import OrganizationCapabilitiesRepository
from db.repositories.tender_fact_sheets import TenderFactSheetsRepository
from observability.logging import get_logger
from services.condiciones_oficiales import construir_condiciones
from services.email_digest import (
    MAX_REQUISITOS,
    BloqueDigest,
    ChecklistDigest,
    PliegoDigest,
    RequisitoDigest,
    visibles_por_bloque,
)
from services.go_no_go import ChecklistVeredicto, GoNoGoChecklist, evaluate
from shared.dto import CondicionesOficiales, OrganizationCapabilities
from shared.tender_facts import TenderFactSheetRecord

log = get_logger(__name__)

_FAMILIAS_SOLVENCIA = ("economic_solvency", "technical_solvency")


def capacidad_declarada(capacidad: OrganizationCapabilities) -> bool:
    """¿Declaró la organización algo contra lo que contrastar?

    Sin nada, todo requisito sale ``desconocido`` y enseñar el veredicto sería
    decir lo mismo con más palabras: se enseñan los requisitos y se calla.
    """
    return bool(
        capacidad.certificaciones
        or capacidad.facturacion
        or capacidad.referencias
        or capacidad.perfiles_equipo
    )


def _peor(veredictos: list[ChecklistVeredicto]) -> ChecklistVeredicto:
    """``no_cumple`` > ``desconocido`` > ``cumple``, como cada familia."""
    if "no_cumple" in veredictos:
        return "no_cumple"
    if "desconocido" in veredictos:
        return "desconocido"
    return "cumple"


def resumen_de_checklist(
    checklist: GoNoGoChecklist, *, con_capacidad: bool, max_requisitos: int = MAX_REQUISITOS
) -> PliegoDigest | None:
    """Lo que el correo cuenta de un checklist. Pura.

    - **Requisitos:** los de solvencia económica y técnica que el pliego (o la
      publicación oficial) trae de verdad, hasta ``max_requisitos``. Los avisos
      de «la ficha no extrajo nada» de una familia no son requisitos y no
      salen. Con capacidad declarada, cada uno lleva su veredicto.
    - **Checklist:** el peor veredicto de todos los requisitos extraídos —las
      cuatro familias, no solo la solvencia— y su recuento. Solo si se puede
      calcular: hay requisitos y hay capacidad contra la que contrastarlos.

    ``None`` si no hay nada que contar.
    """
    requisitos: list[RequisitoDigest] = [
        RequisitoDigest(
            familia=familia.etiqueta,
            texto=item.requisito,
            veredicto=item.veredicto if con_capacidad else None,
        )
        for familia in checklist.familias
        if familia.familia in _FAMILIAS_SOLVENCIA and not familia.sin_hechos
        for item in familia.items
    ][:max_requisitos]

    extraidos = [
        item.veredicto
        for familia in checklist.familias
        if not familia.sin_hechos
        for item in familia.items
    ]
    resumen: ChecklistDigest | None = None
    if con_capacidad and extraidos:
        resumen = ChecklistDigest(
            veredicto=_peor(extraidos),
            cumple=extraidos.count("cumple"),
            no_cumple=extraidos.count("no_cumple"),
            desconocido=extraidos.count("desconocido"),
        )
    if not requisitos and resumen is None:
        return None
    return PliegoDigest(requisitos=requisitos, checklist=resumen)


def _ficha(raw: dict[str, object] | None, licitacion_id: str) -> TenderFactSheetRecord | None:
    if not raw:
        return None
    try:
        return TenderFactSheetRecord.model_validate(raw)
    except ValidationError:
        # Una ficha que no valida no puede tumbar el correo de la mañana: esa
        # licitación sale sin requisitos y queda en el log.
        log.warning("digest_ficha_invalida", licitacion_id=licitacion_id)
        return None


def _oficiales(licitacion_id: str, filas: list[dict[str, object]]) -> CondicionesOficiales | None:
    if not filas:
        return None
    fechas = [str(f["fecha_extraccion"]) for f in filas if f.get("fecha_extraccion")]
    return construir_condiciones(
        licitacion_id,
        {"solvencia": filas, "actualizado": max(fechas) if fechas else None},
    )


def con_pliegos(bloques: list[BloqueDigest], *, hoy: date | None = None) -> list[BloqueDigest]:
    """Los mismos bloques, con ``pliego`` en cada licitación visible que lo tenga.

    Los avisos (``es_aviso``) se quedan como estaban: hablan de un cambio en
    algo que la persona ya sigue, no de una licitación nueva por decidir. Las
    licitaciones que el correo no va a enseñar tampoco se cargan.
    """
    cupo = visibles_por_bloque(bloques)
    visibles: list[tuple[str, int | None]] = [
        (str(lic.get("id_externo") or ""), bloque.organization_id)
        for bloque, n in zip(bloques, cupo, strict=True)
        if not bloque.es_aviso
        for lic in bloque.licitaciones[:n]
    ]
    ids = sorted({lic_id for lic_id, _ in visibles if lic_id})
    if not ids:
        return bloques

    fichas = TenderFactSheetsRepository().get_many(ids)
    solvencia = CondicionesOficialesRepository().solvencia_de(ids)
    repo_capacidad = OrganizationCapabilitiesRepository()
    capacidades: dict[int | None, OrganizationCapabilities] = {None: OrganizationCapabilities()}
    for _, org in visibles:
        if org is not None and org not in capacidades:
            capacidades[org] = OrganizationCapabilities.model_validate(repo_capacidad.get(org))

    dia = hoy or date.today()
    resultado: list[BloqueDigest] = []
    for bloque, n in zip(bloques, cupo, strict=True):
        if bloque.es_aviso or n == 0:
            resultado.append(bloque)
            continue
        capacidad = capacidades[bloque.organization_id]
        con_capacidad = capacidad_declarada(capacidad)
        licitaciones = list(bloque.licitaciones)
        for i, lic in enumerate(licitaciones[:n]):
            lic_id = str(lic.get("id_externo") or "")
            record = _ficha(fichas.get(lic_id), lic_id)
            oficiales = _oficiales(lic_id, solvencia.get(lic_id, []))
            if record is None and oficiales is None:
                continue
            checklist = evaluate(
                licitacion_id=lic_id,
                # El checklist exige un id ≥ 1. Sin organización (entrada
                # legada) la capacidad es la vacía y el id no se lee: el
                # resumen no lo usa.
                organization_id=bloque.organization_id or 1,
                record=record,
                capabilities=capacidad,
                hoy=dia,
                oficiales=oficiales,
            )
            pliego = resumen_de_checklist(checklist, con_capacidad=con_capacidad)
            if pliego:
                licitaciones[i] = {**lic, "pliego": pliego}
        resultado.append(replace(bloque, licitaciones=licitaciones))
    return resultado
