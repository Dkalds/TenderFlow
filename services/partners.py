"""Análisis de ecosistema de partners y grafo de adjudicatarios.

Funciones para construir grafos de co-adjudicación (UTEs),
rankings de ganadores por segmento y sugerencias de partners
para subcontratación.
"""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Any

import pandas as pd

from observability.logging import get_logger
from services.normalization import parse_ute_members

log = get_logger(__name__)


def build_partnership_graph(
    adj: pd.DataFrame,
    *,
    min_contratos: int = 1,
    top_nodes: int = 80,
) -> dict[str, list[dict[str, Any]]]:
    """Construye grafo de co-adjudicaciones en UTEs.

    Nodos = empresas, aristas = co-participación en UTEs.
    Peso de arista = nº contratos juntos + importe acumulado.

    Returns:
        ``{"nodes": [...], "edges": [...]}``
    """
    utes = adj[adj["es_ute"]].copy()
    if utes.empty:
        return {"nodes": [], "edges": []}

    utes["miembros"] = utes["nombre"].apply(parse_ute_members)
    utes_valid = utes[utes["miembros"].apply(len) >= 2]

    pair_counter: Counter[tuple[str, str]] = Counter()
    pair_importe: dict[tuple[str, str], float] = {}

    for _, row in utes_valid.iterrows():
        ms = sorted(set(row["miembros"]))
        imp = float(row["importe_adjudicado"]) if pd.notna(row.get("importe_adjudicado")) else 0.0
        for a, b in combinations(ms, 2):
            key = (a, b)
            pair_counter[key] += 1
            pair_importe[key] = pair_importe.get(key, 0.0) + imp

    # Filter by minimum contratos
    filtered_pairs = {k: v for k, v in pair_counter.items() if v >= min_contratos}
    if not filtered_pairs:
        return {"nodes": [], "edges": []}

    # Collect nodes from filtered edges
    node_importe: dict[str, float] = {}
    node_contratos: dict[str, int] = {}
    for (a, b), n in filtered_pairs.items():
        node_contratos[a] = node_contratos.get(a, 0) + n
        node_contratos[b] = node_contratos.get(b, 0) + n
        imp = pair_importe.get((a, b), 0.0)
        node_importe[a] = node_importe.get(a, 0.0) + imp
        node_importe[b] = node_importe.get(b, 0.0) + imp

    # Limit to top N nodes by importe
    sorted_nodes = sorted(node_importe.items(), key=lambda x: x[1], reverse=True)
    top_node_names = {name for name, _ in sorted_nodes[:top_nodes]}

    edges = [
        {
            "source": a,
            "target": b,
            "contratos": n,
            "importe": pair_importe.get((a, b), 0.0),
        }
        for (a, b), n in filtered_pairs.items()
        if a in top_node_names and b in top_node_names
    ]

    # Detección de comunidades (modularidad) sobre el subgrafo final. Es la única
    # señal sintética nueva y se calcula en backend (§3.8): el frontend colorea por
    # clúster, no lo inventa. `community` es None si el grafo es trivial (≤1 clúster).
    community_map = _detect_communities(top_node_names, edges)

    nodes = [
        {
            "name": name,
            "contratos": node_contratos[name],
            "importe": node_importe[name],
            "community": community_map.get(name),
        }
        for name in top_node_names
    ]

    return {"nodes": nodes, "edges": edges}


def _detect_communities(node_names: set[str], edges: list[dict[str, Any]]) -> dict[str, int]:
    """Asigna un id de comunidad a cada nodo por modularidad (Louvain).

    Devuelve ``{nombre: community_id}``. Vacío si el grafo es trivial (sin aristas
    o una sola comunidad) — en ese caso no hay clustering significativo que mostrar.
    Determinista (``seed`` fijo) para que el coloreo sea estable entre peticiones.
    """
    if not edges or len(node_names) < 3:
        return {}
    try:
        import networkx as nx

        graph = nx.Graph()
        graph.add_nodes_from(node_names)
        for e in edges:
            graph.add_edge(e["source"], e["target"], weight=max(1, int(e["contratos"])))
        communities = nx.community.louvain_communities(graph, weight="weight", seed=42)
    except Exception:
        log.warning("partner_community_detection_failed", exc_info=True)
        return {}
    # Grafo trivial: una sola comunidad → sin clustering útil.
    if len(communities) <= 1:
        return {}
    # Orden estable: comunidades más grandes primero (ids bajos = clústeres grandes).
    ordered = sorted(communities, key=len, reverse=True)
    return {node: idx for idx, comm in enumerate(ordered) for node in comm}


def suggest_partners(
    adj: pd.DataFrame,
    *,
    keywords: list[str] | None = None,
    ccaa: str | None = None,
    min_importe: float = 0.0,
) -> pd.DataFrame:
    """Ranking de partners potenciales filtrado por keywords/CCAA.

    Filtra adjudicaciones por keywords en titulo/CPV, agrupa por empresa
    y calcula métricas de interés para subcontratación.

    Returns:
        DataFrame con columnas: empresa, empresa_key, n_contratos,
        importe_total, ticket_medio, cuota_pct, pct_ute, n_organos, es_pyme.
    """
    dff = adj.copy()

    if keywords:
        pattern = "|".join(keywords)
        titulo_match = dff["titulo"].str.contains(pattern, case=False, na=False)
        cpv_match = (
            dff["cpv"].str.contains(pattern, case=False, na=False)
            if "cpv" in dff.columns
            else False
        )
        dff = dff[titulo_match | cpv_match]

    if ccaa and ccaa != "Todas":
        dff = dff[dff["ccaa"] == ccaa]

    if min_importe > 0:
        dff = dff[dff["importe_adjudicado"].fillna(0) >= min_importe]

    if dff.empty:
        return pd.DataFrame()

    total_mercado = dff["importe_adjudicado"].sum(skipna=True)

    ranking = (
        dff.groupby("empresa_key", dropna=True)
        .agg(
            empresa=("nombre_canonico", "first"),
            n_contratos=("id", "count"),
            importe_total=("importe_adjudicado", "sum"),
            ticket_medio=("importe_adjudicado", "mean"),
            n_organos=("organo_contratacion", "nunique"),
            pct_ute=("es_ute", "mean"),
            es_pyme=("es_pyme", lambda x: int(x.eq(1).any())),
        )
        .reset_index()
        .sort_values("importe_total", ascending=False)
    )
    ranking["cuota_pct"] = ranking["importe_total"] / total_mercado * 100 if total_mercado else 0.0
    ranking["pct_ute"] = (ranking["pct_ute"] * 100).round(1)

    return ranking


def segment_winners(
    adj: pd.DataFrame,
    *,
    top_n: int = 20,
) -> pd.DataFrame:
    """Ranking global de ganadores con métricas de mercado.

    Returns:
        DataFrame con: empresa, empresa_key, n_contratos, importe_total,
        cuota_pct, ticket_medio, n_organos, n_ccaa.
    """
    if adj.empty:
        return pd.DataFrame()

    total_mercado = adj["importe_adjudicado"].sum(skipna=True)

    ranking = (
        adj.groupby("empresa_key", dropna=True)
        .agg(
            empresa=("nombre_canonico", "first"),
            n_contratos=("id", "count"),
            importe_total=("importe_adjudicado", "sum"),
            ticket_medio=("importe_adjudicado", "mean"),
            n_organos=("organo_contratacion", "nunique"),
            n_ccaa=("ccaa", "nunique"),
        )
        .reset_index()
        .sort_values("importe_total", ascending=False)
        .head(top_n)
    )
    ranking["cuota_pct"] = ranking["importe_total"] / total_mercado * 100 if total_mercado else 0.0

    return ranking


def company_profile(adj: pd.DataFrame, empresa_key: str) -> dict[str, Any]:
    """Perfil detallado de una empresa adjudicataria.

    Returns:
        Dict con: nombre, n_contratos, importe_total, top_organos,
        top_cpvs, pct_ute, ccaas, evolucion_mensual.
    """
    emp = adj[adj["empresa_key"] == empresa_key]
    if emp.empty:
        return {}

    nombre = emp["nombre_canonico"].iloc[0] if "nombre_canonico" in emp.columns else empresa_key

    top_organos = emp["organo_contratacion"].value_counts().head(5).to_dict()

    top_cpvs: dict[str, int] = {}
    if "cpv" in emp.columns:
        top_cpvs = dict(emp["cpv"].dropna().value_counts().head(5))

    # Evolución mensual
    evol = pd.DataFrame()
    if "fecha_adjudicacion" in emp.columns:
        tmp = emp.dropna(subset=["fecha_adjudicacion"]).copy()
        if not tmp.empty:
            tmp["mes"] = tmp["fecha_adjudicacion"].dt.to_period("M").astype(str)
            evol = (
                tmp.groupby("mes")
                .agg(n=("id", "count"), importe=("importe_adjudicado", "sum"))
                .reset_index()
            )

    # UTE partners
    ute_rows = emp[emp["es_ute"]]
    ute_partners: Counter[str] = Counter()
    for _, row in ute_rows.iterrows():
        members = parse_ute_members(row["nombre"])
        for m in members:
            ute_partners[m] += 1
    # Remove self
    norm_name = nombre.upper() if nombre else ""
    ute_partners.pop(norm_name, None)

    return {
        "nombre": nombre,
        "empresa_key": empresa_key,
        "n_contratos": len(emp),
        "importe_total": float(emp["importe_adjudicado"].sum(skipna=True)),
        "ticket_medio": float(emp["importe_adjudicado"].mean(skipna=True)),
        "pct_ute": float(emp["es_ute"].mean() * 100),
        "es_pyme": bool(emp["es_pyme"].eq(1).any()) if "es_pyme" in emp.columns else None,
        "top_organos": top_organos,
        "top_cpvs": top_cpvs,
        "ccaas": sorted(emp["ccaa"].dropna().unique().tolist()),
        "ute_partners": dict(ute_partners.most_common(10)),
        "evolucion": evol.to_dict("records") if not evol.empty else [],
    }
