"""Tests para dashboard.clustering."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _make_df(n: int = 30) -> pd.DataFrame:
    """DataFrame de licitaciones sintéticas para tests."""
    rng = np.random.default_rng(42)
    titulos = [
        "Sistema ERP SAP para gestión financiera",
        "Mantenimiento aplicaciones SAP ABAP",
        "Consultoría SAP S/4HANA implantación",
        "Servicios cloud AWS infraestructura",
        "Desarrollo web portal ciudadano",
        "Soporte helpdesk usuarios finales",
    ]
    rows = []
    for i in range(n):
        base = titulos[i % len(titulos)]
        rows.append(
            {
                "id_externo": f"LIC-{i:04d}",
                "titulo": f"{base} lote {i}",
                "descripcion": f"Descripción detallada {base}",
                "organo_contratacion": f"Ministerio {i % 3}",
                "importe": float(rng.integers(10_000, 1_000_000)),
                "ccaa": "Madrid",
                "estado": "PUB",
            }
        )
    return pd.DataFrame(rows)


class TestClusterLicitaciones:
    def test_añade_columnas_cluster(self):
        from dashboard.clustering import cluster_licitaciones

        df = _make_df(30)
        result = cluster_licitaciones(df, n_clusters=3)

        assert "cluster_id" in result.columns
        assert "cluster_label" in result.columns
        assert len(result) == len(df)

    def test_numero_clusters_correcto(self):
        from dashboard.clustering import cluster_licitaciones

        df = _make_df(40)
        result = cluster_licitaciones(df, n_clusters=4)

        n_unique = result["cluster_id"].nunique()
        assert n_unique == 4

    def test_pocos_datos_devuelve_df_sin_cluster(self):
        from dashboard.clustering import cluster_licitaciones

        df = _make_df(5)  # < _MIN_ROWS = 10
        result = cluster_licitaciones(df, n_clusters=3)

        # Debe devolver DataFrame con cluster_id=0 por defecto
        assert "cluster_id" in result.columns
        assert result["cluster_id"].nunique() == 1

    def test_df_vacio_devuelve_vacio(self):
        from dashboard.clustering import cluster_licitaciones

        df = pd.DataFrame(columns=["id_externo", "titulo", "descripcion", "importe"])
        result = cluster_licitaciones(df, n_clusters=3)

        assert len(result) == 0

    def test_labels_no_vacios(self):
        from dashboard.clustering import cluster_licitaciones

        df = _make_df(20)
        result = cluster_licitaciones(df, n_clusters=3)

        labels = result["cluster_label"].unique()
        assert all(isinstance(lb, str) and len(lb) > 0 for lb in labels)


class TestClusterSummary:
    def test_summary_contiene_columnas_esperadas(self):
        from dashboard.clustering import cluster_licitaciones, cluster_summary

        df = _make_df(30)
        clustered = cluster_licitaciones(df, n_clusters=3)
        summary = cluster_summary(clustered)

        assert "cluster_id" in summary.columns
        assert "n" in summary.columns
        assert "importe_total" in summary.columns

    def test_summary_sin_cluster_vacio(self):
        from dashboard.clustering import cluster_summary

        df = pd.DataFrame({"titulo": ["test"], "importe": [100.0]})
        result = cluster_summary(df)
        assert result.empty

    def test_n_filas_suma_total(self):
        from dashboard.clustering import cluster_licitaciones, cluster_summary

        df = _make_df(30)
        clustered = cluster_licitaciones(df, n_clusters=3)
        summary = cluster_summary(clustered)

        assert summary["n"].sum() == len(df)


class TestClusterKeywords:
    def test_devuelve_palabras_del_texto(self):
        from dashboard.clustering import _cluster_keywords

        texts = ["sistema SAP gestión financiera", "SAP ERP módulos financieros"] * 5
        result = _cluster_keywords(texts, top_n=3)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_textos_vacios_devuelve_otros(self):
        from dashboard.clustering import _cluster_keywords

        result = _cluster_keywords([], top_n=3)
        assert result == "otros"
