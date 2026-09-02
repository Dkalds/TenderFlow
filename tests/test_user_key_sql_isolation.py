"""Test de arquitectura: aisla queries contra tablas user-scoped por ``user_key``.

Contexto (auditoría de multi-tenencia, AGENTS.md invariante §3.4/§3.10): el
aislamiento entre usuarios de esta app depende ENTERAMENTE de que cada query
que toca una tabla de usuario incluya ``WHERE user_key = %s`` (o un predicado
equivalente). RLS en Postgres (``db/alembic/versions/v52_rls_lockdown.py``)
cierra el acceso público vía PostgREST/Data API de Supabase, pero el rol de
runtime tiene la política ``tenderflow_app_full_access`` -- ``USING (true)
WITH CHECK (true)`` (ver ``scripts/setup_pg_roles.sql``, sección 3): full
access, sin aislamiento por fila entre tenants. Antes de este archivo, nada
verificaba automáticamente que cada query nueva respete la disciplina de
``user_key``.

Tablas user-scoped (confirmadas con
``grep -rn 'sa.Column("user_key"' db/alembic/versions/*.py`` -- 10 columnas,
no ~9 como sugería la investigación previa -- y lectura completa de
``v51_pg_legacy_tables_backfill.py`` / ``v55_pg_v27_v49_tables_backfill.py``
para confirmar a qué ``CREATE TABLE`` pertenece cada una):

    v51_pg_legacy_tables_backfill.py:
        audit_log            (línea 57)
        notification_reads   (línea 152)
        pending_digests      (línea 163)
        saved_filters        (línea 191)
        watchlist_cpv        (línea 203)
    v55_pg_v27_v49_tables_backfill.py:
        watchlist_empresas   (línea 193)
        watchlist_rules      (línea 338)
        watchlist_items      (línea 363)
        user_notifications   (línea 390)
        user_profiles        (línea 406, user_key es la PK, no solo columna)

Alcance de ESTE test (según el encargo original): escanea literales SQL en
``db/*.py`` y ``db/repositories/*.py`` (ADR-022: "todo el SQL vive en db/").

IMPORTANTE -- gap de cobertura descubierto durante la auditoría: de las 10
tablas de arriba, DOS (``watchlist_rules``, ``user_notifications``) no tienen
NINGÚN literal SQL dentro de ``db/*.py`` ni ``db/repositories/*.py``: su CRUD
completo vive en ``services/watchlist_rules.py``, ``services/notifications.py``,
``scheduler/watchlist_rules_alerts.py`` y ``api/routes/watchlist_rules.py`` --
los 4 archivos que el ratchet TID251 (``pyproject.toml``) tiene grandfathered
como excepción a ADR-022. Escaneando solo ``db/`` este test sería VACUAMENTE
verde para esas 2 tablas (nada que escanear = "0 violaciones", pero NO
"protegido"). Por eso hay un SEGUNDO test en este archivo
(``test_grandfathered_non_db_sql_scopes_by_user_key``) que extiende el
escaneo a esos 4 archivos -- una decisión deliberada más allá de la
instrucción literal ("escanea db/"), documentada aquí para que sea visible y
fácil de revertir si se prefiere restringir el alcance solo a ``db/``.

Heurística (mismo espíritu que el ratchet TID251 / scripts/check_openapi_
contract.py: parseo estructural best-effort con AST + regex sobre literales
de código fuente, NO un parser SQL completo):

  1. Para cada función/método definido en los archivos escaneados, se
     recolectan sus literales de cadena PROPIOS (``ast.Constant`` de tipo
     ``str``, incluyendo trozos de f-strings) -- sin bajar a funciones
     anidadas, que se escanean por separado con su propio qualname. Esto
     evita que una asignación Python como ``user_key = _user_key(ctx)``
     (que no es un literal de cadena) se confunda con un predicado SQL.
  2. Si esos literales contienen una referencia ``FROM``/``JOIN``/``UPDATE``/
     ``DELETE FROM`` a una tabla user-scoped, se considera que la función
     ejecuta un SELECT/UPDATE/DELETE contra esa tabla.
  3. Si esos MISMOS literales no contienen un predicado ``user_key = ...`` en
     ningún punto (cubre también WHERE dinámicos construidos con listas de
     cláusulas, p. ej. ``db/audit.py::list_recent``, cuyo fragmento
     ``"user_key = %s"`` vive en un ``clauses.append(...)`` separado del
     SELECT), se marca como violación.
  4. INSERTs no se verifican (el encargo original solo pide SELECT/UPDATE/
     DELETE) -- un INSERT que grabe mal su ``user_key`` es un bug distinto
     (de integridad de datos, no de falta de predicado de aislamiento).

Limitaciones conocidas (no es un parser SQL real -- igual que TID251/
check_openapi_contract.py no lo son):
  - Granularidad de función: si una función tuviera dos statements contra la
    misma tabla, uno con predicado y otro sin él, este test no los
    distingue (ninguna función auditada hoy hace esto).
  - No sigue nombres de tabla pasados como variable entre funciones. P. ej.
    ``db/repositories/base.py::count_where`` recibe el nombre de tabla como
    parámetro de runtime; hoy su único call site
    (``db/repositories/adjudicaciones.py``) pasa ``"adjudicaciones"``, que no
    es user-scoped, así que no hay corte real -- pero un futuro call site
    con una tabla de ``_TARGET_TABLES`` no sería detectado por este test.
  - ``db/audit.py::list_recent`` acepta un ``user_key`` OPCIONAL (para el
    panel de Observabilidad, que legítimamente lista auditoría de TODOS los
    usuarios cuando no se pasa filtro). Este test solo verifica que la
    query TENGA la capacidad de filtrar por user_key, no que todo caller la
    use siempre -- eso es responsabilidad de la capa de autorización de esa
    ruta, fuera del alcance de un test estático sobre ``db/``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Tablas user-scoped confirmadas (ver docstring del módulo) ───────────────
_TARGET_TABLES: tuple[str, ...] = (
    "audit_log",
    "notification_reads",
    "pending_digests",
    "saved_filters",
    "watchlist_cpv",
    "watchlist_empresas",
    "watchlist_rules",
    "watchlist_items",
    "user_notifications",
    "user_profiles",
)

_USER_KEY_PREDICATE = re.compile(r"user_key\s*=", re.IGNORECASE)


def _table_patterns(table: str) -> list[re.Pattern[str]]:
    escaped = re.escape(table)
    return [
        re.compile(rf'\b(?:FROM|JOIN)\s+"?{escaped}"?\b', re.IGNORECASE),
        re.compile(rf'\bUPDATE\s+"?{escaped}"?\b', re.IGNORECASE),
        re.compile(rf'\bDELETE\s+FROM\s+"?{escaped}"%s\b', re.IGNORECASE),
    ]


_TABLE_PATTERNS: dict[str, list[re.Pattern[str]]] = {t: _table_patterns(t) for t in _TARGET_TABLES}


def _own_string_constants(node: ast.AST) -> list[str]:
    """Literales de cadena del cuerpo de ``node``, SIN bajar a funciones
    anidadas (esas se recolectan aparte, como su propio qualname)."""
    out: list[str] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            out.append(child.value)
        out.extend(_own_string_constants(child))
    return out


def _iter_functions(node: ast.AST, prefix: str = ""):
    """Recorre módulo/clases y produce ``(qualname, nodo)`` de cada función o
    método, incluyendo funciones anidadas (con su qualname punteado)."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from _iter_functions(child, prefix=f"{prefix}{child.name}.")
        elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            qualname = f"{prefix}{child.name}"
            yield qualname, child
            yield from _iter_functions(child, prefix=f"{qualname}.")


def _scan_file(path: Path) -> set[str]:
    """Identificadores ``ruta::qualname`` de funciones con un SELECT/UPDATE/
    DELETE contra una tabla user-scoped sin predicado ``user_key``."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    rel = path.relative_to(_REPO_ROOT).as_posix()

    violations: set[str] = set()
    for qualname, func_node in _iter_functions(tree):
        pool = "\n".join(_own_string_constants(func_node))
        if not pool:
            continue
        touches_target_table = any(
            any(pattern.search(pool) for pattern in patterns)
            for patterns in _TABLE_PATTERNS.values()
        )
        if not touches_target_table:
            continue
        if _USER_KEY_PREDICATE.search(pool):
            continue
        violations.add(f"{rel}::{qualname}")
    return violations


def _scan_files(paths: list[Path]) -> set[str]:
    found: set[str] = set()
    for path in paths:
        found |= _scan_file(path)
    return found


def _db_layer_files() -> list[Path]:
    db_dir = _REPO_ROOT / "db"
    files = sorted(db_dir.glob("*.py")) + sorted((db_dir / "repositories").glob("*.py"))
    return [f for f in files if f.name != "__init__.py"]


# ── Allowlist: SOLO puede encoger (mismo espíritu que el ratchet TID251 /
# scripts/check_openapi_contract.py). Se divide en dos grupos con semántica
# distinta -- ver el test de abajo, que verifica AMBAS direcciones (nuevas
# violaciones sin listar Y entradas obsoletas que ya no corresponden a nada).
#
#   _LEGITIMATE_SWEEPS: queries que POR DISEÑO operan sobre todos los
#   usuarios (jobs de scheduler, integridad del hash chain de auditoría).
#   Se espera que permanezcan aquí indefinidamente -- no son errores.
#
#   _KNOWN_GAPS_PENDING_FIX: violaciones REALES encontradas durante esta
#   auditoría que NO son barridos legítimos por diseño -- son huecos de
#   aislamiento en la capa SQL que deberían corregirse añadiendo
#   ``AND user_key = ?`` a la query (cambio de runtime code, fuera del
#   alcance de este frente, que es aditivo-solo sobre tests/ -- ver informe
#   final). Se documentan aquí, con su razón, para que el ratchet no bloquee
#   la introducción de este test; se espera que este grupo se vacíe con el
#   tiempo a medida que se corrijan.
_LEGITIMATE_SWEEPS: frozenset[str] = frozenset(
    {
        # `load_pending_digests` estuvo aquí hasta 2026-09-02: sigue siendo un
        # barrido global (agrupa los digests pendientes de TODOS los usuarios
        # antes de enviarlos), pero ya no dispara la heurística porque su JOIN
        # correlaciona la regla con el `user_key` del propio digest. Esa
        # correlación no es cosmética: `pending_digests.entry_id` apunta a dos
        # tablas distintas (`watchlist_rules` y el legado `watchlist_cpv`) sin
        # discriminador, y unirla sólo por `id` mezclaba los criterios de un
        # usuario en el correo de otro.
        # Marca como enviados unos ids que vinieron del barrido global de
        # arriba -- nunca de input de usuario final.
        "db/repositories/watchlist.py::WatchlistRepository.mark_digests_sent",
        # Actualiza el timestamp de una entrada tras el barrido global del
        # scheduler (scheduler/watchlist_alerts.py, corre tras cada pipeline);
        # no tiene ningún caller vía api/routes/*.py.
        "db/watchlist.py::update_last_notified",
        # Barrido global de watchlist de empresas con email configurado, para
        # el job scheduler/competitor_alerts.py.
        "db/watchlist_empresas.py::list_all",
        # Mismo patrón que db/watchlist.py::update_last_notified, para el job
        # de alertas de competidores (scheduler/competitor_alerts.py).
        "db/watchlist_empresas.py::update_last_notified",
        # Barrido global de NIF canónicos vigilados por CUALQUIER usuario:
        # scraper/connectors/watched_company_awards.py necesita saber qué
        # empresas buscar en la fuente PLACSP durante la ingesta, no los
        # favoritos de un usuario concreto. Sin caller vía api/routes/*.py.
        "db/repositories/watched_companies.py::WatchedCompanyRepository.list_canonical_nifs",
        # Priorización por demanda real de los dos lotes nocturnos de pliegos
        # (scheduler/jobs/documentos_embeddings.py). Miran `watchlist_items` y
        # `pursuits` de TODOS los usuarios a propósito: la pregunta que
        # responden es «¿este expediente le importa a alguien?», no «¿a quién?».
        # Acotarlas a un user_key no tendría sentido -- el job no corre en
        # nombre de nadie -- y el resultado es un orden, no un dato que se
        # devuelva a un usuario.
        "db/repositories/documentos.py::DocumentosRepository.list_pendientes",
        "db/repositories/tender_fact_sheets.py::"
        "TenderFactSheetsRepository.list_pending_licitaciones",
        # Integridad de la cadena de hashes de auditoría (v26): es UNA
        # cadena global (no una por usuario) -- necesita leer la cola/COUNT
        # de audit_log sin filtrar por usuario para verificar continuidad.
        "db/audit.py::_assert_or_bootstrap_chain_state",
        # Verificación completa de la cadena -- GET /api/v1/security/audit/
        # verify, superficie de operaciones/seguridad (no un endpoint de
        # usuario final); recorre TODO audit_log en orden para detectar
        # manipulación, no puede acotarse a un usuario.
        "db/audit.py::verify_hash_chain",
        # log_action() repite inline la misma lectura de la cola de la cadena
        # que _assert_or_bootstrap_chain_state() (rama de fallback cuando
        # `audit_chain_state` todavía no existe, p. ej. BD pre-migración de
        # ese estado): `SELECT this_hash FROM audit_log ORDER BY id DESC
        # LIMIT 1`. Mismo razonamiento -- integridad de la cadena global, no
        # dato de un usuario. Detectado por este mismo test al ejecutarlo
        # (no estaba en el análisis manual previo): confirma que el escaneo
        # tiene dientes incluso para el propio autor del test.
        "db/audit.py::log_action",
    }
)

# Vaciado: ``remove_entry`` y ``update_frequency`` de ``db/watchlist.py`` ya
# exigen ``user_key`` y lo llevan en su predicado. Eran IDOR latentes —sin
# caller HTTP, pero a un endpoint de distancia— y el grupo no admite entradas
# nuevas: un hueco de aislamiento se corrige, no se documenta.
_KNOWN_GAPS_PENDING_FIX: frozenset[str] = frozenset()

_ALLOWLIST: frozenset[str] = _LEGITIMATE_SWEEPS | _KNOWN_GAPS_PENDING_FIX


def test_db_layer_queries_scope_by_user_key() -> None:
    """Todo SELECT/UPDATE/DELETE en ``db/*.py`` y ``db/repositories/*.py``
    contra una tabla user-scoped debe filtrar por ``user_key`` -- salvo la
    allowlist explícita documentada arriba."""
    found = _scan_files(_db_layer_files())

    nuevas = sorted(found - _ALLOWLIST)
    assert not nuevas, (
        "Query(s) nueva(s) sin predicado `user_key` contra tabla(s) "
        "user-scoped (ver AGENTS.md invariante de multi-tenencia y el "
        f"docstring de este archivo): {nuevas}"
    )

    obsoletas = sorted(_ALLOWLIST - found)
    assert not obsoletas, (
        "Entrada(s) en la allowlist que ya no corresponden a ninguna "
        f"violación real -- el ratchet solo puede encoger, bórralas: {obsoletas}"
    )


# ── Extensión: SQL fuera de db/ para watchlist_rules / user_notifications ──
# Ver nota "IMPORTANTE -- gap de cobertura" en el docstring del módulo.
_GRANDFATHERED_NON_DB_FILES: tuple[str, ...] = (
    "services/watchlist_rules.py",
    "services/notifications.py",
    "scheduler/watchlist_rules_alerts.py",
    "api/routes/watchlist_rules.py",
)

_GRANDFATHERED_LEGITIMATE_SWEEPS: frozenset[str] = frozenset(
    {
        # Carga TODAS las reglas activas para evaluarlas en cada corrida del
        # job (scheduler/watchlist_rules_alerts.py); análogo a
        # load_pending_digests de arriba.
        "scheduler/watchlist_rules_alerts.py::_load_active_rules",
        # Actualiza el timestamp de una regla usando un id que vino del
        # barrido global de arriba -- nunca de input de usuario final.
        "scheduler/watchlist_rules_alerts.py::_update_last_notified",
    }
)

_GRANDFATHERED_KNOWN_GAPS_PENDING_FIX: frozenset[str] = frozenset()

_GRANDFATHERED_ALLOWLIST: frozenset[str] = (
    _GRANDFATHERED_LEGITIMATE_SWEEPS | _GRANDFATHERED_KNOWN_GAPS_PENDING_FIX
)


def test_grandfathered_non_db_sql_scopes_by_user_key() -> None:
    """Cobertura para ``watchlist_rules``/``user_notifications``, cuyo SQL
    vive fuera de ``db/`` por la excepción TID251 grandfathered (ver
    docstring del módulo)."""
    paths = [_REPO_ROOT / rel for rel in _GRANDFATHERED_NON_DB_FILES]
    found = _scan_files(paths)

    nuevas = sorted(found - _GRANDFATHERED_ALLOWLIST)
    assert not nuevas, f"Query(s) nueva(s) sin predicado `user_key`: {nuevas}"

    obsoletas = sorted(_GRANDFATHERED_ALLOWLIST - found)
    assert not obsoletas, f"Entrada(s) de allowlist ya sin violación real (bórralas): {obsoletas}"
