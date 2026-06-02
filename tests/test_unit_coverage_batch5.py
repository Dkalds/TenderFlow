"""Unit tests for services/exports.py, dashboard/cache.py, dashboard/router.py, services/organ_company_graph.py."""

from __future__ import annotations

import pandas as pd

# ===================================================================
# services/exports.py
# ===================================================================


class TestGenerateCsv:
    def test_returns_bytes_with_bom(self) -> None:
        from services.exports import generate_csv

        result = generate_csv([{"id_externo": "L1", "titulo": "Test"}])
        assert isinstance(result, bytes)
        assert result[:3] == b"\xef\xbb\xbf"  # UTF-8 BOM

    def test_uses_semicolon_delimiter(self) -> None:
        from services.exports import generate_csv

        result = generate_csv([{"id_externo": "L1", "titulo": "Test"}])
        content = result[3:].decode("utf-8")  # skip BOM
        assert ";" in content

    def test_custom_columns(self) -> None:
        from services.exports import generate_csv

        result = generate_csv(
            [{"id_externo": "L1", "titulo": "Test", "ccaa": "Madrid"}],
            columns=["id_externo", "ccaa"],
        )
        content = result[3:].decode("utf-8")
        assert "id_externo" in content
        assert "ccaa" in content

    def test_empty_records(self) -> None:
        from services.exports import generate_csv

        result = generate_csv([])
        assert isinstance(result, bytes)

    def test_missing_columns_ignored(self) -> None:
        from services.exports import generate_csv

        result = generate_csv(
            [{"id_externo": "L1"}],
            columns=["id_externo", "nonexistent_col"],
        )
        assert isinstance(result, bytes)


class TestGenerateExcel:
    def test_returns_bytes(self) -> None:
        from services.exports import generate_excel

        result = generate_excel([{"id_externo": "L1", "titulo": "Test"}])
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_custom_sheet_name(self) -> None:
        from services.exports import generate_excel

        result = generate_excel(
            [{"id_externo": "L1"}],
            sheet_name="CustomSheet",
        )
        assert isinstance(result, bytes)

    def test_empty_records(self) -> None:
        from services.exports import generate_excel

        result = generate_excel([])
        assert isinstance(result, bytes)

    def test_timezone_aware_datetime_stripped(self) -> None:
        from services.exports import generate_excel

        df = pd.DataFrame(
            {
                "fecha": pd.to_datetime(["2024-01-01"]).tz_localize("UTC"),
                "titulo": ["Test"],
            }
        )
        result = generate_excel(df.to_dict("records"), columns=["fecha", "titulo"])
        assert isinstance(result, bytes)


class TestGetExportFilename:
    def test_csv_format(self) -> None:
        from services.exports import get_export_filename

        name = get_export_filename("csv")
        assert name.endswith(".csv")
        assert "licitaciones_" in name

    def test_excel_format(self) -> None:
        from services.exports import get_export_filename

        name = get_export_filename("excel")
        assert name.endswith(".xlsx")

    def test_custom_prefix(self) -> None:
        from services.exports import get_export_filename

        name = get_export_filename("csv", prefix="custom")
        assert name.startswith("custom_")


# ===================================================================
# dashboard/cache.py
# ===================================================================


class TestDashboardCache:
    def test_get_cache_returns_singleton(self) -> None:
        from dashboard.cache import get_cache, reset_cache

        reset_cache()
        c1 = get_cache()
        c2 = get_cache()
        assert c1 is c2
        reset_cache()

    def test_reset_cache_clears_singleton(self) -> None:
        from dashboard.cache import get_cache, reset_cache

        reset_cache()
        c1 = get_cache()
        reset_cache()
        c2 = get_cache()
        assert c1 is not c2
        reset_cache()


# ===================================================================
# dashboard/router.py
# ===================================================================


class TestRouter:
    def test_sections_is_dict(self) -> None:
        from dashboard.router import SECTIONS

        assert isinstance(SECTIONS, dict)
        assert len(SECTIONS) > 0

    def test_section_icons_match_sections(self) -> None:
        from dashboard.router import SECTION_ICONS, SECTIONS

        for section in SECTIONS:
            assert section in SECTION_ICONS, f"Missing icon for section: {section}"

    def test_page_icons_cover_all_pages(self) -> None:
        from dashboard.router import PAGE_ICONS, SECTIONS

        all_pages = [p for pages in SECTIONS.values() for p in pages]
        for page in all_pages:
            assert page in PAGE_ICONS, f"Missing icon for page: {page}"

    def test_page_descriptions_cover_all_pages(self) -> None:
        from dashboard.router import PAGE_DESCRIPTIONS, SECTIONS

        all_pages = [p for pages in SECTIONS.values() for p in pages]
        for page in all_pages:
            assert page in PAGE_DESCRIPTIONS, f"Missing description for page: {page}"


# ===================================================================
# services/organ_company_graph.py
# ===================================================================


class TestBuildBipartiteGraph:
    def _make_adj(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "organo_contratacion": ["ORG_A", "ORG_A", "ORG_B", "ORG_B", "ORG_A"],
                "empresa_key": ["EK1", "EK2", "EK1", "EK3", "EK1"],
                "nombre_canonico": ["INDRA", "TELEFONICA", "INDRA", "ACCENTURE", "INDRA"],
                "importe_adjudicado": [50_000.0, 30_000.0, 80_000.0, 60_000.0, 20_000.0],
                "fecha_adjudicacion": pd.to_datetime(
                    ["2024-01-20", "2024-01-20", "2024-02-25", "2024-03-15", "2024-06-01"]
                ),
            }
        )

    def test_returns_nodes_and_edges(self) -> None:
        from services.organ_company_graph import build_bipartite_graph

        result = build_bipartite_graph(self._make_adj())
        assert "nodes" in result
        assert "edges" in result
        assert len(result["nodes"]) > 0
        assert len(result["edges"]) > 0

    def test_missing_columns_returns_empty(self) -> None:
        from services.organ_company_graph import build_bipartite_graph

        result = build_bipartite_graph(pd.DataFrame({"col": [1, 2]}))
        assert result == {"nodes": [], "edges": []}

    def test_empty_dataframe(self) -> None:
        from services.organ_company_graph import build_bipartite_graph

        result = build_bipartite_graph(pd.DataFrame())
        assert result == {"nodes": [], "edges": []}

    def test_min_contratos_filter(self) -> None:
        from services.organ_company_graph import build_bipartite_graph

        result = build_bipartite_graph(self._make_adj(), min_contratos=3)
        assert len(result["edges"]) == 0 or all(e["contratos"] >= 3 for e in result["edges"])

    def test_node_types(self) -> None:
        from services.organ_company_graph import build_bipartite_graph

        result = build_bipartite_graph(self._make_adj())
        node_types = {n["type"] for n in result["nodes"]}
        assert node_types <= {"organo", "empresa"}

    def test_no_fecha_column(self) -> None:
        from services.organ_company_graph import build_bipartite_graph

        adj = self._make_adj().drop(columns=["fecha_adjudicacion"])
        result = build_bipartite_graph(adj)
        assert "nodes" in result

    def test_nan_rows_dropped(self) -> None:
        from services.organ_company_graph import build_bipartite_graph

        adj = self._make_adj()
        adj.loc[0, "organo_contratacion"] = None
        result = build_bipartite_graph(adj)
        assert len(result["nodes"]) > 0

    def test_top_limits(self) -> None:
        from services.organ_company_graph import build_bipartite_graph

        result = build_bipartite_graph(self._make_adj(), top_organos=1, top_empresas=1)
        organo_nodes = [n for n in result["nodes"] if n["type"] == "organo"]
        empresa_nodes = [n for n in result["nodes"] if n["type"] == "empresa"]
        assert len(organo_nodes) <= 2  # 1 +可能的Empresa
        assert len(empresa_nodes) <= 2
