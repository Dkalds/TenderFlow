"""El ejecutor de SQL libre, contra Postgres y conectado como el rol del MCP.

Cada test usa ``rol_mcp``: el rol es el que impone la solo-lectura y la
visibilidad, así que aquí se prueba la frontera de seguridad de verdad (y no
una réplica con el dueño del schema).
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from config.settings import mcp_database_url
from db import consulta_libre
from db.consulta_libre import (
    MAX_CHARS_RESPUESTA,
    ErrorConsulta,
    ejecutar_select,
)
from tests.test_rls_tenant_scope_integration import _sembrar


def _err(sql: str) -> ErrorConsulta:
    with pytest.raises(ErrorConsulta) as exc:
        ejecutar_select(sql)
    return exc.value


@pytest.fixture()
def dos_organizaciones_con_pursuits(tmp_db: Any) -> dict[str, int]:
    db_mod, _ = tmp_db
    return _sembrar(db_mod)


def test_select_devuelve_filas(rol_mcp: str) -> None:
    r = ejecutar_select("SELECT 1 AS a")
    assert r.columnas == ["a"]
    assert r.filas == [[1]]
    assert r.n_filas == 1
    assert not r.truncado


def test_tope_de_filas(rol_mcp: str) -> None:
    r = ejecutar_select("SELECT g FROM generate_series(1, 600) g")
    assert r.n_filas == 500
    assert len(r.filas) == 500
    assert r.truncado


def test_comentario_final(rol_mcp: str) -> None:
    assert ejecutar_select("SELECT 1 AS a -- fin").filas == [[1]]


def test_punto_y_coma_y_espacios_detras(rol_mcp: str) -> None:
    assert ejecutar_select("SELECT 1 AS a; ").filas == [[1]]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 AS a; -- fin",
        "SELECT 1 AS a;\n/* fin */\n",
        "SELECT 1 AS a -- uno\n; -- dos\n/* tres */ ;",
    ],
)
def test_punto_y_coma_con_comentarios_detras(rol_mcp: str, sql: str) -> None:
    assert ejecutar_select(sql).filas == [[1]]


def test_cte(rol_mcp: str) -> None:
    assert ejecutar_select("WITH x AS (SELECT 2 AS b) SELECT b FROM x").filas == [[2]]


def test_like_con_porcentaje(rol_mcp: str) -> None:
    assert ejecutar_select("SELECT 'abc' LIKE '%b%' AS ok").filas == [[True]]


def test_varias_sentencias_rechazadas(rol_mcp: str) -> None:
    err = _err("SELECT 1; DROP TABLE licitaciones")
    assert err.sqlstate == "42601"
    assert err.pista


def test_escape_del_envoltorio_rechazado(rol_mcp: str, tmp_db: Any) -> None:
    """Cerrar el subselect y abrir otro no puede colar una segunda sentencia."""
    db_mod, _ = tmp_db
    err = _err("SELECT 1) AS x; DROP TABLE licitaciones; SELECT (1")
    assert err.sqlstate == "42601"
    assert "multiple commands" in err.mensaje
    # Nada más allá de una sentencia llegó a ejecutarse.
    with db_mod.connect() as c:
        existe = c.execute("SELECT to_regclass('licitaciones')").fetchone()
        assert existe is not None and existe[0] is not None


def test_insert_falla(rol_mcp: str) -> None:
    err = _err("INSERT INTO licitaciones (id_externo) VALUES ('x') RETURNING 1")
    assert err.sqlstate in {"25006", "42501", "42601"}


def test_funcion_que_escribe_cae_en_solo_lectura(rol_mcp: str) -> None:
    """Parsea dentro del envoltorio y solo falla por ``default_transaction_read_only``."""
    err = _err("SELECT lo_create(0)")
    assert err.sqlstate == "25006"
    assert err.pista


@pytest.fixture()
def una_sola_conexion(rol_mcp: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pool de una conexión: la segunda llamada reutiliza por fuerza la primera."""
    monkeypatch.setattr("db.consulta_libre._POOL_MAX", 1)


def _en_el_pool(sql: str) -> tuple[Any, ...]:
    """Ejecuta ``sql`` en una conexión del pool del MCP **sin** pasar por el veto.

    ``set_config`` está vetado en ``ejecutar_select`` (R17); el reinicio de
    sesión del pool es la otra defensa y se prueba aquí por separado.
    """
    pool = consulta_libre._get_pool(mcp_database_url())
    with pool.connection() as conn:
        fila = conn.execute(sql).fetchone()
    assert fila is not None
    return tuple(fila)


def test_set_config_vetado(rol_mcp: str) -> None:
    err = _err("SELECT set_config('statement_timeout', '0', false)")
    assert err.sqlstate is None
    assert "set_config" in err.mensaje


def test_set_config_no_sobrevive_al_pool_timeout(una_sola_conexion: None) -> None:
    """Una consulta no puede debilitar la sesión que usará la siguiente."""
    primera = _en_el_pool(
        "SELECT set_config('statement_timeout', '0', false) AS t, pg_backend_pid() AS pid"
    )
    assert primera[0] == "0"
    err = _err("SELECT pg_sleep(5)")
    assert err.sqlstate == "57014"
    # Mismo proceso de Postgres: la segunda llamada reutilizó la conexión.
    segunda = ejecutar_select("SELECT pg_backend_pid() AS pid")
    assert segunda.filas[0][0] == primera[1]


def test_set_config_no_sobrevive_al_pool_solo_lectura(una_sola_conexion: None) -> None:
    primera = _en_el_pool(
        "SELECT set_config('default_transaction_read_only', 'off', false) AS v, "
        "pg_backend_pid() AS pid"
    )
    assert primera[0] == "off"
    err = _err("SELECT lo_create(0)")
    assert err.sqlstate == "25006"
    segunda = ejecutar_select("SELECT pg_backend_pid() AS pid")
    assert segunda.filas[0][0] == primera[1]


@pytest.fixture()
def rol_como_supabase(una_sola_conexion: None, rol_mcp: str, tmp_db: Any) -> None:
    """El rol del MCP con ``extra_float_digits = 0``, el valor de Supabase.

    En producción el 0 viene del fichero de configuración y el rol puede no
    tener el ``ALTER ROLE … SET extra_float_digits = 3`` de ``sentencias_rol``;
    aquí se le pone 0 al rol para que sea el valor por defecto de la sesión (el
    que restaura ``RESET ALL``) y el ejecutor tenga que corregirlo él solo.
    """
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        c.execute(f'ALTER ROLE "{rol_mcp}" SET extra_float_digits = 0')
    consulta_libre.cerrar_pool_mcp()


def test_real_exacto_aunque_el_servidor_redondee(rol_como_supabase: None) -> None:
    """``11782155::real`` no puede llegar como 11782200 (6 cifras significativas)."""
    assert _en_el_pool("SHOW extra_float_digits")[0] == "3"
    assert ejecutar_select("SELECT 11782155::real AS importe").filas == [[11782155]]
    # La segunda consulta reutiliza la conexión tras el RESET ALL del pool,
    # que devuelve el valor por defecto de la sesión (0): sigue exacto.
    assert ejecutar_select("SELECT 11782155::real AS importe").filas == [[11782155]]
    assert _en_el_pool("SHOW extra_float_digits")[0] == "3"


def test_escritura_en_cte_falla(rol_mcp: str) -> None:
    err = _err(
        "WITH i AS (INSERT INTO licitaciones (id_externo) VALUES ('x') RETURNING 1) SELECT * FROM i"
    )
    assert err.sqlstate in {"25006", "42501", "0A000"}


def test_tabla_oculta_denegada(rol_mcp: str) -> None:
    err = _err("SELECT * FROM api_keys")
    assert err.sqlstate == "42501"
    assert err.pista


def test_columna_excluida_denegada(rol_mcp: str) -> None:
    assert _err("SELECT password_hash FROM users").sqlstate == "42501"


def test_columnas_permitidas_de_users(rol_mcp: str, dos_organizaciones_con_pursuits: Any) -> None:
    r = ejecutar_select("SELECT id, email, is_admin FROM users ORDER BY id")
    assert r.columnas == ["id", "email", "is_admin"]
    assert [fila[1] for fila in r.filas] == ["rls-a@example.test", "rls-b@example.test"]


def test_select_estrella_de_users_denegado(rol_mcp: str) -> None:
    assert _err("SELECT * FROM users").sqlstate == "42501"


def test_ve_dos_organizaciones(rol_mcp: str, dos_organizaciones_con_pursuits: Any) -> None:
    r = ejecutar_select("SELECT DISTINCT organization_id FROM pursuits")
    assert r.n_filas == 2


def test_timeout(rol_mcp: str) -> None:
    err = _err("SELECT pg_sleep(5)")
    assert err.sqlstate == "57014"
    assert err.pista


def test_tipos_reales(rol_mcp: str) -> None:
    r = ejecutar_select(
        "SELECT '{\"a\":1}'::jsonb AS j, ARRAY[1,2] AS arr, gen_random_uuid() AS u, "
        "'\\x00'::bytea AS b, now() AS ahora, interval '1 day' AS iv, "
        "'NaN'::numeric AS nan, NULL AS nada, 1.50::numeric AS dec, "
        "'[1,2,3]'::vector AS v"
    )
    fila = r.filas[0]
    assert fila[0] == {"a": 1}
    assert fila[1] == [1, 2]
    assert isinstance(fila[2], str)
    assert fila[3] is None
    assert isinstance(fila[4], str)
    assert fila[5] == "P1D"
    assert fila[6] is None
    assert fila[7] is None
    assert fila[8] == 1.5
    assert fila[9] is not None
    json.dumps(r.como_dict())


def test_respuesta_acotada(rol_mcp: str) -> None:
    r = ejecutar_select("SELECT repeat('x', 1000) AS t FROM generate_series(1, 500)")
    assert len(json.dumps(r.como_dict())) <= MAX_CHARS_RESPUESTA
    assert r.truncado
    assert 0 < r.n_filas < 500


def test_sin_url_configurada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_DATABASE_URL", raising=False)
    err = _err("SELECT 1")
    assert err.sqlstate is None
    assert "MCP_DATABASE_URL" in err.mensaje


# ── Funciones vetadas contra Postgres de verdad (R17) ──────────────────────


#: Plantillas en las que, para Postgres, ``{f}(1)`` es **código** aunque un
#: léxico ingenuo lo crea dentro de un literal o de un comentario.
CODIGO_ESCONDIDO = [
    "SELECT E'a''\\'' , {f}(1) --'",
    "SELECT 1 --x\r, {f}(1)\n",
    "SELECT E'a'\n'\\'' , {f}(1) --'",
    "SELECT E'a' -- c\n  '\\'' , {f}(1) --'",
    "SELECT $\U0001f600$'$\U0001f600$, {f}(1), 'x'",
]

#: Plantillas en las que ``{f}(1)`` vive en un literal o un comentario.
NO_CODIGO = [
    "SELECT 'a{f}(1)' AS t",
    "SELECT E'\\'{f}(1)' AS t",
    "SELECT $$ {f}(1) $$ AS t",
    "SELECT 1 AS t -- {f}(1)",
    "SELECT 1 AS t /* {f}( /* anidado */ */",
    "SELECT 'a'\n'{f}(1)' AS t",
]


@pytest.mark.parametrize("plantilla", CODIGO_ESCONDIDO)
def test_postgres_lee_codigo_donde_el_veto_lo_ve(rol_mcp: str, plantilla: str) -> None:
    """Contraste con el léxico real: Postgres intenta llamar a la función.

    Con un nombre inexistente Postgres responde ``42883`` (la llamó: era
    código) y con el vetado el ejecutor lo rechaza antes de tocar la base.
    """
    assert _err(plantilla.format(f="funcion_inexistente_mcp")).sqlstate == "42883"
    err = _err(plantilla.format(f="pg_advisory_lock"))
    assert err.sqlstate is None
    assert "pg_advisory_lock" in err.mensaje


@pytest.mark.parametrize("plantilla", NO_CODIGO)
def test_nombre_vetado_en_literal_o_comentario_se_ejecuta(rol_mcp: str, plantilla: str) -> None:
    r = ejecutar_select(plantilla.format(f="pg_advisory_lock"))
    assert r.n_filas == 1


def test_cerrojo_de_la_cadena_de_auditoria_no_se_puede_tomar(rol_mcp: str, tmp_db: Any) -> None:
    """El SQL del LLM no puede tomar el cerrojo con que ``db/audit.py`` serializa ``audit_log``."""
    db_mod, _ = tmp_db
    clave = "hashtext('tenderflow.audit_log.chain.v1')"
    for sql in (
        f"SELECT pg_advisory_lock({clave}), pg_sleep(0.5)",
        f'SELECT "pg_catalog"."pg_advisory_lock"({clave})',
        f"SELECT pg_try_advisory_lock({clave})",
        f"SELECT 1 FROM pg_advisory_lock({clave}) AS x",  # noqa: S608 — clave constante
    ):
        err = _err(sql)
        assert err.sqlstate is None and "advisory" in err.mensaje
    # Nadie lo tiene: la aplicación lo toma sin esperar.
    with db_mod.connect() as c:
        fila = c.execute(f"SELECT pg_try_advisory_xact_lock({clave})").fetchone()
        assert fila is not None and fila[0] is True


# ── Lectura por lotes con cursor de servidor (R19) ─────────────────────────


def test_deja_de_leer_cuando_la_respuesta_ya_no_cabe(rol_mcp: str) -> None:
    """Filas enormes: se para en cuanto se pasa del tope, sin cargar las 500.

    A partir de la fila 300 cada fila divide por cero: si el ejecutor leyera
    todo (``fetchall``) la consulta fallaría con ``22012``. El tope de 100 000
    caracteres se alcanza hacia la fila 100, así que nunca se piden.
    """
    inicio = time.perf_counter()
    r = ejecutar_select(
        "SELECT repeat('x', 100000) || CASE WHEN g > 300 THEN (1 / (g - g))::text "
        "ELSE '' END AS t FROM generate_series(1, 500) AS g"
    )
    assert r.truncado
    assert 0 < r.n_filas < 300
    assert len(json.dumps(r.como_dict())) <= MAX_CHARS_RESPUESTA
    assert time.perf_counter() - inicio < 5


def test_tope_de_tiempo_es_de_la_consulta_entera(rol_mcp: str) -> None:
    """Con el cursor, ``statement_timeout`` vale por ``FETCH``: el plazo es del total.

    El rol de los tests tiene 1 s. Cada lote de 50 filas tarda 0,75 s (menos
    que el tope por sentencia) y las 501 filas, 7,5 s: debe cortarse cerca de 1 s.
    """
    inicio = time.perf_counter()
    err = _err("SELECT pg_sleep(0.015) AS s FROM generate_series(1, 501)")
    assert err.sqlstate == "57014"
    assert err.pista
    assert time.perf_counter() - inicio < 3


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_logical_emit_message(false, 'tf', repeat('x', 1000000))",
        "SELECT pg_logical_emit_message(true, 'tf', repeat('x', 1000000))",
        "SELECT \"pg_catalog\".pg_logical_emit_message(true, 'tf', 'x'::bytea)",
        "SELECT pg_current_xact_id()",
        "SELECT txid_current()",
    ],
)
def test_lo_que_escribe_wal_en_solo_lectura_esta_vetado(rol_mcp: str, sql: str) -> None:
    """``pg_logical_emit_message`` escribe WAL (y asignar un xid, un commit) aun en solo lectura.

    Sin veto, el SQL del LLM podría escribir gigabytes de WAL por llamada dentro
    de los 15 s y llenar el disco de Supabase (que pasa la base a solo lectura).
    """
    err = _err(sql)
    assert err.sqlstate is None
    assert "no está permitida" in err.mensaje
