"""Scope taxonomy and request-to-scope authorization policy.

Sessions represent an interactive user and are authorized by the route's
resource ownership checks.  API keys are machine credentials, so every API-key
request must additionally satisfy a narrowly-defined scope.  Keeping this map
central prevents a newly-added ``require_any_auth`` route from accidentally
becoming reachable by a read-only key.
"""

from __future__ import annotations

from collections.abc import Iterable

_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Transitional aliases for keys issued before the scope taxonomy was made
# exhaustive.  They deliberately grant only their corresponding read surface;
# they never imply a write, account, or administrative capability.
_LEGACY_SCOPE_ALIASES: dict[str, frozenset[str]] = {
    "data:read": frozenset({"read:licitaciones", "licitaciones:read"}),
    "licitaciones:read": frozenset({"data:read", "read:licitaciones"}),
    "watchlist:read": frozenset({"read:watchlist"}),
}

# POST **de lectura** bajo /licitaciones: el cuerpo transporta criterios que no
# caben en query string (multi-CCAA, multi-tecnología, listas de hasta 100 ids),
# no un cambio de estado. Se enumeran uno a uno —y no por prefijo— para que la
# excepción no se contagie a un endpoint mutante que mañana cuelgue del mismo
# subárbol: ampliar esta lista tiene que ser una decisión, no un descuido.
_LICITACIONES_READ_POSTS: frozenset[str] = frozenset(
    {
        "/api/v1/licitaciones/search",
        "/api/v1/licitaciones/bulk-get",
    }
)


def required_scope_for_request(method: str, path: str) -> str:
    """Return the single least-privilege scope required for an API-key request."""
    normalized_path = path.rstrip("/") or "/"
    normalized_method = method.upper()

    # Account and credential management are never covered by generic data
    # scopes.  Account deletion additionally requires a recent cookie session
    # at the route level.
    if normalized_path == "/api/v1/me/data":
        return "account:read"
    if normalized_path == "/api/v1/me":
        return "account:delete" if normalized_method == "DELETE" else "account:read"
    if normalized_path.startswith("/api/v1/me/keys/rotate"):
        return "api_keys:rotate"
    if normalized_path.startswith("/api/v1/me/keys"):
        return "api_keys:read"
    if normalized_path.startswith("/api/v1/me/profile"):
        return "profile:read" if normalized_method in _READ_METHODS else "profile:write"
    if normalized_path.startswith("/api/v1/organizations"):
        return "pursuits:read" if normalized_method in _READ_METHODS else "pursuits:write"
    if normalized_path.startswith("/api/v1/pursuits"):
        return "pursuits:read" if normalized_method in _READ_METHODS else "pursuits:write"

    # Listing flags is useful to authenticated UI/API clients, but changing
    # rollout state is operationally sensitive and remains admin-only.
    if normalized_path.startswith("/api/v1/feature-flags"):
        return "feature_flags:read" if normalized_method in _READ_METHODS else "admin"

    # Shared operational resources require an admin-capable key in addition to
    # the database role check performed by their endpoints.
    if normalized_path.startswith(
        (
            "/api/v1/admin",
            "/api/v1/security",
            "/api/v1/webhooks",
        )
    ):
        return "admin"

    if normalized_path.startswith("/api/v1/ask"):
        return "ask:read"
    if normalized_path.startswith("/api/v1/exports"):
        return "exports:read"
    if normalized_path.startswith("/api/v1/analytics"):
        return "analytics:read"
    # /licitaciones no es un subárbol de solo lectura: bajo él vive
    # ``POST .../ficha-pliego/extract``, que descarga pliegos contra PLACSP,
    # extrae el PDF en un proceso aislado, llama al LLM y **sobrescribe** la
    # ficha vigente. Devolver ``licitaciones:read`` para cualquier verbo dejaba
    # esa mutación cara al alcance de ``data:read`` —el scope por defecto de
    # toda API key nueva y alias de ``licitaciones:read``, ver
    # ``_LEGACY_SCOPE_ALIASES``—. Se ramifica por método, como
    # watchlist/notifications/saved-filters, salvo los POST de lectura ya
    # publicados.
    if normalized_path.startswith("/api/v1/licitaciones"):
        if normalized_method in _READ_METHODS or normalized_path in _LICITACIONES_READ_POSTS:
            return "licitaciones:read"
        return "licitaciones:write"
    if normalized_path.startswith("/api/v1/empresas/reviews"):
        return "admin"
    if normalized_path.startswith("/api/v1/empresas"):
        return "empresas:read"
    if normalized_path.startswith("/api/v1/watchlist"):
        return "watchlist:read" if normalized_method in _READ_METHODS else "watchlist:write"
    if normalized_path.startswith("/api/v1/notifications"):
        return "notifications:read" if normalized_method in _READ_METHODS else "notifications:write"
    if normalized_path.startswith("/api/v1/saved-filters"):
        return "saved_filters:read" if normalized_method in _READ_METHODS else "saved_filters:write"
    if normalized_path.startswith("/api/v1/competitive"):
        return "competitive:read" if normalized_method in _READ_METHODS else "competitive:write"
    if normalized_path.startswith("/api/v1/feedback"):
        return "feedback:read" if normalized_method in _READ_METHODS else "feedback:write"
    if normalized_path.startswith("/api/v1/models"):
        return "models:read"

    return "data:read" if normalized_method in _READ_METHODS else "data:write"


def has_scope(scopes: Iterable[str], required_scope: str) -> bool:
    """Return whether *scopes* grants *required_scope* without wildcard aliases."""
    available = frozenset(scope.strip() for scope in scopes if scope and scope.strip())
    if "*" in available or required_scope in available:
        return True
    return bool(available & _LEGACY_SCOPE_ALIASES.get(required_scope, frozenset()))
