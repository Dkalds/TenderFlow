"""El dossier de decisión de una licitación, en PDF, antes de abrir la oportunidad.

Es el hermano de la ficha de la oportunidad (``services.pursuits.ficha_pdf``)
para la pregunta anterior: ¿nos presentamos? Lleva el expediente, si la
organización cumple lo que pide, contra quién competiría y qué ha hecho ya con
ese órgano y en ese CPV. Usa el mismo renderizador y sus dos reglas: un bloque
sin datos se omite con nota y cada bloque dice de dónde sale
(``services/ficha_pdf.py``).

La organización llega **ya resuelta** por la ruta (``require_organization``);
el checklist la vuelve a comprobar con ``alcance_resuelto``.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from db.repositories.licitaciones import LicitacionRepository
from observability.logging import get_logger
from services.competitive.competencia_esperada import bloque_ficha, competencia_esperada
from services.competitive.historial_propio import HistorialPropio, ResumenPropio, historial_propio
from services.ficha_pdf import BloqueFicha, FichaOportunidad, construir_pdf
from services.go_no_go import GoNoGoChecklist, checklist_de_licitacion

log = get_logger(__name__)

_lic_repo = LicitacionRepository()

_VEREDICTO = {"cumple": "Cumple", "no_cumple": "No cumple", "desconocido": "Sin dato"}


def _euros(valor: object) -> str:
    if isinstance(valor, int | float | Decimal):
        return f"{float(valor):,.2f} €"
    return "—"


def _texto(valor: object, vacio: str = "—") -> str:
    return str(valor) if valor not in (None, "") else vacio


def _bloque_expediente(fila: Mapping[str, object]) -> BloqueFicha:
    base = fila.get("importe_base_sin_iva")
    importe = (
        ("Presupuesto base sin IVA", _euros(base))
        if base is not None
        else ("Importe publicado (base desconocida)", _euros(fila.get("importe")))
    )
    return BloqueFicha(
        titulo="Expediente",
        filas=[
            ("Órgano", _texto(fila.get("organo_contratacion"))),
            ("Identificador", str(fila.get("id_externo"))),
            ("Estado", _texto(fila.get("estado"))),
            importe,
            ("Fecha límite", _texto(fila.get("fecha_limite"), "sin publicar")[:10]),
            ("CPV", _texto(fila.get("cpv"))),
        ],
        procedencia="Publicado por el órgano de contratación.",
    )


def _bloque_checklist(checklist: GoNoGoChecklist | None) -> BloqueFicha:
    titulo = "¿Cumplimos lo que piden?"
    if checklist is None:
        return BloqueFicha(
            titulo=titulo, nota_vacio="No se pudo calcular el checklist al generar el documento."
        )
    if checklist.total_requisitos == 0:
        return BloqueFicha(
            titulo=titulo,
            nota_vacio=(
                "Ni la ficha del pliego ni las condiciones oficiales traen requisitos "
                "con los que comparar todavía."
            ),
        )
    origenes = []
    if checklist.extraction_version:
        origenes.append(f"ficha del pliego ({checklist.extraction_version})")
    if checklist.usa_condiciones_oficiales:
        origenes.append("condiciones oficiales de PLACSP")
    fuente = ", ".join(origenes) or "requisitos del expediente"
    return BloqueFicha(
        titulo=titulo,
        filas=[
            *[(f.etiqueta, _VEREDICTO[f.veredicto]) for f in checklist.familias],
            (
                "Requisitos",
                f"{checklist.cumple} cumple · {checklist.no_cumple} no cumple · "
                f"{checklist.desconocido} sin dato",
            ),
        ],
        procedencia=(
            f"{fuente[0].upper()}{fuente[1:]} contra la "
            "capacidad declarada por la organización. «Sin dato» no es «cumple»."
        ),
    )


def _fila_resumen(etiqueta: str, resumen: ResumenPropio) -> tuple[str, str]:
    if resumen.expedientes == 0:
        return etiqueta, "Ninguna adjudicación"
    ganadas = "ganada" if resumen.expedientes == 1 else "ganadas"
    texto = f"{resumen.expedientes} {ganadas} · {_euros(resumen.importe)}"
    if resumen.baja_mediana_pct is not None:
        texto += f" · baja mediana {resumen.baja_mediana_pct:.1f} % (n={resumen.bajas_n})"
    return etiqueta, texto


def _bloque_historial(historial: HistorialPropio | None) -> BloqueFicha:
    titulo = "Nuestro historial aquí"
    if historial is None:
        return BloqueFicha(
            titulo=titulo, nota_vacio="No se pudo leer el historial al generar el documento."
        )
    if not historial.identidad_conocida:
        return BloqueFicha(
            titulo=titulo,
            nota_vacio="La organización no ha declarado su NIF: no se puede reconocer lo que ganó.",
        )
    filas: list[tuple[str, str]] = []
    if historial.con_organo is not None:
        filas.append(_fila_resumen("Con este órgano", historial.con_organo))
    if historial.en_cpv4 is not None:
        filas.append(_fila_resumen(f"En el CPV {historial.cpv4}", historial.en_cpv4))
    if historial.oportunidades is not None and historial.oportunidades.total:
        o = historial.oportunidades
        filas.append(
            (
                "Oportunidades con el órgano",
                f"{o.total} en total · {o.presentadas} presentadas · {o.ganadas} ganadas · "
                f"{o.perdidas} perdidas",
            )
        )
    return BloqueFicha(
        titulo=titulo,
        filas=filas,
        procedencia="Adjudicaciones publicadas a los NIF de la organización y sus oportunidades.",
        nota_vacio="El expediente no tiene órgano ni CPV con los que buscar historial.",
    )


def dossier_pdf(user_id: int, licitacion_id: str, *, organization_id: int) -> bytes | None:
    """El dossier en PDF; ``None`` si el expediente no existe.

    Cada bloque calculado va en su ``try``: un fallo en uno no tumba el papel,
    el bloque lo dice con su nota.
    """
    fila = _lic_repo.get_by_id(licitacion_id)
    if fila is None:
        return None

    try:
        checklist: GoNoGoChecklist | None = checklist_de_licitacion(
            user_id, licitacion_id, organization_id=organization_id
        )
    except Exception:
        log.warning("dossier_checklist_error", licitacion_id=licitacion_id, exc_info=True)
        checklist = None

    try:
        competencia = competencia_esperada(licitacion_id, organization_id=organization_id)
        bloque_competencia = (
            bloque_ficha(competencia)
            if competencia is not None
            else BloqueFicha(titulo="Competencia esperada", nota_vacio="Sin segmento que medir.")
        )
    except Exception:
        log.warning("dossier_competencia_error", licitacion_id=licitacion_id, exc_info=True)
        bloque_competencia = BloqueFicha(
            titulo="Competencia esperada",
            nota_vacio="No se pudo calcular la competencia esperada al generar el documento.",
        )

    try:
        historial = historial_propio(licitacion_id, organization_id=organization_id)
    except Exception:
        log.warning("dossier_historial_error", licitacion_id=licitacion_id, exc_info=True)
        historial = None

    return construir_pdf(
        FichaOportunidad(
            titulo=str(fila.get("titulo") or licitacion_id),
            subtitulo="Dossier de decisión: ¿nos presentamos?",
            bloques=[
                _bloque_expediente(fila),
                _bloque_checklist(checklist),
                bloque_competencia,
                _bloque_historial(historial),
            ],
        )
    )
