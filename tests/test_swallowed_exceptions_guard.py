"""Guardarraíl: ningún ``except`` amplio nuevo puede tragar el error en silencio.

Motivación
----------
El export GDPR de ``/me/data`` devolvía una lista vacía durante meses porque
``WatchlistRepository.export_by_user_key`` consultaba una tabla inexistente y el
``except Exception: return []`` que la envolvía convertía el fallo en un
resultado indistinguible de "este usuario no tiene datos". Ningún log, ninguna
métrica, ningún test lo señalaron: el bug se encontró leyendo el código.

Esa forma -- capturar ``Exception`` y devolver un valor de "no hay nada" sin
dejar rastro -- es la que este test congela. No prohíbe tragar excepciones
(hay sitios donde es correcto: persistencia best-effort, telemetría que nunca
debe romper el camino principal); prohíbe hacerlo **sin dejar constancia**, que
es lo que impide diagnosticar el fallo después.

Ninguna herramienta del repo ve hoy esta clase: ``pyproject.toml`` ignora
``S110`` (try-except-pass) y ``SIM105`` en ruff, y ``[tool.bandit] skips``
incluye ``B110`` y ``B112``. Todas esas exenciones son deliberadas -- silenciar
el ruido de los best-effort legítimos -- pero dejan el hueco sin cubrir.

Heurística
----------
1. Se recorren ``db/**/*.py`` y ``services/**/*.py`` con ``ast``.
2. De cada ``try`` se examina cada handler. Se considera **amplio** el que
   captura ``Exception``/``BaseException`` o no declara tipo (``except:``).
   Los handlers específicos (``except KeyError``) quedan fuera: capturar lo que
   se espera es justamente el patrón correcto.
3. Un handler amplio **deja constancia** si su cuerpo re-lanza (``raise``),
   registra (``log``/``logger``/``logging``.*, ``print``, ``warnings.warn``),
   alerta (``notify``) o reporta a Sentry (``capture_exception``). Si no hace
   ninguna de esas cosas, es una violación.
4. El identificador es ``ruta::qualname`` de la función contenedora (o
   ``ruta::<module>`` para los ``try`` de nivel de módulo), igual que
   ``tests/test_user_key_sql_isolation.py``. Una función con varios handlers
   silenciosos aparece una sola vez.

Como el resto de ratchets del repo (TID251, ``scripts/check_openapi_contract.py``),
la allowlist **solo puede encoger**: el test falla tanto por violaciones nuevas
sin listar como por entradas que ya no corresponden a nada.

Limitaciones conocidas
----------------------
- Es un análisis estático de una sola función: si el handler llama a un helper
  propio que sí loguea (``_report(exc)``), el test lo cuenta como silencioso.
  Cuando pase, la entrada va a ``_LEGITIMATE_SILENT`` con esa explicación.
- Un ``log.debug`` cuenta como constancia aunque en producción no se emita. Es
  deliberado: el objetivo es que exista el punto de observación, y subir el
  nivel es un cambio de una línea que este test no debe forzar.
- ``db/alembic/`` queda fuera. Las migraciones son append-only (AGENTS.md §3.3):
  congelar su forma no aporta -- no se pueden modificar -- y ensuciaría la
  allowlist con entradas inmutables.
- Granularidad por función, no por handler: si una función tiene cinco handlers
  silenciosos y se arreglan cuatro, la entrada sigue siendo legítima. El ratchet
  no lo detecta hasta que se arregla el último.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Directorios escaneados. `db/alembic/` se excluye (ver "Limitaciones").
_TARGET_DIRS: tuple[str, ...] = ("db", "services")
_EXCLUDED_PARTS: frozenset[str] = frozenset({"alembic", "__pycache__"})

# Nombres cuya invocación dentro del handler cuenta como "dejar constancia".
_LOGGING_ATTRS: frozenset[str] = frozenset(
    {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
)
_LOGGER_OBJECTS: frozenset[str] = frozenset({"log", "logger", "logging", "_log", "_logger"})
_REPORTING_FUNCS: frozenset[str] = frozenset({"print", "notify", "capture_exception", "capture"})


def _is_broad_handler(handler: ast.ExceptHandler) -> bool:
    """``True`` si el handler captura Exception/BaseException o no declara tipo."""
    if handler.type is None:
        return True

    def _names(node: ast.expr) -> Iterator[str]:
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                yield from _names(elt)

    return any(name in {"Exception", "BaseException"} for name in _names(handler.type))


def _leaves_trace(handler: ast.ExceptHandler) -> bool:
    """``True`` si el cuerpo del handler re-lanza, loguea, alerta o reporta."""
    for node in ast.walk(ast.Module(body=handler.body, type_ignores=[])):
        if isinstance(node, ast.Raise):
            return True
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in _LOGGING_ATTRS:
                return True
            # `observability.notify(...)`, `sentry_sdk.capture_exception(...)`
            if func.attr in _REPORTING_FUNCS:
                return True
            if isinstance(func.value, ast.Name) and func.value.id in _LOGGER_OBJECTS:
                return True
        elif isinstance(func, ast.Name) and func.id in _REPORTING_FUNCS:
            return True
    return False


def _own_nodes(node: ast.AST) -> Iterator[ast.AST]:
    """Nodos del cuerpo propio de ``node``, sin descender a funciones ni clases
    anidadas (esas se escanean aparte, con su propio qualname)."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        yield child
        yield from _own_nodes(child)


def _iter_scopes(node: ast.AST, prefix: str = "") -> Iterator[tuple[str, ast.AST]]:
    """Produce ``(qualname, nodo)`` de cada función o método, incluyendo
    anidadas, con el qualname punteado."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from _iter_scopes(child, prefix=f"{prefix}{child.name}.")
        elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            qualname = f"{prefix}{child.name}"
            yield qualname, child
            yield from _iter_scopes(child, prefix=f"{qualname}.")


def _has_silent_handler(scope: ast.AST) -> bool:
    for node in _own_nodes(scope):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            if _is_broad_handler(handler) and not _leaves_trace(handler):
                return True
    return False


def _scan_file(path: Path) -> set[str]:
    """Identificadores ``ruta::qualname`` con al menos un handler amplio mudo."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(_REPO_ROOT).as_posix()

    violations: set[str] = set()
    if _has_silent_handler(tree):
        violations.add(f"{rel}::<module>")
    for qualname, scope in _iter_scopes(tree):
        if _has_silent_handler(scope):
            violations.add(f"{rel}::{qualname}")
    return violations


def _target_files() -> list[Path]:
    files: list[Path] = []
    for directory in _TARGET_DIRS:
        for path in sorted((_REPO_ROOT / directory).rglob("*.py")):
            if _EXCLUDED_PARTS & set(path.parts):
                continue
            files.append(path)
    return files


def _scan_files(paths: list[Path]) -> set[str]:
    found: set[str] = set()
    for path in paths:
        found |= _scan_file(path)
    return found


# ── Allowlist: SOLO puede encoger ───────────────────────────────────────────
#
#   _LEGITIMATE_SILENT: sitios donde tragar sin log es la decisión correcta y
#   se espera que permanezcan. Cada entrada explica por qué.
#
#   _GRANDFATHERED_PENDING_FIX: el censo de lo que ya existía cuando se
#   introdujo este test. No son decisiones de diseño: son puntos ciegos que
#   deberían ganar un `log.warning(..., exc_info=True)` cuando se toque el
#   módulo. Arreglarlos en bloque sería un cambio de runtime enorme y sin
#   revisar; el ratchet garantiza que el grupo solo mengüe.

_LEGITIMATE_SILENT: frozenset[str] = frozenset(
    {
        # Cierre del pool en shutdown: si `close()` falla, el proceso está
        # terminando de todos modos y no hay nadie que lea el log.
        "db/connection.py::_close_pg_pool",
        "db/connection.py::_PgConnAdapter.close",
        # Devolver la conexión al pool, con `close()` como último recurso. Ruta
        # caliente por request; loguear aquí sería ruido en cada fallo de red
        # que el propio pool ya reintenta.
        "db/connection.py::_return_pg_connection",
        # El fallback está en el contrato de la función ("devuelve conjunto
        # vacío si la tabla no existe o no se puede inspeccionar"): quien la
        # llama distingue el caso vacío, no queda enmascarado.
        "db/connection.py::get_table_columns",
        # Probes de disponibilidad: el `return False` ES el resultado que el
        # llamante espera, no un fallback que oculte un fallo.
        "db/search_backend.py::PgTsBackend.available",
        # `check_db` devuelve "error", que viaja hasta /api/v1/health/ready y
        # se convierte en 503. La constancia es la respuesta HTTP.
        "services/health.py::check_db",
    }
)

# 2026-08-07: vaciadas las 12 entradas de autenticación, auditoría y export
# GDPR (api_keys, sessions, totp, audit). Quedan las de búsqueda, webhooks e
# ingesta, que son la siguiente ola.
_GRANDFATHERED_PENDING_FIX: frozenset[str] = frozenset(
    {
        # ── Búsqueda: los fallbacks encadenados degradan sin dejar rastro,
        # así que una búsqueda rota se ve como "sin resultados".
        "db/repositories/licitaciones.py::LicitacionRepository.fts5_bm25_search",
        "db/repositories/licitaciones.py::LicitacionRepository.like_fallback_search",
        "db/repositories/licitaciones.py::LicitacionRepository.search_fts_ids",
        "db/repositories/licitaciones.py::LicitacionRepository.search_like_for_ask",
        "db/repositories/licitaciones.py::LicitacionRepository.fetch_metadata_by_ids",
        "db/search_backend.py::PgTsBackend._ts_search",
        "db/search_backend.py::PgTsBackend.hybrid_search_docs",
        # ── Idempotencia de webhooks: un fallo silencioso aquí puede
        # traducirse en entregas duplicadas o perdidas.
        "db/repositories/webhooks.py::WebhookRepository.idempotency_reserve",
        "db/repositories/webhooks.py::WebhookRepository.idempotency_finalize",
        "db/repositories/webhooks.py::WebhookRepository.idempotency_release",
        "db/repositories/webhooks.py::WebhookRepository.list_deliveries",
        "db/repositories/feedback.py::FeedbackRepository.exists_idempotency",
        # ── Ingesta y analítica: columnas derivadas que caen a defaults
        # (listas vacías, "Otro") sin señalar que el cálculo falló.
        "db/upsert.py::replace_adjudicaciones_batch",
        "db/repositories/extraction_runs.py::ExtractionRunRepository.load_recent_daily_statuses",
        "services/partners.py::_detect_communities",
    }
)

_ALLOWLIST: frozenset[str] = _LEGITIMATE_SILENT | _GRANDFATHERED_PENDING_FIX


def test_broad_handlers_leave_a_trace() -> None:
    """Todo ``except Exception`` en ``db/`` y ``services/`` deja constancia --
    salvo la allowlist documentada arriba, que solo puede encoger."""
    found = _scan_files(_target_files())

    nuevas = sorted(found - _ALLOWLIST)
    assert not nuevas, (
        "Handler(s) `except` amplio(s) que tragan el error sin log ni re-raise. "
        'Añadí `log.warning("<evento>", exc_info=True)` antes de devolver el '
        "valor de fallback -- un fallo indistinguible de 'no hay datos' es el "
        f"bug que este test existe para prevenir: {nuevas}"
    )

    obsoletas = sorted(_ALLOWLIST - found)
    assert not obsoletas, (
        "Entrada(s) en la allowlist que ya no corresponden a ningún handler "
        f"silencioso -- el ratchet solo puede encoger, bórralas: {obsoletas}"
    )
