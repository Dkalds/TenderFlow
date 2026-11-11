"""Scope taxonomy and request-to-scope authorization policy.

Sessions represent an interactive user and are authorized by the route's
resource ownership checks.  API keys are machine credentials, so every API-key
request must additionally satisfy a narrowly-defined scope.  Keeping this map
central prevents a newly-added ``require_any_auth`` route from accidentally
becoming reachable by a read-only key.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

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

# La misma excepción para los POST de lectura que llevan **path param**, que por
# construcción no pueden casar contra el conjunto de arriba: se compara por
# igualdad y su path lleva un identificador dentro.
#
# Sólo hay uno, y su clasificación se verificó siguiendo el handler hasta la BD:
# `/resumen` (api/routes/ask.py) lee el anuncio y los fragmentos de pliego ya
# persistidos y los transforma en tokens; todos sus accesos van por
# `connect_read` y no hay ningún upsert — su propio docstring declara «sin
# caché». Que llame a un LLM y cueste dinero no lo hace escritura: ese coste lo
# acotan el presupuesto por sujeto y el rate limit, que son otros mecanismos. Y
# la ruta ya se autoprotege además con `_check_ask_scope`, que exige `ask:read`.
#
# El patrón termina anclado en `/resumen$` **a propósito**: su vecina
# `/{id}/ficha-pliego/extract` cuelga del mismo subárbol y sí muta —escribe en
# `documentos`, `tender_fact_sheets` y las señales de tecnología, y sobrescribe
# la ficha vigente incluso cuando la petición acaba en 502—, así que un patrón
# por prefijo la habría dejado al alcance de `data:read`, el scope por defecto
# de toda API key nueva. Es justo el hueco que ramificar por verbo cerraba.
_LICITACIONES_READ_POST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/api/v1/licitaciones/.+/resumen$"),
)

# Sub-rutas bajo `/licitaciones/{id}` que cruzan el anuncio con la capacidad,
# el NIF o el historial de oportunidades (`pursuits`) de la organización activa:
# pertenecen al tablero (`pursuits:read`), no al `licitaciones:read` que hereda
# toda API key por defecto (`data:read`).
_LICITACIONES_PURSUITS_GET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^/api/v1/licitaciones/.+/(?:checklist|historial-propio|dossier\.pdf|competencia-esperada)$"
    ),
)

# El rastro de auditoría de una organización (``GET /organizations/{id}/audit``)
# es la superficie más sensible del subárbol: enumera quién hizo qué. Que una
# API key de lectura del tablero (``pursuits:read``, lo que recibe cualquier
# clave que lea oportunidades) lo alcanzara sería conceder más de lo que el
# dueño creyó dar, así que tiene scope propio y se resuelve **antes** que el
# prefijo genérico de ``/organizations``. Lleva el id en medio del path, así
# que se casa por regex, como los POST de lectura de ``/licitaciones``.
_ORGANIZATION_AUDIT_PATTERN: re.Pattern[str] = re.compile(r"^/api/v1/organizations/[^/]+/audit$")


def _es_post_de_lectura_de_licitaciones(path: str) -> bool:
    """¿Este POST bajo /licitaciones sólo lee?

    Dos mecanismos porque hay dos formas de path: literal (igualdad, barato) y
    con parámetro (regex). Ninguno es un prefijo, para que la excepción no se
    contagie a un endpoint mutante que mañana cuelgue del mismo subárbol.
    """
    return path in _LICITACIONES_READ_POSTS or any(
        patron.match(path) for patron in _LICITACIONES_READ_POST_PATTERNS
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
    if normalized_path == "/api/v1/auth/logout-all":
        return "account:write"
    if normalized_path.startswith("/api/v1/me/keys/rotate"):
        return "api_keys:rotate"
    if normalized_path.startswith("/api/v1/me/keys"):
        return "api_keys:read"
    if normalized_path.startswith("/api/v1/me/profile"):
        return "profile:read" if normalized_method in _READ_METHODS else "profile:write"
    if normalized_path.startswith("/api/v1/me/notification-preferences"):
        return "notifications:read" if normalized_method in _READ_METHODS else "notifications:write"
    if normalized_path.startswith("/api/v1/me/"):
        return "account:read" if normalized_method in _READ_METHODS else "account:write"
    if _ORGANIZATION_AUDIT_PATTERN.match(normalized_path):
        return "audit:read"
    if normalized_path.startswith("/api/v1/organizations"):
        if normalized_method in _READ_METHODS:
            return "pursuits:read"
        # Escribir bajo /organizations es administrar el equipo (miembros,
        # invitaciones, traspaso de propiedad, NIF, plantillas, salir): con
        # `pursuits:write`, la clave que un integrador de CRM necesita para
        # mover oportunidades, un robo de esa clave bastaba para añadir
        # miembros. Los pesos del go/no-go son configuración del tablero y se
        # quedan donde estaban.
        if normalized_path.startswith("/api/v1/organizations/go-no-go"):
            return "pursuits:write"
        return "organizations:manage"
    # `/cuentas` y `/etiquetas` no son datos públicos: `GET /cuentas/{id}`
    # devuelve el bloque `oportunidades` (estado, `next_action`, responsable)
    # que `/pursuits` protege con `pursuits:read`. Caer en el `data:*` de abajo
    # —el scope por defecto de toda clave nueva— saltaba esa protección.
    if normalized_path.startswith(("/api/v1/pursuits", "/api/v1/cuentas", "/api/v1/etiquetas")):
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
        if normalized_method in _READ_METHODS and any(
            patron.match(normalized_path) for patron in _LICITACIONES_PURSUITS_GET_PATTERNS
        ):
            return "pursuits:read"
        if normalized_method in _READ_METHODS or _es_post_de_lectura_de_licitaciones(
            normalized_path
        ):
            return "licitaciones:read"
        return "licitaciones:write"
    if normalized_path == "/api/v1/search/global":
        return "pursuits:read"
    if normalized_path.startswith("/api/v1/empresas/reviews"):
        return "admin"
    if normalized_path.startswith("/api/v1/empresas"):
        return "empresas:read"
    if normalized_path.startswith("/api/v1/watchlist"):
        return "watchlist:read" if normalized_method in _READ_METHODS else "watchlist:write"
    # `/follows` (ADR-031) reutiliza los scopes de watchlist y no estrena par
    # propio: es la misma capacidad —«lo que este usuario sigue»— vista desde
    # una sola tabla. Una API key que hoy puede leer favoritos no debería tener
    # que pedir permiso otra vez para leer los mismos favoritos por la ruta
    # nueva, y una que no puede escribirlos no puede escribirlos por aquí.
    if normalized_path.startswith("/api/v1/follows"):
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


def scopes_del_principal(principal: Mapping[str, object]) -> frozenset[str]:
    """Scopes de la API key del principal, sea cual sea la forma en que lleguen."""
    crudos = principal.get("scopes", "")
    if isinstance(crudos, str):
        return frozenset(scope.strip() for scope in crudos.split(",") if scope.strip())
    if isinstance(crudos, (set, frozenset, list, tuple)):
        return frozenset(str(scope).strip() for scope in crudos if str(scope).strip())
    return frozenset()


def organizacion_para_citas(principal: Mapping[str, object]) -> int | None:
    """Organización cuyos documentos propios puede citar una respuesta, o ``None``.

    Una sesión cita los de su organización activa. Una API key solo si además
    puede leer oportunidades (``pursuits:read``): los adjuntos cuelgan de
    ellas, y ni ``ask:read`` ni ``licitaciones:write`` los abrían hasta ADR-040.
    Lo usan las dos superficies que enseñan esas citas: ``/ask`` y el guion.
    """
    organizacion = principal.get("organization_id")
    if not isinstance(organizacion, int) or isinstance(organizacion, bool):
        return None
    if principal.get("auth_method") == "api_key" and not has_scope(
        scopes_del_principal(principal), "pursuits:read"
    ):
        return None
    return organizacion
