"""Fixtures compartidos para aislar la BD en tests."""

from __future__ import annotations

import itertools
import os
import sys

import pytest
from fastapi.testclient import TestClient

# ── Auto-marking de tests por convención de nombre ──────────────────────────
# Evita tener que anotar manualmente los ~70 tests existentes. Reglas:
#   - test_*property* / test_parser_properties → property
#   - test_*performance* / test_*load*         → load
#   - test_*e2e* / test_visual_regression / test_dashboard_smoke → e2e
#   - test_integration_*, test_*_integration   → integration
#   - todo lo demás                            → unit (default)
_E2E_TOKENS = ("_e2e", "visual_regression", "dashboard_smoke", "dashboard_pages")
_LOAD_TOKENS = ("performance", "load")
_PROPERTY_TOKENS = ("property", "properties", "property_based")


def _infer_marker(path: str, name: str) -> str:
    """Infer the pytest marker for a test item based on path/name conventions."""
    p = path.lower().replace("\\", "/")
    n = name.lower()
    for token in _E2E_TOKENS:
        if token in p or token in n:
            return "e2e"
    for token in _LOAD_TOKENS:
        if token in p or token in n:
            return "load"
    for token in _PROPERTY_TOKENS:
        if token in p or token in n:
            return "property"
    # integration: explicit /integration/ path segment or test_integration_* name prefix
    if "/integration/" in p or "integration_" in n:
        return "integration"
    return "unit"


def pytest_collection_modifyitems(config, items):
    for item in items:
        marks_existing = {m.name for m in item.iter_markers()}
        if marks_existing & {"unit", "integration", "e2e", "property", "load"}:
            continue
        marker_name = _infer_marker(str(item.fspath), item.name)
        item.add_marker(getattr(pytest.mark, marker_name))


@pytest.fixture(autouse=True)
def _isolate_database_url(monkeypatch):
    """Evita que un ``DATABASE_URL`` real en ``.env`` contamine tests unitarios.

    pydantic-settings carga ``.env`` al construir ``settings`` sin importar el
    entorno del proceso -- limpiar solo ``os.environ`` (vía ``monkeypatch.delenv``)
    no alcanza porque ``_database_url()`` cae a ``settings.DATABASE_URL`` como
    fallback (ADR-016). Detectado en F3b (2026-07-05) al configurar Supabase:
    varios tests de detección de backend/search_backend empezaron a fallar
    porque ``.env`` ya trae un DATABASE_URL real. Blanquear solo el atributo de
    ``settings`` (no ``os.environ``) preserva el opt-in real de correr el test
    de paridad Postgres exportando la variable en el shell antes de pytest.
    """
    from config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", "", raising=False)


@pytest.fixture(autouse=True)
def _default_placsp_connector_disabled(monkeypatch):
    """Fuerza ``PLACSP_CONNECTOR_ENABLED=False`` por defecto en tests unitarios.

    Detectado 2026-07-12 al activar el flag en producción (F2 flip): decenas
    de tests mockean ``scraper.pipeline.update_daily``/``update_recent`` y
    llaman a ``run_daily_pipeline``/``run_bulk_pipeline`` directamente (o vía
    ``scheduler.jobs.*``) sin fijar el flag. Con el default real ahora en
    True, esos tests dejaban de ejercer el mock e iban por el camino del
    connector real -- en el mejor caso, aserciones sobre el mock nunca
    llamado; en el peor, ``run_connector`` intentando una descarga HTTP real
    contra PLACSP dentro de un test (cuelgue de varios minutos, reproducido
    en ``tests/test_recent_bulk.py::test_partial_failure_...``). Un test que
    sí quiera ejercer el camino connector lo hace explícito con su propio
    ``monkeypatch.setattr(settings, "PLACSP_CONNECTOR_ENABLED", True)``, que
    gana sobre este default (se aplica después, en el cuerpo del test).
    """
    from config import settings

    monkeypatch.setattr(settings, "PLACSP_CONNECTOR_ENABLED", False, raising=False)


@pytest.fixture(autouse=True)
def _disable_rate_limiter(monkeypatch):
    """Disable rate limiting in tests to avoid 429s from shared state."""

    class _NoopLimiter:
        def check(self, key, *, max_calls=120, window_seconds=60.0):
            return True

    monkeypatch.setattr("api.middleware.get_rate_limiter", lambda: _NoopLimiter())


@pytest.fixture(autouse=True)
def _clear_service_data_caches():
    """Limpia las cachés de full-table de la capa de servicios entre tests.

    ``load_stats_dataframe`` / ``load_raw_adjudicaciones`` cachean el snapshot
    en memoria (TTL + señal de ingesta). En tests que mutan la BD y luego leen,
    una caché caliente serviría datos obsoletos; limpiarla antes/después aísla
    cada test.
    """
    from services.adjudicaciones import clear_raw_adj_cache
    from services.analytics.scoring_signals import clear_scoring_signals_cache
    from services.licitaciones import clear_stats_cache

    clear_stats_cache()
    clear_raw_adj_cache()
    clear_scoring_signals_cache()
    yield
    clear_stats_cache()
    clear_raw_adj_cache()
    clear_scoring_signals_cache()


# ── Backend de la suite: Postgres (único motor, ADR-021) ────────────────────
#
# ``TEST_DATABASE_URL`` es **obligatoria**: las fixtures ``tmp_db`` y ``api_db``
# crean un schema aislado por test sobre esa instancia. Levantá el Postgres de
# dev con ``docker compose up -d postgres``.
#
# Históricamente la suite corría sobre ficheros SQLite temporales mientras
# producción era Postgres (ADR-016), y toda diferencia de dialecto quedaba sin
# cubrir — el bug de ``round()`` documentado en services/sql_fragments.py llegó
# al frontend por esa vía. ADR-018 construyó esta infraestructura; ADR-021
# retiró el otro camino.

_PG_SCHEMA_SEQ = itertools.count()


def _pg_test_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture(scope="session")
def _pg_schema_ddl():
    """DDL completo del schema, materializado una vez por sesión.

    Aplicar ``alembic upgrade head`` por test (≈50 tablas + índices) sería
    inviable en tiempo. Se aplica una vez sobre ``public`` y se vuelca su DDL
    con ``pg_dump --schema-only``; cada test lo reproyecta sobre su propio
    schema, que es un par de órdenes de magnitud más barato.

    Returns:
        Tupla ``(url_base, plantilla_ddl)``. La plantilla lleva
        ``__TF_SCHEMA__`` donde va el nombre del schema destino.
    """
    import subprocess

    import psycopg

    url = _pg_test_url()
    if not url:
        raise pytest.UsageError(
            "TEST_DATABASE_URL no configurada. Postgres es el único motor "
            "soportado (ADR-021): levantá el de dev con "
            "`docker compose up -d postgres` y exportá "
            "TEST_DATABASE_URL=postgresql://tenderflow:tenderflow@localhost:5432/tenderflow"  # pragma: allowlist secret -- contenedor local de dev
        )

    env = {**os.environ, "DATABASE_URL": url, "ENV": "dev", "APP_PROFILE": "scraper"}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=env,
        capture_output=True,
    )

    dump = subprocess.run(
        ["pg_dump", "--schema-only", "--no-owner", "--no-privileges", "--schema=public", url],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    # Datos semilla que insertan las propias migraciones (p. ej. las tres filas
    # de `api_key_tiers` en v28). Con `--schema-only` se perdían: cada test
    # veía la tabla vacía y cualquier aserción sobre ellos fallaba, o peor,
    # pasaba vacunada. Recién migrada, la BD no contiene más datos que esos
    # seeds, así que volcarlos enteros es seguro. `--inserts` evita el COPY,
    # que psycopg no ejecuta desde `conn.execute`.
    dump += subprocess.run(
        [
            "pg_dump",
            "--data-only",
            "--inserts",
            "--no-owner",
            "--no-privileges",
            "--schema=public",
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    # Capturado el DDL, se vacían las tablas de `public`. El search_path de cada
    # test es `<schema_del_test>, public`, así que si `public` conserva las
    # tablas de alembic actúa de red de seguridad silenciosa: un test que borre
    # o altere una tabla en su schema seguiría viendo la de `public` y pasaría
    # sin ejercitar nada. `public` debe aportar solo los objetos de extensión
    # (tipos de pgvector, operadores de pg_trgm), nunca datos ni tablas.
    with psycopg.connect(url, autocommit=True) as conn:
        tablas = [
            r[0]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        ]
        for t in tablas:
            conn.execute(f'DROP TABLE IF EXISTS public."{t}" CASCADE')

    # pg_dump cualifica todo como `public.`; se reproyecta al schema del test.
    # Se descartan: sentencias de extensión (son globales a la base), las de
    # search_path (lo fija la propia conexión) y los meta-comandos de psql
    # (`\restrict` / `\unrestrict`, que pg_dump >= 16.10 emite y psycopg no
    # entiende porque no son SQL).
    lines = [
        ln
        for ln in dump.splitlines()
        if not ln.startswith(
            (
                "SET ",
                "SELECT pg_catalog.set_config",
                "CREATE EXTENSION",
                "COMMENT ON EXTENSION",
                "CREATE SCHEMA",
                "COMMENT ON SCHEMA",
                "\\",
            )
        )
    ]
    # Se **elimina** la cualificación `public.` en vez de reescribirla al
    # schema del test: así los objetos propios (tablas, índices) se crean sin
    # cualificar —y caen en el primer schema del search_path, el del test—
    # mientras que los que aporta una extensión y viven en `public`
    # (`vector` de pgvector, `gin_trgm_ops` de pg_trgm) siguen resolviéndose
    # por el search_path sin necesidad de enumerarlos uno a uno.
    ddl = "\n".join(lines).replace("public.", "")
    return url, ddl


@pytest.fixture()
def _pg_schema(_pg_schema_ddl):
    """Schema Postgres limpio y aislado para un único test."""
    import psycopg

    base_url, ddl = _pg_schema_ddl
    schema = f"tf_test_{os.getpid()}_{next(_PG_SCHEMA_SEQ)}"

    with psycopg.connect(base_url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.execute(f'SET search_path TO "{schema}", public')
        conn.execute(ddl)

    sep = "&" if "?" in base_url else "?"
    scoped_url = f"{base_url}{sep}options=-csearch_path%3D{schema}%2Cpublic"

    import db.database as db_mod

    db_mod.close_pool()
    db_mod.set_pg_test_url(scoped_url)
    yield scoped_url
    db_mod.close_pool()
    db_mod.set_pg_test_url(None)

    with psycopg.connect(base_url, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.fixture()
def tmp_db(tmp_path, request):
    """Schema Postgres aislado por test, con las migraciones aplicadas.

    ``tmp_path`` se sigue devolviendo porque muchos tests lo usan para
    artefactos de fichero (modelos, exports), no para la BD.
    """
    import db.database as db_mod

    request.getfixturevalue("_pg_schema")
    db_mod.init_db()
    yield db_mod, tmp_path


# ── Fixtures compartidos para tests de la API REST ───────────────────────


@pytest.fixture()
def api_db(tmp_path, request):
    """Schema Postgres aislado por test, para tests de la API."""
    import db.database as db_mod

    request.getfixturevalue("_pg_schema")
    db_mod.init_db()
    yield tmp_path


@pytest.fixture()
def api_key(api_db):
    """Crea una API key de pruebas con autorización explícita total.

    Los tests que verifican denegaciones por scope emiten sus propias claves
    restringidas.  La fixture genérica representa un cliente ya autorizado,
    para que las pruebas de validación, respuesta y dominio no dependan de la
    taxonomía concreta de scopes de cada ruta.
    """
    from api.auth import create_api_key

    return create_api_key("test-key", scopes="*")


@pytest.fixture()
def client(api_db):
    """TestClient de FastAPI con DB temporal (raise_server_exceptions=True)."""
    from api.app import app

    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def auth(api_key):
    """Headers de autenticación con la API key de test."""
    return {"X-API-Key": api_key}
