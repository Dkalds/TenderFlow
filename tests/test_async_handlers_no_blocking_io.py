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
1. Se recorren los ``async def`` de ``api/routes/``, **subpaquetes incluidos**
   (``api/routes/licitaciones/``…): handlers y también dependencias —una
   dependencia bloqueante es peor, se ejecuta en cada request que la use—.
   Hasta 2026-09 solo se miraba el primer nivel, así que un handler movido a un
   subpaquete salía del radar sin que nada fallara.
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
- Mira ``api/routes/`` y los wrappers async de ``shared/cache.py`` (abajo). El
  resto de la app (scheduler, scraper) es síncrono de principio a fin y no
  tiene event loop que bloquear. ``api/middleware.py`` tampoco entra: sus
  capas ASGI tienen sus propios tests, que comprueban que la cuota se consulta
  en un hilo.
- No distingue una query de 1 ms de una de 5 s. Todas van al threadpool: el
  criterio es "no corre en el loop", no "cuánto tarda".

``shared/cache.py``
-------------------
``cache_response`` envuelve 26 endpoints en un ``async def``, y ese wrapper
llamaba al cliente Redis (síncrono) y (de)serializaba la respuesta entera en el
propio loop: con Redis lento, todos los endpoints —cacheados o no— esperaban.
La regla de ``db.*``/``services.*`` no lo ve (el módulo no importa ninguno de
los dos), así que tiene la suya. En cada ``async def`` del módulo —salvo los de
``_MemoryBackend``, que no hacen E/S: un ``dict`` con un lock— es violación
llamar **sin** ``await`` a:

- ``get_cache(...)``: la primera vez construye el backend, y con Redis eso es
  un ``PING`` (``aget_cache`` lo despacha a un hilo);
- un método de un backend obtenido con ``get_cache``/``aget_cache`` en ese
  mismo ``async def``, al cliente Redis (``self._r``) o, dentro de
  ``_RedisBackend``, a sus métodos síncronos de E/S;
- (de)serialización de la respuesta: ``json.dumps``/``json.loads``,
  ``model_dump``/``model_dump_json``, ``dump_json``/``validate_python``,
  ``to_json``, ``jsonable_encoder``.

La clave de caché se construye en un helper síncrono (``_clave_de_peticion``)
que sí serializa los **parámetros** de la petición: son unos pocos escalares,
no la respuesta, y el test no sigue esa llamada a propósito.
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
        "LicitacionesFilters",
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
        # `db.database.now_utc`: `datetime.now(UTC)`, sin BD. El ping de
        # webhooks lo usa para sellar cuerpo y cabecera con el mismo instante.
        "now_utc",
        # `db.idempotency.scope` (importado como `idem_scope`): concatena el
        # nombre del endpoint con la identidad de quien escribe para formar el
        # ámbito de la clave. Es `":".join(...)` — no abre conexión. Las que sí
        # la abren son `cached_response`/`store_response`, y esas van dentro de
        # la función que se despacha con `run_db`.
        "idem_scope",
        # `services.pursuit_attachments`: firmar y verificar un enlace de
        # descarga es un HMAC-SHA256 sobre veinte bytes (`shared/signing.py`).
        # No abre conexión y no puede: la comprobación de que el adjunto existe
        # y es de tu organización es la que sí va a BD, y esa se despacha con
        # `run_db` unas líneas más abajo en los dos handlers.
        "firmar_descarga",
        "verificar_descarga",
        # `db.sessions.session_public_id`: `token_hash[:N]`. El id público de
        # una sesión es un prefijo del hash que ya está en la fila leída, no una
        # segunda consulta.
        "session_public_id",
        # `services.tecnologias_diccionario.invalidar`: vacía la memoización en
        # proceso bajo un lock. Quien va a BD justo después es `vigente(...)`, y
        # esa sí se despacha con `run_db`.
        "invalidar",
        # `services.rag.resumen.resumen_cache_key`: sha256 del expediente, el
        # modelo y la firma de estado ya cargada. El contexto que firma lo trae
        # `cargar_contexto_resumen`, y ese sí se despacha con `run_db`.
        "resumen_cache_key",
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


def _route_files() -> list[Path]:
    """Todos los ``.py`` de ``api/routes/``, subpaquetes incluidos."""
    return sorted(_ROUTES_DIR.rglob("*.py"))


def _scan_routes() -> set[str]:
    found: set[str] = set()
    for path in _route_files():
        found |= _scan_file(path)
    return found


# ── shared/cache.py ─────────────────────────────────────────────────────────

_CACHE_FILE = _REPO_ROOT / "shared" / "cache.py"

#: Métodos de E/S de los backends: desde un ``async def`` van por su variante
#: ``a*`` (que despacha a un hilo), nunca directos.
_CACHE_IO_METHODS: frozenset[str] = frozenset(
    {"get", "set", "delete", "keys", "clear", "get_respuesta", "set_respuesta"}
)

#: (De)serialización de la respuesta: CPU proporcional a su tamaño.
_SERIALIZATION_LEAVES: frozenset[str] = frozenset(
    {
        "model_dump",
        "model_dump_json",
        "dump_json",
        "validate_python",
        "model_validate",
        "model_validate_json",
        "to_json",
        "jsonable_encoder",
    }
)
_SERIALIZATION_CALLS: frozenset[str] = frozenset({"json.dumps", "json.loads"})

#: Funciones que devuelven un backend de caché.
_CACHE_FACTORIES: frozenset[str] = frozenset({"get_cache", "aget_cache"})


def _cache_backend_names(scope: ast.AST) -> set[str]:
    """Variables del ``async def`` a las que se asigna un backend de caché."""
    names: set[str] = set()
    for node in _own_nodes(scope):
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        value = node.value
        if isinstance(value, ast.Await):
            value = value.value
        if not (isinstance(value, ast.Call) and _call_name(value) in _CACHE_FACTORIES):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names.update(t.id for t in targets if isinstance(t, ast.Name))
    return names


def _cache_violation(node: ast.Call, qualname: str, backends: set[str]) -> bool:
    name = _call_name(node)
    if name == "get_cache" or name in _SERIALIZATION_CALLS:
        return True
    if name.split(".")[-1] in _SERIALIZATION_LEAVES:
        return True
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    receiver = func.value
    # El cliente Redis, venga de donde venga (`self._r.get`, `self._r.scan`…).
    if (
        isinstance(receiver, ast.Attribute)
        and receiver.attr == "_r"
        and isinstance(receiver.value, ast.Name)
    ):
        return True
    if not isinstance(receiver, ast.Name):
        return False
    if receiver.id in backends:
        return True
    return (
        receiver.id == "self"
        and qualname.startswith("_RedisBackend.")
        and func.attr in _CACHE_IO_METHODS
    )


def _scan_cache_source(source: str, rel: str) -> tuple[set[str], set[str]]:
    """``(violaciones, async defs examinados)`` de un módulo de caché."""
    tree = ast.parse(source, filename=rel)
    violations: set[str] = set()
    scanned: set[str] = set()
    for qualname, scope in _iter_async_scopes(tree):
        if qualname.startswith("_MemoryBackend."):
            continue
        scanned.add(qualname)
        awaited = _awaited_call_ids(scope)
        backends = _cache_backend_names(scope)
        for node in _own_nodes(scope):
            if not isinstance(node, ast.Call) or id(node) in awaited:
                continue
            if _cache_violation(node, qualname, backends):
                violations.add(f"{rel}::{qualname}")
    return violations, scanned


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


def test_el_barrido_entra_en_los_subpaquetes_de_routes() -> None:
    """Si el barrido volviera a ser de un solo nivel, esto lo delataría."""
    subpaquetes = [p for p in _route_files() if p.parent != _ROUTES_DIR]
    assert subpaquetes, "api/routes/ tiene subpaquetes (licitaciones/) y deben barrerse"
    assert not any(p.name == "middleware.py" for p in _route_files())


def test_los_wrappers_async_de_la_cache_no_bloquean_el_event_loop() -> None:
    """Ningún ``async def`` de ``shared/cache.py`` hace E/S de Redis ni
    (de)serializa la respuesta en el loop. Sin allowlist: no hay deuda."""
    rel = _CACHE_FILE.relative_to(_REPO_ROOT).as_posix()
    violations, scanned = _scan_cache_source(_CACHE_FILE.read_text(encoding="utf-8"), rel)

    # Sin esto el test podría pasar por no haber examinado nada.
    assert "cache_response.decorator.wrapper" in scanned
    assert {"_RedisBackend.aget_respuesta", "_RedisBackend.aset_respuesta"} <= scanned

    assert not violations, (
        "async def de shared/cache.py con E/S de Redis o (de)serialización en el "
        "event loop. Usá los métodos `a*` del backend (`aget_respuesta`, `aset`…) o "
        f"`anyio.to_thread.run_sync`: {sorted(violations)}"
    )


def test_la_regla_de_la_cache_detecta_el_wrapper_antiguo() -> None:
    """La forma que tenía ``cache_response`` hasta 2026-09 tiene que fallar."""
    antiguo = """
async def wrapper(*args, **kwargs):
    cache = get_cache(namespace)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    result = await func(*args, **kwargs)
    val = result.model_dump()
    cache.set(cache_key, val, ttl=ttl)
    return result


class _RedisBackend:
    async def aget(self, key):
        return self.get(key)

    async def ping(self):
        return self._r.ping()
"""
    violations, _ = _scan_cache_source(antiguo, "antiguo.py")
    assert violations == {
        "antiguo.py::wrapper",
        "antiguo.py::_RedisBackend.aget",
        "antiguo.py::_RedisBackend.ping",
    }
