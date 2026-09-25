"""``db/connection.py`` sin BD: timeout por lectura, lecturas agrupadas y pools.

Todo con dobles de la conexión psycopg y del pool. Lo que se fija:

- ``connect_read(statement_timeout_ms=…)`` baja el timeout solo para el bloque,
  con ``SET LOCAL`` en el mismo viaje que el ``BEGIN``, y el ``ROLLBACK`` de
  cierre lo deshace. Nunca sube el techo de la sesión.
- ``lecturas_agrupadas`` reutiliza una conexión y un ámbito para las lecturas
  anidadas, y no las comparte entre hilos ni entre organizaciones.
- Los pools mantienen ``min_size`` conexiones y verifican las ociosas antes de
  entregarlas.
"""

from __future__ import annotations

import threading
import time
import warnings
from types import SimpleNamespace
from typing import Any

import pytest

import db.connection as conn_mod
from shared.tenant_context import tenant_scope


class _Raw:
    """Conexión psycopg de mentira: sentencias en un registro y estado de transacción."""

    def __init__(self, registro: list[str], *, autocommit: bool = True) -> None:
        from psycopg.pq import TransactionStatus

        self._registro = registro
        self._ts = TransactionStatus
        self.autocommit = autocommit
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.falla_consulta = False

    def execute(self, sql: str, params: Any = None) -> _Raw:
        self._registro.append(sql)
        if sql.startswith(("BEGIN", "ROLLBACK; BEGIN")):
            self.info.transaction_status = self._ts.INTRANS
        return self

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def rollback(self) -> None:
        self._registro.append("ROLLBACK")
        self.info.transaction_status = self._ts.IDLE

    def commit(self) -> None:
        self._registro.append("COMMIT")


class _Cursor:
    def __init__(self, raw: _Raw) -> None:
        self._raw = raw
        self.description = None
        self.rowcount = 0

    def execute(self, sql: str, params: Any = None) -> None:
        self._raw._registro.append(sql)
        if self._raw.falla_consulta:
            self._raw.info.transaction_status = self._raw._ts.INERROR
            raise RuntimeError("consulta fallida")

    def fetchone(self) -> Any:
        return (1,)

    def fetchall(self) -> list[Any]:
        return []


@pytest.fixture()
def pool(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """``_get_conn``/``_return_conn`` de mentira: cuentan checkouts y devoluciones."""
    estado: dict[str, Any] = {"checkouts": 0, "devoluciones": 0, "registro": [], "raws": []}

    def _get_conn(*, read_only: bool = False) -> conn_mod._PgConnAdapter:
        estado["checkouts"] += 1
        raw = _Raw(estado["registro"], autocommit=read_only)
        estado["raws"].append(raw)
        return conn_mod._PgConnAdapter(raw, pool=None)

    def _return_conn(_conn: Any) -> None:
        estado["devoluciones"] += 1

    monkeypatch.setattr(conn_mod, "_get_conn", _get_conn)
    monkeypatch.setattr(conn_mod, "_return_conn", _return_conn)
    return estado


@pytest.fixture()
def techo_30s(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import settings

    monkeypatch.setattr(settings, "DB_STATEMENT_TIMEOUT_MS", 30_000)


# ── statement_timeout por lectura ────────────────────────────────────────────


def test_timeout_sin_ambito_abre_transaccion_y_la_revierte(
    pool: dict[str, Any], techo_30s: None
) -> None:
    with conn_mod.connect_read(statement_timeout_ms=5_000) as c:
        c.execute("SELECT 1").fetchone()

    assert pool["registro"] == [
        "BEGIN; SET LOCAL statement_timeout = 5000",
        "SELECT 1",
        "ROLLBACK",
    ]
    assert pool["checkouts"] == pool["devoluciones"] == 1


def test_una_lectura_sin_timeout_propio_hereda_el_techo_del_contexto(
    pool: dict[str, Any], techo_30s: None
) -> None:
    with conn_mod.techo_de_sentencia(5_000), conn_mod.connect_read() as c:
        c.execute("SELECT 1").fetchone()

    assert pool["registro"] == [
        "BEGIN; SET LOCAL statement_timeout = 5000",
        "SELECT 1",
        "ROLLBACK",
    ]


def test_el_timeout_propio_gana_al_del_contexto(pool: dict[str, Any], techo_30s: None) -> None:
    with conn_mod.techo_de_sentencia(5_000), conn_mod.connect_read(statement_timeout_ms=2_000) as c:
        c.execute("SELECT 1").fetchone()

    assert pool["registro"][0] == "BEGIN; SET LOCAL statement_timeout = 2000"


def test_el_techo_del_contexto_no_sobrevive_al_bloque(
    pool: dict[str, Any], techo_30s: None
) -> None:
    with conn_mod.techo_de_sentencia(5_000):
        pass
    with conn_mod.connect_read() as c:
        c.execute("SELECT 1").fetchone()

    # Sin techo, la lectura vuelve a ser un solo viaje: ni BEGIN ni ROLLBACK.
    assert pool["registro"] == ["SELECT 1"]


@pytest.mark.parametrize("valor", [None, 0])
def test_un_techo_nulo_o_cero_no_cambia_nada(
    pool: dict[str, Any], techo_30s: None, valor: int | None
) -> None:
    with conn_mod.techo_de_sentencia(valor), conn_mod.connect_read() as c:
        c.execute("SELECT 1").fetchone()

    assert pool["registro"] == ["SELECT 1"]


def test_un_techo_imposible_falla_al_fijarlo() -> None:
    with pytest.raises(ValueError), conn_mod.techo_de_sentencia(-5):
        pass
    with pytest.raises(ValueError):
        conn_mod.fijar_techo_de_sentencia(-5)


def test_timeout_con_ambito_va_en_el_mismo_viaje_que_el_set_local(
    pool: dict[str, Any], techo_30s: None
) -> None:
    with tenant_scope(7), conn_mod.connect_read(statement_timeout_ms=5_000) as c:
        c.execute("SELECT 1")

    assert pool["registro"] == [
        "BEGIN; SET LOCAL app.organization_id = '7'; SET LOCAL statement_timeout = 5000",
        "SELECT 1",
        "ROLLBACK",
    ]


def test_timeout_igual_o_mayor_que_el_techo_no_cuesta_nada(
    pool: dict[str, Any], techo_30s: None
) -> None:
    with conn_mod.connect_read(statement_timeout_ms=30_000) as c:
        c.execute("SELECT 1")
    with conn_mod.connect_read(statement_timeout_ms=90_000) as c:
        c.execute("SELECT 2")

    assert pool["registro"] == ["SELECT 1", "SELECT 2"], "nunca sube el techo de la sesión"


def test_sin_techo_cualquier_timeout_se_aplica(
    pool: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from config import settings

    monkeypatch.setattr(settings, "DB_STATEMENT_TIMEOUT_MS", 0)

    with conn_mod.connect_read(statement_timeout_ms=8_000) as c:
        c.execute("SELECT 1")

    assert pool["registro"][0] == "BEGIN; SET LOCAL statement_timeout = 8000"


@pytest.mark.parametrize("valor", [0, -1, True, 1.5, "8000"])
def test_timeout_invalido_se_rechaza(pool: dict[str, Any], valor: Any) -> None:
    with pytest.raises(ValueError), conn_mod.connect_read(statement_timeout_ms=valor):
        pass
    assert pool["checkouts"] == 0


def test_si_la_consulta_falla_la_conexion_vuelve_sin_el_timeout(
    pool: dict[str, Any], techo_30s: None
) -> None:
    with (
        pytest.raises(RuntimeError),
        conn_mod.connect_read(statement_timeout_ms=5_000) as c,
    ):
        pool["raws"][0].falla_consulta = True
        c.execute("SELECT 1")

    assert pool["registro"][-1] == "ROLLBACK"
    assert pool["devoluciones"] == 1


def test_sin_timeout_la_lectura_sigue_siendo_un_viaje(pool: dict[str, Any]) -> None:
    with conn_mod.connect_read() as c:
        c.execute("SELECT 1")

    assert pool["registro"] == ["SELECT 1"]


# ── lecturas_agrupadas ───────────────────────────────────────────────────────


def test_lecturas_agrupadas_usan_una_conexion_y_un_ambito(pool: dict[str, Any]) -> None:
    adaptadores = []
    with tenant_scope(7), conn_mod.lecturas_agrupadas():
        for n in range(3):
            with conn_mod.connect_read() as c:
                adaptadores.append(c)
                c.execute(f"SELECT {n}")

    assert pool["checkouts"] == pool["devoluciones"] == 1
    assert pool["registro"] == [
        "BEGIN; SET LOCAL app.organization_id = '7'",
        "SELECT 0",
        "SELECT 1",
        "SELECT 2",
        "ROLLBACK",
    ]
    # Un adaptador por bloque (cada uno con su cursor) sobre la misma conexión.
    assert len({id(a) for a in adaptadores}) == 3
    assert len({id(a._conn) for a in adaptadores}) == 1


def test_sin_ambito_agrupa_sin_transaccion(pool: dict[str, Any]) -> None:
    with conn_mod.lecturas_agrupadas():
        with conn_mod.connect_read() as c:
            c.execute("SELECT 1")
        with conn_mod.connect_read() as c:
            c.execute("SELECT 2")

    assert pool["checkouts"] == 1
    assert pool["registro"] == ["SELECT 1", "SELECT 2"]


def test_una_lectura_fallida_no_contagia_a_la_siguiente(pool: dict[str, Any]) -> None:
    """Como cuando cada lectura tenía su conexión: el fallo capturado no
    deja la transacción del grupo rechazando todo lo que viene detrás."""
    with tenant_scope(7), conn_mod.lecturas_agrupadas():
        raw = pool["raws"][0]
        try:
            with conn_mod.connect_read() as c:
                raw.falla_consulta = True
                c.execute("SELECT roto")
        except RuntimeError:
            pass  # un loader que captura y devuelve un neutro
        raw.falla_consulta = False
        with conn_mod.connect_read() as c:
            c.execute("SELECT sano")

    assert "ROLLBACK; BEGIN; SET LOCAL app.organization_id = '7'" in pool["registro"]
    assert pool["registro"].index("SELECT sano") > pool["registro"].index(
        "ROLLBACK; BEGIN; SET LOCAL app.organization_id = '7'"
    )
    assert pool["checkouts"] == 1


def test_si_algo_cerro_la_transaccion_del_grupo_se_reabre(pool: dict[str, Any]) -> None:
    with tenant_scope(7), conn_mod.lecturas_agrupadas():
        with conn_mod.connect_read() as c:
            c.rollback()  # alguien cerró la transacción (y con ella el ámbito)
        with conn_mod.connect_read() as c:
            c.execute("SELECT 1")

    registro = pool["registro"]
    assert registro.count("BEGIN; SET LOCAL app.organization_id = '7'") == 2
    assert registro.index("SELECT 1") > 2


def test_otra_organizacion_no_hereda_el_ambito_del_grupo(pool: dict[str, Any]) -> None:
    with tenant_scope(7), conn_mod.lecturas_agrupadas():
        with tenant_scope(8), conn_mod.connect_read() as c:
            c.execute("SELECT de_la_8")
        with conn_mod.connect_read() as c:
            c.execute("SELECT de_la_7")

    assert pool["checkouts"] == 2
    assert "BEGIN; SET LOCAL app.organization_id = '8'" in pool["registro"]


def test_otro_hilo_no_comparte_la_conexion_del_grupo(pool: dict[str, Any]) -> None:
    import contextvars

    with conn_mod.lecturas_agrupadas():
        contexto = contextvars.copy_context()  # el grupo es visible desde el otro hilo...

        def _leer() -> None:
            with conn_mod.connect_read() as c:
                c.execute("SELECT desde_otro_hilo")

        hilo = threading.Thread(target=contexto.run, args=(_leer,))
        hilo.start()
        hilo.join()

    assert pool["checkouts"] == 2, "...pero no puede usar su conexión"


def test_un_timeout_propio_sale_del_grupo(pool: dict[str, Any], techo_30s: None) -> None:
    with conn_mod.lecturas_agrupadas():
        with conn_mod.connect_read(statement_timeout_ms=5_000) as c:
            c.execute("SELECT analitica")

    assert pool["checkouts"] == 2
    assert "BEGIN; SET LOCAL statement_timeout = 5000" in pool["registro"]


def test_anidar_lecturas_agrupadas_no_abre_otro_grupo(pool: dict[str, Any]) -> None:
    with conn_mod.lecturas_agrupadas(), conn_mod.lecturas_agrupadas():
        with conn_mod.connect_read() as c:
            c.execute("SELECT 1")

    assert pool["checkouts"] == pool["devoluciones"] == 1


def test_una_excepcion_en_el_grupo_cierra_y_devuelve(pool: dict[str, Any]) -> None:
    with pytest.raises(ZeroDivisionError), tenant_scope(7), conn_mod.lecturas_agrupadas():
        _ = 1 / 0

    assert pool["registro"][-1] == "ROLLBACK"
    assert pool["devoluciones"] == 1
    assert conn_mod._lectura_agrupada.get() is None


# ── Pools: min_size y verificación de ociosas ────────────────────────────────


@pytest.fixture()
def pool_falso(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """``psycopg_pool.ConnectionPool`` de mentira: guarda los kwargs de cada pool."""
    import psycopg_pool

    creados: list[dict[str, Any]] = []

    class _PoolFalso:
        def __init__(self, **kwargs: Any) -> None:
            creados.append(kwargs)

    monkeypatch.setattr(psycopg_pool, "ConnectionPool", _PoolFalso)
    monkeypatch.setattr(conn_mod, "_database_url", lambda: "postgresql://u:p@h:5432/d")
    return creados


def test_los_pools_se_crean_con_min_size_y_check(
    pool_falso: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from config import settings

    monkeypatch.setattr(settings, "DB_POOL_SIZE", 12)
    monkeypatch.setattr(settings, "DB_READ_POOL_SIZE", 12)
    monkeypatch.setattr(settings, "DB_POOL_MIN_SIZE", 2)
    monkeypatch.setattr(settings, "DB_READ_POOL_MIN_SIZE", 4)

    conn_mod._build_pool(read_only=False)
    conn_mod._build_pool(read_only=True)

    escritura, lectura = pool_falso
    assert (escritura["min_size"], escritura["max_size"]) == (2, 12)
    assert (lectura["min_size"], lectura["max_size"]) == (4, 12)
    assert callable(escritura["check"]) and callable(lectura["check"])
    assert "num_workers" not in lectura, "crecer no se acelera con más workers"


def test_min_size_nunca_pasa_del_maximo(
    pool_falso: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from config import settings

    monkeypatch.setattr(settings, "DB_POOL_SIZE", 2)
    monkeypatch.setattr(settings, "DB_READ_POOL_SIZE", 3)
    monkeypatch.setattr(settings, "DB_READ_POOL_MIN_SIZE", 50)

    conn_mod._build_pool(read_only=True)

    assert pool_falso[0]["min_size"] == 3


def test_keepalives_en_cada_conexion_salvo_los_de_la_url() -> None:
    kwargs = conn_mod._pg_connect_kwargs("postgresql://h/d")
    assert kwargs["keepalives"] == 1
    assert kwargs["keepalives_idle"] == 30

    explicitos = conn_mod._pg_connect_kwargs("postgresql://h/d?keepalives_idle=5")
    assert "keepalives_idle" not in explicitos, "el valor de la URL gana"
    assert explicitos["keepalives_interval"] == 10


class _ConexionDelPool:
    """Lo que recibe el ``check`` del pool: una conexión psycopg."""

    def __init__(self, *, autocommit: bool = True, rota: bool = False) -> None:
        self.autocommit = autocommit
        self.rota = rota
        self.consultas: list[str] = []

    def execute(self, sql: str) -> None:
        self.consultas.append(sql)
        if self.rota:
            raise ConnectionError("server closed the connection unexpectedly")


def test_una_conexion_usada_hace_poco_no_se_verifica() -> None:
    conexion = _ConexionDelPool()
    conn_mod._marcar_actividad(conexion)

    conn_mod._make_pg_check(read_only=True)(conexion)

    assert conexion.consultas == [], "con tráfico, verificar sería un viaje por checkout"


def test_una_conexion_ociosa_se_verifica_antes_de_entregarla() -> None:
    conexion = _ConexionDelPool(autocommit=False)
    setattr(
        conexion,
        conn_mod._ATRIBUTO_ACTIVIDAD,
        time.monotonic() - conn_mod._VERIFICAR_OCIOSA_TRAS_S - 1,
    )

    conn_mod._make_pg_check(read_only=False)(conexion)

    assert conexion.consultas == [""], "una consulta vacía: un viaje"
    assert conexion.autocommit is False, "la de escritura vuelve a su modo"
    ultima = getattr(conexion, conn_mod._ATRIBUTO_ACTIVIDAD)
    assert time.monotonic() - ultima < 1, "verificada cuenta como actividad"


def test_una_conexion_sin_marca_se_verifica() -> None:
    conexion = _ConexionDelPool()

    conn_mod._make_pg_check(read_only=True)(conexion)

    assert conexion.consultas == [""]


def test_una_ociosa_muerta_purga_las_demas_y_se_descarta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    purgas = {"n": 0}

    class _Pool:
        def check(self) -> None:
            purgas["n"] += 1

    monkeypatch.setattr(conn_mod, "_pg_read_pool", _Pool())
    conexion = _ConexionDelPool(rota=True)

    with pytest.raises(ConnectionError):
        conn_mod._make_pg_check(read_only=True)(conexion)

    assert purgas["n"] == 1


def test_devolver_una_conexion_la_marca_como_activa(monkeypatch: pytest.MonkeyPatch) -> None:
    devueltas = []

    class _Pool:
        def putconn(self, conn: Any) -> None:
            devueltas.append(conn)

    conexion = _ConexionDelPool()
    conn_mod._return_pg_connection(conn_mod._PgConnAdapter(conexion, pool=_Pool()))

    assert devueltas == [conexion]
    assert time.monotonic() - getattr(conexion, conn_mod._ATRIBUTO_ACTIVIDAD) < 1


def test_una_conexion_recien_abierta_cuenta_como_activa(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import settings

    monkeypatch.setattr(settings, "DB_STATEMENT_TIMEOUT_MS", 0)
    monkeypatch.setattr(settings, "DB_IDLE_TX_TIMEOUT_MS", 0)
    conexion = _ConexionDelPool()

    # Sin ajustes que fijar (timeouts a 0, pool de escritura) no ejecuta nada:
    # lo único que se comprueba es la marca.
    conn_mod._make_pg_configure(read_only=False)(conexion)

    assert time.monotonic() - getattr(conexion, conn_mod._ATRIBUTO_ACTIVIDAD) < 1


# ── Settings ─────────────────────────────────────────────────────────────────

_SECRETOS_API = {
    "SIGNING_KEY": "k" * 32,
    "API_HMAC_SECRET": "h" * 32,
    "REDIS_URL": "redis://localhost:6379/0",
    "REDIS_PASSWORD": "p" * 32,
    "AUDIT_HMAC_KEY": "z" * 32,
}


def _settings(**kwargs: Any) -> Any:
    from config.settings import Settings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Settings(DATABASE_URL="", **kwargs)


def test_la_api_de_produccion_mantiene_conexiones_calientes() -> None:
    s = _settings(ENV="prod", APP_PROFILE="api", **_SECRETOS_API)

    assert (s.DB_POOL_MIN_SIZE, s.DB_READ_POOL_MIN_SIZE) == (2, 4)


@pytest.mark.parametrize(
    ("env", "perfil"),
    [("dev", "api"), ("prod", "worker"), ("prod", "scraper"), ("dev", "scraper")],
)
def test_el_resto_se_queda_en_una_conexion(env: str, perfil: str) -> None:
    s = _settings(ENV=env, APP_PROFILE=perfil, AUDIT_HMAC_KEY="z" * 32)

    assert (s.DB_POOL_MIN_SIZE, s.DB_READ_POOL_MIN_SIZE) == (1, 1)


def test_un_min_size_explicito_gana_siempre() -> None:
    s = _settings(ENV="dev", APP_PROFILE="api", DB_READ_POOL_MIN_SIZE=3)

    assert s.DB_READ_POOL_MIN_SIZE == 3


@pytest.mark.parametrize("campo", ["DB_POOL_MIN_SIZE", "DB_READ_POOL_MIN_SIZE"])
def test_min_size_menor_que_uno_se_rechaza(campo: str) -> None:
    with pytest.raises(ValueError, match="MIN_SIZE"):
        _settings(**{campo: 0})


def test_timeout_de_analitica_por_defecto_y_validacion() -> None:
    # Apagado por defecto hasta medir en producción (ver su comentario).
    assert _settings().API_ANALYTICS_STATEMENT_TIMEOUT_MS == 0
    assert (
        _settings(API_ANALYTICS_STATEMENT_TIMEOUT_MS=15_000).API_ANALYTICS_STATEMENT_TIMEOUT_MS
        == 15_000
    )
    with pytest.raises(ValueError, match="API_ANALYTICS_STATEMENT_TIMEOUT_MS"):
        _settings(API_ANALYTICS_STATEMENT_TIMEOUT_MS=-1)
