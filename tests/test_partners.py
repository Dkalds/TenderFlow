"""Tests para services/partners.py – grafo de partners y rankings."""

from __future__ import annotations

import pandas as pd

from services.partners import (
    build_partnership_graph,
    company_profile,
    segment_winners,
    suggest_partners,
)

# ── helpers ──────────────────────────────────────────────────────────────────

_COLS = [
    "id",
    "nombre",
    "nombre_canonico",
    "empresa_key",
    "organo_contratacion",
    "importe_adjudicado",
    "ccaa",
    "cpv",
    "titulo",
    "es_ute",
    "es_pyme",
    "fecha_adjudicacion",
]


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """Crea un DataFrame con las columnas estándar de adjudicaciones."""
    df = pd.DataFrame(rows, columns=_COLS)
    if "fecha_adjudicacion" in df.columns:
        df["fecha_adjudicacion"] = pd.to_datetime(df["fecha_adjudicacion"])
    return df


def _ute_row(id_: int, name: str, importe: float, **kw) -> dict:
    """Shortcut para crear una fila UTE con nombre tipo 'UTE A / B'."""
    return {
        "id": id_,
        "nombre": name,
        "nombre_canonico": name,
        "empresa_key": f"key_{id_}",
        "organo_contratacion": kw.get("organo", "ORGANO1"),
        "importe_adjudicado": importe,
        "ccaa": kw.get("ccaa", "Madrid"),
        "cpv": kw.get("cpv", "45000000"),
        "titulo": kw.get("titulo", "Obra genérica"),
        "es_ute": True,
        "es_pyme": kw.get("es_pyme", 0),
        "fecha_adjudicacion": kw.get("fecha", "2024-01-15"),
    }


def _normal_row(id_: int, name: str, importe: float, **kw) -> dict:
    """Fila de adjudicación individual (no UTE)."""
    return {
        "id": id_,
        "nombre": name,
        "nombre_canonico": name,
        "empresa_key": kw.get("empresa_key", name.lower().replace(" ", "_")),
        "organo_contratacion": kw.get("organo", "ORGANO1"),
        "importe_adjudicado": importe,
        "ccaa": kw.get("ccaa", "Madrid"),
        "cpv": kw.get("cpv", "45000000"),
        "titulo": kw.get("titulo", "Obra genérica"),
        "es_ute": False,
        "es_pyme": kw.get("es_pyme", 0),
        "fecha_adjudicacion": kw.get("fecha", "2024-01-15"),
    }


# ── build_partnership_graph ──────────────────────────────────────────────────


class TestBuildPartnershipGraph:
    def test_ute_produces_nodes_and_edges(self):
        df = _make_df(
            [
                _ute_row(1, "UTE ACME / BETA", 100_000),
                _ute_row(2, "UTE ACME / BETA", 200_000),
            ]
        )
        result = build_partnership_graph(df)
        assert len(result["nodes"]) >= 2
        assert len(result["edges"]) >= 1
        edge = result["edges"][0]
        assert "source" in edge and "target" in edge
        assert edge["contratos"] == 2

    def test_empty_dataframe(self):
        df = _make_df([])
        result = build_partnership_graph(df)
        assert result == {"nodes": [], "edges": []}

    def test_no_utes_returns_empty(self):
        df = _make_df([_normal_row(1, "ACME", 50_000)])
        result = build_partnership_graph(df)
        assert result == {"nodes": [], "edges": []}

    def test_min_contratos_filter(self):
        df = _make_df(
            [
                _ute_row(1, "UTE X / Y", 100_000),
            ]
        )
        # Only 1 contract, require 2
        result = build_partnership_graph(df, min_contratos=2)
        assert result == {"nodes": [], "edges": []}

    def test_nodes_carry_community_field(self):
        """Cada nodo expone `community` (int o None) — contrato del grafo."""
        df = _make_df(
            [
                _ute_row(1, "UTE ACME / BETA", 100_000),
                _ute_row(2, "UTE ACME / BETA", 200_000),
            ]
        )
        result = build_partnership_graph(df)
        assert all("community" in n for n in result["nodes"])

    def test_community_detects_two_clusters(self):
        """Dos tríadas densas y desconectadas → ≥2 comunidades distintas."""
        rows = [
            # Clúster 1: A-B, B-C, A-C (todas co-licitan entre sí, repetidas)
            _ute_row(1, "UTE A / B", 100_000),
            _ute_row(2, "UTE A / B", 100_000),
            _ute_row(3, "UTE B / C", 100_000),
            _ute_row(4, "UTE B / C", 100_000),
            _ute_row(5, "UTE A / C", 100_000),
            _ute_row(6, "UTE A / C", 100_000),
            # Clúster 2: X-Y, Y-Z, X-Z (desconectado del clúster 1)
            _ute_row(7, "UTE X / Y", 100_000),
            _ute_row(8, "UTE X / Y", 100_000),
            _ute_row(9, "UTE Y / Z", 100_000),
            _ute_row(10, "UTE Y / Z", 100_000),
            _ute_row(11, "UTE X / Z", 100_000),
            _ute_row(12, "UTE X / Z", 100_000),
        ]
        result = build_partnership_graph(_make_df(rows))
        comms = {n["name"]: n["community"] for n in result["nodes"]}
        # Todos asignados (grafo no trivial) y ≥2 comunidades.
        assert all(v is not None for v in comms.values())
        assert len({v for v in comms.values()}) >= 2
        # A, B, C en la misma comunidad; X, Y, Z en otra.
        assert comms["A"] == comms["B"] == comms["C"]
        assert comms["X"] == comms["Y"] == comms["Z"]
        assert comms["A"] != comms["X"]


# ── suggest_partners ─────────────────────────────────────────────────────────


class TestSuggestPartners:
    def test_keyword_filter(self):
        df = _make_df(
            [
                _normal_row(1, "ACME", 100_000, titulo="Limpieza de edificios"),
                _normal_row(2, "BETA", 200_000, titulo="Construcción de puente"),
            ]
        )
        result = suggest_partners(df, keywords=["limpieza"])
        assert len(result) == 1
        assert result.iloc[0]["empresa"] == "ACME"

    def test_ccaa_filter(self):
        df = _make_df(
            [
                _normal_row(1, "ACME", 100_000, ccaa="Madrid"),
                _normal_row(2, "BETA", 200_000, ccaa="Cataluña"),
            ]
        )
        result = suggest_partners(df, ccaa="Madrid")
        assert len(result) == 1

    def test_no_matches_returns_empty(self):
        df = _make_df(
            [
                _normal_row(1, "ACME", 100_000, titulo="Obra civil"),
            ]
        )
        result = suggest_partners(df, keywords=["inexistente"])
        assert result.empty


# ── segment_winners ──────────────────────────────────────────────────────────


class TestSegmentWinners:
    def test_returns_top_n(self):
        rows = [
            _normal_row(i, f"EMP{i}", (100 - i) * 1000, empresa_key=f"emp{i}") for i in range(5)
        ]
        df = _make_df(rows)
        result = segment_winners(df, top_n=3)
        assert len(result) == 3

    def test_empty_dataframe(self):
        df = _make_df([])
        result = segment_winners(df)
        assert result.empty

    def test_sorted_by_importe(self):
        df = _make_df(
            [
                _normal_row(1, "SMALL", 10_000, empresa_key="small"),
                _normal_row(2, "BIG", 999_000, empresa_key="big"),
            ]
        )
        result = segment_winners(df, top_n=10)
        assert result.iloc[0]["empresa_key"] == "big"


# ── company_profile ──────────────────────────────────────────────────────────


class TestCompanyProfile:
    def test_correct_structure(self):
        df = _make_df(
            [
                _normal_row(1, "ACME", 100_000, empresa_key="acme"),
                _normal_row(2, "ACME", 200_000, empresa_key="acme", organo="ORGANO2"),
            ]
        )
        profile = company_profile(df, "acme")
        assert profile["nombre"] == "ACME"
        assert profile["n_contratos"] == 2
        assert profile["importe_total"] == 300_000.0
        assert "top_organos" in profile
        assert "ccaas" in profile

    def test_nonexistent_key(self):
        df = _make_df([_normal_row(1, "ACME", 100_000, empresa_key="acme")])
        profile = company_profile(df, "no_existe")
        assert profile == {}
