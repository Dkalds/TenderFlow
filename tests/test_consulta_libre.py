"""Piezas puras del ejecutor de SQL libre del MCP (sin base de datos)."""

from __future__ import annotations

import contextlib
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from db.consulta_libre import (
    MAX_CHARS_SQL,
    ErrorConsulta,
    envolver,
    normalizar_sql,
    serializar_valor,
)


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
    ],
)
def test_normalizar_es_lineal(sql: str) -> None:
    assert _tiempo(sql) < 0.5
