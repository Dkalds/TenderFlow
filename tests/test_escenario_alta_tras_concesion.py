"""Escenario del acceso de punta a punta: pedirlo, concederlo y crearse la cuenta.

Recorrido por la API con sesión real. Ver ``tests/escenarios.py`` y
``docs/casos-de-uso.md``. El alta va en **modo cerrado** —el de producción— y
sin lista estática, así que solo cuenta la concesión que escribe el panel
(RFC 2026-10-21-alta-con-contrasena-tras-concesion).
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import patch
from urllib.parse import unquote

from fastapi.testclient import TestClient

from tests.escenarios import abrir_sesion

_PASSWORD = "Recorrido2026Seguro"  # pragma: allowlist secret # gitleaks:allow
_ORIGEN = "https://app.example"


class _Buzon:
    def __init__(self) -> None:
        self.enviados: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> bool:
        self.enviados.append(kwargs)
        return True

    def enlace(self, patron: str) -> str:
        for correo in reversed(self.enviados):
            m = re.search(patron, correo["texto"])
            if m:
                return m.group(0)
        raise AssertionError(f"ningún correo con {patron!r}: {self.enviados}")


def test_cu31_pedir_acceso_recibirlo_y_crearse_la_cuenta(client, api_db):
    """CU-31 — pide acceso, se le concede, se crea la cuenta, entra; al revocar, ya no."""
    from api.app import app
    from config import settings
    from db.users import set_admin

    # La administradora entra antes de cerrar el alta: es la cuenta del panel.
    admin = abrir_sesion("operadora@tenderflow.example", client)
    set_admin(admin.user_id, True)

    buzon = _Buzon()
    persona = TestClient(app, raise_server_exceptions=True)
    with (
        patch("api.routes.auth._registro_abierto", return_value=False),
        patch("services.access_grants.oauth_email_allowed", return_value=False),
        patch("services.solicitudes_acceso.enviar_email_transaccional", new=buzon),
        patch("services.email_verification.enviar_email_transaccional", new=buzon),
        patch.object(settings, "CORS_ALLOWED_ORIGINS", _ORIGEN),
    ):
        # Sin concesión, el alta no entra.
        sin_acceso = persona.post(
            "/api/v1/auth/register", json={"email": "ana@cliente.example", "password": _PASSWORD}
        )
        assert sin_acceso.status_code == 403
        assert sin_acceso.json()["detail"] == "access_not_granted"

        # Pide acceso desde la portada.
        pedida = persona.post(
            "/api/v1/publico/solicitudes-acceso",
            data={"email": "ana@cliente.example", "empresa": "Cliente SL", "consentimiento": "1"},
            follow_redirects=False,
        )
        assert pedida.status_code == 303, pedida.text

        # La operadora la ve en la cola y la concede por correo.
        cola = admin.get("/admin/solicitudes-acceso", params={"estado": "pendiente"}).json()
        solicitud = next(s for s in cola if s["email"] == "ana@cliente.example")
        concedida = admin.patch(
            f"/admin/solicitudes-acceso/{solicitud['id']}",
            json={"estado": "atendida", "conceder": "email"},
        )
        assert concedida.status_code == 200, concedida.text
        assert concedida.json()["notificado"] is True

        # El correo de acceso abre «Crear cuenta» con su dirección puesta.
        alta_url = buzon.enlace(r"https://app\.example/login\?modo=registro&email=\S+")
        assert unquote(alta_url.split("email=")[1]) == "ana@cliente.example"

        # Se da de alta: no entra todavía, le llega el enlace de activación.
        alta = persona.post(
            "/api/v1/auth/register", json={"email": "ana@cliente.example", "password": _PASSWORD}
        )
        assert alta.status_code == 202, alta.text
        assert persona.get("/api/v1/auth/me").status_code == 401
        antes = persona.post(
            "/api/v1/auth/login", json={"email": "ana@cliente.example", "password": _PASSWORD}
        )
        assert antes.status_code == 403
        assert antes.json()["detail"] == "email_not_verified"

        enlace = buzon.enlace(r"https://app\.example/verificar-correo#token=\S+")
        token = unquote(enlace.split("#token=")[1])
        verificada = persona.post("/api/v1/auth/verify-email", json={"token": token})
        assert verificada.status_code == 200, verificada.text
        assert persona.get("/api/v1/auth/me").json()["email"] == "ana@cliente.example"

        # Sale y vuelve a entrar con su contraseña.
        csrf = str(verificada.cookies["csrf_token"])
        assert (
            persona.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
        )
        entra = persona.post(
            "/api/v1/auth/login", json={"email": "ana@cliente.example", "password": _PASSWORD}
        )
        assert entra.status_code == 200, entra.text

        # La operadora revoca la concesión: la contraseña deja de abrir la puerta.
        grants = admin.get("/admin/solicitudes-acceso/grants").json()
        grant = next(g for g in grants if g["value"] == "ana@cliente.example")
        assert admin.delete(f"/admin/solicitudes-acceso/grants/{grant['id']}").status_code == 200
        persona.cookies.clear()
        revocada = persona.post(
            "/api/v1/auth/login", json={"email": "ana@cliente.example", "password": _PASSWORD}
        )
        assert revocada.status_code == 403
        assert revocada.json()["detail"] == "access_not_granted"
