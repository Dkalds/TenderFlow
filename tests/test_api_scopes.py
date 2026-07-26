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
