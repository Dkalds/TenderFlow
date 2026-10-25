"""Ratchet TID251: la whitelist de ``pyproject.toml`` solo puede ENCOGER.

Por qué existe este test
-----------------------
ADR-022 y AGENTS.md §3.10 dicen que todo el SQL vive en ``db/``, y ruff lo
impone con ``TID251`` (``banned-api`` sobre ``connect``/``connect_read``). La
deuda legacy se aparca en una whitelist de ``per-file-ignores`` que, por
contrato, **solo se puede recortar**.

Hasta 2026-09-03 esa dirección era prosa: un comentario en ``pyproject.toml``.
Nada la ejecutaba. ``scripts/gen_status.py`` *publica* el tamaño en
``docs/STATUS.md`` y CI verifica que el documento está sincronizado, pero
sincronizado no es lo mismo que decreciente: quien añadiese una entrada nueva y
regenerase ``STATUS.md`` en el mismo commit pasaba el tablero en verde. El único
guardián era la revisión humana, y una whitelist con 28 líneas es exactamente el
sitio donde una línea nueva no se ve.

Lo que se congela aquí es el número MEDIDO el 2026-09-03 —28 entradas, tras
liberar las cuatro rutas de ``api/routes/``— con la regla de que solo puede
bajar. Bajar el tope es parte de cerrar cada ola; subirlo requiere cambiar este
test, que es justo la conversación que la revisión necesita tener.

El escaneo de SQL de la segunda mitad cubre lo que ruff NO ve: ``TID251``
prohíbe *abrir la conexión*, no *escribir la query*. Una ruta que construyese el
literal y se lo pasara a un helper de ``db/`` pasaría ruff sin problema y sería
la misma regresión de capas.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

#: Tamaño MEDIDO de la whitelist. **Solo puede bajar.** Venía de 32; bajó a 28
#: el 2026-09-03 al sacar `api/routes/` (empresas, eventos, exports,
#: watchlist_rules) y a 26 el 2026-09-16 al sacar
#: `scheduler/kpi_precompute.py` y `services/competitive/mercado.py`, y a 25 el
#: 2026-09-24 al sacar `services/ml/scoring.py`, y a 22 el 2026-09-28 al
#: borrar tres scripts de un solo uso (`dedupe_licitaciones`,
#: `fix_dates_adjudicaciones`, `retrain`), y a 19 el 2026-10-23 al sacar
#: `services/notifications.py` y `services/watchlist_rules.py` (su SQL bajó a
#: `db/`) y el fósil `services/ml/tech_classifier.py`, que solo nombraba
#: `connect()` en un docstring, y a 18 el 2026-10-25 al borrar `medir_solape`,
#: lo último que abría conexión en `services/dedupe.py`, y a 12 el mismo
#: 2026-10-25 al bajar a `db/` el SQL de `services/resoluciones.py`,
#: `services/deadline_reminders.py`, `services/competitive/renovaciones.py`,
#: `scheduler/competitor_alerts.py`, `scheduler/retention.py` y
#: `scripts/rotate_api_keys.py`.
#: El objetivo del plan de arquitectura de septiembre (≤ 24) queda cumplido.
MAX_ENTRADAS_WHITELIST = 12

#: Las cuatro rutas liberadas en esta ola. Su SQL vive ahora en
#: ``db/repositories/{empresas,licitaciones,watchlist,watchlist_rules}.py``.
#: Se listan por nombre —y no se escanea ``api/routes/`` entero— porque el
#: propósito es fijar ESTA liberación: si mañana otra ruta nace con SQL, quien
#: la denuncia es ruff, no este test.
_RUTAS_LIBERADAS = (
    "api/routes/empresas.py",
    "api/routes/eventos.py",
    "api/routes/exports.py",
    "api/routes/watchlist_rules.py",
)

# SQL de verdad, no menciones a verbos HTTP. `exports.py` documenta en su
# docstring el retirado ``DELETE /exports/{id}``: un patrón que buscase la
# palabra `DELETE` suelta lo denunciaría y el test moriría de falsos positivos.
_SQL = re.compile(
    r"\bSELECT\b[\s\S]*?\bFROM\b"
    r"|\bINSERT\s+INTO\b"
    r"|\bUPDATE\s+\w+\s+SET\b"
    r"|\bDELETE\s+FROM\b",
    re.IGNORECASE,
)

# Aperturas de conexión prohibidas fuera de `db/` (las mismas cuatro rutas que
# `[tool.ruff.lint.flake8-tidy-imports.banned-api]`).
_CONNECT = {"connect", "connect_read"}


def _bloque_ratchet() -> str:
    texto = _PYPROJECT.read_text(encoding="utf-8")
    bloque = re.search(r"# ── RATCHET TID251.*?# ── fin RATCHET TID251 ──", texto, re.DOTALL)
    assert bloque is not None, "Desapareció el bloque RATCHET TID251 de pyproject.toml"
    return bloque.group(0)


def _whitelist() -> list[str]:
    """Mismo parseo y mismo recorte que ``scripts/gen_status.py``.

    Deliberadamente duplicado en vez de importado: ``scripts/`` está fuera de
    mypy strict y del paquete instalable, y un test que dependiese de él
    dejaría de fallar el día que alguien tocase el script. Aquí la fuente de
    verdad es el fichero de configuración, no el generador del informe.

    ``db/**`` y ``tests/*`` quedan fuera —igual que en el informe— porque no
    son deuda: son la infraestructura donde el SQL *debe* vivir y la suite que
    lo ejercita. Contarlos rompería la comparación con el número que publica
    ``docs/STATUS.md`` y con el objetivo del plan (≤ 24).
    """
    entradas = re.findall(r'^"([^"]+)"\s*=\s*\[[^\]]*"TID251"', _bloque_ratchet(), re.MULTILINE)
    return sorted(e for e in entradas if not e.startswith(("db/", "tests/")))


def test_whitelist_solo_puede_encoger() -> None:
    """El invariante del ratchet, ejecutable."""
    entradas = _whitelist()
    assert len(entradas) <= MAX_ENTRADAS_WHITELIST, (
        f"La whitelist TID251 creció a {len(entradas)} entradas (tope medido: "
        f"{MAX_ENTRADAS_WHITELIST}). Añadir entradas está prohibido (ADR-022, "
        "AGENTS.md §3.10): mové el SQL a db/ en vez de ampliar la excepción."
    )


def test_el_tope_declarado_no_va_por_delante_de_la_realidad() -> None:
    """Un ratchet que sobra deja de apretar.

    Si una ola recorta la whitelist y nadie baja ``MAX_ENTRADAS_WHITELIST``, el
    hueco resultante admite entradas nuevas en silencio. Esta mitad obliga a
    cerrar el ratchet en el mismo commit que lo recorta.
    """
    entradas = _whitelist()
    assert len(entradas) == MAX_ENTRADAS_WHITELIST, (
        f"La whitelist tiene {len(entradas)} entradas pero el tope declarado es "
        f"{MAX_ENTRADAS_WHITELIST}. Bajá MAX_ENTRADAS_WHITELIST a "
        f"{len(entradas)} y regenerá docs/STATUS.md."
    )


def test_ninguna_ruta_de_la_api_sigue_en_la_whitelist() -> None:
    """``api/**`` salió entero el 2026-09-03 y no vuelve a entrar.

    Es el resultado concreto de esta ola: el handler HTTP no abre conexiones.
    Un `api/...` reapareciendo aquí es la regresión que el conteo global —que
    puede bajar por otro lado a la vez— no distinguiría.
    """
    intrusas = [e for e in _whitelist() if e.startswith("api/")]
    assert not intrusas, f"Rutas de la API de vuelta en la whitelist TID251: {intrusas}"


#: Módulos que exponen las APIs vetadas por ``banned-api`` en ``pyproject.toml``.
_MODULOS_CONEXION = ("db.connection", "db.database")


def _usos_reales_de_conexion(arbol: ast.AST) -> list[str]:
    """Usos de ``connect``/``connect_read`` en CÓDIGO, no en prosa.

    Cuenta lo mismo que hace saltar ``TID251``: importar el nombre vetado de
    ``db.connection``/``db.database`` (a nivel de módulo o dentro de una
    función, con o sin alias), o acceder a él como atributo de esos módulos
    (``database.connect``, ``db.database.connect_read``). Un docstring o un
    comentario que lo nombre no es un nodo de este tipo, que es justo lo que
    hace falta: ``services/ml/tech_classifier.py`` siguió en la whitelist meses
    después de dejar de abrir conexiones porque su docstring decía
    ``sqlite3.connect()``.
    """
    alias_de_modulo: set[str] = set()
    usos: list[str] = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom):
            modulo = nodo.module or ""
            if modulo in _MODULOS_CONEXION:
                usos.extend(
                    f"from {modulo} import {a.name}" for a in nodo.names if a.name in _CONNECT
                )
            elif modulo == "db":
                alias_de_modulo.update(
                    a.asname or a.name for a in nodo.names if a.name in ("connection", "database")
                )
        elif isinstance(nodo, ast.Import):
            for a in nodo.names:
                if a.name in _MODULOS_CONEXION:
                    alias_de_modulo.add(a.asname or a.name)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Attribute) and nodo.attr in _CONNECT:
            base = ast.unparse(nodo.value)
            if base in alias_de_modulo or base in _MODULOS_CONEXION:
                usos.append(f"{base}.{nodo.attr}")
    return usos


def test_sin_entradas_fosiles() -> None:
    """Una whitelist que solo decrece también acumula fósiles.

    Dos formas de fósil, y las dos inflan el conteo del ratchet con deuda que ya
    no existe, de modo que el número deja de medir nada:

    * El archivo se borró o renombró y su línea se quedó. Mismo criterio que
      ``scripts/gen_status.py::_stale_whitelist_entries`` (los patrones con
      ``*`` no se resuelven a un fichero y quedan fuera).
    * El archivo existe pero ya no usa ``connect``/``connect_read``: su SQL
      bajó a ``db/`` y nadie quitó la excepción. Peor que el anterior, porque
      además deja pasar en silencio la próxima regresión de ese fichero.
    """
    entradas = [e for e in _whitelist() if "*" not in e]
    borradas = [e for e in entradas if not (_REPO_ROOT / e).exists()]
    assert not borradas, f"Entradas del ratchet que ya no apuntan a nada (borralas): {borradas}"

    sin_uso = [
        e
        for e in entradas
        if not _usos_reales_de_conexion(ast.parse((_REPO_ROOT / e).read_text(encoding="utf-8")))
    ]
    assert not sin_uso, (
        "Entradas del ratchet TID251 que ya no abren conexiones (borralas de "
        f"pyproject.toml y bajá MAX_ENTRADAS_WHITELIST): {sin_uso}"
    )


def test_el_detector_de_fosiles_distingue_codigo_de_prosa() -> None:
    """El detector no puede fallar hacia el lado cómodo.

    Si devolviera siempre «hay uso», el test de fósiles no apretaría nunca; si
    contase menciones en docstrings, ``tech_classifier`` no habría salido.
    """
    solo_prosa = ast.parse('"""Se retiró el fallback ``sqlite3.connect()``."""\n# connect_read()\n')
    assert _usos_reales_de_conexion(solo_prosa) == []
    for codigo in (
        "from db.database import connect\n",
        "from db.connection import connect_read as leer\n",
        "def f():\n    from db.database import connect as db_connect\n",
        "from db import database\ndatabase.connect()\n",
        "import db.database\ndb.database.connect_read()\n",
    ):
        assert _usos_reales_de_conexion(ast.parse(codigo)), codigo
    # `sqlite3.connect` o un `connect` propio no son la API vetada.
    assert (
        _usos_reales_de_conexion(ast.parse("import sqlite3\nsqlite3.connect(':memory:')\n")) == []
    )


def _literales(arbol: ast.AST) -> list[str]:
    """Todas las cadenas del módulo, incluidos los trozos de f-string."""
    return [
        n.value for n in ast.walk(arbol) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def test_las_rutas_liberadas_no_llevan_sql_crudo() -> None:
    """El hueco que ruff no cubre: TID251 veta la conexión, no la query.

    Antes del 2026-09-03 estas cuatro rutas construían el SQL en el propio
    handler (``_list_empresas``, ``_get_empresa``, ``_licitacion_existe``,
    ``_rules_with_counts``, ``_calendario_rows``…). Que hoy no importen
    ``connect`` no basta para dar la capa por cerrada: el literal podría volver
    y viajar a un helper de ``db/`` sin que ruff dijera nada.
    """
    con_sql = []
    for rel in _RUTAS_LIBERADAS:
        arbol = ast.parse((_REPO_ROOT / rel).read_text(encoding="utf-8"))
        if any(_SQL.search(lit) for lit in _literales(arbol)):
            con_sql.append(rel)
    assert not con_sql, (
        f"SQL crudo de vuelta en el handler: {con_sql}. Movelo a db/ (ADR-022); "
        "los valores de usuario van por parámetro (%s), nunca interpolados."
    )


def test_las_rutas_liberadas_no_abren_conexiones() -> None:
    """La mitad que ruff sí cubre, fijada también aquí.

    No es redundancia gratuita: ruff deja de mirar en cuanto alguien vuelve a
    añadir la entrada a ``per-file-ignores``, y ese es precisamente el
    movimiento que este archivo existe para hacer visible.
    """
    culpables: list[str] = []
    for rel in _RUTAS_LIBERADAS:
        arbol = ast.parse((_REPO_ROOT / rel).read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if (
                isinstance(nodo, ast.ImportFrom)
                and (nodo.module or "").startswith(("db.connection", "db.database"))
                and any(a.name in _CONNECT for a in nodo.names)
            ):
                culpables.append(f"{rel}::import {nodo.module}")
    assert not culpables, f"Apertura de conexión de vuelta en la ruta: {culpables}"
