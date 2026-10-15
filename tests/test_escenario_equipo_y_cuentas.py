"""Escenarios de cuentas objetivo, equipo y cuenta propia.

Recorridos completos por la API con sesión real. Ver ``tests/escenarios.py`` y
``docs/casos-de-uso.md``.
"""

from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient

from tests.escenarios import PASSWORD, abrir_sesion, sembrar_licitacion


def test_cu11_cuenta_objetivo_del_organo_a_su_ficha(client, api_db):
    """CU-11 — buscar un órgano, convertirlo en cuenta, leer su ficha y soltarla."""
    organo = "Consejería de Hacienda de Pruebas"
    sembrar_licitacion("EXP-CTA-1", "Soporte SAP", organo_contratacion=organo)
    sembrar_licitacion("EXP-CTA-2", "Licencias SAP", organo_contratacion=organo)
    sembrar_licitacion("EXP-CTA-3", "Limpieza", organo_contratacion="Otro órgano cualquiera")
    sesion = abrir_sesion("cuentas@example.com", client)

    candidatos = sesion.get("/cuentas/buscar-organos", params={"q": "Hacienda"})
    assert candidatos.status_code == 200, candidatos.text
    (candidato,) = candidatos.json()
    assert candidato["organo_nombre"] == organo
    assert candidato["expedientes"] == 2
    assert candidato["cuenta_id"] is None

    creada = sesion.post("/cuentas", json={"organo": organo, "nombre": "Hacienda"})
    assert creada.status_code == 201, creada.text
    cid = creada.json()["id"]

    # El buscador ya sabe que ese órgano es de una cuenta.
    (candidato,) = sesion.get("/cuentas/buscar-organos", params={"q": "Hacienda"}).json()
    assert candidato["cuenta_id"] == cid

    ficha = sesion.get(f"/cuentas/{cid}")
    assert ficha.status_code == 200, ficha.text
    assert ficha.json()["cuenta"]["nombre"] == "Hacienda"

    anotada = sesion.patch(f"/cuentas/{cid}", json={"nota": "Renueva soporte cada dos años"})
    assert anotada.status_code == 200, anotada.text
    (cuenta,) = sesion.get("/cuentas").json()
    assert cuenta["nota"] == "Renueva soporte cada dos años"

    resumen = sesion.get("/cuentas/resumen")
    assert resumen.status_code == 200, resumen.text
    assert [f["cuenta_id"] for f in resumen.json()["filas"]] == [cid]

    assert sesion.delete(f"/cuentas/{cid}").status_code == 204
    assert sesion.get("/cuentas").json() == []
    assert sesion.get(f"/cuentas/{cid}").status_code == 404


def test_cu12_equipo_invitar_colaborar_y_retirar_el_acceso(client, api_db):
    """CU-12 — una organización de dos: el rol decide qué puede hacer cada una."""
    sembrar_licitacion("EXP-EQ-1", "Portal del empleado SAP")
    duena = abrir_sesion("duena@example.com", client)
    colega = abrir_sesion("colega@example.com")

    equipo = duena.post("/organizations", json={"name": "Consultora de Pruebas"})
    assert equipo.status_code == 201, equipo.text
    oid = equipo.json()["id"]

    # Antes de invitarla, la organización no existe para la colega.
    assert colega.get("/pursuits", params={"organization_id": oid}).status_code == 403

    invitada = duena.post(
        f"/organizations/{oid}/members", json={"email": colega.email, "role": "viewer"}
    )
    assert invitada.status_code == 201, invitada.text
    miembros = duena.get(f"/organizations/{oid}/members").json()
    assert {m["email"]: m["role"] for m in miembros} == {
        duena.email: "owner",
        colega.email: "viewer",
    }

    oportunidad = duena.post(
        "/pursuits", json={"licitacion_id": "EXP-EQ-1", "organization_id": oid}
    )
    assert oportunidad.status_code == 201, oportunidad.text
    pid = oportunidad.json()["id"]

    # Como lectora ve la oportunidad, pero no la mueve.
    vista = colega.get(f"/pursuits/{pid}", params={"organization_id": oid})
    assert vista.status_code == 200, vista.text
    intento = colega.patch(
        f"/pursuits/{pid}", params={"organization_id": oid}, json={"status": "qualifying"}
    )
    assert intento.status_code == 403, intento.text

    # Ascendida a miembro, sí; y la dueña ve su trabajo.
    ascenso = duena.put(
        f"/organizations/{oid}/members/{colega.user_id}",
        json={"user_id": colega.user_id, "role": "member", "status": "active"},
    )
    assert ascenso.status_code == 200, ascenso.text
    movida = colega.patch(
        f"/pursuits/{pid}", params={"organization_id": oid}, json={"status": "qualifying"}
    )
    assert movida.status_code == 200, movida.text
    comentario = colega.post(
        f"/pursuits/{pid}/comments",
        params={"organization_id": oid},
        json={"body": "He pedido el pliego técnico."},
    )
    assert comentario.status_code == 201, comentario.text
    hilo = duena.get(f"/pursuits/{pid}/comments", params={"organization_id": oid}).json()
    assert [c["body"] for c in hilo["items"]] == ["He pedido el pliego técnico."]
    assert duena.get(f"/pursuits/{pid}", params={"organization_id": oid}).json()["status"] == (
        "qualifying"
    )

    # Retirado el acceso, deja de ver la organización.
    retirada = duena.put(
        f"/organizations/{oid}/members/{colega.user_id}",
        json={"user_id": colega.user_id, "role": "member", "status": "revoked"},
    )
    assert retirada.status_code == 200, retirada.text
    assert colega.get(f"/pursuits/{pid}", params={"organization_id": oid}).status_code == 403


def test_cu13_lo_de_una_organizacion_no_se_ve_desde_otra(client, api_db):
    """CU-13 — dos clientes del producto no se cruzan datos, ni por id directo."""
    sembrar_licitacion("EXP-AIS-1", "Expediente compartido por el mercado")
    una = abrir_sesion("una@example.com", client)
    ajena = abrir_sesion("ajena@example.com")

    pid = una.post(
        "/pursuits", json={"licitacion_id": "EXP-AIS-1", "organization_id": una.organization_id}
    ).json()["id"]
    assert una.post("/watchlist/items", json={"id_externo": "EXP-AIS-1"}).status_code == 201
    regla = una.post("/watchlist/rules", json={"keyword": "compartido"}).json()["id"]

    # Con su propia organización, la ajena no encuentra nada de la otra.
    assert ajena.get("/pursuits").json()["total"] == 0
    assert ajena.get(f"/pursuits/{pid}").status_code == 404
    assert ajena.get("/watchlist/items").json()["items"] == []
    assert ajena.get(f"/watchlist/rules/{regla}/matches").status_code == 404

    # Y pidiendo la organización de la otra por su id, se le niega.
    assert (
        ajena.get("/pursuits", params={"organization_id": una.organization_id}).status_code == 403
    )
    assert (
        ajena.patch(
            f"/pursuits/{pid}",
            params={"organization_id": una.organization_id},
            json={"status": "qualifying"},
        ).status_code
        == 403
    )

    # El mismo expediente sí puede abrirlo cada una por su cuenta.
    propia = ajena.post(
        "/pursuits", json={"licitacion_id": "EXP-AIS-1", "organization_id": ajena.organization_id}
    )
    assert propia.status_code == 201, propia.text
    assert una.get("/pursuits").json()["total"] == 1


def test_cu14_clave_de_api_crear_usar_rotar_y_revocar(client, api_db):
    """CU-14 — la clave abre la API sin sesión, rotarla entrega una nueva y revocarla la apaga."""
    from api.app import app

    sembrar_licitacion("EXP-KEY-1", "Integración con el ERP", tecnologia="SAP")
    sesion = abrir_sesion("integra@example.com", client)

    creada = sesion.post("/me/keys", json={"name": "Integración CRM"})
    assert creada.status_code == 201, creada.text
    token = creada.json()["api_key"]

    # El listado nombra la clave, pero no vuelve a enseñar el token.
    claves = sesion.get("/me/keys").json()["items"]
    assert [c["name"] for c in claves] == ["Integración CRM"]
    assert token not in sesion.get("/me/keys").text

    # Un cliente sin cookies entra con la clave y lee el mercado.
    maquina = TestClient(app, raise_server_exceptions=True)
    assert maquina.get("/api/v1/licitaciones").status_code == 401
    con_clave = maquina.get("/api/v1/licitaciones", headers={"X-API-Key": token})
    assert con_clave.status_code == 200, con_clave.text
    assert [i["id_externo"] for i in con_clave.json()["items"]] == ["EXP-KEY-1"]
    # Nace con el mínimo privilegio: lee datos, no lo personal de su dueña.
    personal = maquina.get("/api/v1/watchlist/items", headers={"X-API-Key": token})
    assert personal.status_code == 403, personal.text

    rotada = sesion.post("/me/keys/rotate", params={"key_id": creada.json()["id"]})
    assert rotada.status_code == 201, rotada.text
    nuevo = rotada.json()["new_token"]
    assert nuevo != token
    con_nueva = maquina.get("/api/v1/licitaciones", headers={"X-API-Key": nuevo})
    assert con_nueva.status_code == 200, con_nueva.text
    # Durante la gracia la vieja sigue abriendo: la integración migra sin cortes.
    assert maquina.get("/api/v1/licitaciones", headers={"X-API-Key": token}).status_code == 200

    # Migrada la integración, revocar la vieja la apaga al momento, sin esperar
    # a que acabe la gracia, y la nueva sigue valiendo.
    assert sesion.delete(f"/me/keys/{creada.json()['id']}").status_code == 204
    assert maquina.get("/api/v1/licitaciones", headers={"X-API-Key": token}).status_code == 401
    assert maquina.get("/api/v1/licitaciones", headers={"X-API-Key": nuevo}).status_code == 200
    claves = {c["name"]: c["is_active"] for c in sesion.get("/me/keys").json()["items"]}
    assert claves == {"Integración CRM": False, "Integración CRM (rotada)": True}


def test_cu15_exportar_mis_datos_y_borrar_la_cuenta(client, api_db):
    """CU-15 — RGPD: lo que guardé sale en mi exportación, y borrar la cuenta cierra la puerta."""
    from api.app import app

    sembrar_licitacion("EXP-RGPD-1", "Expediente seguido")
    sesion = abrir_sesion("rgpd@example.com", client)
    assert sesion.post("/watchlist/items", json={"id_externo": "EXP-RGPD-1"}).status_code == 201

    exportacion = sesion.get("/me/data")
    assert exportacion.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exportacion.content)) as paquete:
        contenido = "".join(
            paquete.read(nombre).decode("utf-8", errors="replace") for nombre in paquete.namelist()
        )
    assert "EXP-RGPD-1" in contenido
    assert sesion.email in contenido

    token = sesion.post("/me/keys", json={"name": "Clave que debe morir"}).json()["api_key"]

    # Sin la confirmación explícita no se borra nada.
    assert sesion.delete("/me").status_code == 422
    assert sesion.get("/auth/me").status_code == 200

    borrada = sesion.delete("/me", json={"confirmation": "DELETE"})
    assert borrada.status_code == 200, borrada.text

    # La sesión ya no vale, la clave tampoco y las credenciales tampoco.
    assert sesion.get("/auth/me").status_code == 401
    maquina = TestClient(app, raise_server_exceptions=True)
    assert maquina.get("/api/v1/licitaciones", headers={"X-API-Key": token}).status_code == 401
    relogin = sesion.client.post(
        "/api/v1/auth/login", json={"email": sesion.email, "password": PASSWORD}
    )
    assert relogin.status_code in (401, 403), relogin.text


def test_cu24_direccion_ve_la_carga_y_la_actividad_del_equipo(client, api_db):
    """CU-24 — quién lleva qué y qué se ha movido, y solo para quien dirige."""
    sembrar_licitacion("EXP-DIR-1", "Mantenimiento de aplicaciones")
    sembrar_licitacion("EXP-DIR-2", "Oficina técnica SAP")
    jefa = abrir_sesion("jefa@example.com", client, nombre="Julia Jefa")
    tecnica = abrir_sesion("tecnica@example.com", nombre="Teresa Técnica")
    oid = jefa.post("/organizations", json={"name": "Equipo de Dirección"}).json()["id"]
    en = {"organization_id": oid}
    assert (
        jefa.post(
            f"/organizations/{oid}/members", json={"email": tecnica.email, "role": "member"}
        ).status_code
        == 201
    )

    propia = jefa.post("/pursuits", json={"licitacion_id": "EXP-DIR-1", **en}).json()["id"]
    delegada = jefa.post("/pursuits", json={"licitacion_id": "EXP-DIR-2", **en}).json()["id"]
    asignada = jefa.patch(
        f"/pursuits/{delegada}", params=en, json={"responsible_user_id": tecnica.user_id}
    )
    assert asignada.status_code == 200, asignada.text
    assert asignada.json()["responsible_name"] == "Teresa Técnica"

    # La técnica trabaja la suya: la mueve y deja una tarea con fecha.
    assert (
        tecnica.patch(f"/pursuits/{delegada}", params=en, json={"status": "qualifying"}).status_code
        == 200
    )
    assert (
        tecnica.post(
            f"/pursuits/{delegada}/tasks",
            params=en,
            json={"titulo": "Pedir el aval", "vence": "2026-12-01"},
        ).status_code
        == 201
    )

    # Dirección ve la carga repartida entre las dos.
    carga = jefa.get("/pursuits/direccion/carga", params=en)
    assert carga.status_code == 200, carga.text
    assert carga.json()["total_abiertas"] == 2
    assert {r["nombre"]: r["abiertas"] for r in carga.json()["responsables"]} == {
        "Julia Jefa": 1,
        "Teresa Técnica": 1,
    }

    # Y el movimiento de la técnica, con su nombre y lo que cambió.
    actividad = jefa.get("/pursuits/actividad", params=en).json()
    movimiento = next(
        item
        for item in actividad["items"]
        if {"campo": "status", "desde": "identified", "hasta": "qualifying"} in item["cambios"]
    )
    assert movimiento["pursuit_id"] == delegada
    assert movimiento["actor"] == "Teresa Técnica"
    assert {i["pursuit_id"] for i in actividad["items"]} == {propia, delegada}

    tareas = jefa.get("/pursuits/tasks/agenda", params=en).json()
    assert [t["titulo"] for t in tareas] == ["Pedir el aval"]

    cuadro = jefa.get("/pursuits/direccion", params=en)
    assert cuadro.status_code == 200, cuadro.text
    assert cuadro.json()["cierres"] == 0

    # El cuadro de Dirección es para quien dirige: una miembro no entra.
    assert tecnica.get("/pursuits/direccion", params=en).status_code == 403
    assert tecnica.get("/pursuits/direccion/carga", params=en).status_code == 403
