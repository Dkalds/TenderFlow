"""SQL del rol del MCP en ``db/mcp_rol.py``: generación pura, sin BD.

La política real (qué tablas salen) la cubren ``test_mcp_catalogo.py`` y su
versión de integración; aquí, el contrato de las funciones de ``db/``.
"""

from __future__ import annotations

import pytest

from db.mcp_rol import sentencias_grants, sentencias_rol


def test_grants_tabla_entera_o_por_columnas() -> None:
    sentencias = sentencias_grants("rol_x", "public", [("a", None), ("b", ("c1", "c2"))], "pol_x")

    assert 'GRANT SELECT ON "public"."a" TO "rol_x"' in sentencias
    assert 'GRANT SELECT ("c1", "c2") ON "public"."b" TO "rol_x"' in sentencias


def test_grants_comprueban_tablas_y_crean_la_politica_indicada() -> None:
    sentencias = sentencias_grants("rol_x", "public", [("a", None), ("b", None)], "pol_x")

    assert "ARRAY['a', 'b']" in sentencias[0]
    assert sentencias[1] == 'REVOKE ALL ON ALL TABLES IN SCHEMA "public" FROM "rol_x"'
    assert "CREATE POLICY pol_x ON %I.%I FOR SELECT TO %I USING (true)" in sentencias[-1]
    assert "policyname = 'pol_x' AND 'rol_x' = ANY (roles)" in sentencias[-1]


@pytest.mark.parametrize(
    ("tablas", "politica"),
    [
        pytest.param([("a'; DROP TABLE x; --", None)], "pol", id="tabla"),
        pytest.param([("a", ('c"; --',))], "pol", id="columna"),
        pytest.param([("a", None)], "pol'; --", id="politica"),
        pytest.param([("A", None)], "pol", id="mayusculas"),
    ],
)
def test_grants_rechazan_identificadores_fuera_de_la_lista_blanca(
    tablas: list[tuple[str, tuple[str, ...] | None]], politica: str
) -> None:
    with pytest.raises(ValueError, match="Identificador SQL no válido"):
        sentencias_grants("rol_x", "public", tablas, politica)


def test_rol_rechaza_identificador_con_comilla() -> None:
    with pytest.raises(ValueError, match="Identificador SQL no válido"):
        sentencias_rol("rol'x")
