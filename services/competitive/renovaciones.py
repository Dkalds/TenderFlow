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
re-exporta desde aquí; mover también los dos agregados dejaría quitar la
entrada de este módulo del ratchet TID251.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from db.database import connect_read
from db.repositories.base import rows_to_dicts

# `proximas_renovaciones` se re-exporta: su SQL se movió a `db/` (ADR-022) pero
# el nombre sigue importándose desde aquí en `services/pursuits.py`,
# `scheduler/competitor_alerts.py` y la suite. Es un alias, no una capa
# passthrough (ADR-024): los llamadores nuevos deben ir al repository.
from db.repositories.renovaciones import (  # noqa: F401
    dias_restantes_sql,
    proximas_renovaciones,
    rango_vencimiento_sql,
)
from services.dedupe import exclude_duplicados_sql

# FECHA_FIN_SQL se re-exporta por compatibilidad con imports externos.
from services.sql_fragments import (  # noqa: F401
    FECHA_FIN_SQL,
    TECHNOLOGY_OBSERVED_SQL,
    fecha_fin_sql,
)

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
    months_ahead = max(1, min(int(months_ahead), 60))
    fecha_fin = fecha_fin_sql()
    sql = f"""
        SELECT a.empresa_id,
               COALESCE(e.nombre_canonico, a.nombre) AS empresa,
               COUNT(*) AS contratos_venciendo,
               COALESCE(SUM(a.importe_adjudicado), 0) AS importe_en_juego,
               MIN({fecha_fin}) AS proximo_vencimiento
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
        WHERE {fecha_fin} {rango_vencimiento_sql()}
          AND {TECHNOLOGY_OBSERVED_SQL}
          AND {exclude_duplicados_sql()}
    """  # noqa: S608 — fragmentos constantes de services.sql_fragments; valores con ?
    params: list[Any] = [months_ahead]
    tecnologias = [t for t in (tecnologias or []) if t]
    if tecnologias:
        placeholders = ",".join("%s" for _ in tecnologias)
        sql += f" AND l.tecnologia IN ({placeholders})"
        params.extend(tecnologias)
    sql += """
        GROUP BY a.empresa_id, empresa
        ORDER BY importe_en_juego DESC
        LIMIT 100
    """
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


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
    months_ahead = max(1, min(int(months_ahead), 60))
    fecha_fin = fecha_fin_sql()
    dias_restantes = dias_restantes_sql(fecha_fin)
    sql = f"""
        SELECT COUNT(*) AS contratos_venciendo,
               COALESCE(SUM(a.importe_adjudicado), 0) AS importe_en_juego,
               COALESCE(
                   SUM(a.importe_adjudicado) FILTER (WHERE pr.riesgo_cambio >= %s), 0
               ) AS importe_alto_riesgo,
               COUNT(*) FILTER (
                   WHERE pr.riesgo_cambio >= %s AND {dias_restantes} <= %s
               ) AS calientes
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        LEFT JOIN predicciones_retencion pr ON pr.licitacion_id = a.licitacion_id
        WHERE {fecha_fin} {rango_vencimiento_sql()}
          AND {TECHNOLOGY_OBSERVED_SQL}
          AND {exclude_duplicados_sql()}
    """  # noqa: S608 — fragmentos constantes de services.sql_fragments; valores con ?
    params: list[Any] = [RIESGO_ALTO, RIESGO_ALTO, DIAS_CALIENTE, months_ahead]
    tecnologias = [t for t in (tecnologias or []) if t]
    if tecnologias:
        placeholders = ",".join("%s" for _ in tecnologias)
        sql += f" AND l.tecnologia IN ({placeholders})"
        params.extend(tecnologias)
    with connect_read() as c:
        rows = rows_to_dicts(c.execute(sql, params))
    if not rows:
        return {
            "contratos_venciendo": 0,
            "importe_en_juego": 0,
            "importe_alto_riesgo": 0,
            "calientes": 0,
        }
    return rows[0]
