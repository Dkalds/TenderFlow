"""Preflight de schema de los workflows de datos (``python -m db.schema_revision``).

Motivación
----------
El único fallo de ``ml-scoring.yml`` en sus últimos 30 runs (2026-09-19) fue
``UndefinedColumn: column "lote_numero" of relation "predicciones_baja" does
not exist``: código de la migración v140 contra una BD que aún no la tenía, y
el job lo descubrió con un traceback en mitad del batch. El preflight lo
descubre antes de escribir y dice qué hacer. Lo que se fija aquí es el contrato
que lee el YAML: el código de salida de cada estado, el evento estructurado y
la línea legible de stderr, más la receta de conexión que garantiza que el
proceso no deja hilos de pool detrás.

Todo corre **sin base de datos**: las fuentes de revisión se sustituyen en el
módulo. Los dos tests de subproceso ejecutan el CLI de verdad (entry point,
logging JSON, fin del proceso) sin llegar a Postgres: uno sin DSN y otro contra
un puerto local cerrado.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from db import schema_revision

ROOT = Path(__file__).resolve().parent.parent

_CABEZA = "v141_tasas_anulacion_organo"
_ANTERIOR = "v140_predicciones_baja_por_lote"
_CONOCIDAS = (_ANTERIOR, _CABEZA)
_DSN = "postgresql://app@db.example:5432/tenderflow"


@pytest.fixture
def eventos(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """El logger del CLI, sustituido por un doble que registra cada llamada.

    Sin tocar el logging global: ``configure_logging`` reemplaza los handlers
    del root logger, y hacerlo desde un test ata el de stderr al ``capsys`` de
    ese test. Tampoco sirve ``structlog.testing.capture_logs``: con
    ``cache_logger_on_first_use`` un logger usado antes de otro
    ``configure_logging`` de la suite queda atado a la lista de processors
    vieja y la captura deja de verlo según el orden de los tests. El camino
    real del logging lo cubren los tests de subproceso.
    """
    registro = MagicMock()
    monkeypatch.setattr(schema_revision, "configure_logging", lambda **_: None)
    monkeypatch.setattr(schema_revision, "get_logger", lambda *_: registro)
    return registro


def _fuentes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    url: str = _DSN,
    cabezas: tuple[str, ...] = (_CABEZA,),
    aplicadas: tuple[str, ...] = (_CABEZA,),
) -> list[str]:
    """Sustituye las tres fuentes del sondeo; devuelve qué se llegó a consultar."""
    consultadas: list[str] = []

    def _repo() -> tuple[tuple[str, ...], tuple[str, ...]]:
        consultadas.append("repo")
        return cabezas, _CONOCIDAS

    def _aplicadas() -> tuple[str, ...]:
        consultadas.append("aplicadas")
        return aplicadas

    monkeypatch.setattr(schema_revision, "database_url", lambda: url)
    monkeypatch.setattr(schema_revision, "revisiones_repo", _repo)
    monkeypatch.setattr(schema_revision, "revisiones_aplicadas", _aplicadas)
    return consultadas


# ---------------------------------------------------------------------------
# El contrato del CLI: un código de salida por estado
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fuentes", "codigo", "resultado", "pistas"),
    [
        pytest.param({}, 0, "ok", (f"schema_revision = ok ({_CABEZA})",), id="ok"),
        pytest.param(
            {"aplicadas": (_ANTERIOR,)},
            1,
            "behind",
            (f"behind ({_ANTERIOR} < {_CABEZA})", "migrate.yml", "mode=apply"),
            id="behind",
        ),
        pytest.param(
            {"aplicadas": ("v142_futura",)},
            1,
            "ahead",
            (f"ahead (v142_futura > {_CABEZA})", "checkout", "rollback"),
            id="ahead",
        ),
        pytest.param(
            {"cabezas": ()},
            1,
            "unknown",
            ("schema_revision = unknown.", "No se pudo determinar"),
            id="unknown-sin-cabezas",
        ),
        pytest.param(
            {"url": ""},
            1,
            "unconfigured",
            ("schema_revision = unconfigured.", "DATABASE_URL está vacía"),
            id="unconfigured",
        ),
    ],
)
def test_cada_estado_tiene_su_codigo_de_salida_evento_y_linea(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    eventos: MagicMock,
    fuentes: dict[str, Any],
    codigo: int,
    resultado: str,
    pistas: tuple[str, ...],
) -> None:
    """Solo ``ok`` deja pasar; el resto bloquea diciendo qué hacer.

    ``behind`` y ``ahead`` se arreglan al revés (migrar frente a revisar el
    checkout), así que el mensaje tiene que nombrar la salida correcta; y
    ``unknown``/``unconfigured`` también bloquean: sin alineación verificada el
    job no escribe a ciegas.
    """
    _fuentes(monkeypatch, **fuentes)

    assert schema_revision.main() == codigo

    salida = capsys.readouterr()
    assert salida.out == "", "el contrato es exit code + stderr; stdout queda libre"
    (linea,) = salida.err.splitlines()
    for pista in pistas:
        assert pista in linea

    (llamada,) = eventos.method_calls
    nivel, argumentos, campos = llamada
    assert campos["resultado"] == resultado
    if codigo == 0:
        assert (nivel, argumentos) == ("info", ("schema_preflight_ok",))
        assert not linea.startswith("::"), "un ok no es una anotación de error"
    else:
        assert (nivel, argumentos) == ("error", ("schema_preflight_failed",))
        assert linea.startswith("::error title=")
        assert campos["accion"] in linea
        assert campos["estado"] in linea


def test_sin_dsn_no_se_lee_el_repo_ni_se_intenta_conectar(
    monkeypatch: pytest.MonkeyPatch, eventos: MagicMock
) -> None:
    """``unconfigured`` sale antes de recorrer ~130 migraciones o abrir un socket."""
    consultadas = _fuentes(monkeypatch, url="")

    assert schema_revision.main() == 1
    assert consultadas == []


def test_un_fallo_del_sondeo_bloquea_con_el_motivo_en_una_linea_y_sin_credenciales(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    eventos: MagicMock,
) -> None:
    """El motivo llega al run, pero nunca la contraseña del DSN.

    Las dos formas: la de ``DATABASE_URL`` y la ``postgresql+psycopg://`` que
    se construye para SQLAlchemy, que ``redact_dsn`` no reconoce. Y en una sola
    línea, porque una anotación de Actions solo muestra la primera.
    """
    _fuentes(monkeypatch)

    def _revienta() -> tuple[str, ...]:
        # DSN falsos a propósito: el test comprueba que la contraseña se redacta.
        raise RuntimeError(
            "connection failed: postgresql+psycopg://app:secreta@db.example:5432/tf\n"  # pragma: allowlist secret
            "retry: postgresql://app:secreta@db.example:5432/tf"  # pragma: allowlist secret
        )

    monkeypatch.setattr(schema_revision, "revisiones_aplicadas", _revienta)

    assert schema_revision.main() == 1

    (linea,) = capsys.readouterr().err.splitlines()
    assert linea.startswith("::error title=Schema sin verificar::schema_revision = unknown.")
    assert "Detalle: RuntimeError: connection failed" in linea
    assert "secreta" not in linea

    (llamada,) = eventos.method_calls
    _, _, campos = llamada
    assert campos["resultado"] == "unknown"
    assert "app:***@db.example" in campos["error"]
    assert "secreta" not in campos["error"]


def test_estado_schema_devuelve_el_vocabulario_y_nunca_propaga(
    monkeypatch: pytest.MonkeyPatch, eventos: MagicMock
) -> None:
    """La API en proceso: la misma cadena que publica ``/health/ready``."""
    _fuentes(monkeypatch, aplicadas=(_ANTERIOR,))
    assert schema_revision.estado_schema() == f"behind ({_ANTERIOR} < {_CABEZA})"
    assert eventos.method_calls == []

    def _revienta() -> tuple[tuple[str, ...], tuple[str, ...]]:
        raise OSError("alembic no disponible")

    monkeypatch.setattr(schema_revision, "revisiones_repo", _revienta)

    assert schema_revision.estado_schema() == "unknown"
    (llamada,) = eventos.method_calls
    nivel, argumentos, campos = llamada
    assert (nivel, argumentos) == ("warning", ("schema_revision_check_failed",))
    assert campos["error"] == "OSError: alembic no disponible"


# ---------------------------------------------------------------------------
# La receta de conexión: NullPool, cerrada siempre, fuera del pool de db/
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("falla_la_conexion", [False, True])
def test_revisiones_aplicadas_abre_una_conexion_nullpool_y_la_cierra_siempre(
    monkeypatch: pytest.MonkeyPatch, falla_la_conexion: bool
) -> None:
    """Sin pool no hay hilos que esperar al salir, y el motor se libera aunque falle.

    El pool de ``db.connection`` arranca un planificador y tres workers por
    pool que alguien tiene que cerrar; ``ml-scoring.yml`` documenta un minuto
    perdido el 2026-09-20 esperándolos. El preflight no lo toca: abre una
    conexión ``NullPool`` con la receta de ``db/alembic/env.py`` y la suelta.
    """
    import sqlalchemy
    from alembic import migration
    from sqlalchemy import pool

    from config import settings
    from db import connection

    motores: list[SimpleNamespace] = []

    def _crear_motor(url: str, **opciones: Any) -> SimpleNamespace:
        motor = SimpleNamespace(url=url, opciones=opciones, cerrado=False)

        def _conectar() -> contextlib.AbstractContextManager[str]:
            if falla_la_conexion:
                raise ConnectionRefusedError("connection refused")
            return contextlib.nullcontext("conexion")

        def _cerrar() -> None:
            motor.cerrado = True

        motor.connect = _conectar
        motor.dispose = _cerrar
        motores.append(motor)
        return motor

    def _configurar(conexion: str) -> SimpleNamespace:
        assert conexion == "conexion"
        return SimpleNamespace(get_current_heads=lambda: (_CABEZA,))

    monkeypatch.setattr(sqlalchemy, "create_engine", _crear_motor)
    monkeypatch.setattr(migration, "MigrationContext", SimpleNamespace(configure=_configurar))
    monkeypatch.setattr(
        settings,
        "DATABASE_URL",
        SecretStr(
            "postgresql://app:secreta@db.example:5432/tf?sslmode=verify-full"  # pragma: allowlist secret
        ),
    )
    monkeypatch.setattr(settings, "DATABASE_SSL_ROOT_CERT", " /etc/ssl/supabase-ca.crt ")
    monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", 7)
    pools_antes = (connection._pg_pool, connection._pg_read_pool)

    if falla_la_conexion:
        with pytest.raises(ConnectionRefusedError):
            schema_revision.revisiones_aplicadas()
    else:
        assert schema_revision.revisiones_aplicadas() == (_CABEZA,)

    (motor,) = motores
    # Dialecto psycopg v3 explícito: "postgresql://" resolvería a psycopg2,
    # que el proyecto no instala.
    assert (
        motor.url
        == "postgresql+psycopg://app:secreta@db.example:5432/tf?sslmode=verify-full"  # pragma: allowlist secret
    )
    assert motor.opciones["poolclass"] is pool.NullPool
    assert motor.opciones["connect_args"] == {
        "sslrootcert": "/etc/ssl/supabase-ca.crt",
        "connect_timeout": 7,
    }
    assert motor.cerrado, "el motor no se liberó"
    assert connection._pg_pool is pools_antes[0]
    assert connection._pg_read_pool is pools_antes[1]


def test_revisiones_aplicadas_sin_dsn_no_crea_motor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin DSN falla en el acto; ``diagnosticar`` ni siquiera llega a llamarla."""
    import sqlalchemy

    def _no_debe_llamarse(*_: Any, **__: Any) -> None:
        raise AssertionError("create_engine sin DSN")

    monkeypatch.setattr(sqlalchemy, "create_engine", _no_debe_llamarse)

    with pytest.raises(RuntimeError, match="DATABASE_URL vacía"):
        schema_revision.revisiones_aplicadas()


# ---------------------------------------------------------------------------
# El CLI de verdad, en un proceso aparte
# ---------------------------------------------------------------------------


def _cli(**entorno: str) -> subprocess.CompletedProcess[str]:
    """``python -m db.schema_revision`` con logging JSON, como en CI."""
    env = {
        **os.environ,
        "ENV": "dev",
        "LOG_FORMAT": "json",
        "PYTHONIOENCODING": "utf-8",
        **entorno,
    }
    return subprocess.run(
        [sys.executable, "-m", "db.schema_revision"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        # Un proceso que no termina es justo el fallo que se vigila (hilos de
        # pool vivos al salir): el timeout lo convierte en rojo en vez de en
        # un job colgado.
        timeout=300,
    )


def _evento(stderr: str, nombre: str) -> dict[str, Any]:
    for linea in stderr.splitlines():
        if not linea.startswith("{"):
            continue
        datos: dict[str, Any] = json.loads(linea)
        if datos.get("event") == nombre:
            return datos
    pytest.fail(f"no hay evento JSON {nombre!r} en stderr:\n{stderr}")


def test_el_cli_real_sin_dsn_sale_con_1_evento_json_y_anotacion() -> None:
    """Entry point, logging de la casa y código de salida, sin red ni alembic.

    ``DATABASE_URL`` vacía en el entorno gana al ``.env`` de quien corre la
    suite (en pydantic-settings el entorno manda), así que este proceso nunca
    toca una BD real.
    """
    proc = _cli(DATABASE_URL="")

    assert proc.returncode == 1, proc.stderr
    assert proc.stdout == ""
    evento = _evento(proc.stderr, "schema_preflight_failed")
    assert evento["resultado"] == "unconfigured"
    assert evento["level"] == "error"
    assert evento["logger"] == "db.schema_revision"
    ultima = proc.stderr.splitlines()[-1]
    assert ultima.startswith("::error title=Schema sin verificar::schema_revision = unconfigured.")


@pytest.mark.slow
def test_el_cli_real_contra_un_puerto_cerrado_termina_en_unknown_sin_filtrar_la_contrasena() -> (
    None
):
    """El camino completo: recorre las migraciones del repo y conecta de verdad.

    Contra un puerto local sin nadie escuchando: psycopg falla al conectar, el
    CLI sale con ``1`` diciendo ``unknown`` y el proceso termina, que es la
    prueba de que no quedan hilos vivos. ``slow`` porque recorre las ~130
    migraciones y abre un socket; CI lo ejecuta en la suite completa.
    """
    with socket.socket() as sonda:
        sonda.bind(("127.0.0.1", 0))
        puerto = sonda.getsockname()[1]

    proc = _cli(
        DATABASE_URL=f"postgresql://app:secreta@127.0.0.1:{puerto}/tf",  # pragma: allowlist secret
        DB_CONNECT_TIMEOUT="3",
    )

    assert proc.returncode == 1, proc.stderr
    assert "secreta" not in proc.stderr
    evento = _evento(proc.stderr, "schema_preflight_failed")
    assert evento["resultado"] == "unknown"
    assert evento["error"], "el motivo del fallo no llegó al evento"
    ultima = proc.stderr.splitlines()[-1]
    assert ultima.startswith("::error title=Schema sin verificar::schema_revision = unknown.")
    assert "Detalle: " in ultima
