"""Glosario y tools de esquema del MCP: lo que no necesita Postgres (unitarios)."""

from __future__ import annotations

import re

import pytest

from mcp_server.catalogo import tablas_visibles
from mcp_server.tools import ErrorHerramienta
from mcp_server.tools.esquema import describir_tabla, ejemplos_sql_del_glosario, glosario


@pytest.mark.parametrize(
    "tabla",
    ['users"; --', "api_keys", "pg_shadow", "LICITACIONES", "", "mcp_oauth_tokens"],
)
def test_describir_tabla_rechaza_fuera_de_catalogo(tabla: str) -> None:
    with pytest.raises(ErrorHerramienta) as e:
        describir_tabla(tabla)
    assert "describir_esquema" in (e.value.pista or "")


def test_el_error_lista_las_tablas_validas_y_no_repite_basura() -> None:
    hostil = "x" * 5_000
    with pytest.raises(ErrorHerramienta) as e:
        describir_tabla(hostil)
    assert "licitaciones" in (e.value.pista or "")
    assert hostil not in e.value.mensaje
    assert len(e.value.mensaje) < 300


def test_glosario_no_vacio_y_cubre_canonica_e_importe() -> None:
    g = glosario()
    assert "canónica" in g
    assert "importe" in g


def test_glosario_cubre_los_puntos_del_brief() -> None:
    g = glosario()
    for fragmento in (
        "licitaciones_duplicados",
        "importe_adjudicado",
        "importe_tipo",
        "con_iva",
        "estado",
        "id_externo",
        "NIF",
        "DIR3",
        "organization_id",
        "pursuit",
        "tecnologia",
        "text",
    ):
        assert fragmento in g, fragmento


def test_glosario_es_compacto_y_se_lee_una_sola_vez() -> None:
    assert len(glosario().splitlines()) < 250
    assert glosario() is glosario()


def test_ejemplos_del_glosario_solo_tocan_tablas_visibles() -> None:
    visibles = {e.tabla for e in tablas_visibles()}
    ejemplos = ejemplos_sql_del_glosario()
    assert len(ejemplos) >= 6
    for sql in ejemplos:
        tablas = re.findall(r"\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)", sql, flags=re.IGNORECASE)
        assert tablas, sql
        for t in tablas:
            # CTEs del propio ejemplo (WITH x AS …) no son tablas.
            if re.search(rf"\bWITH\s+{t}\b|,\s*{t}\s+AS\b", sql):
                continue
            assert t in visibles, f"{t} no es visible en: {sql}"
