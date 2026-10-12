"""Escenarios de la cuenta y el acceso: el segundo factor y la organización.

Recorridos completos por la API con sesión real. Ver ``tests/escenarios.py`` y
``docs/casos-de-uso.md``.
"""

from __future__ import annotations

from dataclasses import replace

from tests.escenarios import PASSWORD, Sesion, abrir_sesion, codigo_totp


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
