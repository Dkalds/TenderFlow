"""El ejecutor de SQL libre, contra Postgres y conectado como el rol del MCP.

Cada test usa ``rol_mcp``: el rol es el que impone la solo-lectura y la
visibilidad, así que aquí se prueba la frontera de seguridad de verdad (y no
una réplica con el dueño del schema).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

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


def test_set_config_no_sobrevive_al_pool_timeout(una_sola_conexion: None) -> None:
    """Una consulta no puede debilitar la sesión que usará la siguiente."""
    primera = ejecutar_select(
        "SELECT set_config('statement_timeout', '0', false) AS t, pg_backend_pid() AS pid"
    )
    assert primera.filas[0][0] == "0"
    err = _err("SELECT pg_sleep(5)")
    assert err.sqlstate == "57014"
    # Mismo proceso de Postgres: la segunda llamada reutilizó la conexión.
    segunda = ejecutar_select("SELECT pg_backend_pid() AS pid")
    assert segunda.filas[0][0] == primera.filas[0][1]


def test_set_config_no_sobrevive_al_pool_solo_lectura(una_sola_conexion: None) -> None:
    primera = ejecutar_select(
        "SELECT set_config('default_transaction_read_only', 'off', false) AS v, "
        "pg_backend_pid() AS pid"
    )
    assert primera.filas[0][0] == "off"
    err = _err("SELECT lo_create(0)")
    assert err.sqlstate == "25006"
    segunda = ejecutar_select("SELECT pg_backend_pid() AS pid")
    assert segunda.filas[0][0] == primera.filas[0][1]


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
