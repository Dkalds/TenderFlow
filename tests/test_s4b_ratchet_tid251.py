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

#: Tamaño MEDIDO de la whitelist el 2026-09-03, tras sacar `api/routes/`
#: (empresas, eventos, exports, watchlist_rules). **Solo puede bajar.**
#: Venía de 32; el objetivo del plan de arquitectura de septiembre es ≤ 24.
MAX_ENTRADAS_WHITELIST = 28

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


def test_sin_entradas_fosiles() -> None:
    """Una whitelist que solo decrece también acumula fósiles.

    Al borrar o renombrar un archivo su línea se queda, e infla el conteo del
    ratchet con deuda que ya no existe: el número deja de medir nada. Mismo
    criterio que ``scripts/gen_status.py::_stale_whitelist_entries`` (los
    patrones con ``*`` no se resuelven a un fichero y quedan fuera).
    """
    fosiles = [e for e in _whitelist() if "*" not in e and not (_REPO_ROOT / e).exists()]
    assert not fosiles, f"Entradas del ratchet que ya no apuntan a nada (borralas): {fosiles}"


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
