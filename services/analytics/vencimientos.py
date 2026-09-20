"""Calendario de vencimientos — cierres de plazo por día (RFC ux-calendario #2-#4).

El Calendario respondía «¿cuándo se publicó?», que para quien licita no es
accionable. Lo accionable es «¿qué me vence y cuándo?»: el fin del plazo de
presentación (``fecha_limite``). Este módulo sirve esa serie diaria —conteo e
importe en juego por día de cierre— y los tres KPIs que la acompañan.

Todo se agrega en Postgres (:class:`AggregateRepository`, ADR-023); aquí sólo
se calculan las ventanas y el día pico sobre la serie ya agregada. El universo
es el del listado al que enlaza cada día (ver la nota de la sección en el
repositorio), para que la cifra del calendario y las filas que abre coincidan.

**Cota del tamaño.** La serie crece con la longitud de la ventana, no con el
número de licitaciones: se limita a :data:`MAX_VENTANA_DIAS` días, que cubre un
año natural bisiesto entero (lo que pinta el calendario) y nada más.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger

log = get_logger(__name__)

_repo = AggregateRepository()

#: Techo de la ventana pedida, en días. Un año natural bisiesto son 366.
MAX_VENTANA_DIAS = 366


class VentanaInvalida(ValueError):
    """La ventana pedida no tiene sentido o excede :data:`MAX_VENTANA_DIAS`."""


class VencimientosFilters(BaseModel):
    """Ventana de cierre + el ámbito global de la barra de filtros."""

    desde: date
    hasta: date
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    estado: str | None = None
    q: str | None = None
    importe_min: float | None = None
    solo_abiertas: bool = False


class VencimientoDia(BaseModel):
    """Cierres de plazo de un día."""

    fecha: str = Field(description="Día de cierre, YYYY-MM-DD.")
    count: int
    importe: float = Field(description="Suma del presupuesto de las que cierran ese día.")


class VencimientosKpis(BaseModel):
    """Cierres relativos a HOY, independientes de la ventana pintada."""

    hoy: str = Field(description="Fecha de referencia (UTC), YYYY-MM-DD.")
    vencen_hoy: int = 0
    vencen_7d: int = Field(default=0, description="Cierres de hoy a hoy+6, ambos incluidos.")
    vencen_resto_mes: int = Field(
        default=0, description="Cierres de hoy al último día del mes en curso, ambos incluidos."
    )


class VencimientosResult(BaseModel):
    """Serie diaria de cierres en la ventana pedida y KPIs de cierre."""

    desde: str
    hasta: str
    dias: list[VencimientoDia] = Field(default_factory=list)
    total: int = Field(default=0, description="Cierres en toda la ventana.")
    dia_pico: VencimientoDia | None = Field(
        default=None,
        description=(
            "Día de la ventana con más cierres (el primero si hay empate). "
            "`null` si la ventana no tiene ninguno."
        ),
    )
    kpis: VencimientosKpis


def _to_repo_filters(f: VencimientosFilters) -> LicitacionesFilters:
    return LicitacionesFilters(
        fecha_desde=f.fecha_desde.isoformat() if f.fecha_desde else None,
        fecha_hasta=f.fecha_hasta.isoformat() if f.fecha_hasta else None,
        ccaa=f.ccaa,
        tecnologia=f.tecnologia,
        estado=f.estado,
        q=f.q,
        importe_min=f.importe_min,
        solo_abiertas=f.solo_abiertas,
    )


def validar_ventana(desde: date, hasta: date) -> None:
    """Lanza :class:`VentanaInvalida` si la ventana está invertida o es demasiado ancha."""
    if hasta < desde:
        raise VentanaInvalida("`hasta` no puede ser anterior a `desde`.")
    dias = (hasta - desde).days + 1
    if dias > MAX_VENTANA_DIAS:
        raise VentanaInvalida(
            f"La ventana abarca {dias} días; el máximo es {MAX_VENTANA_DIAS}. "
            "Pide el calendario año a año."
        )


def ventanas_kpi(hoy: date) -> tuple[str, str, str, str]:
    """(hoy, mañana, hoy+7, 1.º del mes siguiente) — cotas ISO de los KPIs.

    Las tres últimas son exclusivas: «próximos 7 días» es ``[hoy, hoy+7)`` y
    «resto de mes» ``[hoy, día 1 del mes siguiente)``.
    """
    ultimo = calendar.monthrange(hoy.year, hoy.month)[1]
    fin_mes = date(hoy.year, hoy.month, ultimo) + timedelta(days=1)
    return (
        hoy.isoformat(),
        (hoy + timedelta(days=1)).isoformat(),
        (hoy + timedelta(days=7)).isoformat(),
        fin_mes.isoformat(),
    )


def dia_pico(dias: list[VencimientoDia]) -> VencimientoDia | None:
    """Día con más cierres; el primero en caso de empate. ``None`` si no hay."""
    if not dias:
        return None
    return max(dias, key=lambda d: d.count)


def get_vencimientos(
    filters: VencimientosFilters, *, hoy: date | None = None
) -> VencimientosResult:
    """Serie diaria de cierres de plazo y KPIs de cierre."""
    validar_ventana(filters.desde, filters.hasta)
    referencia = hoy or datetime.now(UTC).date()
    repo_filters = _to_repo_filters(filters)
    log.info(
        "analytics_vencimientos_start",
        desde=filters.desde.isoformat(),
        hasta=filters.hasta.isoformat(),
    )

    filas = _repo.vencimientos_diarios(
        repo_filters,
        desde_iso=filters.desde.isoformat(),
        hasta_exclusivo_iso=(filters.hasta + timedelta(days=1)).isoformat(),
    )
    dias = [
        VencimientoDia(
            fecha=str(fila["dia"]),
            count=int(fila["count"]),
            importe=float(fila["importe"] or 0),
        )
        for fila in filas
    ]

    hoy_iso, manana_iso, fin_7d, fin_mes = ventanas_kpi(referencia)
    kpis = _repo.vencimientos_kpis(
        repo_filters,
        hoy_iso=hoy_iso,
        manana_iso=manana_iso,
        fin_7d_exclusivo_iso=fin_7d,
        fin_mes_exclusivo_iso=fin_mes,
    )

    result = VencimientosResult(
        desde=filters.desde.isoformat(),
        hasta=filters.hasta.isoformat(),
        dias=dias,
        total=sum(d.count for d in dias),
        dia_pico=dia_pico(dias),
        kpis=VencimientosKpis(
            hoy=hoy_iso,
            vencen_hoy=kpis["hoy"],
            vencen_7d=kpis["proximos_7d"],
            vencen_resto_mes=kpis["resto_mes"],
        ),
    )
    log.info("analytics_vencimientos_done", dias=len(dias), total=result.total)
    return result
