"""Cuota de mercado, concentración (HHI) y presión competitiva.

Todas las métricas se calculan sobre empresas canónicas del maestro (v35),
no sobre strings de nombre — sin eso las cuotas estarían fragmentadas entre
variantes del mismo adjudicatario.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import median
from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from services.dedupe import exclude_duplicados_sql
from services.sql_fragments import round_sql

_SEGMENT_COLUMNS = {
    "cpv": "substr(l.cpv, 1, 2)",
    "ccaa": "l.ccaa",
    "organo": "l.organo_contratacion",
    "tecnologia": "l.tecnologia",
}


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
    filters = ""
    params: list[Any] = []
    if cpv_prefix:
        filters += " AND l.cpv LIKE ?"
        params.append(f"{cpv_prefix}%")
    if ccaa:
        filters += " AND l.ccaa = ?"
        params.append(ccaa)
    if desde:
        filters += " AND a.fecha_adjudicacion >= ?"
        params.append(desde)

    sql = f"""
        WITH segmento AS (
            SELECT a.empresa_id,
                   COALESCE(e.nombre_canonico, a.nombre) AS empresa,
                   MAX(COALESCE(e.es_ute, 0)) AS es_ute,
                   COUNT(*) AS contratos,
                   COALESCE(SUM(a.importe_adjudicado), 0) AS importe,
                   {round_sql("AVG(a.n_ofertas_recibidas)", 1)} AS ofertas_medias
            FROM adjudicaciones a
            JOIN licitaciones l ON l.id_externo = a.licitacion_id
            LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
            WHERE a.importe_adjudicado > 0 AND {exclude_duplicados_sql()} {filters}
            GROUP BY a.empresa_id, empresa
        )
        SELECT empresa_id, empresa, es_ute, contratos, importe, ofertas_medias,
               {round_sql("importe * 100.0 / NULLIF((SELECT SUM(importe) FROM segmento), 0)", 2)}
                   AS cuota_pct
        FROM segmento
        ORDER BY importe DESC
        LIMIT ?
    """  # noqa: S608 — filters se construye solo con fragmentos constantes; valores con ?
    params.append(max(1, min(int(limit), 500)))
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


def concentracion_hhi(*, segment_by: str = "cpv", min_contratos: int = 5) -> list[dict[str, Any]]:
    """Índice Herfindahl-Hirschman por segmento (0-10000).

    HHI = suma de (cuota_i * 100)^2. Lectura estándar: <1500 competitivo,
    1500-2500 moderadamente concentrado, >2500 concentrado. Un segmento
    concentrado con vencimientos próximos es una oportunidad de entrada;
    uno competitivo exige afinar la baja (ver ``bajas``).
    """
    if segment_by not in _SEGMENT_COLUMNS:
        raise ValueError(
            f"segment_by inválido: {segment_by!r} (válidos: {sorted(_SEGMENT_COLUMNS)})"
        )
    seg_col = _SEGMENT_COLUMNS[segment_by]

    sql = f"""
        WITH por_empresa AS (
            SELECT {seg_col} AS segmento,
                   a.empresa_id,
                   SUM(a.importe_adjudicado) AS importe
            FROM adjudicaciones a
            JOIN licitaciones l ON l.id_externo = a.licitacion_id
            WHERE a.importe_adjudicado > 0 AND {seg_col} IS NOT NULL
              AND {exclude_duplicados_sql()}
            GROUP BY segmento, a.empresa_id
        ),
        totales AS (
            SELECT segmento,
                   SUM(importe) AS total,
                   COUNT(*) AS empresas
            FROM por_empresa GROUP BY segmento
        )
        SELECT * FROM (
            SELECT p.segmento,
                   t.empresas,
                   t.total AS importe_total,
                   (SELECT COUNT(*) FROM adjudicaciones a2
                    JOIN licitaciones l2 ON l2.id_externo = a2.licitacion_id
                    WHERE {seg_col.replace("l.", "l2.")} = p.segmento
                      AND a2.importe_adjudicado > 0
                      AND {exclude_duplicados_sql("l2.id_externo")}) AS contratos,
                   {round_sql("SUM((p.importe * 100.0 / t.total) * (p.importe * 100.0 / t.total))", 0)}
                       AS hhi
            FROM por_empresa p
            JOIN totales t ON t.segmento = p.segmento
            GROUP BY p.segmento, t.empresas, t.total
        ) seg
        WHERE contratos >= ?
        ORDER BY hhi DESC
    """  # noqa: S608 — seg_col sale de _SEGMENT_COLUMNS (whitelist); valores con ?
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, [max(1, int(min_contratos))]))


def _scope_sql(
    *,
    empresa_id: int | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    cpv_prefix: str | None = None,
    ccaas: list[str] | None = None,
    tecnologias: list[str] | None = None,
    importe_min: float | None = None,
) -> tuple[str, list[Any]]:
    """Build the shared award scope with parameterised values only."""
    clauses = [exclude_duplicados_sql()]
    params: list[Any] = []
    if empresa_id is not None:
        clauses.append("a.empresa_id = ?")
        params.append(empresa_id)
    if fecha_desde is not None:
        clauses.append("a.fecha_adjudicacion >= ?")
        params.append(fecha_desde.isoformat())
    if fecha_hasta is not None:
        clauses.append("a.fecha_adjudicacion <= ?")
        params.append(fecha_hasta.isoformat())
    if cpv_prefix:
        clauses.append("l.cpv LIKE ?")
        params.append(f"{cpv_prefix}%")
    if ccaas:
        placeholders = ", ".join("?" for _ in ccaas)
        clauses.append(f"l.ccaa IN ({placeholders})")
        params.extend(ccaas)
    if tecnologias:
        placeholders = ", ".join("?" for _ in tecnologias)
        clauses.append(f"l.tecnologia IN ({placeholders})")
        params.extend(tecnologias)
    if importe_min is not None:
        clauses.append("l.importe >= ?")
        params.append(max(0.0, float(importe_min)))
    return " AND ".join(clauses), params


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
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    cpv_prefix: str | None = None,
    ccaas: list[str] | None = None,
    tecnologias: list[str] | None = None,
    importe_min: float | None = None,
) -> dict[str, Any]:
    """Return an explainable, filter-coherent competitive company dossier.

    Todas las queries sobre licitaciones/adjudicaciones usan `_scope_sql()`,
    que aplica `exclude_duplicados_sql()` para excluir duplicados cross-fuente.
    """
    scope_where, scope_params = _scope_sql(
        empresa_id=empresa_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        cpv_prefix=cpv_prefix,
        ccaas=ccaas,
        tecnologias=tecnologias,
        importe_min=importe_min,
    )
    baseline_where, baseline_params = _scope_sql(
        empresa_id=empresa_id,
        cpv_prefix=cpv_prefix,
        ccaas=ccaas,
        tecnologias=tecnologias,
        importe_min=importe_min,
    )
    market_where, market_params = _scope_sql(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        cpv_prefix=cpv_prefix,
        ccaas=ccaas,
        tecnologias=tecnologias,
        importe_min=importe_min,
    )
    history_where, history_params = _scope_sql(empresa_id=empresa_id)
    activity_select = """
        SELECT a.licitacion_id,
               l.titulo,
               a.fecha_adjudicacion,
               a.importe_adjudicado,
               a.n_ofertas_recibidas,
               l.importe AS presupuesto_licitacion,
               l.organo_contratacion,
               l.ccaa,
               l.cpv,
               l.tecnologia
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
    """
    with connect_read() as c:
        identity_rows = rows_to_dicts(
            c.execute(
                "SELECT e.empresa_id, e.nombre_canonico, e.nif_canonico, e.es_ute, "
                "       g.nombre AS grupo "
                "FROM empresas e LEFT JOIN grupos_empresariales g ON g.grupo_id = e.grupo_id "
                "WHERE e.empresa_id = ?",
                (empresa_id,),
            )
        )
        history_rows = rows_to_dicts(
            c.execute(
                f"""
                SELECT COUNT(*) AS contratos,
                       COALESCE(SUM(a.importe_adjudicado), 0) AS importe_total,
                       MIN(a.fecha_adjudicacion) AS primera_adjudicacion,
                       MAX(a.fecha_adjudicacion) AS ultima_adjudicacion
                FROM adjudicaciones a
                JOIN licitaciones l ON l.id_externo = a.licitacion_id
                WHERE {history_where}
                """,  # noqa: S608 -- history_where only contains constant fragments
                history_params,
            )
        )
        scope_rows = rows_to_dicts(
            c.execute(f"{activity_select} WHERE {scope_where}", scope_params)
        )
        baseline_rows = (
            scope_rows
            if fecha_desde is None and fecha_hasta is None
            else rows_to_dicts(
                c.execute(
                    f"{activity_select} WHERE {baseline_where}",
                    baseline_params,
                )
            )
        )
        position_rows = rows_to_dicts(
            c.execute(
                f"""
                WITH segmento AS (
                    SELECT a.empresa_id,
                           COALESCE(SUM(a.importe_adjudicado), 0) AS importe
                    FROM adjudicaciones a
                    JOIN licitaciones l ON l.id_externo = a.licitacion_id
                    WHERE a.empresa_id IS NOT NULL AND {market_where}
                    GROUP BY a.empresa_id
                ),
                ranked AS (
                    SELECT empresa_id,
                           importe,
                           RANK() OVER (ORDER BY importe DESC) AS rank,
                           COUNT(*) OVER () AS empresas,
                           SUM(importe) OVER () AS importe_segmento
                    FROM segmento
                )
                SELECT empresa_id, rank, empresas, importe_segmento,
                       importe * 100.0 / NULLIF(importe_segmento, 0) AS cuota_pct
                FROM ranked WHERE empresa_id = ?
                """,  # noqa: S608 -- market_where only contains constant fragments
                [*market_params, empresa_id],
            )
        )

    identity = (
        identity_rows[0]
        if identity_rows
        else {
            "empresa_id": empresa_id,
            "nombre_canonico": f"Empresa {empresa_id}",
            "nif_canonico": None,
            "es_ute": 0,
            "grupo": None,
        }
    )
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
    }


_AWARD_SORT_SQL = {
    "fecha_desc": "a.fecha_adjudicacion IS NULL, a.fecha_adjudicacion DESC",
    "fecha_asc": "a.fecha_adjudicacion IS NULL, a.fecha_adjudicacion ASC",
    "importe_desc": "a.importe_adjudicado IS NULL, a.importe_adjudicado DESC",
    "importe_asc": "a.importe_adjudicado IS NULL, a.importe_adjudicado ASC",
}


def listar_adjudicaciones_empresa(
    empresa_id: int,
    *,
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
) -> dict[str, Any]:
    """Return the company's real awards with server-side filtering and pagination.

    Usa `_scope_sql()`, que aplica `exclude_duplicados_sql()` para excluir
    duplicados cross-fuente de las tablas licitaciones/adjudicaciones.
    """
    where, params = _scope_sql(
        empresa_id=empresa_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        cpv_prefix=cpv_prefix,
        ccaas=ccaas,
        tecnologias=tecnologias,
        importe_min=importe_min,
    )
    clauses = [where]
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        clauses.append(
            "(LOWER(COALESCE(l.titulo, '')) LIKE ? "
            "OR LOWER(COALESCE(l.organo_contratacion, '')) LIKE ? "
            "OR LOWER(COALESCE(a.licitacion_id, '')) LIKE ?)"
        )
        params.extend([needle, needle, needle])
    if organo and organo.strip():
        clauses.append("LOWER(COALESCE(l.organo_contratacion, '')) LIKE ?")
        params.append(f"%{organo.strip().lower()}%")
    full_where = " AND ".join(clauses)
    safe_limit = max(1, min(int(limit), 500))
    safe_offset = max(0, int(offset))
    order_sql = _AWARD_SORT_SQL.get(sort, _AWARD_SORT_SQL["fecha_desc"])

    with connect_read() as c:
        total = int(
            c.execute(
                f"""
                SELECT COUNT(*)
                FROM adjudicaciones a
                JOIN licitaciones l ON l.id_externo = a.licitacion_id
                WHERE {full_where}
                """,  # noqa: S608 -- full_where only contains constant fragments
                params,
            ).fetchone()[0]
        )
        items = rows_to_dicts(
            c.execute(
                f"""
                SELECT a.licitacion_id,
                       l.titulo,
                       l.organo_contratacion,
                       a.fecha_adjudicacion,
                       l.cpv,
                       l.ccaa,
                       l.tecnologia,
                       l.importe AS presupuesto_licitacion,
                       a.importe_adjudicado,
                       CASE
                         WHEN l.importe > 0 AND a.importe_adjudicado IS NOT NULL
                         THEN (1.0 - (a.importe_adjudicado * 1.0) / l.importe) * 100
                         ELSE NULL
                       END AS baja_pct,
                       a.n_ofertas_recibidas
                FROM adjudicaciones a
                JOIN licitaciones l ON l.id_externo = a.licitacion_id
                WHERE {full_where}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
                """,  # noqa: S608 -- fragments come from whitelists/constants
                [*params, safe_limit, safe_offset],
            )
        )
    return {"items": items, "total": total, "limit": safe_limit, "offset": safe_offset}
