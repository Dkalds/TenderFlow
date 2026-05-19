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
    """Inserta licitaciones de prueba, una extracción y un run en extraction_runs."""
    from db.database import Licitacion, log_extraccion, upsert_licitaciones

    lics = [Licitacion(**row) for row in _SEED_LICITACIONES]
    upsert_licitaciones(lics)
    log_extraccion("smoke-test", nuevas=len(lics), actualizadas=0, total=len(lics))

    # Seed extraction_runs para que la página Calidad de Datos no quede vacía
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT OR IGNORE INTO extraction_runs "
            "(run_id, started_at, ended_at, duration_ms, status, "
            " months_attempted, months_ok, months_failed, "
            " licitaciones_nuevas, licitaciones_actualizadas, "
            " errores_parseo, errores_descarga) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "smoke-run-001",
                (_NOW - __import__("datetime").timedelta(hours=2)).isoformat(),
                _NOW.isoformat(),
                7200000,
                "ok",
                1,
                1,
                0,
                5,
                0,
                0,
                0,
            ],
        )
        c.commit()


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
    "Tecnologías",
    "Competidores",
    "Pipeline & Alertas",
    "Mi Watchlist",
    "Observabilidad",
    "Calidad de Datos",
    "Clusters",
    "Administración",
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


# ---------------------------------------------------------------------------
# Edge case: empty dataset
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page_name", _PAGES)
def test_page_renders_empty_dataset(page_name: str, monkeypatch, tmp_path) -> None:
    """Cada página debe renderizar sin excepciones cuando el dataset está vacío."""

    import db.database as db_mod

    db_path = tmp_path / "smoke_empty.db"
    monkeypatch.setenv("TURSO_DATABASE_URL", "")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    monkeypatch.setenv("DB_PATH", str(db_path))
    db_mod.close_pool()
    db_mod.set_db_path_override(str(db_path))
    db_mod.init_db()
    yield_path = str(db_path)
    db_mod.close_pool()
    db_mod.set_db_path_override(None)

    from streamlit.testing.v1 import AppTest

    script = f"""\
import importlib, os
os.environ["DB_PATH"] = r"{yield_path}"
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
    assert not at.exception, (
        f"Página '{page_name}' lanzó excepción con dataset vacío: {at.exception}"
    )


# ---------------------------------------------------------------------------
# Edge case: extreme / dirty data
# ---------------------------------------------------------------------------

_SEED_EXTREME = [
    {
        "id_externo": "LIC-EXTREME-0",
        "titulo": "x",  # muy corto
        "descripcion": None,  # nulo
        "organo_contratacion": None,
        "importe": 0.0,  # cero
        "moneda": "EUR",
        "cpv": "72",  # CPV inválido
        "tipo_contrato": None,
        "estado": "PUB",
        "fecha_publicacion": "9999-12-31T00:00:00",  # fecha futura
        "fecha_limite": None,
        "url": None,
        "raw_keywords": None,
        "provincia": None,
        "ccaa": None,
        "nuts_code": None,
        "fecha_extraccion": datetime.now(UTC).isoformat(),
    },
    {
        "id_externo": "LIC-EXTREME-1",
        "titulo": None,  # nulo
        "descripcion": "A" * 5000,  # descripción muy larga
        "organo_contratacion": "Órgano con caractères spéciaux & <tags>",
        "importe": -1.0,  # negativo
        "moneda": "USD",
        "cpv": "00000000",
        "tipo_contrato": "999",  # tipo desconocido
        "estado": "UNKNOWN",  # estado desconocido
        "fecha_publicacion": "1900-01-01T00:00:00",  # fecha muy antigua
        "fecha_limite": "1900-01-01T00:00:00",
        "url": "not-a-url",
        "raw_keywords": "",
        "provincia": "Provincia Inexistente",
        "ccaa": "CCAA Inexistente",
        "nuts_code": "ZZ99",
        "fecha_extraccion": datetime.now(UTC).isoformat(),
    },
]


@pytest.fixture()
def _extreme_db(monkeypatch, tmp_path):
    """BD temporal con datos extremos/sucios."""
    import db.database as db_mod

    db_path = tmp_path / "extreme.db"
    monkeypatch.setenv("TURSO_DATABASE_URL", "")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    monkeypatch.setenv("DB_PATH", str(db_path))
    db_mod.close_pool()
    db_mod.set_db_path_override(str(db_path))
    db_mod.init_db()

    from db.database import Licitacion, upsert_licitaciones

    upsert_licitaciones([Licitacion(**row) for row in _SEED_EXTREME])
    yield db_mod
    db_mod.close_pool()
    db_mod.set_db_path_override(None)


@pytest.mark.parametrize("page_name", ["Resumen", "Tendencias", "Calidad de Datos", "Geografía"])
def test_page_renders_extreme_data(page_name: str, _extreme_db, monkeypatch) -> None:
    """Páginas clave deben tolerarse ante datos sucios, nulos y valores extremos."""
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
    assert not at.exception, (
        f"Página '{page_name}' lanzó excepción con datos extremos: {at.exception}"
    )
