"""``describir_esquema`` / ``describir_tabla`` contra Postgres con el rol del MCP."""

from __future__ import annotations

import json
from typing import Any

import pytest

from db.consulta_libre import (
    ErrorConsulta,
    JSONValue,
    claves_foraneas_de,
    columnas_de,
    ejecutar_select,
    ejemplo_de,
    filas_aproximadas,
)
from mcp_server.catalogo import DOMINIOS, Visibilidad, tablas_visibles
from mcp_server.tools.esquema import (
    describir_esquema,
    describir_tabla,
    ejemplos_sql_del_glosario,
    glosario,
)


def _dict(valor: JSONValue) -> dict[str, JSONValue]:
    assert isinstance(valor, dict)
    return valor


def _lista(valor: JSONValue) -> list[JSONValue]:
    assert isinstance(valor, list)
    return valor


def _nombres_de_columnas(d: dict[str, JSONValue]) -> set[str]:
    return {str(_dict(c)["nombre"]) for c in _lista(d["columnas"])}


def _tablas_listadas() -> set[str]:
    return {
        str(_dict(t)["tabla"])
        for dominio in _lista(describir_esquema()["dominios"])
        for t in _lista(_dict(dominio)["tablas"])
    }


def test_describir_esquema_lista_solo_visibles(rol_mcp: str) -> None:
    nombres = _tablas_listadas()
    assert "licitaciones" in nombres
    assert "api_keys" not in nombres
    assert nombres == {e.tabla for e in tablas_visibles()}


def test_describir_esquema_forma_y_glosario(rol_mcp: str) -> None:
    esquema = describir_esquema()
    assert esquema["glosario"] == glosario()
    dominios = [_dict(d) for d in _lista(esquema["dominios"])]
    orden = [d["dominio"] for d in dominios]
    assert orden == [d for d in DOMINIOS if d in orden]
    for d in dominios:
        for t in _lista(d["tablas"]):
            tabla = _dict(t)
            assert set(tabla) == {"tabla", "descripcion", "filas_aprox"}
            filas = tabla["filas_aprox"]
            assert isinstance(filas, int) and filas >= 0
    json.dumps(esquema)


def test_describir_tabla_users_sin_password_hash(rol_mcp: str) -> None:
    d = describir_tabla("users")
    assert "password_hash" not in _nombres_de_columnas(d)
    assert "password_hash" not in _lista(_dict(d["ejemplo"])["columnas"])


def test_describir_tabla_nunca_muestra_columnas_excluidas(rol_mcp: str) -> None:
    revisadas = 0
    for entrada in tablas_visibles():
        if entrada.visibilidad is not Visibilidad.COLUMNAS_EXCLUIDAS:
            continue
        d = describir_tabla(entrada.tabla)
        nombres = _nombres_de_columnas(d)
        assert nombres, entrada.tabla
        assert nombres <= set(entrada.columnas_permitidas), entrada.tabla
        assert not nombres & set(entrada.columnas_excluidas), entrada.tabla
        columnas_ejemplo = {str(c) for c in _lista(_dict(d["ejemplo"])["columnas"])}
        assert columnas_ejemplo == nombres, entrada.tabla
        revisadas += 1
    assert revisadas >= 3


def test_describir_tabla_licitaciones_con_ejemplo(rol_mcp: str, tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        c.executemany(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) VALUES (%s, %s, %s)",
            [(f"LIC-ESQ-{i}", f"Expediente {i}", "2026-09-01T00:00:00+00:00") for i in range(5)],
        )
    d = describir_tabla("licitaciones")
    assert d["tabla"] == "licitaciones"
    assert d["dominio"] == "Licitaciones y fuente"
    assert d["descripcion"]
    por_nombre = {str(_dict(c)["nombre"]): _dict(c) for c in _lista(d["columnas"])}
    assert por_nombre["id_externo"]["nulo"] is False
    assert por_nombre["importe"]["nulo"] is True
    assert por_nombre["importe"]["tipo"] == "double precision"
    ejemplo = _dict(d["ejemplo"])
    assert ejemplo["n_filas"] == 3
    assert ejemplo["truncado"] is False
    assert "id_externo" in _lista(ejemplo["columnas"])
    json.dumps(d)


def test_describir_tabla_claves_foraneas(rol_mcp: str) -> None:
    fks = _lista(describir_tabla("adjudicaciones")["claves_foraneas"])
    esperada: JSONValue = {
        "columna": "licitacion_id",
        "tabla_destino": "licitaciones",
        "columna_destino": "id_externo",
    }
    assert esperada in fks


def test_las_fk_hacia_tablas_ocultas_no_se_muestran(rol_mcp: str) -> None:
    visibles = {e.tabla for e in tablas_visibles()}
    for e in tablas_visibles():
        for fk in _lista(describir_tabla(e.tabla)["claves_foraneas"]):
            assert _dict(fk)["tabla_destino"] in visibles


def test_introspeccion_no_interpola_el_nombre(rol_mcp: str) -> None:
    hostil = 'users"; DROP TABLE users; --'
    assert columnas_de(hostil) == []
    assert claves_foraneas_de(hostil) == []
    assert filas_aproximadas([hostil]) == {hostil: 0}
    with pytest.raises(ErrorConsulta):
        ejemplo_de(hostil, ["id"])
    with pytest.raises(ErrorConsulta):
        ejemplo_de("users", ['id" FROM users; --'])


def test_columnas_de_respeta_los_privilegios_del_rol(rol_mcp: str) -> None:
    nombres = {str(c["nombre"]) for c in columnas_de("users")}
    assert "id" in nombres
    assert "password_hash" not in nombres


def test_filas_aproximadas_nunca_negativas(rol_mcp: str) -> None:
    r = filas_aproximadas(["licitaciones", "adjudicaciones"])
    assert set(r) == {"licitaciones", "adjudicaciones"}
    assert all(v >= 0 for v in r.values())


def test_ejemplo_de_acota_a_tres_filas(rol_mcp: str, tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        c.executemany(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) VALUES (%s, %s, %s)",
            [(f"LIC-EJ-{i}", "t", "2026-09-01T00:00:00+00:00") for i in range(10)],
        )
    r = ejemplo_de("licitaciones", ["id_externo", "titulo"])
    assert r.columnas == ["id_externo", "titulo"]
    assert r.n_filas == 3


def test_los_ejemplos_del_glosario_se_ejecutan_con_el_rol_mcp(rol_mcp: str) -> None:
    """Cada ejemplo SQL del glosario es válido contra el esquema real y visible."""
    ejemplos = ejemplos_sql_del_glosario()
    assert len(ejemplos) >= 10
    for sql in ejemplos:
        try:
            ejecutar_select(sql)
        except ErrorConsulta as exc:
            pytest.fail(f"{exc.sqlstate}: {exc.mensaje}\n{sql}")


def test_describir_tabla_funciona_en_todas_las_tablas_visibles(rol_mcp: str) -> None:
    """Ninguna tabla visible (tipos raros incluidos) tumba la tool ni deja el ejemplo vacío."""
    for entrada in tablas_visibles():
        d = describir_tabla(entrada.tabla)
        assert _nombres_de_columnas(d), entrada.tabla
        json.dumps(d)
