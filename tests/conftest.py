"""Fixtures compartidos para aislar la BD en tests."""

from __future__ import annotations

import itertools
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ── Auto-marking de tests por convención de nombre + uso de fixtures ────────
# Evita anotar manualmente los tests. Reglas, en orden:
#   - módulo test_*property*/test_*performance*/test_*load*    → property/load
#   - test_*e2e* / test_visual_regression / test_dashboard_smoke → e2e
#   - test_integration_*, test_*_integration   → integration
#   - cierre de fixtures incluye tmp_db/api_db → integration (BD real)
#   - todo lo demás                            → unit (sin I/O externo, ahora
#                                                de verdad: un test que abre
#                                                Postgres nunca queda `unit`)
_E2E_TOKENS = ("_e2e", "visual_regression", "dashboard_smoke", "dashboard_pages")
# `load`/`property` solo se miran en la RUTA del módulo, no en el nombre del
# test: como substring del nombre dan falsos positivos masivos (`test_load_
# dataframe`, `test_upsert_result_properties`, `test_ml_model_pin::test_load_
# rejects_when_pin_mismatch`, ~100 tests que cargan datos o verifican
# propiedades de un objeto, sin relación con load-testing ni Hypothesis).
# Detectado 2026-08-03 auditando el merge con master: esos tests quedaban
# marcados `load`/`property`, ninguno de los dos en el `-m "(unit or
# integration) and not slow"` de `make check` -- fuera del gate sin que nadie
# lo notara. Los módulos que sí son load/property-testing llevan el token en
# su propio nombre de archivo (`test_performance.py`, `test_property_based.py`,
# `test_load_scraper_placsp.py`, …), así que la ruta basta como señal.
_LOAD_TOKENS = ("performance", "load")
_PROPERTY_TOKENS = ("property", "properties", "property_based")

# Fixtures raíz que abren el schema Postgres aislado (ambas piden
# `_pg_schema` vía `getfixturevalue`, que es dinámico y NO aparece en el
# cierre estático — por eso se detectan las raíces declaradas, no
# `_pg_schema`). `item.fixturenames` sí contiene el cierre transitivo de lo
# DECLARADO, así que esto cubre también lo construido encima de `api_db`
# (`client`, `api_key`, `auth`, …) sin enumerarlo.
_PG_FIXTURES = frozenset({"tmp_db", "api_db"})


def _infer_marker(path: str, name: str) -> str:
    """Infer the pytest marker for a test item based on path/name conventions."""
    p = path.lower().replace("\\", "/")
    n = name.lower()
    for token in _E2E_TOKENS:
        if token in p or token in n:
            return "e2e"
    for token in _LOAD_TOKENS:
        if token in p:
            return "load"
    for token in _PROPERTY_TOKENS:
        if token in p:
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
        if marker_name == "unit" and _PG_FIXTURES & set(getattr(item, "fixturenames", ())):
            marker_name = "integration"
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
def _isolate_dotenv_from_fresh_settings(monkeypatch):
    """Evita que el ``.env`` del desarrollador entre en un ``Settings(...)`` nuevo.

    ``_isolate_database_url`` (arriba) blanquea el singleton ya construido, pero
    no cubre a los tests que instancian ``Settings`` ellos mismos con inputs
    controlados: pydantic-settings mezcla ``.env`` en **cada** construcción, así
    que los kwargs explícitos del test conviven con valores reales de la
    máquina.

    Detectado 2026-08-21: ``.env`` define ``GOOGLE_CLIENT_ID`` sin
    ``OAUTH_ALLOWED_DOMAINS``/``_EMAILS``, y eso encendía Google OAuth en dos
    tests de ``test_config_settings.py`` que no hablan de OAuth. Uno fallaba con
    el error del allowlist de OAuth; el otro, peor, esperaba un fallo por
    ``sslmode`` y recibía el de OAuth — un test verde-por-el-motivo-equivocado a
    un paso de distancia.

    Se neutralizan **solo las credenciales de OAuth**, no el dotenv entero:
    desactivarlo por completo (``env_file=None``) rompe otros 16 tests de
    ``test_config_settings.py``, que dan por hecho que ``.env`` aporta los
    secretos obligatorios del perfil ``api``. Ese acoplamiento se queda: el
    ``.env`` es un paso de arranque documentado (README) y desmontarlo es un
    cambio con alcance propio. Lo que sí arregla este fixture es que el
    **contenido** de ese fichero, que varía de una máquina a otra y no está
    versionado, decida el resultado de tests que no hablan de OAuth.

    Poner la variable a cadena vacía en el entorno basta porque en
    pydantic-settings el entorno del proceso **gana** al dotenv. Un test que
    necesite OAuth encendido lo sigue pudiendo declarar explícitamente en los
    kwargs de ``Settings``.
    """
    for credencial in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        monkeypatch.setenv(credencial, "")


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
    """Limpia las cachés en memoria de la capa de servicios entre tests.

    Las señales de scoring cachean su snapshot agregado (TTL + señal de
    ingesta). En tests que mutan la BD y luego leen, una caché caliente
    serviría datos obsoletos; limpiarla antes/después aísla cada test. (Las
    cachés full-table de licitaciones/adjudicaciones se retiraron con la
    migración ADR-023 — la analítica agrega en SQL y no cachea en proceso.)
    """
    from services.analytics.scoring_signals import clear_scoring_signals_cache

    clear_scoring_signals_cache()
    yield
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
    """URL del Postgres de tests: entorno primero, ``.env`` como fallback.

    El fallback existe para las sesiones remotas de agentes, donde el hook
    ``SessionStart`` (``.claude/hooks/session_start_pg.py``) provisiona el
    cluster y deja la URL en ``.env``: un hook no puede exportar variables al
    shell del agente, así que sin este fallback habría que recordar el
    ``export`` en cada invocación y la suite seguiría abortando por olvido.
    El entorno mantiene la precedencia — CI la inyecta por ``env:`` y no debe
    verse afectado por un ``.env`` que ni siquiera está versionado.
    """
    from_env = os.environ.get("TEST_DATABASE_URL", "")
    if from_env:
        return from_env
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if not env_file.is_file():
        return ""
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("TEST_DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


@pytest.fixture(scope="session")
def _pg_schema_ddl(tmp_path_factory):
    """DDL completo del schema, materializado una vez por sesión.

    Aplicar ``alembic upgrade head`` por test (≈50 tablas + índices) sería
    inviable en tiempo. Se aplica una vez sobre ``public`` y se vuelca su DDL
    con ``pg_dump --schema-only``; cada test lo reproyecta sobre su propio
    schema, que es un par de órdenes de magnitud más barato.

    Bajo pytest-xdist (opt-in: ``make test-parallel``) cada worker es un
    proceso con su propia fixture de sesión — sin coordinación, N workers
    correrían ``alembic upgrade head`` y el vaciado de ``public`` en paralelo
    contra la misma base. Un lock de fichero en el tmp compartido del run
    serializa la materialización: el primer worker la ejecuta y deja el DDL
    cacheado; el resto lo lee. (Los nombres de schema por test ya llevan el
    pid, así que no colisionan entre workers.)

    Returns:
        Tupla ``(url_base, ddl)``.
    """
    url = _pg_test_url()
    if not url:
        raise pytest.UsageError(
            "TEST_DATABASE_URL no configurada (ni en el entorno ni en .env). "
            "Postgres es el único motor soportado (ADR-021): levantá el de dev "
            "con `docker compose up -d postgres` y exportá "
            "TEST_DATABASE_URL=postgresql://tenderflow:tenderflow@localhost:5432/tenderflow"  # pragma: allowlist secret -- contenedor local de dev
            ". En una sesión remota de agente lo provisiona el hook "
            "`.claude/hooks/session_start_pg.py`; si no corrió, ejecutalo a mano."
        )

    if os.environ.get("PYTEST_XDIST_WORKER") is None:
        return url, _materialize_schema_ddl(url)

    import fcntl

    shared_dir = tmp_path_factory.getbasetemp().parent
    cache = shared_dir / "tf_pg_schema_ddl.sql"
    with open(shared_dir / "tf_pg_schema_ddl.lock", "w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            if cache.exists():
                return url, cache.read_text(encoding="utf-8")
            ddl = _materialize_schema_ddl(url)
            cache.write_text(ddl, encoding="utf-8")
            return url, ddl
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def _materialize_schema_ddl(url: str) -> str:
    """alembic → pg_dump → vaciado de ``public`` → DDL reproyectable."""
    import subprocess

    import psycopg

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
    return "\n".join(lines).replace("public.", "")


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
