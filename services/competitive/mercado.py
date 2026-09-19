"""Cuota de mercado, concentración (HHI) y presión competitiva.

Todas las métricas se calculan sobre empresas canónicas del maestro (v35),
no sobre strings de nombre — sin eso las cuotas estarían fragmentadas entre
variantes del mismo adjudicatario.

El SQL vive en ``db/repositories/mercado.py`` (ADR-022). Aquí queda el dominio
(ADR-024): qué filtros lleva cada alcance del dossier, la ventana de
comparación, los desgloses, las medianas y los movimientos.

Este módulo no escribe SQL, pero sí lo transporta. Cuota, HHI y denominador
reciben valores de filtro. El dossier y el listado reciben alcances: los
construye ``mercado_repo.alcance_sql`` a partir de valores de filtro (el
universo, por nombre) y el servicio los entrega al repositorio como
``mercado_repo.Alcance``, cuyo ``where`` es SQL ya armado.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any

from db.repositories import mercado as mercado_repo
from services.competitive.batallas import (
    MIN_POR_CELDA,
    corte_por_procedimiento,
    corte_por_tramo,
)
from shared.metric_scope import MetricScope

AnalysisUniverse = mercado_repo.UniversoAnalisis


def metric_scope(
    *,
    cpv_prefix: str | None = None,
    ccaa: str | None = None,
    desde: str | None = None,
) -> MetricScope:
    """Alcance exacto del agregado de cuota/HHI sobre el corpus observado."""
    filters: dict[str, str] = {}
    if cpv_prefix:
        filters["cpv_prefix"] = cpv_prefix
    if ccaa:
        filters["ccaa"] = ccaa
    if desde:
        filters["desde"] = desde
    denominador = mercado_repo.denominador_cuota(cpv_prefix=cpv_prefix, ccaa=ccaa, desde=desde)
    lineage = denominador.linaje
    sources = sorted({str(item["fuente"]) for item in lineage if item.get("fuente")})
    filter_versions = sorted(
        {str(item["filter_version"]) for item in lineage if item.get("filter_version")}
    )
    model_versions = sorted(
        {
            str(item["classifier_model_version"])
            for item in lineage
            if item.get("classifier_model_version")
        }
    )
    return MetricScope(
        label="Cuota dentro del segmento tecnológico observado",
        universe=(
            "technology_observed (más filas históricas previas al linaje); excluye "
            "watched_company_awards_observed y no representa todo el mercado español"
        ),
        denominator_records=denominador.registros,
        denominator_amount_eur=denominador.importe_eur,
        filters=filters,
        sources=sources,
        filter_versions=filter_versions,
        model_versions=model_versions,
        window_from=desde,
        window_to=date.today().isoformat(),
        computed_at=datetime.now(UTC).isoformat(),
        caveat=(
            "El denominador depende de la cobertura de fuentes y de las reglas de inclusión "
            "vigentes. Versiones vacías corresponden a filas históricas anteriores al linaje."
        ),
    )


def cuota_mercado(
    *,
    cpv_prefix: str | None = None,
    ccaa: str | None = None,
    desde: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Ranking de empresas por importe adjudicado con cuota % del segmento.

    La presión competitiva media (``ofertas_medias``) contextualiza la cuota:
    dominar un segmento con 1.2 ofertas medias no es lo mismo que con 8.
    """
    return mercado_repo.cuota_mercado(
        cpv_prefix=cpv_prefix,
        ccaa=ccaa,
        desde=desde,
        limit=limit,
    )


def concentracion_hhi(*, segment_by: str = "cpv", min_contratos: int = 5) -> list[dict[str, Any]]:
    """Índice Herfindahl-Hirschman por segmento (0-10000).

    HHI = suma de (cuota_i * 100)^2. Lectura estándar: <1500 competitivo,
    1500-2500 moderadamente concentrado, >2500 concentrado. Un segmento
    concentrado con vencimientos próximos es una oportunidad de entrada;
    uno competitivo exige afinar la baja (ver ``bajas``).

    Un ``segment_by`` que no esté en la whitelist de segmentación lanza
    ``ValueError``: el repositorio la valida antes de interpolar la columna.
    """
    return mercado_repo.concentracion_hhi(segment_by=segment_by, min_contratos=min_contratos)


def _scope_sql(
    *,
    empresa_id: int | None = None,
    empresa_ids: list[int] | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    cpv_prefix: str | None = None,
    ccaas: list[str] | None = None,
    tecnologias: list[str] | None = None,
    importe_min: float | None = None,
    analysis_universe: AnalysisUniverse = "technology_observed",
) -> mercado_repo.Alcance:
    """Build the shared award scope with parameterised values only.

    ``empresa_ids`` agrupa varias identidades del maestro (mismo competidor
    analítico sin fusionar aún) bajo un único dossier — tiene prioridad sobre
    ``empresa_id`` cuando se informan ambos.

    Delega el SQL en ``mercado_repo.alcance_sql``, que traduce el universo de
    análisis a su predicado y siembra ``exclude_duplicados_sql()``.
    """
    return mercado_repo.alcance_sql(
        universo=analysis_universe,
        empresa_id=empresa_id,
        empresa_ids=empresa_ids,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        cpv_prefix=cpv_prefix,
        ccaas=ccaas,
        tecnologias=tecnologias,
        importe_min=importe_min,
    )


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _pct(value: float, total: float) -> float:
    return round(value * 100.0 / total, 1) if total else 0.0


def _variation(current: float, previous: float) -> float | None:
    if previous == 0:
        return 0.0 if current == 0 else None
    return round((current - previous) * 100.0 / previous, 1)


def _breakdown(
    rows: list[dict[str, Any]],
    *,
    key: str,
    code_prefix: bool = False,
    limit: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"contratos": 0, "importe": 0.0}
    )
    for row in rows:
        raw = row.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        label = str(raw).strip()
        if code_prefix:
            label = label[:2]
        grouped[label]["contratos"] = int(grouped[label]["contratos"]) + 1
        grouped[label]["importe"] = float(grouped[label]["importe"]) + float(
            row.get("importe_adjudicado") or 0
        )
    total = sum(float(values["importe"]) for values in grouped.values())
    ordered = sorted(
        grouped.items(),
        key=lambda item: (float(item[1]["importe"]), int(item[1]["contratos"])),
        reverse=True,
    )
    result: list[dict[str, Any]] = []
    legacy_key = {
        "cpv": "cpv2",
        "ccaa": "ccaa",
        "organo_contratacion": "organo",
    }.get(key)
    for label, values in ordered[:limit]:
        entry: dict[str, Any] = {
            "codigo": label if code_prefix else None,
            "label": f"CPV {label}" if code_prefix else label,
            "contratos": int(values["contratos"]),
            "importe": float(values["importe"]),
            "cuota_empresa_pct": _pct(float(values["importe"]), total),
        }
        if legacy_key:
            entry[legacy_key] = label
        result.append(entry)
    return result


def _comparison_window(
    rows: list[dict[str, Any]],
    *,
    fecha_desde: date | None,
    fecha_hasta: date | None,
) -> dict[str, Any]:
    current_end = fecha_hasta or date.today()
    current_start = fecha_desde or (current_end - timedelta(days=364))
    if current_start > current_end:
        current_start, current_end = current_end, current_start
    span = (current_end - current_start).days + 1
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=span - 1)

    def aggregate(start: date, end: date) -> tuple[int, float]:
        scoped = [
            row
            for row in rows
            if (row_date := _as_date(row.get("fecha_adjudicacion"))) is not None
            and start <= row_date <= end
        ]
        return len(scoped), sum(float(row.get("importe_adjudicado") or 0) for row in scoped)

    current_count, current_amount = aggregate(current_start, current_end)
    previous_count, previous_amount = aggregate(previous_start, previous_end)
    return {
        "desde": current_start.isoformat(),
        "hasta": current_end.isoformat(),
        "anterior_desde": previous_start.isoformat(),
        "anterior_hasta": previous_end.isoformat(),
        "contratos": current_count,
        "contratos_anterior": previous_count,
        "variacion_contratos_pct": _variation(float(current_count), float(previous_count)),
        "importe": current_amount,
        "importe_anterior": previous_amount,
        "variacion_importe_pct": _variation(current_amount, previous_amount),
    }


def _company_movements(
    *,
    comparison: dict[str, Any],
    concentration: dict[str, Any],
    pct_single: float | None,
    offer_coverage_count: int,
    baseline_rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    movements: list[dict[str, str]] = []
    amount_delta = comparison.get("variacion_importe_pct")
    if isinstance(amount_delta, (int, float)) and abs(float(amount_delta)) >= 10:
        growing = float(amount_delta) > 0
        movements.append(
            {
                "kind": "growth",
                "tone": "positive" if growing else "negative",
                "title": "Aceleración de actividad" if growing else "Retroceso de actividad",
                "detail": (
                    f"El importe adjudicado varía un {float(amount_delta):+.1f}% "
                    "frente al periodo comparable anterior."
                ),
            }
        )

    current_start = _as_date(comparison.get("desde"))
    current_end = _as_date(comparison.get("hasta"))
    previous_start = _as_date(comparison.get("anterior_desde"))
    previous_end = _as_date(comparison.get("anterior_hasta"))
    if current_start and current_end and previous_start and previous_end:
        current_regions = {
            str(row["ccaa"])
            for row in baseline_rows
            if row.get("ccaa")
            and (row_date := _as_date(row.get("fecha_adjudicacion"))) is not None
            and current_start <= row_date <= current_end
        }
        previous_regions = {
            str(row["ccaa"])
            for row in baseline_rows
            if row.get("ccaa")
            and (row_date := _as_date(row.get("fecha_adjudicacion"))) is not None
            and previous_start <= row_date <= previous_end
        }
        new_regions = sorted(current_regions - previous_regions)
        if new_regions:
            movements.append(
                {
                    "kind": "territory",
                    "tone": "positive",
                    "title": "Expansión territorial",
                    "detail": "Nueva actividad en " + ", ".join(new_regions[:3]) + ".",
                }
            )

    if float(concentration.get("top1_importe_pct") or 0) >= 50:
        movements.append(
            {
                "kind": "concentration",
                "tone": "warning",
                "title": "Dependencia elevada de un cliente",
                "detail": (
                    f"El principal organismo concentra "
                    f"{float(concentration['top1_importe_pct']):.1f}% del importe."
                ),
            }
        )

    if pct_single is not None and offer_coverage_count >= 3 and pct_single >= 50:
        movements.append(
            {
                "kind": "competition",
                "tone": "warning",
                "title": "Alta exposición a concursos con oferta única",
                "detail": (
                    f"El {pct_single:.1f}% de las adjudicaciones con dato de ofertas "
                    "se resolvió con un solo ofertante."
                ),
            }
        )

    if not movements:
        movements.append(
            {
                "kind": "stable",
                "tone": "neutral",
                "title": "Sin movimientos extraordinarios",
                "detail": "La actividad observada no supera los umbrales de cambio del periodo.",
            }
        )
    return movements[:4]


def perfil_empresa(
    empresa_id: int,
    *,
    empresa_ids: list[int] | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    cpv_prefix: str | None = None,
    ccaas: list[str] | None = None,
    tecnologias: list[str] | None = None,
    importe_min: float | None = None,
    analysis_universe: AnalysisUniverse = "technology_observed",
) -> dict[str, Any]:
    """Return an explainable, filter-coherent competitive company dossier.

    ``empresa_ids`` permite agregar el dossier de un competidor analítico
    que el maestro todavía tiene repartido en varias identidades legales
    (mismo nombre/NIF conectado pero sin fusionar) — el usuario nunca elige
    cuál abrir, el dossier suma la actividad de todas.

    Todas las queries sobre licitaciones/adjudicaciones usan `_scope_sql()`,
    que aplica `exclude_duplicados_sql()` para excluir duplicados cross-fuente.
    """
    group_ids = sorted({empresa_id, *(empresa_ids or [])})
    is_group = len(group_ids) > 1

    # Cada alcance responde a una pregunta distinta del dossier: la actividad
    # filtrada (con ventana), la base de comparación (mismos filtros sin
    # ventana, para poder medir contra el periodo anterior), el mercado (sin
    # empresa, para la posición) y la historia (solo empresa y universo).
    scope_alcance = _scope_sql(
        empresa_id=empresa_id,
        empresa_ids=group_ids if is_group else None,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        cpv_prefix=cpv_prefix,
        ccaas=ccaas,
        tecnologias=tecnologias,
        importe_min=importe_min,
        analysis_universe=analysis_universe,
    )
    baseline_alcance = _scope_sql(
        empresa_id=empresa_id,
        empresa_ids=group_ids if is_group else None,
        cpv_prefix=cpv_prefix,
        ccaas=ccaas,
        tecnologias=tecnologias,
        importe_min=importe_min,
        analysis_universe=analysis_universe,
    )
    market_alcance = _scope_sql(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        cpv_prefix=cpv_prefix,
        ccaas=ccaas,
        tecnologias=tecnologias,
        importe_min=importe_min,
        analysis_universe=analysis_universe,
    )
    history_alcance = _scope_sql(
        empresa_id=empresa_id,
        empresa_ids=group_ids if is_group else None,
        analysis_universe=analysis_universe,
    )
    filas = mercado_repo.filas_perfil_empresa(
        group_ids,
        alcance=scope_alcance,
        # Sin ventana de fechas la base es la misma actividad: el repositorio
        # reutiliza esas filas en vez de repetir la consulta.
        alcance_base=None if fecha_desde is None and fecha_hasta is None else baseline_alcance,
        alcance_mercado=market_alcance,
        alcance_historia=history_alcance,
    )
    identity_rows = filas.identidades
    history_rows = filas.historia
    scope_rows = filas.actividad
    baseline_rows = filas.base
    position_rows = filas.posicion
    ute_identity_rows = filas.utes
    ute_activity_rows = filas.actividad_utes
    ute_miembros_rows = filas.miembros_utes

    primary_identity = next(
        (row for row in identity_rows if row.get("empresa_id") == empresa_id),
        None,
    )
    identity = (
        primary_identity
        or (identity_rows[0] if identity_rows else None)
        or {
            "empresa_id": empresa_id,
            "nombre_canonico": f"Empresa {empresa_id}",
            "nif_canonico": None,
            "es_ute": 0,
            "grupo": None,
        }
    )
    if is_group and identity_rows:
        # Agregado: NIF solo se muestra si todas las identidades comparten el
        # mismo (si no, ambigüo mostrar uno); es_ute/grupo se toman de
        # cualquiera de las identidades que lo tenga.
        distinct_nifs = {row["nif_canonico"] for row in identity_rows if row.get("nif_canonico")}
        identity = {
            **identity,
            "nif_canonico": next(iter(distinct_nifs)) if len(distinct_nifs) == 1 else None,
            "es_ute": any(bool(row.get("es_ute")) for row in identity_rows),
            "grupo": next((row.get("grupo") for row in identity_rows if row.get("grupo")), None),
        }
    history = history_rows[0]
    amounts = [
        float(row["importe_adjudicado"])
        for row in scope_rows
        if row.get("importe_adjudicado") is not None and float(row["importe_adjudicado"]) >= 0
    ]
    offers = [
        int(row["n_ofertas_recibidas"])
        for row in scope_rows
        if row.get("n_ofertas_recibidas") is not None
    ]
    discounts = [
        (1.0 - float(row["importe_adjudicado"]) / float(row["presupuesto_licitacion"])) * 100
        for row in scope_rows
        if row.get("importe_adjudicado") is not None
        and row.get("presupuesto_licitacion") is not None
        and float(row["presupuesto_licitacion"]) > 0
    ]
    valid_dates = [
        parsed
        for row in scope_rows
        if (parsed := _as_date(row.get("fecha_adjudicacion"))) is not None
    ]
    cpv_rows = _breakdown(scope_rows, key="cpv", code_prefix=True, limit=10)
    ccaa_rows = _breakdown(scope_rows, key="ccaa", limit=20)
    organ_rows = _breakdown(scope_rows, key="organo_contratacion", limit=10)
    total_amount = sum(amounts)
    total_contracts = len(scope_rows)
    pct_single = (
        _pct(float(sum(value <= 1 for value in offers)), float(len(offers))) if offers else None
    )

    top_org = organ_rows[0] if organ_rows else None
    top3_amount = sum(float(row["importe"]) for row in organ_rows[:3])
    concentration = {
        "organo_principal": top_org["label"] if top_org else None,
        "top1_contratos_pct": (
            _pct(float(top_org["contratos"]), float(total_contracts)) if top_org else 0.0
        ),
        "top1_importe_pct": (_pct(float(top_org["importe"]), total_amount) if top_org else 0.0),
        "top3_importe_pct": _pct(top3_amount, total_amount),
    }

    years: dict[int, dict[str, float | int]] = defaultdict(lambda: {"contratos": 0, "importe": 0.0})
    for row in scope_rows:
        row_date = _as_date(row.get("fecha_adjudicacion"))
        if row_date is None:
            continue
        years[row_date.year]["contratos"] = int(years[row_date.year]["contratos"]) + 1
        years[row_date.year]["importe"] = float(years[row_date.year]["importe"]) + float(
            row.get("importe_adjudicado") or 0
        )
    year_rows = [
        {
            "anio": year,
            "contratos": int(values["contratos"]),
            "importe": float(values["importe"]),
        }
        for year, values in sorted(years.items())
    ]

    comparison = _comparison_window(
        baseline_rows,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )
    position = position_rows[0] if position_rows else {}
    activity_by_ute = {int(row["ute_empresa_id"]): row for row in ute_activity_rows}
    miembros_by_ute: dict[int, list[str]] = defaultdict(list)
    for row in ute_miembros_rows:
        miembros_by_ute[int(row["ute_empresa_id"])].append(str(row["nombre_canonico"]))
    participaciones_ute = [
        {
            "ute_empresa_id": int(row["ute_empresa_id"]),
            "ute_nombre": row["ute_nombre"],
            "otros_miembros": miembros_by_ute.get(int(row["ute_empresa_id"]), []),
            "contratos": int(
                activity_by_ute.get(int(row["ute_empresa_id"]), {}).get("contratos", 0)
            ),
            "importe_total": float(
                activity_by_ute.get(int(row["ute_empresa_id"]), {}).get("importe_total", 0)
            ),
        }
        for row in ute_identity_rows
    ]
    movements = _company_movements(
        comparison=comparison,
        concentration=concentration,
        pct_single=pct_single,
        offer_coverage_count=len(offers),
        baseline_rows=baseline_rows,
    )
    recent_contracts = []
    for row in sorted(
        scope_rows,
        key=lambda item: str(item.get("fecha_adjudicacion") or ""),
        reverse=True,
    )[:12]:
        budget = float(row.get("presupuesto_licitacion") or 0)
        awarded = row.get("importe_adjudicado")
        baja_pct = (
            (1.0 - float(awarded) / budget) * 100 if budget > 0 and awarded is not None else None
        )
        recent_contracts.append(
            {
                "licitacion_id": row["licitacion_id"],
                "titulo": row.get("titulo"),
                "organo_contratacion": row.get("organo_contratacion"),
                "fecha_adjudicacion": row.get("fecha_adjudicacion"),
                "importe_adjudicado": awarded,
                "baja_pct": baja_pct,
            }
        )
    return {
        "_exists": bool(identity_rows),
        "empresa": {
            "empresa_id": empresa_id,
            "nombre": identity.get("nombre_canonico") or f"Empresa {empresa_id}",
            "nif": identity.get("nif_canonico"),
            "es_ute": bool(identity.get("es_ute")),
            "grupo": identity.get("grupo"),
        },
        "scope": {
            "fecha_desde": fecha_desde.isoformat() if fecha_desde else None,
            "fecha_hasta": fecha_hasta.isoformat() if fecha_hasta else None,
            "cpv": cpv_prefix,
            "ccaas": ccaas or [],
            "tecnologias": tecnologias or [],
            "importe_min": importe_min,
            "analysis_universe": analysis_universe,
        },
        "actividad_historica": {
            "contratos": int(history.get("contratos") or 0),
            "importe_total": float(history.get("importe_total") or 0),
            "primera_adjudicacion": history.get("primera_adjudicacion"),
            "ultima_adjudicacion": history.get("ultima_adjudicacion"),
        },
        "totales": {
            "contratos": total_contracts,
            "importe_total": total_amount,
            "importe_mediano": float(median(amounts)) if amounts else None,
            "ofertas_medias": round(sum(offers) / len(offers), 1) if offers else None,
            "baja_media_pct": round(sum(discounts) / len(discounts), 1) if discounts else None,
            "pct_oferta_unica": pct_single,
            "cobertura_ofertas_pct": _pct(float(len(offers)), float(total_contracts)),
            "primera_adjudicacion": min(valid_dates).isoformat() if valid_dates else None,
            "ultima_adjudicacion": max(valid_dates).isoformat() if valid_dates else None,
            "organos": len(
                {row["organo_contratacion"] for row in scope_rows if row.get("organo_contratacion")}
            ),
            "territorios": len({row["ccaa"] for row in scope_rows if row.get("ccaa")}),
            "familias_cpv": len({str(row["cpv"])[:2] for row in scope_rows if row.get("cpv")}),
        },
        "posicion_mercado": {
            "rank": int(position["rank"]) if position.get("rank") is not None else None,
            "empresas": int(position.get("empresas") or 0),
            "cuota_pct": (
                round(float(position["cuota_pct"]), 2)
                if position.get("cuota_pct") is not None
                else None
            ),
            "importe_segmento": float(position.get("importe_segmento") or 0),
        },
        "comparacion": comparison,
        "concentracion_clientes": concentration,
        "por_cpv": cpv_rows,
        "por_ccaa": ccaa_rows,
        "organos_principales": organ_rows,
        "por_anio": year_rows,
        "movimientos": movements,
        "contratos_recientes": recent_contracts,
        "participaciones_ute": participaciones_ute,
        **_cortes_f35(scope_rows),
    }


def _cortes_f35(scope_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """F3.5 — los cortes por procedimiento y por tramo sobre la actividad filtrada.

    `corte_por_procedimiento`/`corte_por_tramo` agrupan por ``importe`` (el de
    licitación: la baja se mide contra él y el tramo LCSP también). En las
    filas del dossier ese número se llama ``presupuesto_licitacion``, así que
    se renombra aquí en vez de tocar la consulta que comparten todas las
    secciones del perfil.
    """
    filas = [{**row, "importe": row.get("presupuesto_licitacion")} for row in scope_rows]
    return {
        "por_procedimiento": [c.model_dump() for c in corte_por_procedimiento(filas)],
        "por_tramo_importe": [c.model_dump() for c in corte_por_tramo(filas)],
        "corte_min_n": MIN_POR_CELDA,
    }


def listar_adjudicaciones_empresa(
    empresa_id: int,
    *,
    empresa_ids: list[int] | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    cpv_prefix: str | None = None,
    ccaas: list[str] | None = None,
    tecnologias: list[str] | None = None,
    importe_min: float | None = None,
    q: str | None = None,
    organo: str | None = None,
    sort: str = "fecha_desc",
    limit: int = 25,
    offset: int = 0,
    analysis_universe: AnalysisUniverse = "technology_observed",
) -> dict[str, Any]:
    """Return the company's real awards with server-side filtering and pagination.

    ``empresa_ids`` agrega las adjudicaciones de varias identidades del
    maestro que representan al mismo competidor analítico (ver `perfil_empresa`).

    Usa `_scope_sql()`, que aplica `exclude_duplicados_sql()` para excluir
    duplicados cross-fuente de las tablas licitaciones/adjudicaciones.

    ``limit`` y ``offset`` los acota el repositorio junto a la consulta; la
    respuesta devuelve los efectivos, no los pedidos.
    """
    group_ids = sorted({empresa_id, *(empresa_ids or [])})
    scope_alcance = _scope_sql(
        empresa_id=empresa_id,
        empresa_ids=group_ids if len(group_ids) > 1 else None,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        cpv_prefix=cpv_prefix,
        ccaas=ccaas,
        tecnologias=tecnologias,
        importe_min=importe_min,
        analysis_universe=analysis_universe,
    )
    pagina = mercado_repo.adjudicaciones_empresa(
        scope_alcance,
        q=q,
        organo=organo,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return {
        "items": pagina.items,
        "total": pagina.total,
        "limit": pagina.limit,
        "offset": pagina.offset,
    }
