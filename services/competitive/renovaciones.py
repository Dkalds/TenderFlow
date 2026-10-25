"""Pipeline de renovaciones: contratos adjudicados que vencen próximamente.

La fecha de fin efectiva se calcula en SQL con esta prioridad:

1. ``licitaciones.fecha_fin`` explícita (solo ~6% de las filas).
2. ``fecha_inicio + duracion`` (unidades CODICE: ANN/MON/DAY).
3. ``fecha_adjudicacion + duracion`` como último recurso.

Un contrato que vence es una oportunidad: o lo defiende el adjudicatario
actual o se lo disputa quien llegue primero a la relicitación.

Aquí quedan los DTOs del contrato API↔web y los dos agregados de la ventana.
El **listado** (``proximas_renovaciones``, con su orden por score de
oportunidad) se movió a ``db/repositories/renovaciones.py`` por ADR-022 y se
re-exporta desde aquí, y el SQL de los dos agregados bajó a ese mismo
módulo el 2026-10-25: aquí queda la definición de «contrato caliente»
(:data:`RIESGO_ALTO`, :data:`DIAS_CALIENTE`) y la forma de la respuesta.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# `proximas_renovaciones` se re-exporta: su SQL se movió a `db/` (ADR-022) pero
# el nombre sigue importándose desde aquí en `services/pursuits_agenda.py`,
# `scheduler/competitor_alerts.py` y la suite. Es un alias, no una capa
# passthrough (ADR-024): los llamadores nuevos deben ir al repository.
from db.repositories.renovaciones import dias_restantes_sql as dias_restantes_sql
from db.repositories.renovaciones import (
    proximas_renovaciones as proximas_renovaciones,
)
from db.repositories.renovaciones import (
    rango_vencimiento_sql as rango_vencimiento_sql,
)

# Los dos agregados aplican el mismo tope que `GET /renovaciones` y que el
# horizonte del scoring de retención (`HORIZONTE_RENOVACIONES_MAX_MESES`, en el
# repositorio): un clamp propio aquí dejaría el resumen y el listado midiendo
# ventanas distintas el día que alguien cambie uno.
from db.repositories.renovaciones import (
    resumen_por_empresa,
    totales_ventana,
)

# FECHA_FIN_SQL se re-exporta por compatibilidad con imports externos.
from services.sql_fragments import FECHA_FIN_SQL as FECHA_FIN_SQL
from services.sql_fragments import TECHNOLOGY_OBSERVED_SQL as TECHNOLOGY_OBSERVED_SQL
from services.sql_fragments import fecha_fin_sql as fecha_fin_sql

# ── Umbrales de "contrato caliente" ───────────────────────────────────────
# Definición canónica y única (ADR-014): vivía duplicada en el cliente
# (`renovaciones/page.tsx` la calculaba sobre una lista truncada a 1000 filas y
# la presentaba como total del dataset). Al vivir aquí, el número que ve el
# usuario es el del dataset completo y hay un solo sitio donde cambiarla.
RIESGO_ALTO = 0.6
DIAS_CALIENTE = 30


# ── DTOs de respuesta ─────────────────────────────────────────────────────
# El contrato API↔web (AGENTS §3.5) exige que la forma viaje en el OpenAPI:
# sin esto las rutas devuelven `dict[str, Any]`, el cliente generado las tipa
# como `{ [key: string]: unknown }` y el frontend reescribe la forma a mano.
# Ver scripts/check_openapi_contract.py.


class Renovacion(BaseModel):
    """Un contrato-adjudicatario con fecha de fin dentro de la ventana.

    Los campos **no llevan default**: la query siempre devuelve todas las
    columnas, así que la clave está siempre presente aunque el valor sea
    ``None``. Ponerles default los marcaría opcionales en el OpenAPI y el
    cliente generado tendría que tratar `undefined` en sitios donde nunca
    ocurre.
    """

    licitacion_id: str
    titulo: str | None
    organo_contratacion: str | None
    cpv: str | None
    ccaa: str | None
    url: str | None
    empresa_id: int | None
    empresa: str | None
    es_ute: int | None
    importe_adjudicado: float | None
    fecha_adjudicacion: str | None
    duracion_valor: float | None
    duracion_unidad: str | None
    fecha_fin_efectiva: str | None
    dias_restantes: int | None
    riesgo_cambio: float | None
    retencion_model_version: int | None
    #: ``real`` si la fuente publicó la fecha de fin; ``estimada_inicio`` o
    #: ``estimada_adjudicacion`` si se calculó con la duración; ``desconocida``
    #: si no hubo con qué. Ver ``db/sql_fragments.py::FECHA_FIN_ORIGEN_SQL``.
    fecha_fin_origen: str | None
    #: Prórroga máxima que declara el pliego, leída de la ficha estructurada.
    #: ``None`` cuando no hay ficha o la cláusula no expresa una duración.
    prorroga_meses: int | None
    #: ``fecha_fin_efectiva`` más la prórroga: el último día en que el contrato
    #: puede seguir vivo sin volver a licitarse.
    fecha_fin_con_prorroga: str | None


def enriquecer_renovaciones(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Añade a cada fila la prórroga leída de la ficha y la fecha fin máxima.

    Se hace aquí y no en SQL porque la cláusula de prórroga es texto con
    evidencia, no un número: interpretarla es dominio, y ``db/`` no debe
    conocer el formato de la ficha. Quita ``ficha_json`` de la fila: es un
    documento entero y no forma parte del contrato de respuesta.
    """
    from services.renovaciones_prorroga import meses_de_prorroga, sumar_meses

    enriquecidas: list[dict[str, Any]] = []
    for row in rows:
        fila = dict(row)
        ficha = fila.pop("ficha_json", None)
        meses = meses_de_prorroga(ficha)
        fila["prorroga_meses"] = meses
        fila["fecha_fin_con_prorroga"] = sumar_meses(fila.get("fecha_fin_efectiva"), meses)
        fila.setdefault("fecha_fin_origen", None)
        enriquecidas.append(fila)
    return enriquecidas


class RenovacionesResult(BaseModel):
    """Respuesta de ``GET /competitive/renovaciones``."""

    items: list[Renovacion] = Field(default_factory=list)
    months_ahead: int


class CarteraEmpresa(BaseModel):
    """Cartera en juego de una empresa dentro de la ventana."""

    empresa_id: int | None
    empresa: str | None
    contratos_venciendo: int
    importe_en_juego: float
    proximo_vencimiento: str | None


class RenovacionesTotales(BaseModel):
    """Totales sobre el dataset completo (no sobre la página servida)."""

    contratos_venciendo: int
    importe_en_juego: float
    importe_alto_riesgo: float
    calientes: int


class RenovacionesResumenResult(BaseModel):
    """Respuesta de ``GET /competitive/renovaciones/resumen``."""

    items: list[CarteraEmpresa] = Field(default_factory=list)
    months_ahead: int
    totales: RenovacionesTotales


def resumen_renovaciones(
    *,
    months_ahead: int = 12,
    tecnologias: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Vencimientos agregados por empresa para la ventana dada.

    Responde "¿qué cartera de cada competidor está en juego?": número de
    contratos e importe que vencen, con el vencimiento más próximo.
    """
    return resumen_por_empresa(months_ahead=months_ahead, tecnologias=tecnologias)


def totales_renovaciones(
    *,
    months_ahead: int = 6,
    tecnologias: list[str] | None = None,
) -> dict[str, Any]:
    """Totales agregados (sin GROUP BY) de contratos que vencen en la ventana.

    Devuelve las cuatro cifras del panel de renovaciones calculadas sobre el
    **dataset completo**: número de contratos, importe en juego, importe en
    riesgo alto y contratos "calientes" (riesgo alto venciendo en menos de
    ``DIAS_CALIENTE`` días).

    Las dos últimas se computaban en el cliente sumando la lista paginada
    (`limit=1000`) y se presentaban como totales, que es el patrón nº2 de
    ADR-014: si hay más contratos que el tope, el usuario ve cifras
    silenciosamente bajas.
    """
    rows = totales_ventana(
        months_ahead=months_ahead,
        tecnologias=tecnologias,
        riesgo_alto=RIESGO_ALTO,
        dias_caliente=DIAS_CALIENTE,
    )
    if not rows:
        return {
            "contratos_venciendo": 0,
            "importe_en_juego": 0,
            "importe_alto_riesgo": 0,
            "calientes": 0,
        }
    return rows[0]
