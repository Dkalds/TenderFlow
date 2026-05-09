"""Job de pre-cálculo de KPIs — se ejecuta tras cada scraping.

Calcula métricas clave sobre las licitaciones y las persiste en la tabla
``kpi_snapshots``. El dashboard puede leer estos snapshots en vez de
recalcular sobre el DataFrame completo en cada sesión.

Uso:
    python -m scheduler.kpi_precompute          # Ejecuta el cálculo
    python -m scheduler.kpi_precompute --latest # Muestra el último snapshot
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)


# ── Definición de KPIs a pre-calcular ────────────────────────────────────────

def _compute_all_kpis(conn: Any) -> list[dict[str, Any]]:
    """Calcula todos los KPIs desde la BD directamente (sin cargar Streamlit).

    Returns:
        Lista de {metrica, dimension, valor, valor_text}.
    """
    snapshots: list[dict[str, Any]] = []
    now = datetime.now(UTC).isoformat()

    # ── Métricas globales ─────────────────────────────────────────────────

    # Total de licitaciones
    row = conn.execute("SELECT COUNT(*) FROM licitaciones").fetchone()
    snapshots.append({"metrica": "total_licitaciones", "dimension": "global", "valor": row[0]})

    # Importe total y medio
    row = conn.execute(
        "SELECT SUM(importe), AVG(importe) FROM licitaciones WHERE importe IS NOT NULL"
    ).fetchone()
    snapshots.append({"metrica": "importe_total", "dimension": "global", "valor": row[0] or 0.0})
    snapshots.append({"metrica": "importe_medio", "dimension": "global", "valor": row[1] or 0.0})

    # Órganos distintos
    row = conn.execute(
        "SELECT COUNT(DISTINCT organo_contratacion) FROM licitaciones "
        "WHERE organo_contratacion IS NOT NULL"
    ).fetchone()
    snapshots.append({"metrica": "n_organos", "dimension": "global", "valor": row[0]})

    # CCAA distintas
    row = conn.execute(
        "SELECT COUNT(DISTINCT ccaa) FROM licitaciones WHERE ccaa IS NOT NULL"
    ).fetchone()
    snapshots.append({"metrica": "n_ccaa", "dimension": "global", "valor": row[0]})

    # Licitaciones últimos 30 días
    row = conn.execute(
        "SELECT COUNT(*) FROM licitaciones "
        "WHERE fecha_publicacion >= date('now', '-30 days')"
    ).fetchone()
    snapshots.append({"metrica": "licitaciones_30d", "dimension": "global", "valor": row[0]})

    # Licitaciones 30d anteriores (para delta)
    row = conn.execute(
        "SELECT COUNT(*) FROM licitaciones "
        "WHERE fecha_publicacion >= date('now', '-60 days') "
        "  AND fecha_publicacion < date('now', '-30 days')"
    ).fetchone()
    snapshots.append({"metrica": "licitaciones_30d_prev", "dimension": "global", "valor": row[0]})

    # ── Por CCAA ──────────────────────────────────────────────────────────

    rows = conn.execute(
        "SELECT ccaa, COUNT(*) as n, SUM(importe) as total "
        "FROM licitaciones WHERE ccaa IS NOT NULL "
        "GROUP BY ccaa ORDER BY n DESC"
    ).fetchall()
    ccaa_data = [{"ccaa": r[0], "n": r[1], "importe": r[2]} for r in rows]
    snapshots.append({
        "metrica": "licitaciones_por_ccaa",
        "dimension": "global",
        "valor": None,
        "valor_text": json.dumps(ccaa_data, ensure_ascii=False),
    })

    # ── Por estado ────────────────────────────────────────────────────────

    rows = conn.execute(
        "SELECT estado, COUNT(*) FROM licitaciones WHERE estado IS NOT NULL "
        "GROUP BY estado ORDER BY 2 DESC"
    ).fetchall()
    estado_data = {r[0]: r[1] for r in rows}
    snapshots.append({
        "metrica": "licitaciones_por_estado",
        "dimension": "global",
        "valor": None,
        "valor_text": json.dumps(estado_data, ensure_ascii=False),
    })

    # ── Adjudicaciones ────────────────────────────────────────────────────

    row = conn.execute("SELECT COUNT(*), COUNT(DISTINCT licitacion_id) FROM adjudicaciones").fetchone()
    snapshots.append({"metrica": "total_adjudicaciones", "dimension": "global", "valor": row[0]})
    snapshots.append({"metrica": "licitaciones_con_adj", "dimension": "global", "valor": row[1]})

    # Top 10 adjudicatarios por importe
    rows = conn.execute(
        "SELECT nombre, COUNT(*) as n, SUM(importe_adjudicado) as total "
        "FROM adjudicaciones WHERE nombre IS NOT NULL AND importe_adjudicado IS NOT NULL "
        "GROUP BY nombre ORDER BY total DESC LIMIT 10"
    ).fetchall()
    top_adj = [{"nombre": r[0], "n": r[1], "importe": r[2]} for r in rows]
    snapshots.append({
        "metrica": "top10_adjudicatarios",
        "dimension": "global",
        "valor": None,
        "valor_text": json.dumps(top_adj, ensure_ascii=False),
    })

    # ── Serie mensual últimos 24 meses ────────────────────────────────────

    rows = conn.execute(
        "SELECT strftime('%Y-%m', fecha_publicacion) as mes, "
        "       COUNT(*) as n, SUM(importe) as total "
        "FROM licitaciones "
        "WHERE fecha_publicacion >= date('now', '-24 months') "
        "GROUP BY mes ORDER BY mes"
    ).fetchall()
    serie = [{"mes": r[0], "n": r[1], "importe": r[2]} for r in rows]
    snapshots.append({
        "metrica": "serie_mensual_24m",
        "dimension": "global",
        "valor": None,
        "valor_text": json.dumps(serie, ensure_ascii=False),
    })

    # Añadir timestamp a todos
    for s in snapshots:
        s.setdefault("valor_text", None)
        s["computed_at"] = now

    return snapshots


def _persist_snapshots(conn: Any, snapshots: list[dict[str, Any]]) -> int:
    """Inserta los snapshots en la BD. Devuelve el número de filas insertadas."""
    conn.execute(
        "DELETE FROM kpi_snapshots WHERE computed_at = (SELECT MAX(computed_at) FROM kpi_snapshots)"
        " OR 1"  # Limpiar todos antes de insertar nuevo snapshot completo
    )
    n = 0
    for s in snapshots:
        conn.execute(
            "INSERT INTO kpi_snapshots (computed_at, metrica, dimension, valor, valor_text) "
            "VALUES (?, ?, ?, ?, ?)",
            (s["computed_at"], s["metrica"], s["dimension"], s.get("valor"), s.get("valor_text")),
        )
        n += 1
    return n


def run_kpi_precompute() -> dict[str, Any]:
    """Ejecuta el pre-cálculo completo de KPIs y los persiste en la BD.

    Returns:
        Resumen con n_metricas calculadas y tiempo de ejecución.
    """
    import time

    from db.database import connect, init_db

    t0 = time.monotonic()
    init_db()

    with connect() as c:
        snapshots = _compute_all_kpis(c)
        n = _persist_snapshots(c, snapshots)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    log.info("kpi_precompute.done", n_metricas=n, elapsed_ms=elapsed_ms)
    return {"n_metricas": n, "elapsed_ms": elapsed_ms}


def get_latest_snapshot(metrica: str, dimension: str = "global") -> dict[str, Any] | None:
    """Lee el snapshot más reciente de una métrica desde la BD.

    Args:
        metrica: Nombre de la métrica (e.g. "total_licitaciones").
        dimension: Dimensión (default "global").

    Returns:
        Dict con {valor, valor_text, computed_at} o None si no hay datos.
    """
    from db.database import connect

    with connect() as c:
        row = c.execute(
            "SELECT valor, valor_text, computed_at FROM kpi_snapshots "
            "WHERE metrica = ? AND dimension = ? "
            "ORDER BY computed_at DESC LIMIT 1",
            [metrica, dimension],
        ).fetchone()
    if row is None:
        return None
    result: dict[str, Any] = {"valor": row[0], "computed_at": row[2]}
    if row[1]:
        try:
            result["valor_text"] = json.loads(row[1])
        except json.JSONDecodeError:
            result["valor_text"] = row[1]
    return result


def get_all_latest() -> dict[str, Any]:
    """Devuelve todos los snapshots más recientes como un dict plano.

    Útil para que el dashboard cargue todos los KPIs pre-calculados de una vez.
    """
    from db.database import connect

    with connect() as c:
        # Obtener la fecha del snapshot más reciente
        row = c.execute("SELECT MAX(computed_at) FROM kpi_snapshots").fetchone()
        if not row or not row[0]:
            return {}
        latest_ts = row[0]

        rows = c.execute(
            "SELECT metrica, dimension, valor, valor_text FROM kpi_snapshots "
            "WHERE computed_at = ?",
            [latest_ts],
        ).fetchall()

    result: dict[str, Any] = {"_computed_at": latest_ts}
    for metrica, dimension, valor, valor_text in rows:
        key = metrica if dimension == "global" else f"{metrica}__{dimension}"
        if valor_text:
            try:
                result[key] = json.loads(valor_text)
            except json.JSONDecodeError:
                result[key] = valor_text
        else:
            result[key] = valor
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        print("Calculando KPIs...")
        result = run_kpi_precompute()
        print(f"  Métricas calculadas: {result['n_metricas']}")
        print(f"  Tiempo: {result['elapsed_ms']}ms")
    elif cmd == "--latest":
        from db.database import init_db
        init_db()
        data = get_all_latest()
        if not data:
            print("No hay snapshots disponibles. Ejecuta primero: python -m scheduler.kpi_precompute")
        else:
            print(f"Snapshot de: {data.get('_computed_at')}")
            for k, v in data.items():
                if k != "_computed_at":
                    print(f"  {k}: {v}")
    else:
        print("Uso: python -m scheduler.kpi_precompute [run|--latest]")
        sys.exit(1)
