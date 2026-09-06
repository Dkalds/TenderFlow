"""F2.8 — poner dos o tres pliegos uno al lado del otro.

El comparador de Detalle compara **metadatos del anuncio** —importe, plazo,
CCAA—, que es lo que ya se ve en la tabla. Lo que decide entre dos pliegos no
es eso: es si uno exige una solvencia que no tenemos, si el otro reparte 60
puntos en juicio de valor, o si uno pide una garantía del 5 % y el otro del 3.

Determinista y sin LLM
----------------------
La comparación es una tabla de las familias de la ficha, tal como se
extrajeron. No hay síntesis: el usuario compara, no le comparan. Una familia
vacía **se muestra vacía** —«este pliego no publica criterios ponderados»— en
vez de omitirse, porque el hueco es la mitad de la comparación: saber que uno
de los dos no dice nada de solvencia técnica es exactamente lo que hay que ver.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shared.tender_facts import TenderFactSheet

__all__ = ["MAX_EXPEDIENTES", "ComparacionFichas", "FilaComparacion", "comparar"]

#: Tope de expedientes a comparar. Tres caben en una tabla legible y es lo que
#: el plan fija; con cuatro columnas la tabla deja de leerse en pantalla y
#: empieza a necesitar scroll horizontal, que es donde se pierde la
#: comparación.
MAX_EXPEDIENTES = 3

#: Familias que se comparan, en el orden en que se decide: primero lo que
#: excluye (solvencia), luego lo que puntúa (criterios), luego lo que cuesta
#: (garantías, penalidades) y al final el detalle.
FAMILIAS: tuple[tuple[str, str], ...] = (
    ("lots", "Lotes"),
    ("award_criteria", "Criterios de adjudicación"),
    ("price_formula", "Fórmula del precio"),
    ("technical_solvency", "Solvencia técnica"),
    ("economic_solvency", "Solvencia económica"),
    ("certifications", "Certificaciones exigidas"),
    ("team_requirements", "Equipo exigido"),
    ("required_documents", "Documentos a presentar"),
    ("guarantees", "Garantías"),
    ("penalties", "Penalidades"),
    ("service_levels", "Niveles de servicio"),
    ("subcontracting", "Subcontratación"),
    ("extensions", "Prórrogas"),
    ("rate_cards", "Tarifas por perfil"),
    ("budget_breakdown", "Desglose del presupuesto"),
    ("critical_deadlines", "Plazos críticos"),
    ("technologies", "Tecnologías"),
)


class CeldaComparacion(BaseModel):
    """Lo que una ficha dice de una familia."""

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    #: Cuántos hechos trae la familia. `0` = el pliego no lo publica, o el
    #: extractor no lo encontró; las dos cosas se ven igual en pantalla y las
    #: dos significan «aquí no hay dato», que es lo que el usuario necesita.
    n: int = Field(ge=0)
    #: Hasta tres descripciones, para no convertir la celda en un muro.
    ejemplos: list[str] = Field(default_factory=list)


class FilaComparacion(BaseModel):
    """Una familia, con lo que dice cada pliego."""

    model_config = ConfigDict(extra="forbid")

    familia: str
    etiqueta: str
    celdas: list[CeldaComparacion] = Field(default_factory=list)
    #: `True` si ningún pliego publica nada de esta familia. La UI puede
    #: plegarla, pero **no se omite**: que los tres callen sobre la solvencia
    #: técnica es información.
    vacia_en_todos: bool = False


class ComparacionFichas(BaseModel):
    """La tabla completa."""

    model_config = ConfigDict(extra="forbid")

    licitacion_ids: list[str] = Field(default_factory=list)
    filas: list[FilaComparacion] = Field(default_factory=list)
    #: Expedientes pedidos que no tienen ficha extraída todavía. Se declaran
    #: para que una columna en blanco no se confunda con un pliego que no
    #: exige nada.
    sin_ficha: list[str] = Field(default_factory=list)


def _descripcion(item: Any) -> str:
    """El texto de un hecho, sea de la familia que sea.

    Todas las familias heredan de ``FactItem`` y tienen ``description``; las
    que además tienen ``name`` lo anteponen, porque es lo que identifica el
    criterio o el documento concreto.
    """
    nombre = getattr(item, "name", None) or getattr(item, "role", None)
    descripcion = str(getattr(item, "description", "") or "").strip()
    if nombre:
        return f"{nombre}: {descripcion}" if descripcion else str(nombre)
    return descripcion


def comparar(fichas: dict[str, TenderFactSheet | None]) -> ComparacionFichas:
    """Compara hasta ``MAX_EXPEDIENTES`` fichas, familia a familia.

    ``fichas`` mapea ``licitacion_id`` a su ficha, o a ``None`` si todavía no
    se ha extraído. El orden de las columnas es el de las claves recibidas:
    quien pide la comparación decide qué expediente va primero, y reordenarlas
    aquí le rompería la lectura.
    """
    ids = list(fichas)[:MAX_EXPEDIENTES]
    sin_ficha = [i for i in ids if fichas.get(i) is None]

    filas: list[FilaComparacion] = []
    for familia, etiqueta in FAMILIAS:
        celdas: list[CeldaComparacion] = []
        for licitacion_id in ids:
            ficha = fichas.get(licitacion_id)
            items: list[Any] = list(getattr(ficha, familia, []) or []) if ficha else []
            celdas.append(
                CeldaComparacion(
                    licitacion_id=licitacion_id,
                    n=len(items),
                    ejemplos=[_descripcion(i)[:300] for i in items[:3]],
                )
            )
        filas.append(
            FilaComparacion(
                familia=familia,
                etiqueta=etiqueta,
                celdas=celdas,
                vacia_en_todos=all(c.n == 0 for c in celdas),
            )
        )

    return ComparacionFichas(licitacion_ids=ids, filas=filas, sin_ficha=sin_ficha)
