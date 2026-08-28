"""Regression tests for the centralized API-key authorization policy."""

from __future__ import annotations

from api.scopes import has_scope, required_scope_for_request


def test_sensitive_routes_require_explicit_scopes() -> None:
    assert required_scope_for_request("GET", "/api/v1/me/data") == "account:read"
    assert required_scope_for_request("DELETE", "/api/v1/me") == "account:delete"
    assert required_scope_for_request("POST", "/api/v1/me/keys/rotate") == "api_keys:rotate"
    assert required_scope_for_request("POST", "/api/v1/webhooks") == "admin"
    assert required_scope_for_request("GET", "/api/v1/feature-flags") == "feature_flags:read"
    assert required_scope_for_request("PUT", "/api/v1/feature-flags") == "admin"
    assert required_scope_for_request("POST", "/api/v1/empresas/reviews/42/resolve") == "admin"


def test_read_scope_never_implies_write_scope() -> None:
    assert required_scope_for_request("GET", "/api/v1/watchlist/items") == "watchlist:read"
    assert required_scope_for_request("POST", "/api/v1/watchlist/items") == "watchlist:write"
    assert not has_scope(frozenset({"watchlist:read"}), "watchlist:write")


def test_legacy_aliases_are_read_only() -> None:
    assert has_scope(frozenset({"data:read"}), "licitaciones:read")
    assert not has_scope(frozenset({"data:read"}), "data:write")


def test_licitaciones_branches_by_method() -> None:
    """El subárbol /licitaciones no es de solo lectura.

    ``POST .../ficha-pliego/extract`` descarga pliegos contra PLACSP, extrae
    PDF y llama al LLM antes de sobrescribir la ficha vigente; con la rama sin
    ramificar pedía ``licitaciones:read`` como cualquier GET.
    """
    assert required_scope_for_request("GET", "/api/v1/licitaciones") == "licitaciones:read"
    assert (
        required_scope_for_request("GET", "/api/v1/licitaciones/ABC-1/ficha-pliego")
        == "licitaciones:read"
    )
    assert (
        required_scope_for_request("POST", "/api/v1/licitaciones/ABC-1/ficha-pliego/extract")
        == "licitaciones:write"
    )


def test_default_api_key_scope_cannot_reach_the_extract_route() -> None:
    """Mecanismo exacto del 403 de ``api/auth.py``: ``data:read`` —el scope por
    defecto de toda API key nueva— es alias de ``licitaciones:read`` y no debe
    alcanzar la ruta mutante y cara."""
    for scopes in (frozenset({"data:read"}), frozenset({"licitaciones:read"})):
        assert not has_scope(scopes, "licitaciones:write")


def test_read_only_posts_of_licitaciones_stay_readable() -> None:
    """``search`` y ``bulk-get`` son POST porque el criterio no cabe en query
    string, no porque muten nada: son superficie pública documentada y exigirles
    ``licitaciones:write`` las rompería sin cerrar ningún hueco."""
    assert required_scope_for_request("POST", "/api/v1/licitaciones/search") == "licitaciones:read"
    assert (
        required_scope_for_request("POST", "/api/v1/licitaciones/bulk-get") == "licitaciones:read"
    )
    assert has_scope(frozenset({"data:read"}), "licitaciones:read")


def test_licitaciones_write_has_no_legacy_alias() -> None:
    """La excepción de ``search``/``bulk-get`` se compara por igualdad exacta:
    ninguna ruta que cuelgue de ellas hereda el permiso de lectura."""
    assert (
        required_scope_for_request("POST", "/api/v1/licitaciones/search/reindex")
        == "licitaciones:write"
    )
    assert not has_scope(frozenset({"read:licitaciones"}), "licitaciones:write")
