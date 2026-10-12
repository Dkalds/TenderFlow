"""Escenarios de la cuenta y el acceso: el segundo factor y la organización.

Recorridos completos por la API con sesión real. Ver ``tests/escenarios.py`` y
``docs/casos-de-uso.md``.
"""

from __future__ import annotations

from dataclasses import replace

from tests.escenarios import PASSWORD, Sesion, abrir_sesion, codigo_totp, sembrar_licitacion


def _volver_a_entrar(sesion: Sesion) -> Sesion:
    """Cierra la sesión y entra de nuevo con contraseña: la cookie y el CSRF cambian."""
    assert sesion.post("/auth/logout").status_code == 200
    login = sesion.client.post(
        "/api/v1/auth/login", json={"email": sesion.email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return replace(sesion, csrf=str(login.cookies["csrf_token"]))


def test_cu25_verificacion_en_dos_pasos_activar_entrar_y_quitar(client, api_db):
    """CU-25 — la activa, entrar le pide el código, y solo la quita con un código."""
    sesion = abrir_sesion("dosfactores@example.com", client)
    assert sesion.get("/auth/me").json()["mfa_required"] is False

    # Un alta a medias no bloquea: el segundo intento empieza de cero.
    assert sesion.post("/auth/totp/setup").status_code == 200
    alta = sesion.post("/auth/totp/setup")
    assert alta.status_code == 200, alta.text
    uri = alta.json()["otpauth_uri"]
    assert "issuer=TenderFlow" in uri

    confirmada = sesion.post("/auth/totp/confirm", json={"code": codigo_totp(uri)})
    assert confirmada.status_code == 200, confirmada.text
    recuperacion = confirmada.json()["recovery_codes"]
    assert len(recuperacion) == 10
    assert sesion.get("/auth/me").json()["mfa_required"] is True

    # Entrar con la contraseña ya no basta: la sesión queda pendiente del código.
    sesion = _volver_a_entrar(sesion)
    assert sesion.get("/me/keys").status_code == 403
    assert sesion.post("/auth/totp/verify", json={"code": codigo_totp(uri)}).status_code == 200
    assert sesion.get("/me/keys").status_code == 200

    # Sin el móvil, un código de recuperación abre la cuenta… una sola vez.
    sesion = _volver_a_entrar(sesion)
    assert sesion.post("/auth/totp/verify", json={"code": recuperacion[0]}).status_code == 200
    assert sesion.get("/me/keys").status_code == 200
    sesion = _volver_a_entrar(sesion)
    assert sesion.post("/auth/totp/verify", json={"code": recuperacion[0]}).status_code == 401
    assert sesion.post("/auth/totp/verify", json={"code": recuperacion[1]}).status_code == 200

    # Quitarla pide un código: ni la sesión sola ni uno inventado bastan.
    assert sesion.delete("/auth/totp").status_code == 422
    assert sesion.delete("/auth/totp", json={"code": "000000"}).status_code in (400, 429)
    assert sesion.get("/auth/me").json()["mfa_required"] is True
    quitada = sesion.delete("/auth/totp", json={"code": codigo_totp(uri)})
    assert quitada.status_code == 200, quitada.text

    # Y la cuenta vuelve a abrirse solo con la contraseña.
    sesion = _volver_a_entrar(sesion)
    assert sesion.get("/auth/me").json()["mfa_required"] is False
    assert sesion.get("/me/keys").status_code == 200


def _organizaciones(sesion: Sesion) -> set[int]:
    return {int(o["id"]) for o in sesion.get("/organizations").json()}


def test_cu26_salir_traspasar_y_borrar_la_organizacion(client, api_db):
    """CU-26 — quien se va, se va; la propiedad cambia de manos; y borrarla avisa antes."""
    sembrar_licitacion("EXP-CICLO-1", "Soporte de la plataforma de contratación")
    duena = abrir_sesion("duena-ciclo@example.com", client, nombre="Dora Dueña")
    colega = abrir_sesion("colega-ciclo@example.com", nombre="Carla Colega")
    socia = abrir_sesion("socia-ciclo@example.com", nombre="Sara Socia")

    oid = duena.post("/organizations", json={"name": "Consultora Ciclo"}).json()["id"]
    en = {"organization_id": oid}
    for persona, rol in ((colega, "member"), (socia, "admin")):
        alta = duena.post(
            f"/organizations/{oid}/members", json={"email": persona.email, "role": rol}
        )
        assert alta.status_code == 201, alta.text
    pid = duena.post("/pursuits", json={"licitacion_id": "EXP-CICLO-1", **en}).json()["id"]
    comentario = duena.post(
        f"/pursuits/{pid}/comments", params=en, json={"body": "Pedir el pliego"}
    )
    assert comentario.status_code == 201, comentario.text

    # La propietaria no puede irse dejando la organización sin nadie al mando,
    # y el motivo dice qué hacer, en castellano.
    sin_salida = duena.post(f"/organizations/{oid}/leave")
    assert sin_salida.status_code == 409
    assert "traspasa la propiedad" in sin_salida.json()["detail"]

    # Una miembro sí se va, y deja de ver la organización.
    assert colega.post(f"/organizations/{oid}/leave").status_code == 200
    assert oid not in _organizaciones(colega)
    assert colega.get("/pursuits", params=en).status_code == 403

    # Traspasar es solo de la propietaria; tras hacerlo queda como administradora.
    assert (
        socia.post(
            f"/organizations/{oid}/transfer-ownership", json={"nuevo_owner_user_id": duena.user_id}
        ).status_code
        == 403
    )
    traspaso = duena.post(
        f"/organizations/{oid}/transfer-ownership", json={"nuevo_owner_user_id": socia.user_id}
    )
    assert traspaso.status_code == 200, traspaso.text
    roles = {m["email"]: m["role"] for m in duena.get(f"/organizations/{oid}/members").json()}
    assert roles[socia.email] == "owner"
    assert roles[duena.email] == "admin"

    # Borrar avisa antes de lo que se lleva, y solo lo ve quien puede borrar.
    assert duena.get(f"/organizations/{oid}/deletion-preview").status_code == 403
    vista_previa = socia.get(f"/organizations/{oid}/deletion-preview")
    assert vista_previa.status_code == 200, vista_previa.text
    assert vista_previa.json() == {
        "oportunidades": 1,
        "comentarios": 1,
        "miembros": 2,
        "adjuntos": 0,
    }

    # Sin la palabra exacta no se borra nada.
    erronea = socia.post(f"/organizations/{oid}/delete", json={"confirmacion": "borrar"})
    assert erronea.status_code == 409
    assert oid in _organizaciones(socia)

    borrada = socia.post(f"/organizations/{oid}/delete", json={"confirmacion": "BORRAR"})
    assert borrada.status_code == 200, borrada.text
    assert borrada.json()["oportunidades"] == 1
    assert oid not in _organizaciones(socia)
    assert oid not in _organizaciones(duena)
    assert duena.get("/pursuits", params=en).status_code == 403

    # La personal no se borra por aquí: el motivo dice dónde se cierra la cuenta.
    personal = socia.post(
        f"/organizations/{socia.organization_id}/delete", json={"confirmacion": "BORRAR"}
    )
    assert personal.status_code == 409
    assert "Ajustes, en Datos y cuenta" in personal.json()["detail"]
