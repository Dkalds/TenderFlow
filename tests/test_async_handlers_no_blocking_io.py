"""Guardarraíl: ningún handler ``async def`` puede bloquear el event loop.

Motivación
----------
La API es async, pero toda la persistencia es síncrona (psycopg3 sobre
``db.connection``). Cuando un ``async def`` llama directamente a ``db.*`` o
``services.*``, ese trabajo no corre en un hilo: corre **sobre el event loop**,
y mientras dura no se atiende ninguna otra request de todo el proceso. Los 149
endpoints se paran juntos, ``/health`` incluido — así que el probe de la
plataforma no ve "degradado", ve un servicio muerto y reinicia.

El caso que originó este test (auditoría 2026-08-07): ``GET /exports/download``
con ``format=pdf`` traía hasta 50 000 filas y maquetaba el PDF con reportlab en
el propio loop; ``POST /auth/login`` hacía seis viajes a BD más el ``argon2``
de ``verify_password`` (caro **por diseño**: es un KDF), de modo que dos logins
concurrentes se serializaban con toda la API detrás; y
``api/routes/dual_auth.py::require_any_auth``, de la que cuelga casi toda la
superficie autenticada, leía el usuario propietario en cada request.

Ninguna herramienta del repo veía esta clase: ruff y mypy no modelan qué es
bloqueante, y los tests funcionales pasan igual — un handler bloqueante da la
respuesta *correcta*, solo que a costa de parar el proceso. Por eso hace falta
un test estructural.

El idioma correcto ya existía en el repo (``api/routes/watchlist_rules.py::
post_rule``): agrupar el trabajo síncrono en una función anidada y despacharla
con un solo ``await run_db(...)`` (``api/concurrency.py``), que además crea el
span OTEL ``db.query``. Un solo salto al threadpool por handler, no N.

Heurística
----------
1. Se recorren los ``async def`` de ``api/routes/*.py`` (handlers y también
   dependencias: una dependencia bloqueante es peor, se ejecuta en cada
   request que la use).
2. De cada uno se examina **solo su cuerpo propio**: no se desciende a
   funciones anidadas ni a ``lambda``, porque justamente ese es el destino del
   trabajo síncrono — lo que se pasa a ``run_db`` corre en el threadpool. Es el
   mismo criterio de ``_own_nodes`` en ``tests/test_swallowed_exceptions_guard.py``.
3. Es violación llamar, **sin** ``await``, a:
   - ``connect``/``connect_read`` (abrir conexión directamente), o
   - cualquier nombre importado de ``db.*`` o ``services.*``, ya sea en el
     import de cabecera del módulo o en un import local dentro del handler.
4. ``_PURE_CALLS`` exime los nombres que vienen de esos paquetes pero no hacen
   I/O (constructores de modelos, helpers de formato). Cada uno documentado.

Como el resto de ratchets del repo (TID251, ``test_user_key_sql_isolation.py``,
``test_swallowed_exceptions_guard.py``), la allowlist **solo puede encoger**:
el test falla tanto por violaciones nuevas sin listar como por entradas que ya
no corresponden a nada.

Limitaciones conocidas
----------------------
- No sigue llamadas: si un handler llama a un helper propio del módulo que a su
  vez va a BD (``_check_db()`` en ``health.py``), este test no lo ve. Cubre la
  forma dominante — la llamada directa a ``db.*``/``services.*`` —, no todas.
- Solo mira ``api/routes/``. El resto de la app (scheduler, scraper) es
  síncrono de principio a fin y no tiene event loop que bloquear.
- No distingue una query de 1 ms de una de 5 s. Todas van al threadpool: el
  criterio es "no corre en el loop", no "cuánto tarda".
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ROUTES_DIR = _REPO_ROOT / "api" / "routes"

# Paquetes cuya superficie es síncrona y va a BD.
_SYNC_PACKAGES: frozenset[str] = frozenset({"db", "services"})

# Aperturas de conexión: bloqueantes se importen como se importen.
_CONNECT_CALLS: frozenset[str] = frozenset({"connect", "connect_read"})

# Nombres que vienen de db/services pero NO hacen I/O. Exentos con motivo.
_PURE_CALLS: frozenset[str] = frozenset(
    {
        # Modelos Pydantic/dataclasses: construir o validar no toca la BD.
        "EventoFeedItem",
        "EventosFeedResult",
        "RenovacionesResult",
        "RenovacionesResumenResult",
        "ResumenHoyFilters",
        "WatchlistEmpresaEntry",
        # Instanciar el repositorio no abre conexión; la abren sus métodos,
        # que sí tienen que ir por run_db.
        "TecnologiaPliegoRepository",
        # Formato de fecha puro (datetime.now().strftime), sin BD.
        "get_export_filename",
        "now_utc_iso",
    }
)


def _own_nodes(node: ast.AST) -> Iterator[ast.AST]:
    """Nodos del cuerpo propio, sin bajar a funciones anidadas ni lambdas.

    Ese descenso es exactamente lo que NO se quiere: ``def _work(): ...``
    seguido de ``await run_db(_work)`` es el patrón correcto, y contar lo de
    dentro lo marcaría como violación.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        yield child
        yield from _own_nodes(child)


def _call_name(node: ast.Call) -> str:
    """Nombre punteado del invocado (``_repo.get_by_id``, ``connect``…)."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: list[str] = []
        current: ast.AST = func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def _sync_names(tree: ast.AST) -> set[str]:
    """Nombres importados de ``db.*``/``services.*`` en todo el módulo.

    Incluye los imports locales dentro de funciones: en este repo son la forma
    habitual de evitar ciclos, así que ignorarlos dejaría fuera casi todo.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.split(".")[0] in _SYNC_PACKAGES
        ):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _awaited_call_ids(scope: ast.AST) -> set[int]:
    """``id()`` de las llamadas que están directamente bajo un ``await``."""
    return {
        id(node.value)
        for node in _own_nodes(scope)
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
    }


def _iter_async_scopes(
    node: ast.AST, prefix: str = ""
) -> Iterator[tuple[str, ast.AsyncFunctionDef]]:
    """``(qualname, nodo)`` de cada ``async def``, incluidos los anidados."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from _iter_async_scopes(child, prefix=f"{prefix}{child.name}.")
        elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            qualname = f"{prefix}{child.name}"
            if isinstance(child, ast.AsyncFunctionDef):
                yield qualname, child
            yield from _iter_async_scopes(child, prefix=f"{qualname}.")


def _scan_file(path: Path) -> set[str]:
    """Identificadores ``ruta::qualname`` con trabajo bloqueante en el loop."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(_REPO_ROOT).as_posix()
    sync_names = _sync_names(tree)

    violations: set[str] = set()
    for qualname, scope in _iter_async_scopes(tree):
        awaited = _awaited_call_ids(scope)
        for node in _own_nodes(scope):
            if not isinstance(node, ast.Call) or id(node) in awaited:
                continue
            name = _call_name(node)
            if not name:
                continue
            root = name.split(".")[0]
            leaf = name.split(".")[-1]
            if root in _PURE_CALLS or leaf in _PURE_CALLS:
                continue
            if leaf in _CONNECT_CALLS or root in sync_names or name in sync_names:
                violations.add(f"{rel}::{qualname}")
    return violations


def _scan_routes() -> set[str]:
    found: set[str] = set()
    for path in sorted(_ROUTES_DIR.glob("*.py")):
        found |= _scan_file(path)
    return found


# ── Allowlist: SOLO puede encoger ───────────────────────────────────────────
#
# Vacía a propósito. El barrido que introdujo este test migró los 22 handlers
# que existían, así que no hay deuda que congelar: cualquier entrada nueva aquí
# es un handler bloqueante que se decidió aceptar, y debe explicar por qué.
_ALLOWLIST: frozenset[str] = frozenset()


def test_async_handlers_do_not_block_the_event_loop() -> None:
    """Ningún ``async def`` de ``api/routes/`` llama a ``db.*``/``services.*``
    sin pasar por ``run_db``/``run_ml`` -- salvo la allowlist de arriba, que
    solo puede encoger."""
    found = _scan_routes()

    nuevas = sorted(found - _ALLOWLIST)
    assert not nuevas, (
        "Handler(s) async con trabajo síncrono sobre el event loop. Mientras "
        "ese trabajo corre, NINGÚN endpoint del proceso responde. Agrupá las "
        "llamadas en una función anidada y despachala con un solo "
        "`await run_db(_work)` (api/concurrency.py), como hace "
        f"api/routes/watchlist_rules.py::post_rule: {nuevas}"
    )

    obsoletas = sorted(_ALLOWLIST - found)
    assert not obsoletas, (
        "Entrada(s) en la allowlist que ya no corresponden a ningún handler "
        f"bloqueante -- el ratchet solo puede encoger, bórralas: {obsoletas}"
    )
