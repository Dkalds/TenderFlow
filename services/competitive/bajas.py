"""Análisis de bajas: presupuesto de licitación vs importe adjudicado.

Responde "¿cuánto hay que bajar para ganar?" segmentado por empresa, órgano
de contratación o CPV. El presupuesto de referencia es el del LOTE cuando la
adjudicación tiene uno resuelto (v65_lotes), o el del expediente completo si
no — comparar un lote contra el presupuesto de todo el expediente
sobreestima la baja en cualquier procedimiento con más de un lote. Solo
considera pares con presupuesto y adjudicación positivos y descarta
outliers donde el adjudicado supera ese presupuesto en más de un 50%
(errores de fuente o modificados mal atribuidos).

El SQL vive en ``db/repositories/bajas.py`` (ADR-022); aquí queda la regla
de qué base se compara.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from db.repositories.bajas import fila_baja_de_referencia, filas_bajas_agregadas
from db.sql_fragments import (
    BASE_DECLARADA_SQL,
    BASE_MIXTA,
    BASE_SIN_IVA,
    SIN_IVA_CONOCIDO_SQL,
)


def _filtro_de_base(solo_base_declarada: bool) -> tuple[str, str]:
    """Devuelve ``(predicado_sql, etiqueta)`` de la base de comparación (C1.1).

    Dos modos, y el default es el honesto:

    - **Por defecto** (``False``): excluye lo que se SABE que lleva IVA y
      conserva el histórico `desconocido`. Es la corrección disponible hoy — no
      recupera el pasado, pero deja de mezclar lo identificado. La respuesta
      declara ``base: "mixta"``, porque llamarla "sin IVA" sería la misma
      mentira que este ítem vino a quitar, con otra etiqueta.
    - **``solo_base_declarada=True``**: solo filas con base sin IVA declarada.
      Hace verdad un ``base: "sin_iva"`` y hoy devuelve poco: la columna se
      puebla con la re-ingesta, no con la migración `v113`. Cuando la cobertura
      sea suficiente, este pasa a ser el default y el otro modo se retira.
    """
    if solo_base_declarada:
        return BASE_DECLARADA_SQL, BASE_SIN_IVA
    return SIN_IVA_CONOCIDO_SQL, BASE_MIXTA


def bajas_agregadas(
    *,
    group_by: str = "empresa",
    min_contratos: int = 3,
    cpv_prefix: str | None = None,
    ccaa: str | None = None,
    limit: int = 100,
    solo_base_declarada: bool = False,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    importe_min: float | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Baja media/mediana-aproximada por dimensión.

    ``baja_pct`` = (presupuesto - adjudicado) / presupuesto * 100, con
    presupuesto = el del lote si la adjudicación lo tiene resuelto (ver
    :data:`db.sql_fragments.EFFECTIVE_BUDGET_SQL`). Devuelve media,
    mínimo, máximo, nº de contratos e importe total por grupo;
    ``min_contratos`` filtra grupos sin masa estadística.

    Filtros de ámbito (RFC ux-competidores #1), con la MISMA semántica que el
    resto de la página de Competidores (``services/analytics/competitors.py``),
    para que el ranking de bajas y las cards de al lado midan el mismo
    universo:

    - ``fecha_desde``/``fecha_hasta`` acotan la **fecha de adjudicación**
      (ambas incluidas), no la de publicación: una baja existe cuando hay
      adjudicación.
    - ``importe_min`` acota el **presupuesto de la licitación** (``l.importe``),
      el mismo campo que filtra la barra global.
    - ``ccaa`` admite varias separadas por comas, como la barra global. Antes
      se comparaba el CSV entero por igualdad y con dos CCAA no casaba nada.
    """
    filtro_base, base = _filtro_de_base(solo_base_declarada)
    filas = filas_bajas_agregadas(
        group_by=group_by,
        filtro_base=filtro_base,
        min_contratos=min_contratos,
        cpv_prefix=cpv_prefix,
        ccaa=ccaa,
        limit=limit,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        importe_min=importe_min,
    )
    return filas, base


def baja_de_referencia(
    *,
    organo: str | None = None,
    cpv_prefix: str | None = None,
    solo_base_declarada: bool = False,
) -> dict[str, Any]:
    """Baja media y rango en un segmento concreto (órgano y/o CPV).

    Es el dato accionable al preparar una oferta: "en este órgano, para este
    CPV, la baja ganadora media es X%". Devuelve también la distribución de
    ofertas recibidas como indicador de presión competitiva.

    ``base`` en la respuesta declara sobre qué población se calculó: ver
    :func:`_filtro_de_base`. Sin ese campo, la cifra no se puede interpretar.
    """
    filtro_base, base = _filtro_de_base(solo_base_declarada)
    result = fila_baja_de_referencia(filtro_base=filtro_base, organo=organo, cpv_prefix=cpv_prefix)
    result["organo"] = organo
    result["cpv_prefix"] = cpv_prefix
    result["base"] = base
    return result
