"""Alineación código ↔ schema: revisión alembic aplicada frente a la del repo.

Compara ``alembic_version`` (lo que la BD tiene aplicado) con las cabezas de
``db/alembic/versions`` (lo que exige este checkout) y lo traduce al vocabulario
que publica ``/health/ready`` en ``schema_revision``:

- ``ok (<rev>)``: BD y código son la misma generación.
- ``behind (<aplicadas> < <cabezas>)``: la BD va por detrás; falta lanzar
  ``migrate.yml`` (mode=apply).
- ``ahead (<aplicadas> > <cabezas>)``: la BD tiene revisiones que este checkout
  no conoce; el código es más viejo que el schema.
- ``unknown``: no se pudo determinar (BD inalcanzable, repo sin cabezas).
- ``unconfigured``: sin ``DATABASE_URL`` no hay nada que comparar.

Nació dentro de ``api/routes/health.py`` (S6.2) y se mudó aquí cuando hizo falta
fuera de la API. El único fallo de ``ml-scoring.yml`` en sus últimos 30 runs
(2026-09-19) fue ``UndefinedColumn: column "lote_numero" of relation
"predicciones_baja" does not exist``: código de la migración v140 contra una BD
que aún no la tenía. ``migrate.yml`` es manual a propósito y Render/Actions
despliegan código solos, así que ese desfase es un estado normal durante horas;
el job lo descubrió con un traceback en mitad del batch. Con la comparación en
``db/`` el endpoint y los jobs usan el mismo criterio y no pueden discrepar
sobre qué es un desfase.

Preflight de los workflows de datos
-----------------------------------
::

    python -m db.schema_revision

Lo ejecutan los workflows que escriben en la BD como paso previo, antes de tocar
una fila. El primero es ``.github/workflows/ml-scoring.yml`` (step «Preflight de
schema»). Contrato:

- exit ``0`` solo con ``ok (…)``;
- exit ``1`` con ``behind``, ``ahead``, ``unknown`` o ``unconfigured``: sin
  alineación verificada el job no escribe. ``unknown`` también bloquea: un
  sondeo que no pudo leer no autoriza a escribir a ciegas;
- un evento estructurado por corrida con el logging de la casa (JSON con
  ``LOG_FORMAT=json``, que es como corre en CI): ``schema_preflight_ok`` o
  ``schema_preflight_failed``, con ``resultado`` (``ok``/``behind``/…),
  ``estado`` (la cadena completa) y, si falla, ``accion`` y ``error``;
- una línea legible en stderr, ``schema_revision = <estado>. <qué hacer>``; si
  falla, precedida del prefijo de anotación de Actions
  (``::error title=<título>::``), que el run enseña en su resumen sin abrir el
  log. stdout queda vacío.

No abre el pool de ``db.connection`` (ver :func:`revisiones_aplicadas`), así que
el proceso termina en cuanto imprime: no quedan hilos del pool que esperar.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Collection
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from observability.logging import configure_logging, get_logger, redact_dsn

# Nombre fijo y no ``__name__``: con ``python -m`` este módulo corre como
# ``__main__`` y sus eventos saldrían firmados con ese nombre.
_LOGGER = "db.schema_revision"

# Logger de módulo solo para el punto de observación de :func:`diagnosticar`.
# Los eventos del CLI y del endpoint se piden con `get_logger(_LOGGER)` en cada
# llamada, que es lo que sus tests sustituyen; este no pasa por ahí, así que no
# se cuela en esas aserciones.
_log = get_logger(_LOGGER)

ALEMBIC_DIR = Path(__file__).resolve().parent / "alembic"

# `redact_dsn` redacta la contraseña de un DSN `postgresql://`, pero no la de la
# forma con driver (`postgresql+psycopg://`) que construye `revisiones_aplicadas` para
# SQLAlchemy. Un mensaje de error que la arrastrase dejaría la contraseña en el
# log del run, y los secrets de Actions solo se enmascaran con su valor exacto.
_DSN_CON_DRIVER = re.compile(r"(postgres(?:ql)?\+[\w.]+://[^:/?#@\s]+:)[^@/?#\s]+(@)")

_FuenteUrl = Callable[[], str]
_FuenteRepo = Callable[[], tuple[tuple[str, ...], tuple[str, ...]]]
_FuenteAplicadas = Callable[[], tuple[str, ...]]


def _abreviar(revisiones: Collection[str]) -> str:
    """Rinde un conjunto de revisiones en algo legible en una línea."""
    if not revisiones:
        return "ninguna"
    return ",".join(sorted(revisiones))


def comparar_revisiones(
    aplicadas: Collection[str],
    cabezas: Collection[str],
    conocidas: Collection[str],
) -> str:
    """Traduce (aplicadas, cabezas, conocidas) al vocabulario del payload.

    Función **pura**: es la que los tests ejercitan inyectando las revisiones,
    sin BD y sin repo. ``conocidas`` es el conjunto de todas las revisiones que
    este checkout conoce; sirve para distinguir los dos desalineamientos, que se
    arreglan de forma opuesta:

    - ``behind``: la BD va por detrás. El código desplegado exige columnas que
      todavía no existen → hay que correr ``migrate.yml`` (mode=apply).
    - ``ahead``: la BD tiene revisiones que este checkout no conoce, o sea que
      el código desplegado es MÁS VIEJO que el schema. Migrar no arregla nada;
      lo que toca es desplegar el código correcto (o revisar un rollback).
    """
    aplicadas_set = set(aplicadas)
    cabezas_set = set(cabezas)
    if not cabezas_set:
        return "unknown"
    if aplicadas_set == cabezas_set:
        return f"ok ({_abreviar(cabezas_set)})"
    if aplicadas_set - set(conocidas):
        return f"ahead ({_abreviar(aplicadas_set)} > {_abreviar(cabezas_set)})"
    return f"behind ({_abreviar(aplicadas_set)} < {_abreviar(cabezas_set)})"


@lru_cache(maxsize=1)
def revisiones_repo() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Devuelve ``(cabezas, todas las revisiones)`` según este checkout.

    Import diferido: alembic ya es dependencia (lo instalan ``requirements.txt``
    y ``requirements-api.txt``, y lo usa ``migrate.yml``), pero no tiene por qué
    cargarse en el arranque de la API solo para que exista un endpoint de salud.
    ``lru_cache`` porque el árbol de revisiones no cambia dentro de un proceso y
    construirlo importa todos los módulos de migración (134 en 2026-09).
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    # `script_location` explícito en vez de leer `alembic.ini`: el fichero no
    # tiene por qué existir en la imagen ni en el cwd del proceso, y aquí solo
    # se necesita el árbol de versiones.
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    script = ScriptDirectory.from_config(cfg)
    cabezas = tuple(sorted(script.get_heads()))
    todas = tuple(sorted(rev.revision for rev in script.walk_revisions()))
    return cabezas, todas


def database_url() -> str:
    """DSN de Postgres, tolerante a que ``DATABASE_URL`` no sea un ``SecretStr``.

    ``tests/conftest.py`` blanquea el atributo con la cadena vacía (``monkeypatch
    .setattr(settings, "DATABASE_URL", "")``) para que un DSN real de ``.env`` no
    contamine los tests unitarios. Sin esta tolerancia, un ``.get_secret_value()``
    a secas lanzaría ``AttributeError`` en cada petición de salud de la suite y
    este sondeo se pasaría el CI entero reportando ``unknown`` por el motivo
    equivocado.
    """
    from pydantic import SecretStr

    from config import settings

    valor: object = settings.DATABASE_URL
    if isinstance(valor, SecretStr):
        return valor.get_secret_value()
    return str(valor or "")


def revisiones_aplicadas() -> tuple[str, ...]:
    """Lee ``alembic_version`` de la BD vía la API de alembic.

    Conexión propia ``NullPool`` que se cierra al salir (``dispose`` en el
    ``finally``), y no el pool de ``db.connection``, por dos motivos:

    - **Hilos.** Cada pool de ``psycopg_pool`` arranca un planificador y tres
      workers que alguien tiene que cerrar. El CLI de este módulo termina en
      cuanto imprime; ``ml-scoring.yml`` documenta un minuto perdido el
      2026-09-20 esperando hilos de pool que su CLI no cerraba.
    - **Presupuesto.** En la API los dos pools tienen su tamaño contado al
      detalle en ``render.yaml``; el sondeo de salud no debe quitarles una
      conexión.

    La consulta la emite ``MigrationContext``: sabe dónde vive la tabla de
    versiones y devuelve ``()`` si aún no existe, que es una BD nueva
    (``behind (ninguna < …)``) y no un ``UndefinedTable``. La receta es la de
    ``db/alembic/env.py``: dialecto psycopg v3, ``sslrootcert`` y
    ``connect_timeout``. Basta la credencial de runtime: ``alembic_version``
    queda fuera de la RLS de v52 y ``scripts/setup_pg_roles.sql`` da ``SELECT``
    sobre todas las tablas a ``tenderflow_app``.
    """
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine, pool

    from config import settings

    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL vacía")
    # SQLAlchemy resuelve "postgresql://" a psycopg2, que este proyecto no
    # declara: se fuerza el dialecto psycopg (v3), igual que en env.py.
    for prefijo in ("postgresql://", "postgres://"):
        if url.startswith(prefijo):
            url = "postgresql+psycopg://" + url[len(prefijo) :]
            break

    connect_args: dict[str, str | int] = {}
    ssl_root_cert = settings.DATABASE_SSL_ROOT_CERT.strip()
    if ssl_root_cert:
        connect_args["sslrootcert"] = ssl_root_cert
    if settings.DB_CONNECT_TIMEOUT > 0:
        connect_args["connect_timeout"] = int(settings.DB_CONNECT_TIMEOUT)

    engine = create_engine(url, poolclass=pool.NullPool, connect_args=connect_args)
    try:
        with engine.connect() as conn:
            return tuple(sorted(MigrationContext.configure(conn).get_current_heads()))
    finally:
        engine.dispose()


@dataclass(frozen=True, slots=True)
class Diagnostico:
    """Desenlace del sondeo: el estado y, si el sondeo falló, por qué."""

    #: La cadena del vocabulario de ``/health/ready`` (``ok (v140)``, …).
    estado: str
    #: Motivo del fallo, en una línea y sin credenciales. Solo acompaña a un
    #: ``unknown`` por excepción; el de un repo sin cabezas no trae error.
    error: str | None = None

    @property
    def resultado(self) -> str:
        """``ok``, ``behind``, ``ahead``, ``unknown`` o ``unconfigured``."""
        return self.estado.partition(" ")[0]


def _describir(exc: BaseException) -> str:
    """El motivo de un fallo en una línea y sin credenciales.

    En una línea porque acaba en una anotación de Actions, que solo muestra la
    primera, y los errores de psycopg/SQLAlchemy traen varias. Con el tipo
    delante porque hay excepciones sin mensaje (un ``TimeoutError()`` a secas
    daría un motivo vacío).
    """
    texto = " ".join(f"{type(exc).__name__}: {exc}".split())
    return _DSN_CON_DRIVER.sub(r"\1***\2", redact_dsn(texto))


def diagnosticar(
    *,
    url: _FuenteUrl | None = None,
    repo: _FuenteRepo | None = None,
    aplicadas: _FuenteAplicadas | None = None,
) -> Diagnostico:
    """Ejecuta el sondeo completo. Nunca propaga.

    ``unconfigured`` sin DSN, sin intentar nada más (no hay BD que leer), y
    ``unknown`` ante cualquier fallo: un sondeo que no puede leer el estado no
    es lo mismo que un schema desalineado. Quien llama decide qué significa
    cada cosa: ``/health`` solo degrada con ``behind``/``ahead`` y el preflight
    bloquea con todo lo que no sea ``ok``.

    Las fuentes son inyectables porque hay dos llamadores con dos superficies de
    sustitución: ``/health`` pasa sus alias de siempre (``_database_url``,
    ``_repo_revisions``, ``_applied_revisions``), que es donde sus tests las
    cambian; el CLI usa las de este módulo, resueltas en cada llamada para que
    también se puedan sustituir aquí.
    """
    leer_url: _FuenteUrl = database_url if url is None else url
    leer_repo: _FuenteRepo = revisiones_repo if repo is None else repo
    leer_aplicadas: _FuenteAplicadas = revisiones_aplicadas if aplicadas is None else aplicadas
    try:
        if not leer_url():
            return Diagnostico("unconfigured")
        cabezas, conocidas = leer_repo()
        return Diagnostico(comparar_revisiones(leer_aplicadas(), cabezas, conocidas))
    except Exception as exc:
        error = _describir(exc)
        # El aviso lo emite quien llama (`schema_preflight_failed`,
        # `health_schema_check_failed`, `schema_revision_check_failed`) con este
        # mismo `error`; aquí queda el punto de observación del propio sondeo.
        # Sin `exc_info`: la traza puede arrastrar el DSN con la contraseña, y
        # `_describir` ya lo deja redactado.
        _log.debug("schema_revision_sondeo_fallido", error=error)
        return Diagnostico("unknown", error=error)


def estado_schema() -> str:
    """El estado en el vocabulario de ``/health/ready``. Nunca propaga.

    Para quien quiera comprobarlo dentro de su propio proceso; el fallo del
    sondeo queda en el log como ``schema_revision_check_failed``.
    """
    diagnostico = diagnosticar()
    if diagnostico.error is not None:
        get_logger(_LOGGER).warning("schema_revision_check_failed", error=diagnostico.error)
    return diagnostico.estado


#: Qué decir ante cada desenlace que no es ``ok``: título de la anotación de
#: Actions (sin ``:`` ni ``,``, que ahí hay que escapar) y la acción concreta.
#: Los dos desalineamientos se arreglan al revés, así que el mensaje tiene que
#: nombrar la salida correcta y no un genérico «schema desalineado».
_DESENLACES: dict[str, tuple[str, str]] = {
    "behind": (
        "Schema por detrás del código",
        "La BD no tiene todavía las migraciones que exige este código: lanzá "
        "Actions > 'Apply DB migrations (alembic)' (migrate.yml) con mode=apply "
        "y volvé a lanzar este job.",
    ),
    "ahead": (
        "Schema por delante del código",
        "La BD tiene revisiones que este checkout no conoce, así que el código es "
        "más viejo que el schema: revisá qué ref se hizo checkout o si hubo un "
        "rollback. Migrar no lo arregla.",
    ),
    "unknown": (
        "Schema sin verificar",
        "No se pudo determinar si la BD y el código son la misma generación: "
        "revisá DATABASE_URL, DATABASE_SSL_ROOT_CERT y la conectividad con la BD. "
        "Sin esa comprobación el job no escribe.",
    ),
    "unconfigured": (
        "Schema sin verificar",
        "DATABASE_URL está vacía: no hay BD contra la que comparar ni en la que "
        "escribir. Revisá que el secret llegue a este step.",
    ),
}


def main() -> int:
    """Preflight de schema: ``0`` si BD y código están alineados, ``1`` si no.

    El contrato completo (códigos, eventos y línea de stderr) está en el
    docstring del módulo: los workflows de datos lo invocan antes de escribir.
    """
    configure_logging()
    log = get_logger(_LOGGER)
    diagnostico = diagnosticar()

    if diagnostico.resultado == "ok":
        log.info("schema_preflight_ok", resultado="ok", estado=diagnostico.estado)
        print(
            f"schema_revision = {diagnostico.estado}. BD y código son la misma generación.",
            file=sys.stderr,
        )
        return 0

    titulo, accion = _DESENLACES.get(diagnostico.resultado, _DESENLACES["unknown"])
    log.error(
        "schema_preflight_failed",
        resultado=diagnostico.resultado,
        estado=diagnostico.estado,
        accion=accion,
        error=diagnostico.error,
    )
    detalle = f" Detalle: {diagnostico.error}" if diagnostico.error else ""
    print(
        f"::error title={titulo}::schema_revision = {diagnostico.estado}. {accion}{detalle}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
