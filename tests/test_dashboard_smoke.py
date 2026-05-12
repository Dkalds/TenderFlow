"""Smoke tests: cada página del dashboard renderiza sin errores.

Se usa ``streamlit.testing.v1.AppTest`` con una BD temporal y datos
representativos. El objetivo NO es verificar contenido, sino que el render
completo no lance excepciones.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(UTC)

_SEED_LICITACIONES = [
    {
        "id_externo": f"LIC-SMOKE-{i}",
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
        "fecha_extraccion": _NOW.isoformat(),
    }
    for i in range(5)
]


def _seed_db(db_mod: object) -> None:
    """Inserta licitaciones de prueba y una extracción."""
    from db.database import Licitacion, log_extraccion, upsert_licitaciones

    lics = [Licitacion(**row) for row in _SEED_LICITACIONES]
    upsert_licitaciones(lics)
    log_extraccion("smoke-test", nuevas=len(lics), actualizadas=0, total=len(lics))


# ---------------------------------------------------------------------------
# Fixture: BD temporal con datos representativos
# ---------------------------------------------------------------------------


@pytest.fixture()
def _smoke_db(monkeypatch, tmp_path):
    """BD SQLite temporal poblada con 5 licitaciones representativas."""
    import db.database as db_mod

    db_path = tmp_path / "smoke.db"
    monkeypatch.setenv("TURSO_DATABASE_URL", "")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    monkeypatch.setenv("DB_PATH", str(db_path))

    # Usar DI hook en vez de importlib.reload() masivo
    db_mod.close_pool()
    db_mod.set_db_path_override(str(db_path))

    db_mod.init_db()
    _seed_db(db_mod)
    yield db_mod
    db_mod.close_pool()
    db_mod.set_db_path_override(None)


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------

_PAGES = [
    "Resumen",
    "Tendencias",
    "Detalle",
    "Órganos",
    "Geografía",
    "Proyectos & Módulos",
    "Competidores",
    "Pipeline & Alertas",
    "Mi Watchlist",
    "Observabilidad",
]


@pytest.mark.parametrize("page_name", _PAGES)
def test_page_renders_without_error(page_name: str, _smoke_db, monkeypatch) -> None:
    """Renderizar ``page_name`` no debe lanzar excepción."""
    import os

    from streamlit.testing.v1 import AppTest

    db_path = os.environ["DB_PATH"]

    script = f"""\
import importlib, os
os.environ["DB_PATH"] = r"{db_path}"
os.environ["TURSO_DATABASE_URL"] = ""
os.environ["TURSO_AUTH_TOKEN"] = ""
os.environ["DASHBOARD_PASSWORD"] = ""

import sys; importlib.import_module("config.settings"); importlib.reload(sys.modules["config.settings"])
import config as cfg; importlib.reload(cfg)
import db.database as db_mod; importlib.reload(db_mod)
import db.migrations as mig; importlib.reload(mig)

from dashboard.data_loader import load_dataframe
from dashboard.pages import PAGE_REGISTRY
from dashboard.pages._base import PageContext
from dashboard.filters.state import FiltersState
from dashboard.theme import TOKENS, get_color_sequence, register_plotly_template

importlib.reload(importlib.import_module("dashboard.data_loader"))
df_full = load_dataframe()
plotly_tpl = register_plotly_template(TOKENS)
color_seq = get_color_sequence(TOKENS)
ctx = PageContext(
    df=df_full, df_full=df_full,
    filters=FiltersState(),
    tokens=TOKENS,
    plotly_template=plotly_tpl,
    color_sequence=color_seq,
)
PAGE_REGISTRY["{page_name}"](ctx)
"""
    at = AppTest.from_string(script)
    at.run(timeout=15)
    assert not at.exception, f"Página '{page_name}' lanzó excepción: {at.exception}"
