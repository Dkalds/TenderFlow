"""Forecast analytics — volume forecasting and retendering predictions.

ADR-023: el forecast de volumen consume la serie mensual YA agregada en
Postgres (``forecast_monthly`` → ``forecast_volume_from_monthly``) y el de
re-licitación una proyección ACOTADA (solo filas con duración positiva o
``fecha_fin`` explícita — las únicas que pueden producir una fecha de fin).
Hasta 2026-08 ambos cargaban las dos tablas completas al proceso API —
bloqueado en Render por el cortacircuitos full-table, que dejaba los
endpoints vacíos en producción.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger
from services.analytics.forecast import (
    BANDA_SIGMAS,
    build_forecast_df,
    forecast_volume_from_monthly,
)

log = get_logger(__name__)

_repo = AggregateRepository()

# Ventana por defecto de la estacionalidad: tres años de publicaciones. Es el
# tamaño que pide T5 del plan 2026-09 y el que hace que cada mes del calendario
# tenga tres observaciones — suficiente para que un mes atípico no mueva la
# media de su casilla al doble.
VENTANA_ESTACIONALIDAD_MESES = 36

# Mínimo de meses de historia para publicar la curva (ADR-014: sin denominador
# no se pinta). Por debajo de doce ni siquiera se ha observado un ciclo anual
# completo: habría meses del calendario con denominador cero, y una casilla
# vacía por falta de cobertura se lee igual que una casilla vacía por ausencia
# de publicaciones. Quien decide esto es el servicio, no la pantalla.
MIN_MESES_ESTACIONALIDAD = 12


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class ForecastFilters(BaseModel):
    months_ahead: int = 6
    metric: str = "count"
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None


class ForecastSeriesPoint(BaseModel):
    mes: str
    valor: float
    tipo: str
    lower: float | None = None
    upper: float | None = None


class ForecastVolumeResult(BaseModel):
    series: list[ForecastSeriesPoint] = Field(default_factory=list)
    # Qué motor produjo la proyección ("holt-winters" | "regresion-lineal"). La
    # caída al fallback lineal solo se veía en el log, y la pantalla presentaba
    # ambas igual: quien lee la curva no sabía si miraba un suavizado estacional
    # o una recta. `None` cuando no hay serie.
    modelo: str | None = None
    # Sigmas de la banda `lower`/`upper`. NO es un intervalo de confianza: es
    # +/-N sigma de TODA la serie histórica, idéntico en los seis horizontes (un IC
    # real se ensancha con el horizonte). Se publica para que la UI la rotule
    # con el número real en vez de dejar que se lea como un IC.
    banda_sigmas: float = BANDA_SIGMAS


class RetenderingFilters(BaseModel):
    meses_anticipacion: int = 6
    solo_mantenimiento: bool = True
    horizonte_dias: int = 365
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None


class ForecastEntry(BaseModel):
    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = None
    fecha_fin_estimada: str | None = None
    dias_hasta_fin: int | None = None
    estado_forecast: str | None = None
    adjudicatarios: str | None = None
    baja_pct: float | None = None


class RetenderingResumen(BaseModel):
    ya_vencido: int = 0
    menos_3m: int = 0
    tres_seis_m: int = 0
    seis_doce_m: int = 0
    mas_doce_m: int = 0


class RetenderingResult(BaseModel):
    forecast_entries: list[ForecastEntry] = Field(default_factory=list)
    resumen: RetenderingResumen = Field(default_factory=RetenderingResumen)


class EstacionalidadFilters(BaseModel):
    """Ámbito de la estacionalidad por órgano.

    ``organo`` es obligatorio: la estacionalidad de "todos los órganos a la vez"
    es el forecast de volumen, que ya existe. ``hasta`` ancla la ventana (por
    defecto el mes en curso) para que una consulta sea reproducible.
    """

    organo: str
    meses: int = VENTANA_ESTACIONALIDAD_MESES
    hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None


class EstacionalidadMes(BaseModel):
    """Una casilla del calendario de compra, con su denominador al lado."""

    mes: int
    publicaciones: int
    # Veces que ese mes del calendario cae dentro de la ventana observada. Es
    # el denominador de ``media`` y NO es constante: una ventana de 36 meses
    # que empieza en marzo tiene tres marzos y dos febreros. Dividir los doce
    # por el mismo número —lo que hace el drill-down de órgano, ``n_years``—
    # infla los meses del borde.
    anios_observados: int
    media: float


class EstacionalidadOrganoResult(BaseModel):
    """Publicaciones por mes de calendario de un órgano, con su universo declarado.

    ADR-014: el resultado declara la ventana pedida, el tramo realmente
    cubierto, cuántos meses de ese tramo tienen publicaciones y el total; y
    cuando el tramo cubierto no llega a
    :data:`MIN_MESES_ESTACIONALIDAD`, ``meses`` viene **vacío** con
    ``suficiente=False``. La pantalla no tiene que decidir nada: si no hay
    curva es porque no la hay.
    """

    organo: str
    ventana_meses: int
    mes_desde: str | None = None
    mes_hasta: str | None = None
    # Meses entre la primera y la última publicación dentro de la ventana. Es
    # el `n` del criterio de aceptación: los meses de historia observados.
    n_meses: int = 0
    # De esos, cuántos tienen al menos una publicación. Un mes cubierto y vacío
    # es un cero real (el órgano no publicó), no un hueco de cobertura.
    meses_con_publicaciones: int = 0
    total_publicaciones: int = 0
    suficiente: bool = False
    motivo: str | None = None
    meses: list[EstacionalidadMes] = Field(default_factory=list)


def _to_repo_filters(filters: Any) -> LicitacionesFilters:
    fecha_desde = getattr(filters, "fecha_desde", None)
    fecha_hasta = getattr(filters, "fecha_hasta", None)
    return LicitacionesFilters(
        fecha_desde=fecha_desde.isoformat() if fecha_desde else None,
        fecha_hasta=fecha_hasta.isoformat() if fecha_hasta else None,
        ccaa=getattr(filters, "ccaa", None),
        tecnologia=getattr(filters, "tecnologia", None),
        organo=getattr(filters, "organo", None),
    )


def _ordinal_mes(mes_iso: str) -> int | None:
    """``YYYY-MM`` → índice absoluto de mes; ``None`` si el bucket no lo es.

    Sirve para restar y contar meses sin aritmética de calendario.
    """
    partes = mes_iso.split("-")
    if len(partes) != 2 or not (partes[0].isdigit() and partes[1].isdigit()):
        return None
    anio, mes = int(partes[0]), int(partes[1])
    if not 1 <= mes <= 12:
        return None
    return anio * 12 + (mes - 1)


def _mes_iso(ordinal: int) -> str:
    """Inversa de :func:`_ordinal_mes`."""
    return f"{ordinal // 12:04d}-{ordinal % 12 + 1:02d}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_forecast_volume(filters: ForecastFilters) -> ForecastVolumeResult:
    """Forecast licitaciones volume using Holt-Winters / linear fallback."""
    log.info("analytics_forecast_volume_start", filters=filters.model_dump(exclude_none=True))
    monthly = _repo.forecast_monthly(_to_repo_filters(filters), metric=filters.metric)
    if not monthly:
        return ForecastVolumeResult()

    hist = pd.DataFrame(
        {
            "mes": [pd.Timestamp(str(r["mes"]) + "-01") for r in monthly],
            "valor": [float(r["valor"] or 0) for r in monthly],
        }
    )
    result_df = forecast_volume_from_monthly(hist, months_ahead=filters.months_ahead)
    if result_df.empty:
        return ForecastVolumeResult()

    series = [
        ForecastSeriesPoint(
            mes=row["mes"].strftime("%Y-%m") if pd.notna(row["mes"]) else "",
            valor=float(row["valor"]) if pd.notna(row.get("valor")) else 0.0,
            tipo=str(row.get("tipo", "")),
            lower=float(row["lower"]) if pd.notna(row.get("lower")) else None,
            upper=float(row["upper"]) if pd.notna(row.get("upper")) else None,
        )
        for _, row in result_df.iterrows()
    ]

    # `modelo` es constante en todo el DataFrame (lo fija el motor que produjo
    # la proyección), así que basta con leerlo de la primera fila.
    modelo = str(result_df["modelo"].iloc[0]) if "modelo" in result_df.columns else None

    log.info("analytics_forecast_volume_done", points=len(series), modelo=modelo)
    return ForecastVolumeResult(series=series, modelo=modelo)


def get_estacionalidad_organo(filters: EstacionalidadFilters) -> EstacionalidadOrganoResult:
    """Publicaciones por mes de calendario de UN órgano en los últimos N meses.

    Es la mitad "cuándo compra" del pre-radar: el anuncio previo dice qué va a
    salir, esto dice en qué meses ese órgano ha sacado históricamente sus
    expedientes.

    El corte de ADR-014 lo aplica esta función, no la pantalla: por debajo de
    :data:`MIN_MESES_ESTACIONALIDAD` meses de historia el resultado sale con
    ``suficiente=False``, ``motivo`` y **sin** ``meses``. Un cliente que ignore
    ``suficiente`` no puede pintar una curva, porque no hay ninguna que pintar.
    """
    organo = filters.organo.strip()
    ventana = max(filters.meses, 1)
    log.info(
        "analytics_estacionalidad_organo_start",
        organo=organo,
        ventana_meses=ventana,
    )
    if not organo:
        return EstacionalidadOrganoResult(
            organo="",
            ventana_meses=ventana,
            motivo="No se pidió ningún órgano.",
        )

    ancla = filters.hasta or datetime.now(UTC).date()
    fin_ventana = ancla.year * 12 + (ancla.month - 1)
    inicio_ventana = fin_ventana - (ventana - 1)

    # ``_to_repo_filters`` es el mismo traductor del forecast de volumen; aquí
    # no hay fecha_desde/fecha_hasta que pasar porque la ventana la acota el
    # propio repositorio por meses.
    rows = _repo.publicaciones_mensuales(
        _to_repo_filters(filters),
        mes_desde=_mes_iso(inicio_ventana),
        mes_hasta=_mes_iso(fin_ventana),
    )

    base = EstacionalidadOrganoResult(organo=organo, ventana_meses=ventana)
    por_mes: dict[int, int] = {}
    for row in rows:
        mes_iso = str(row["mes"])
        publicaciones = int(row["publicaciones"] or 0)
        if not publicaciones:
            continue
        # ``fecha_publicacion`` es TEXT y hay filas legado que el CHECK de v59
        # no cubre (ver cabecera de db/repositories/aggregates.py): un bucket
        # que no sea YYYY-MM se descarta en vez de tumbar el endpoint o de
        # colarse como un mes 13.
        ordinal = _ordinal_mes(mes_iso)
        if ordinal is None:
            log.warning("analytics_estacionalidad_mes_descartado", organo=organo, mes=mes_iso)
            continue
        por_mes[ordinal] = publicaciones
    if not por_mes:
        base.motivo = "El órgano no tiene publicaciones en la ventana."
        log.info("analytics_estacionalidad_organo_done", organo=organo, n_meses=0, suficiente=False)
        return base

    primero, ultimo = min(por_mes), max(por_mes)
    base.mes_desde = _mes_iso(primero)
    base.mes_hasta = _mes_iso(ultimo)
    base.n_meses = ultimo - primero + 1
    base.meses_con_publicaciones = len(por_mes)
    base.total_publicaciones = sum(por_mes.values())

    if base.n_meses < MIN_MESES_ESTACIONALIDAD:
        base.motivo = (
            f"Solo {base.n_meses} meses de historia en la ventana; "
            f"hacen falta {MIN_MESES_ESTACIONALIDAD} para un ciclo anual completo."
        )
        log.info(
            "analytics_estacionalidad_organo_done",
            organo=organo,
            n_meses=base.n_meses,
            suficiente=False,
        )
        return base

    # Denominador por mes del calendario: cuántas veces cae ese mes en el tramo
    # cubierto. Con n_meses >= 12 los doce tienen al menos una ocurrencia, así
    # que ninguna casilla se publica con denominador cero.
    denominadores: Counter[int] = Counter(o % 12 + 1 for o in range(primero, ultimo + 1))
    numeradores: Counter[int] = Counter()
    for ordinal, publicaciones in por_mes.items():
        numeradores[ordinal % 12 + 1] += publicaciones

    base.suficiente = True
    base.meses = [
        EstacionalidadMes(
            mes=mes,
            publicaciones=numeradores.get(mes, 0),
            anios_observados=denominadores[mes],
            media=round(numeradores.get(mes, 0) / denominadores[mes], 2),
        )
        for mes in range(1, 13)
    ]
    log.info(
        "analytics_estacionalidad_organo_done",
        organo=organo,
        n_meses=base.n_meses,
        total=base.total_publicaciones,
        suficiente=True,
    )
    return base


def get_retendering_forecast(filters: RetenderingFilters) -> RetenderingResult:
    """Retendering forecast using build_forecast_df logic.

    .. deprecated:: 2026-07-20
       Sin consumidor en `web/` desde el rework de Pipeline & Alertas — ver
       nota de deprecación en ``api/routes/analytics.py::forecast_retendering``
       y docs/IMPROVEMENT_BACKLOG.md (Cerrados, 2026-07-20).
    """
    log.info("analytics_retendering_start", filters=filters.model_dump(exclude_none=True))
    rows = _repo.retendering_universe(_to_repo_filters(filters))
    if not rows:
        return RetenderingResult()

    df = pd.DataFrame(rows)
    df = df.assign(
        importe=pd.to_numeric(df["importe"], errors="coerce"),
        duracion_valor=pd.to_numeric(df["duracion_valor"], errors="coerce"),
    )
    titulo_lower = df["titulo"].fillna("").str.lower()
    df["tipo_proyecto"] = "Otro"
    df.loc[titulo_lower.str.contains("mantenimiento|soporte", na=False), "tipo_proyecto"] = (
        "Mantenimiento"
    )

    adj_rows = _repo.adjudicaciones_para_forecast(
        [str(i) for i in df["id_externo"].astype(str).tolist()]
    )
    adj_df = pd.DataFrame(adj_rows)
    if not adj_df.empty:
        adj_df = adj_df.assign(
            fecha_adjudicacion=pd.to_datetime(adj_df["fecha_adjudicacion"], errors="coerce"),
            importe_adjudicado=pd.to_numeric(adj_df["importe_adjudicado"], errors="coerce"),
            n_ofertas_recibidas=pd.to_numeric(adj_df["n_ofertas_recibidas"], errors="coerce"),
        )

    forecast_df = build_forecast_df(
        df,
        adj_df,
        meses_anticipacion=filters.meses_anticipacion,
        solo_mantenimiento=filters.solo_mantenimiento,
    )

    if forecast_df.empty:
        return RetenderingResult()

    # Filter by horizonte_dias
    horizonte = filters.horizonte_dias
    forecast_df = forecast_df[
        forecast_df["dias_hasta_fin"].notna() & (forecast_df["dias_hasta_fin"] <= horizonte)
    ]

    # Build resumen
    estado_counts = forecast_df["estado_forecast"].value_counts()
    resumen = RetenderingResumen(
        ya_vencido=int(estado_counts.get("Ya vencido", 0)),
        menos_3m=int(estado_counts.get("<3 meses", 0)),
        tres_seis_m=int(estado_counts.get("3-6 meses", 0)),
        seis_doce_m=int(estado_counts.get("6-12 meses", 0)),
        mas_doce_m=int(estado_counts.get(">12 meses", 0)),
    )

    entries = []
    for _, row in forecast_df.iterrows():
        entries.append(
            ForecastEntry(
                id_externo=str(row.get("id_externo", "")),
                titulo=row.get("titulo") if pd.notna(row.get("titulo")) else None,
                organo_contratacion=(
                    row.get("organo_contratacion")
                    if pd.notna(row.get("organo_contratacion"))
                    else None
                ),
                importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
                fecha_fin_estimada=(
                    row["fecha_fin_estimada"].isoformat()
                    if pd.notna(row.get("fecha_fin_estimada"))
                    else None
                ),
                dias_hasta_fin=(
                    int(row["dias_hasta_fin"]) if pd.notna(row.get("dias_hasta_fin")) else None
                ),
                estado_forecast=(
                    str(row["estado_forecast"]) if pd.notna(row.get("estado_forecast")) else None
                ),
                adjudicatarios=(
                    str(row["adjudicatarios"]) if pd.notna(row.get("adjudicatarios")) else None
                ),
                baja_pct=(float(row["baja_pct"]) if pd.notna(row.get("baja_pct")) else None),
            )
        )

    log.info("analytics_retendering_done", entries=len(entries))
    return RetenderingResult(forecast_entries=entries, resumen=resumen)
