"""Tests de ``db/solicitudes_acceso.py`` — CRUD de la cola de solicitudes."""

from __future__ import annotations

import pytest

from db.solicitudes_acceso import (
    actualizar_estado,
    contar_pendientes,
    crear_solicitud,
    listar_solicitudes,
)


def _crear(email: str = "ana@empresa.example", **extra) -> int:
    datos = {"empresa": None, "mensaje": None, "origen": None}
    datos.update(extra)
    return crear_solicitud(email=email, **datos)


def test_una_solicitud_nueva_nace_pendiente(api_db):
    solicitud_id = _crear(empresa="Empresa SL", origen="landing")

    fila = next(f for f in listar_solicitudes() if f["id"] == solicitud_id)
    assert fila["estado"] == "pendiente"
    assert fila["empresa"] == "Empresa SL"
    assert fila["origen"] == "landing"


def test_contar_pendientes_solo_cuenta_lo_que_espera_revision(api_db):
    primera = _crear("a@e.example")
    _crear("b@e.example")
    assert contar_pendientes() == 2

    actualizar_estado(primera, "atendida")

    assert contar_pendientes() == 1


def test_listar_filtra_por_estado(api_db):
    atendida = _crear("a@e.example")
    _crear("b@e.example")
    actualizar_estado(atendida, "atendida")

    assert [f["id"] for f in listar_solicitudes(estado="atendida")] == [atendida]
    assert atendida not in [f["id"] for f in listar_solicitudes(estado="pendiente")]


def test_actualizar_una_solicitud_inexistente_devuelve_false(api_db):
    assert actualizar_estado(999_999, "atendida") is False


def test_un_estado_fuera_del_conjunto_no_llega_a_la_consulta(api_db):
    """El CHECK de la tabla lo rechazaría igual; esto falla antes y más claro."""
    solicitud_id = _crear()

    with pytest.raises(ValueError, match="estado no válido"):
        actualizar_estado(solicitud_id, "aprobada")
