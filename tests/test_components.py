"""Tests unitarios de dashboard/components y helpers de UI — sin Streamlit real."""

from __future__ import annotations

import re

import pandas as pd
import pytest


# ── dashboard.utils.pagination (lógica pura — sin mock de Streamlit) ────


class TestPaginatedDfLogic:
    """Verifica la matemática de paginación: slices, límites, páginas."""

    def _make_df(self, n: int) -> pd.DataFrame:
        return pd.DataFrame({"id": range(n), "val": range(n)})

    def test_first_page_slice(self, monkeypatch):
        """La página 1 devuelve las primeras page_size filas."""
        df = self._make_df(250)
        import streamlit as st

        monkeypatch.setattr(st, "caption", lambda *a, **kw: None)
        monkeypatch.setattr(st, "button", lambda *a, **kw: False)
        monkeypatch.setattr(st, "selectbox", lambda *a, **kw: "1")
        monkeypatch.setattr(st, "columns", lambda n: [_FakeCol() for _ in range(n if isinstance(n, int) else len(n))])
        # session_state starts at page 1 (default)
        st.session_state["_pg_test_key"] = 1

        from dashboard.utils.pagination import paginated_df

        page_df, page_num = paginated_df(df, page_size=100, key="test_key")
        assert page_num == 1
        assert list(page_df["id"]) == list(range(100))

    def test_empty_df_returns_empty(self, monkeypatch):
        import streamlit as st

        monkeypatch.setattr(st, "caption", lambda *a, **kw: None)
        monkeypatch.setattr(st, "button", lambda *a, **kw: False)
        monkeypatch.setattr(st, "selectbox", lambda *a, **kw: "1")
        monkeypatch.setattr(st, "columns", lambda n: [_FakeCol() for _ in range(n if isinstance(n, int) else len(n))])

        from dashboard.utils.pagination import paginated_df

        page_df, _ = paginated_df(pd.DataFrame(), page_size=100, key="empty_key")
        assert page_df.empty

    def test_last_page_slice(self, monkeypatch):
        """La última página devuelve las filas sobrantes."""
        df = self._make_df(250)
        import streamlit as st

        monkeypatch.setattr(st, "caption", lambda *a, **kw: None)
        monkeypatch.setattr(st, "button", lambda *a, **kw: False)
        monkeypatch.setattr(st, "selectbox", lambda *a, **kw: "3")
        monkeypatch.setattr(st, "columns", lambda n: [_FakeCol() for _ in range(n if isinstance(n, int) else len(n))])
        st.session_state["_pg_test_key2"] = 3

        from dashboard.utils.pagination import paginated_df

        page_df, page_num = paginated_df(df, page_size=100, key="test_key2")
        assert page_num == 3
        assert len(page_df) == 50  # 250 - 200 = 50 filas en la última página
        assert list(page_df["id"]) == list(range(200, 250))

    def test_page_clamped_to_bounds(self, monkeypatch):
        """Una página fuera de rango se clampea al rango válido."""
        df = self._make_df(50)
        import streamlit as st

        monkeypatch.setattr(st, "caption", lambda *a, **kw: None)
        monkeypatch.setattr(st, "button", lambda *a, **kw: False)
        monkeypatch.setattr(st, "selectbox", lambda *a, **kw: "1")
        monkeypatch.setattr(st, "columns", lambda n: [_FakeCol() for _ in range(n if isinstance(n, int) else len(n))])
        # Página 99 con solo 1 página disponible → debe devolver página 1
        st.session_state["_pg_test_key3"] = 99

        from dashboard.utils.pagination import paginated_df

        page_df, page_num = paginated_df(df, page_size=100, key="test_key3")
        assert page_num == 1
        assert len(page_df) == 50

    def test_reset_pagination(self, monkeypatch):
        import streamlit as st

        st.session_state["_pg_reset_key"] = 5
        from dashboard.utils.pagination import reset_pagination

        reset_pagination("reset_key")
        assert st.session_state["_pg_reset_key"] == 1


class _FakeCol:
    """Context manager mock de st.columns()."""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    # Absorbe cualquier st.* call dentro del with-block
    def __getattr__(self, name):
        return lambda *a, **kw: None


# ── dashboard.components.icons ───────────────────────────────────────────


class TestIcon:
    """Función `icon()` genera SVG inline válido para Lucide."""

    def test_returns_svg_string(self):
        from dashboard.components.icons import icon

        result = icon("search", 16)
        assert result.startswith("<svg")
        assert result.endswith("</svg>")

    def test_width_and_height_set(self):
        from dashboard.components.icons import icon

        result = icon("bell", 24)
        assert 'width="24"' in result
        assert 'height="24"' in result

    def test_default_size(self):
        from dashboard.components.icons import icon

        result = icon("search")
        assert 'width="16"' in result

    def test_unknown_icon_returns_safe_svg(self):
        """Icono desconocido devuelve un SVG vacío (rect transparente) no ejecuta nada."""
        from dashboard.components.icons import icon

        result = icon("this-icon-does-not-exist", 16)
        # El SVG contiene un rect transparente de fallback — no es cadena vacía
        assert "<svg" in result
        # No contiene ningún path activo (sólo el rect de relleno nulo)
        assert "<path" not in result

    def test_current_color_stroke(self):
        from dashboard.components.icons import icon

        result = icon("trending-up", 16)
        assert 'stroke="currentColor"' in result

    def test_no_script_injection(self):
        """El nombre de icono no puede inyectar scripts."""
        from dashboard.components.icons import icon

        result = icon('<script>alert(1)</script>', 16)
        # Icono desconocido → SVG de fallback, sin script ejecutable
        assert "<script>" not in result


# ── dashboard.components.kpi (funciones puras) ──────────────────────────


class TestCatmullRomToBezier:
    """Función auxiliar de spline — resultados deterministas."""

    def _fn(self):
        from dashboard.components.kpi import _catmull_rom_to_bezier

        return _catmull_rom_to_bezier

    def test_empty_list_returns_empty(self):
        assert self._fn()([]) == ""

    def test_single_point_returns_empty(self):
        assert self._fn()([(0.0, 0.0)]) == ""

    def test_two_points_line(self):
        result = self._fn()([(0.0, 10.0), (80.0, 5.0)])
        assert result.startswith("M0.0,10.0")
        assert "L80.0,5.0" in result

    def test_multiple_points_starts_with_M(self):
        pts = [(i * 10.0, float(i)) for i in range(5)]
        result = self._fn()(pts)
        assert result.startswith("M")

    def test_bezier_curve_contains_C(self):
        pts = [(i * 10.0, float(i)) for i in range(4)]
        result = self._fn()(pts)
        assert "C" in result  # cubic bezier segments


class TestSparklineSvg:
    """Función auxiliar sparkline — genera SVG válido o string vacío."""

    def _fn(self):
        from dashboard.components.kpi import _sparkline_svg

        return _sparkline_svg

    def test_empty_list_returns_empty(self):
        assert self._fn()([], 80, 24) == ""

    def test_single_value_returns_empty(self):
        assert self._fn()([5.0], 80, 24) == ""

    def test_two_values_returns_svg(self):
        result = self._fn()([1.0, 2.0], 80, 24)
        assert result.startswith("<svg")
        assert result.endswith("</svg>")

    def test_up_color_green(self):
        result = self._fn()([1.0, 2.0], 80, 24, up=True)
        assert "#86BC25" in result

    def test_down_color_red(self):
        result = self._fn()([2.0, 1.0], 80, 24, up=False)
        assert "#E21836" in result

    def test_dimensions_in_svg(self):
        result = self._fn()([1.0, 2.0, 3.0], 100, 30)
        assert 'width="100"' in result
        assert 'height="30"' in result

    def test_nan_values_ignored(self):
        import math

        result = self._fn()([1.0, math.nan, 3.0], 80, 24)
        assert result.startswith("<svg")

    def test_constant_values_no_crash(self):
        """Todos los valores iguales (rng=0) no debe lanzar ZeroDivisionError."""
        result = self._fn()([5.0, 5.0, 5.0], 80, 24)
        assert result.startswith("<svg")


class TestKpiCard:
    """kpi_card() genera HTML seguro y con estructura esperada."""

    def test_contains_label_and_value(self):
        from dashboard.components.kpi import kpi_card

        html = kpi_card("Nuevas", "42")
        assert "Nuevas" in html
        assert "42" in html

    def test_html_escaping_label(self):
        from dashboard.components.kpi import kpi_card

        html = kpi_card("<script>", "0")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_html_escaping_value(self):
        from dashboard.components.kpi import kpi_card

        html = kpi_card("Val", '<img src=x onerror="alert(1)">')
        # La cadena peligrosa está escapada — no debe aparecer sin escapar
        assert '<img src=x onerror="alert(1)">' not in html
        # El escape correcto convierte " en &quot;
        assert 'onerror=&quot;' in html or 'onerror=&#' in html

    def test_delta_up_shows_arrow(self):
        from dashboard.components.kpi import kpi_card

        html = kpi_card("KPI", "10", delta="+5%", delta_up=True)
        assert "▲" in html
        assert "up" in html

    def test_delta_down_shows_arrow(self):
        from dashboard.components.kpi import kpi_card

        html = kpi_card("KPI", "10", delta="-3%", delta_up=False)
        assert "▼" in html
        assert "down" in html

    def test_no_delta_no_arrow(self):
        from dashboard.components.kpi import kpi_card

        html = kpi_card("KPI", "10")
        assert "▲" not in html
        assert "▼" not in html

    def test_anomaly_badge_present(self):
        from dashboard.components.kpi import kpi_card

        html = kpi_card("KPI", "999", anomaly=True)
        assert "anomaly-badge" in html

    def test_no_anomaly_badge_by_default(self):
        from dashboard.components.kpi import kpi_card

        html = kpi_card("KPI", "42")
        assert "anomaly-badge" not in html

    def test_sparkline_rendered(self):
        from dashboard.components.kpi import kpi_card

        html = kpi_card("KPI", "42", sparkline=[1.0, 2.0, 3.0])
        assert "sparkline-wrap" in html
        assert "<svg" in html

    def test_tooltip_in_title_attr(self):
        from dashboard.components.kpi import kpi_card

        html = kpi_card("KPI", "42", tooltip="Suma de importes")
        assert 'title="Suma de importes"' in html

    def test_has_role_group(self):
        from dashboard.components.kpi import kpi_card

        html = kpi_card("KPI", "42")
        assert 'role="group"' in html

    def test_aria_label_contains_label_and_value(self):
        from dashboard.components.kpi import kpi_card

        html = kpi_card("Importe total", "1.2M€")
        assert 'aria-label="Importe total: 1.2M€"' in html


# ── dashboard.components.cards (lógica HTML pura) ───────────────────────


class TestTopCard:
    """top_card() genera HTML seguro para tarjetas de licitación."""

    @pytest.fixture(autouse=True)
    def _capture_markdown(self, monkeypatch):
        """Captura el HTML que top_card pasa a st.markdown."""
        self._captured: list[str] = []

        import streamlit as st

        monkeypatch.setattr(
            st,
            "markdown",
            lambda html, **kw: self._captured.append(html),
        )

    def _call(self, **kwargs):
        from dashboard.components.cards import top_card

        top_card(**kwargs)
        return "".join(self._captured)

    def test_valid_url_renders_link(self):
        html = self._call(
            amount="€ 100.000",
            title="SAP S/4HANA",
            meta="Ministerio",
            url="https://example.com/lic/1",
        )
        assert "<a " in html
        assert "https://example.com/lic/1" in html

    def test_invalid_url_renders_plain_text(self):
        html = self._call(
            amount="€ 50.000",
            title="SAP ERP",
            meta="Órgano",
            url="javascript:alert(1)",
        )
        assert "<a " not in html
        assert "javascript" not in html

    def test_none_url_renders_plain_text(self):
        html = self._call(amount="€ 0", title="SAP ERP", meta="Órgano", url=None)
        assert "<a " not in html

    def test_title_is_escaped(self):
        html = self._call(amount="€ 0", title='<b>XSS</b>', meta="Meta", url=None)
        assert "<b>XSS</b>" not in html
        assert "&lt;b&gt;" in html

    def test_highlight_shown_bold(self):
        html = self._call(amount="€ 0", title="SAP", meta="Meta", url=None, highlight="€ 500.000")
        assert "<b>" in html
        assert "500.000" in html

    def test_meta_is_escaped(self):
        html = self._call(amount="€ 0", title="SAP", meta='<img src=x onerror="x">', url=None)
        # La cadena peligrosa debe estar escapada — no sin escapar
        assert '<img src=x onerror="x">' not in html
        assert 'onerror=&quot;' in html or 'onerror=&#' in html

    def test_link_has_noopener(self):
        html = self._call(amount="€ 0", title="SAP", meta="m", url="https://example.com")
        assert "noopener" in html

    def test_title_truncated_to_120(self):
        long_title = "A" * 200
        html = self._call(amount="€ 0", title=long_title, meta="m", url=None)
        # The title is truncated to 120 chars before HTML escaping
        assert "A" * 121 not in html
