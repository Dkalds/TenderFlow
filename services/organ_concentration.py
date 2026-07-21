"""Concentración / incumbencia por órgano contratante.

Función pura sobre DataFrame (sin BD ni mocks). Para cada órgano calcula la
estructura de su base de proveedores: nº de empresas distintas, cuota del top-1
y CR3 (top-3), índice **HHI** (0-10000, misma convención que
``services.analytics.competitors._compute_hhi``) y una clasificación de
**apertura** del comprador. Responde la pregunta "¿qué órganos son cotos
cerrados y cuáles compran de forma abierta?".
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Umbrales estándar (DOJ/FTC) sobre HHI 0-10000.
_HHI_ABIERTO = 1500.0
_HHI_MODERADO = 2500.0


def _clasificar_apertura(hhi: float) -> str:
    """Clasifica la apertura de un comprador por su HHI (0-10000)."""
    if hhi < _HHI_ABIERTO:
        return "Abierto"
    if hhi < _HHI_MODERADO:
        return "Moderado"
    return "Cerrado"


def build_organ_concentration(
    adj: pd.DataFrame,
    *,
    min_contratos: int = 5,
    top_n: int = 25,
) -> dict[str, Any]:
    """Concentración de la base de proveedores por órgano.

    Cada fila del resultado agrega las adjudicaciones de un órgano y describe cuán
    concentrada está entre sus empresas adjudicatarias. Las cuotas se calculan por
    **importe** (si el órgano no tiene importe, se degradan a nº de contratos).

    Args:
        adj: DataFrame con ``organo_contratacion``, ``empresa_key``,
            ``nombre_canonico``, ``importe_adjudicado``.
        min_contratos: descarta órganos con menos adjudicaciones (ruido).
        top_n: nº máximo de órganos devueltos (ordenados por HHI desc).

    Returns:
        ``{"organos": [...], "total_organos": int}``. Cada órgano trae:
        ``organo``, ``n_empresas``, ``n_contratos``, ``importe_total``,
        ``top_empresa``, ``cuota_top1``, ``cuota_top3``, ``hhi``, ``apertura``.
    """
    required = {"organo_contratacion", "empresa_key", "nombre_canonico", "importe_adjudicado"}
    if not required.issubset(adj.columns):
        return {"organos": [], "total_organos": 0}

    dff = adj.dropna(subset=["organo_contratacion", "empresa_key"]).copy()
    if dff.empty:
        return {"organos": [], "total_organos": 0}

    dff["importe_adjudicado"] = pd.to_numeric(dff["importe_adjudicado"], errors="coerce").fillna(
        0.0
    )

    total_organos = int(dff["organo_contratacion"].nunique())

    filas: list[dict[str, Any]] = []
    for organo, grupo in dff.groupby("organo_contratacion", sort=False):
        n_contratos = len(grupo)
        if n_contratos < min_contratos:
            continue

        por_empresa = grupo.groupby("empresa_key").agg(
            importe=("importe_adjudicado", "sum"),
            nombre=("nombre_canonico", "first"),
        )
        importe_total = float(por_empresa["importe"].sum())

        # Peso para las cuotas: importe si existe, si no nº de contratos.
        if importe_total > 0:
            pesos = por_empresa["importe"]
            base = importe_total
        else:
            pesos = grupo.groupby("empresa_key").size().reindex(por_empresa.index).fillna(0)
            base = float(pesos.sum())

        if base <= 0:
            continue

        shares = (pesos / base * 100.0).sort_values(ascending=False)
        # HHI = Σ (cuota_i)^2 con cuota en % → 0-10000 (misma convención que
        # competitors._compute_hhi). 1 solo proveedor ⇒ 10000 (coto cerrado).
        hhi = float((shares**2).sum())
        cuota_top1 = float(shares.iloc[0])
        cuota_top3 = float(shares.iloc[:3].sum())
        top_key = shares.index[0]
        top_empresa = str(por_empresa.loc[top_key, "nombre"])

        filas.append(
            {
                "organo": str(organo),
                "n_empresas": int(por_empresa.shape[0]),
                "n_contratos": n_contratos,
                "importe_total": importe_total,
                "top_empresa": top_empresa,
                "cuota_top1": round(cuota_top1, 1),
                "cuota_top3": round(cuota_top3, 1),
                "hhi": round(hhi, 1),
                "apertura": _clasificar_apertura(hhi),
            }
        )

    # Orden: los cotos más cerrados primero (HHI desc), importe como desempate.
    filas.sort(key=lambda r: (r["hhi"], r["importe_total"]), reverse=True)
    return {"organos": filas[:top_n], "total_organos": total_organos}
