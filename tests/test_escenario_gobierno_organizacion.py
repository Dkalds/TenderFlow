"""Escenarios de gobierno de la organización: cómo decide y qué quedó escrito.

Recorridos completos por la API con sesión real. Ver ``tests/escenarios.py`` y
``docs/casos-de-uso.md``. Son lo que la consola hace desde Equipo ›
Organización (los pesos del go/no-go) y Equipo › Actividad (el rastro).
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta

from tests.escenarios import abrir_sesion, sembrar_licitacion


def _puntuar(sesion, pid: int, organizacion: int, criterio: str, puntuacion: int) -> dict:
    respuesta = sesion.put(
        f"/pursuits/{pid}/go-no-go",
        params={"organization_id": organizacion},
        json={"criterio": criterio, "puntuacion": puntuacion},
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def test_cu06_los_pesos_de_la_organizacion_cambian_la_recomendacion(client, api_db):
    """CU-06 — quien dirige pondera los criterios y la matriz los usa; un lector no.

    Encaje 4 y riesgo 1 con pesos iguales dan 2,5: por debajo del umbral. Si la
    organización decide que el encaje pesa el triple, la misma ficha da 3,25 y
    la recomendación cambia sin tocar las puntuaciones.
    """
    sembrar_licitacion("EXP-PESOS-1", "Soporte de la plataforma de expedientes")
    duena = abrir_sesion("pesos-duena@example.com", client)
    lectora = abrir_sesion("pesos-lectora@example.com")

    equipo = duena.post("/organizations", json={"name": "Preventa de Pruebas"})
    assert equipo.status_code == 201, equipo.text
    oid = equipo.json()["id"]
    alta = duena.post(
        f"/organizations/{oid}/members", json={"email": lectora.email, "role": "viewer"}
    )
    assert alta.status_code == 201, alta.text

    # De partida, los cinco criterios con el mismo peso y el umbral en 3.
    pesos = duena.get("/organizations/go-no-go/weights", params={"organization_id": oid})
    assert pesos.status_code == 200, pesos.text
    assert pesos.json()["umbral"] == 3
    assert {c["criterio"]: c["peso"] for c in pesos.json()["criterios"]} == {
        "encaje": 1,
        "capacidad": 1,
        "competencia": 1,
        "rentabilidad": 1,
        "riesgo": 1,
    }

    creada = duena.post("/pursuits", json={"licitacion_id": "EXP-PESOS-1", "organization_id": oid})
    assert creada.status_code == 201, creada.text
    pid = creada.json()["id"]
    _puntuar(duena, pid, oid, "encaje", 4)
    matriz = _puntuar(duena, pid, oid, "riesgo", 1)
    assert (matriz["total"], matriz["recomendacion"]) == (2.5, "no_go")

    # La lectora ve los pesos, pero no los cambia.
    assert (
        lectora.get("/organizations/go-no-go/weights", params={"organization_id": oid}).status_code
        == 200
    )
    vetada = lectora.put(
        "/organizations/go-no-go/weights",
        params={"organization_id": oid},
        json={"pesos": {"encaje": 9}},
    )
    assert vetada.status_code == 403, vetada.text

    # La dueña sube el encaje y solo cambia ese: el resto conserva su peso.
    guardada = duena.put(
        "/organizations/go-no-go/weights",
        params={"organization_id": oid},
        json={"pesos": {"encaje": 3}},
    )
    assert guardada.status_code == 200, guardada.text
    assert {c["criterio"]: c["peso"] for c in guardada.json()["criterios"]}["encaje"] == 3
    assert {c["criterio"]: c["peso"] for c in guardada.json()["criterios"]}["riesgo"] == 1

    recalculada = duena.get(f"/pursuits/{pid}/go-no-go", params={"organization_id": oid}).json()
    assert (recalculada["total"], recalculada["recomendacion"]) == (3.25, "go")


def test_cu31_rastro_de_la_organizacion_filtrar_paginar_y_exportar(client, api_db):
    """CU-32 — lo que cambió en la organización, quién lo hizo y llevárselo en CSV."""
    duena = abrir_sesion("rastro-duena@example.com", client)
    colega = abrir_sesion("rastro-colega@example.com")

    equipo = duena.post("/organizations", json={"name": "Auditoría de Pruebas"})
    assert equipo.status_code == 201, equipo.text
    oid = equipo.json()["id"]
    assert (
        duena.post(
            f"/organizations/{oid}/members", json={"email": colega.email, "role": "member"}
        ).status_code
        == 201
    )
    assert (
        duena.put(
            "/organizations/go-no-go/weights",
            params={"organization_id": oid},
            json={"pesos": {"rentabilidad": 2}},
        ).status_code
        == 200
    )

    # Del más reciente al más antiguo, con el actor por id y nunca por correo.
    rastro = duena.get(f"/organizations/{oid}/audit")
    assert rastro.status_code == 200, rastro.text
    entradas = rastro.json()["items"]
    tipos = [e["event_type"] for e in entradas]
    # El cambio de pesos es configuración de la organización: tiene que estar
    # en su rastro aunque se escribiera como `organization:<id>`.
    assert tipos[0] == "go_no_go.weights_updated"
    assert "org.member_added" in tipos
    assert {e["actor_user_id"] for e in entradas} == {duena.user_id}
    assert all(colega.email not in e["detail"] for e in entradas)

    # Página a página por cursor: sin repetir ni saltarse nada.
    primera = duena.get(f"/organizations/{oid}/audit", params={"limit": 1}).json()
    assert primera["has_more"] is True
    segunda = duena.get(
        f"/organizations/{oid}/audit", params={"limit": 1, "cursor": primera["next_cursor"]}
    ).json()
    assert [e["id"] for e in primera["items"] + segunda["items"]] == [e["id"] for e in entradas[:2]]

    # Un rango que no toca hoy no trae nada.
    ayer = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    assert duena.get(f"/organizations/{oid}/audit", params={"hasta": ayer}).json()["items"] == []

    # El CSV es la misma página, con el cursor de la siguiente en la cabecera.
    descarga = duena.get(f"/organizations/{oid}/audit", params={"formato": "csv", "limit": 1})
    assert descarga.status_code == 200, descarga.text
    assert descarga.headers["content-type"].startswith("text/csv")
    assert f"auditoria-org-{oid}.csv" in descarga.headers["content-disposition"]
    assert descarga.headers["x-next-cursor"] == primera["next_cursor"]
    (fila,) = list(csv.DictReader(io.StringIO(descarga.text)))
    assert fila["event_type"] == "go_no_go.weights_updated"

    # Un miembro que no administra no lo lee.
    assert colega.get(f"/organizations/{oid}/audit").status_code == 403
