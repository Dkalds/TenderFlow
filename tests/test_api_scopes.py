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


def test_el_resumen_es_lectura_aunque_lleve_path_param() -> None:
    """``POST /licitaciones/{id}/resumen`` sólo lee, y por eso no exige ``write``.

    Lee el anuncio y los fragmentos de pliego ya persistidos y los transforma en
    tokens: todos sus accesos van por ``connect_read`` y no hay ningún upsert.
    Que llame a un LLM y cueste dinero no lo convierte en escritura — el coste
    lo acotan el presupuesto por sujeto y el rate limit, que son otros
    mecanismos, y la ruta se autoprotege además con ``ask:read``.

    Hace falta un patrón y no la lista de igualdad porque el path lleva el
    identificador dentro, así que nunca podría casar por igualdad.
    """
    assert (
        required_scope_for_request("POST", "/api/v1/licitaciones/EXP-1/resumen")
        == "licitaciones:read"
    )
    # `id_externo` de PLACSP con barras (p.ej. `PA-S 2026/000058`): el `:path`
    # de la ruta las admite, y la excepción tiene que seguirlas admitiendo.
    assert (
        required_scope_for_request("POST", "/api/v1/licitaciones/PA-S 2026/000058/resumen")
        == "licitaciones:read"
    )


def test_la_extraccion_de_ficha_sigue_exigiendo_escritura() -> None:
    """La vecina de ``/resumen`` en el mismo subárbol sí muta, y no puede colarse.

    ``ficha-pliego/extract`` descarga documentos contra PLACSP, marca las filas
    de ``documentos`` y **sobrescribe la ficha vigente — incluso cuando la
    petición acaba en 502**. Es el hueco que motivó ramificar por verbo: con la
    regla anterior quedaba al alcance de ``data:read``, el scope por defecto de
    toda API key nueva.

    Por eso el patrón de ``/resumen`` va anclado en ``$`` y no es un prefijo.
    """
    assert (
        required_scope_for_request("POST", "/api/v1/licitaciones/EXP-1/ficha-pliego/extract")
        == "licitaciones:write"
    )
    # Una ruta mutante que colgara de un path con «resumen» dentro tampoco hereda.
    assert (
        required_scope_for_request("POST", "/api/v1/licitaciones/EXP-1/resumen/extract")
        == "licitaciones:write"
    )
    assert not has_scope(frozenset({"data:read"}), "licitaciones:write")
