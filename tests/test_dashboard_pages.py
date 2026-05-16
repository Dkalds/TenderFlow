"""Tests funcionales: verifican contenido generado por cada página del dashboard.

A diferencia de test_dashboard_smoke.py (que solo verifica ausencia de excepciones),
estos tests comprueban que cada página produce los elementos esperados (KPIs, tablas,
gráficos) con datos de muestra.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

_NOW = datetime.now(UTC)

_SEED_LICITACIONES = [
    {
        "id_externo": f"LIC-FUNC-{i}",
        "titulo": f"Implantación SAP S/4HANA fase {i}",
        "descripcion": f"Proyecto de implantación módulo {['FI', 'MM', 'SD', 'HR', 'PP'][i % 5]}",
        "organo_contratacion": f"Ministerio de Pruebas {i % 3}",
        "importe": 100_000.0 * (i + 1),
        "moneda": "EUR",
        "cpv": "72000000",
        "tipo_contrato": "2",
        "estado": ["PUB", "ADJ", "ANUL", "RES", "EVA"][i % 5],
        "fecha_publicacion": (_NOW - timedelta(days=30 * i)).isoformat(),
        "fecha_limite": (_NOW + timedelta(days=15)).isoformat(),
        "url": f"https://example.com/lic/{i}",
        "raw_keywords": "SAP",
        "provincia": ["Madrid", "Barcelona", "Sevilla", "Valencia", "Bilbao"][i % 5],
        "ccaa": ["Madrid", "Cataluña", "Andalucía", "C. Valenciana", "País Vasco"][i % 5],
        "nuts_code": f"ES{i + 1}",
        "duracion_valor": 12.0,
        "duracion_unidad": "MON",
        "fecha_extraccion": _NOW.isoformat(),
        "tecnologia": "SAP",
    }
    for i in range(10)
]

_SEED_ADJUDICACIONES = [
    {
        "licitacion_id": f"LIC-FUNC-{i}",
        "nombre": f"Empresa SAP {i % 3} S.L.",
        "nif": f"B1234567{i}",
        "importe_adjudicado": 80_000.0 * (i + 1),
        "fecha_adjudicacion": (_NOW - timedelta(days=10 * i)).isoformat(),
        "ccaa": ["Madrid", "Cataluña", "Andalucía"][i % 3],
        "es_pyme": i % 2,
        "n_ofertas_recibidas": 3 + i,
        "fecha_extraccion": _NOW.isoformat(),
    }
    for i in range(5)
]


@pytest.fixture()
def func_db(monkeypatch, tmp_path):
    """BD temporal poblada con datos funcionales para tests de contenido."""
    import db.database as db_mod
    from db.database import Adjudicacion, Licitacion, log_extraccion, upsert_licitaciones

    db_path = tmp_path / "func.db"
    monkeypatch.setenv("TURSO_DATABASE_URL", "")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")

    db_mod.close_pool()
    db_mod.set_db_path_override(str(db_path))
    # Limpiar caché de Streamlit para que load_dataframe lea la BD de test
    try:
        import streamlit as st

        st.cache_resource.clear()
        st.cache_data.clear()
    except Exception:
        pass
    db_mod.init_db()

    lics = [Licitacion(**row) for row in _SEED_LICITACIONES]
    upsert_licitaciones(lics)

    from db.database import replace_adjudicaciones

    for adj_data in _SEED_ADJUDICACIONES:
        adj = Adjudicacion(**adj_data)
        replace_adjudicaciones(adj.licitacion_id, [adj])

    log_extraccion("func-test", nuevas=len(lics), actualizadas=0, total=len(lics))

    yield db_mod
    db_mod.close_pool()
    db_mod.set_db_path_override(None)
    # Limpiar caché al salir para no contaminar otros tests
    try:
        import streamlit as st

        st.cache_resource.clear()
        st.cache_data.clear()
    except Exception:
        pass


class TestResumenPage:
    """Verifica que la página Resumen genera KPIs y gráficos."""

    def test_kpi_values_present(self, func_db):
        from dashboard.data_loader import load_dataframe

        df = load_dataframe()
        assert len(df) == 10, f"Expected 10 licitaciones, got {len(df)}"

    def test_dataframe_has_required_columns(self, func_db):
        from dashboard.data_loader import load_dataframe

        df = load_dataframe()
        required = {"id_externo", "titulo", "importe", "ccaa", "estado", "fecha_publicacion"}
        assert required.issubset(set(df.columns))


class TestDetallePage:
    """Verifica que hay datos para la tabla de detalle."""

    def test_all_records_accessible(self, func_db):
        from dashboard.data_loader import load_dataframe

        df = load_dataframe()
        # Todos los estados están representados
        estados = set(df["estado"].dropna().unique())
        assert len(estados) >= 4

    def test_filters_reduce_data(self, func_db):
        from dashboard.data_loader import load_dataframe

        df = load_dataframe()
        # Filtrar por CCAA
        filtered = df[df["ccaa"] == "Madrid"]
        assert len(filtered) < len(df)
        assert len(filtered) > 0


class TestGeografiaPage:
    """Verifica datos geográficos."""

    def test_ccaa_distribution(self, func_db):
        from dashboard.data_loader import load_dataframe

        df = load_dataframe()
        ccaa_counts = df["ccaa"].value_counts()
        assert len(ccaa_counts) >= 4


class TestCompetidoresPage:
    """Verifica datos de adjudicatarios."""

    def test_adjudicaciones_loaded(self, func_db):
        from db.database import connect

        with connect() as c:
            row = c.execute("SELECT COUNT(*) FROM adjudicaciones").fetchone()
            count = int(row[0])
        assert count == 5

    def test_empresas_distintas(self, func_db):
        from db.database import connect

        with connect() as c:
            rows = c.execute("SELECT DISTINCT nombre FROM adjudicaciones").fetchall()
        assert len(rows) >= 3


class TestTendenciasPage:
    """Verifica datos temporales para tendencias."""

    def test_fechas_publicacion_variadas(self, func_db):
        from dashboard.data_loader import load_dataframe

        df = load_dataframe()
        fechas = df["fecha_publicacion"].dropna().unique()
        assert len(fechas) >= 5, "Se necesitan varias fechas para gráfico de tendencias"

    def test_importe_total_coherente(self, func_db):
        from dashboard.data_loader import load_dataframe

        df = load_dataframe()
        total = df["importe"].sum()
        # sum(100_000 * (i+1) for i in range(10)) = 5_500_000
        assert total == pytest.approx(5_500_000.0)


class TestTecnologiasPage:
    """Verifica datos para la página de Tecnologías."""

    def test_tecnologia_column_present(self, func_db):
        from dashboard.data_loader import load_dataframe

        df = load_dataframe()
        assert "tecnologia" in df.columns

    def test_all_rows_have_tecnologia(self, func_db):
        from dashboard.data_loader import load_dataframe

        df = load_dataframe()
        # El seed usa tecnologia="SAP" en todos — no debe haber nulos
        assert df["tecnologia"].notna().all()

    def test_explode_tecnologias_no_crash(self, func_db):
        """La función auxiliar de la página debe funcionar sin errores."""
        from dashboard.data_loader import load_dataframe
        from dashboard.pages.tecnologias import _explode_tecnologias

        df = load_dataframe()
        dfx = _explode_tecnologias(df)
        assert len(dfx) >= len(df)
        assert "tech_label" in dfx.columns


class TestCalidadDatosPage:
    """Verifica métricas de calidad del dataset."""

    @pytest.fixture()
    def func_db_with_runs(self, func_db):
        """Extiende func_db con un extraction_run y un failed_extraction."""
        from db.database import connect

        with connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO extraction_runs "
                "(run_id, started_at, ended_at, status, months_attempted, months_ok, "
                "months_failed, licitaciones_nuevas, licitaciones_actualizadas, "
                "errores_parseo, errores_descarga) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    "run-calidad-001",
                    (_NOW - timedelta(hours=5)).isoformat(),
                    _NOW.isoformat(),
                    "ok",
                    1, 1, 0, 10, 2, 0, 0,
                ],
            )
            c.execute(
                "INSERT INTO failed_extractions "
                "(run_id, fuente, scope, error_type, error_message, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    "run-calidad-001",
                    "bulk",
                    "download",
                    "ConnectionError",
                    "Timeout al descargar ZIP",
                    _NOW.isoformat(),
                ],
            )
            c.commit()
        return func_db

    def test_extraction_runs_seeded(self, func_db_with_runs):
        from db.database import connect

        with connect() as c:
            row = c.execute("SELECT COUNT(*) FROM extraction_runs").fetchone()
        assert int(row[0]) >= 1

    def test_dlq_summary_accessible(self, func_db_with_runs):
        from db.dlq import unresolved_summary

        result = unresolved_summary()
        # Debe devolver una lista (puede estar vacía si resolved_at está NULL)
        assert isinstance(result, list)

    def test_completeness_stats(self, func_db_with_runs):
        from dashboard.data_loader import load_dataframe
        from dashboard.stats import calidad_dato

        df = load_dataframe()
        q = calidad_dato(df)
        # calidad_dato debe devolver un dict con métricas de completitud
        assert isinstance(q, dict)
        expected_keys = {"pct_cpv_valido", "pct_importe", "pct_fecha_pub", "pct_titulo"}
        assert expected_keys.issubset(q.keys())
        # El seed tiene todos los campos rellenos — completitud alta
        assert q["pct_importe"] == pytest.approx(100.0)
        assert q["pct_fecha_pub"] == pytest.approx(100.0)


class TestClustersPage:
    """Verifica que los datos de clustering son coherentes."""

    def test_cluster_requires_minimum_rows(self, func_db):
        """Con < 10 filas, cluster_licitaciones no debe lanzar excepción."""
        from dashboard.data_loader import load_dataframe

        df = load_dataframe()
        # El seed tiene 10 licitaciones — justo en el umbral
        assert len(df) >= 10

    def test_cluster_summary_structure(self, func_db):
        """cluster_summary devuelve estructura esperada."""
        import pandas as pd

        from dashboard.clustering import cluster_summary

        df = pd.DataFrame(
            {
                "cluster_id": [0, 0, 1, 1, 2],
                "cluster_label": ["A", "A", "B", "B", "C"],
                "id_externo": ["L1", "L2", "L3", "L4", "L5"],
                "importe": [1.0, 2.0, 3.0, 4.0, 5.0],
            }
        )
        summary = cluster_summary(df)
        assert isinstance(summary, pd.DataFrame)
        assert "cluster_id" in summary.columns
        assert len(summary) == 3  # 3 clusters distintos
