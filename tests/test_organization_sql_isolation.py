"""Test de arquitectura: las rutas nunca resuelven organización por su cuenta.

Contexto (auditoría de multi-tenencia, AGENTS.md invariante §3.4/§3.10,
hermano de ``test_user_key_sql_isolation.py``): hasta esta corrección, 6 de
los 7 route files que aceptan ``organization_id`` solo llamaban a
``resolve_organization`` (``services/organizations.py``) dentro de
``if organization_id is not None:`` -- omitir el parámetro (el default del
cliente) saltaba la resolución entera y dejaba pasar ``None`` hasta el
repositorio, que en ese caso cae a una query sin filtro de organización (o,
en ``db/saved_filters.py::delete_saved_filter``, sin predicado alguno).

A diferencia del ratchet de ``user_key`` -- que escanea literales SQL en
``db/*.py`` buscando un predicado ausente --, el bug de organización no vive
en el SQL: ``resolve_organization`` ya sabe caer correctamente a la
organización personal del usuario cuando se le pasa ``None`` explícitamente
(ver su docstring). El bug vivía en la CAPA DE RUTAS, que decidía si
llamarla en absoluto. Clonar literalmente el escáner de SQL produciría una
allowlist enorme y sin valor real: servicios legítimos (export GDPR en
``services/gdpr.py``, el motor de scoring en
``services/analytics/scoring.py``, tests unitarios de CRUD) llaman a
``services/watchlist_rules.py``/``services/notifications.py``/
``db/repositories/user_profiles.py``/etc. con ``organization_id=None`` a
propósito, para leer TODOS los datos de un usuario sin importar la
organización -- eso no es el bug, es una capacidad necesaria.

El invariante real y verificable es: **ningún route file importa
``resolve_organization`` directamente** -- todos pasan por
``api/tenancy.py`` (``require_organization``/``resolve_organization_ctx``),
que la llama incondicionalmente (nunca solo "si el cliente lo mandó").
``api/tenancy.py`` es el único punto de confianza; cualquier nuevo import
directo en una ruta reintroduce exactamente la clase de bug que ya se dio
independientemente en 6 archivos distintos.

``services/pursuits.py`` también importa y llama a ``resolve_organization``
directamente (siempre incondicional -- el patrón correcto, anterior a esta
corrección), pero vive en ``services/``, no en ``api/routes/``, así que este
test no lo escanea: no es donde se demostró el bug ni donde un nuevo route
handler podría reintroducirlo.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ROUTES_DIR = _REPO_ROOT / "api" / "routes"

_BANNED_MODULE = "services.organizations"
_BANNED_NAME = "resolve_organization"

# ── Allowlist: SOLO puede encoger (mismo espíritu que TID251 /
# check_openapi_contract.py / test_user_key_sql_isolation.py). Vacía porque
# los 7 route files que necesitaban resolve_organization ya migraron a
# api/tenancy.py -- cualquier entrada nueva aquí es una regresión real, no
# una excepción legítima que documentar.
_ALLOWLIST: frozenset[str] = frozenset()


def _route_files() -> list[Path]:
    return sorted(p for p in _ROUTES_DIR.glob("*.py") if p.name != "__init__.py")


def _imports_resolve_organization_directly(path: Path) -> bool:
    """True si el archivo importa ``resolve_organization`` desde
    ``services.organizations`` -- el único símbolo que debe pasar siempre
    por ``api/tenancy.py`` en vez de resolverse a mano en una ruta."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == _BANNED_MODULE
            and any(alias.name == _BANNED_NAME for alias in node.names)
        ):
            return True
    return False


def test_routes_never_import_resolve_organization_directly() -> None:
    """``resolve_organization`` solo debe importarse desde ``api/tenancy.py``.

    Un import directo en ``api/routes/*.py`` es la firma exacta del bug que
    corrigió esta ola: permite (re)implementar la resolución de organización
    a mano, con el riesgo de volver a hacerla condicional a que el cliente
    la pida ("if organization_id is not None"), que es como una petición sin
    ``organization_id`` terminaba saltándose el filtro por completo.
    """
    found = {
        path.relative_to(_REPO_ROOT).as_posix()
        for path in _route_files()
        if _imports_resolve_organization_directly(path)
    }

    nuevas = sorted(found - _ALLOWLIST)
    assert not nuevas, (
        "Ruta(s) que importan resolve_organization directamente en vez de "
        "pasar por api/tenancy.py (require_organization/"
        f"resolve_organization_ctx) -- ver docstring de este archivo: {nuevas}"
    )

    obsoletas = sorted(_ALLOWLIST - found)
    assert not obsoletas, (
        "Entrada(s) en la allowlist que ya no corresponden a ninguna "
        f"violación real -- el ratchet solo puede encoger, bórralas: {obsoletas}"
    )


def test_tenancy_dependency_resolves_unconditionally() -> None:
    """``api/tenancy.py`` debe llamar a resolve_organization sin guardarla
    tras un ``if ... is not None``, para las dos rutas de uso (Query en
    ``require_organization``, body en ``resolve_organization_ctx``).

    Verificación estructural mínima -- no un intérprete de flujo de control
    completo: confirma que la ÚNICA llamada a resolve_organization en el
    módulo vive directamente en el cuerpo de ``resolve_organization_ctx``
    (no anidada dentro de un ``ast.If``), que es de donde beben ambas rutas
    de uso.
    """
    tenancy_path = _REPO_ROOT / "api" / "tenancy.py"
    tree = ast.parse(tenancy_path.read_text(encoding="utf-8"), filename=str(tenancy_path))

    target_fn: ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "resolve_organization_ctx":
            target_fn = node
            break
    assert target_fn is not None, "resolve_organization_ctx no encontrada en api/tenancy.py"

    def _references_resolve_organization(node: ast.AST) -> bool:
        # ``resolve_organization`` se invoca vía ``run_db(resolve_organization,
        # ...)`` -- pasada por referencia como argumento, no como
        # ``resolve_organization(...)`` directo -- así que basta con
        # localizar el ``Name`` en cualquier posición, no solo como función
        # de un ``Call``.
        return isinstance(node, ast.Name) and node.id == _BANNED_NAME

    def _contains_reference_outside_if(node: ast.AST) -> bool:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If):
                continue
            if _references_resolve_organization(child) or _contains_reference_outside_if(child):
                return True
        return False

    assert _contains_reference_outside_if(target_fn), (
        "resolve_organization_ctx ya no llama a resolve_organization fuera de "
        "un `if` -- si la resolución volvió a hacerse condicional, una "
        "petición sin organization_id explícito puede volver a saltarse la "
        "frontera de organización."
    )
