"""Escenario de la administración: el panel de accesos y lo que la CSP bloqueó.

Recorrido completo por la API con sesión real. Ver ``tests/escenarios.py`` y
``docs/casos-de-uso.md``.

Dos piezas no las hace una persona y por eso el escenario las hace a mano: la
solicitud de acceso que llega desde la landing (``db.solicitudes_acceso``) y
el informe de CSP que envía el navegador por su cuenta
(``POST /security/csp-report``, sin sesión).
"""

from __future__ import annotations

from tests.escenarios import abrir_sesion


def _hacer_admin(user_id: int) -> None:
    """Lo que hace el bootstrap (``ADMIN_EMAILS``) o un administrador anterior."""
    from db.users import set_admin

    set_admin(user_id, True, granted_by="escenario")


def _solicitud_de(email: str) -> int:
    from db.solicitudes_acceso import crear_solicitud

    return crear_solicitud(email=email, empresa="Empresa SL", mensaje=None, origen="landing")


def _informe_csp(client, blocked_uri: str) -> None:
    respuesta = client.post(
        "/api/v1/security/csp-report",
        json={
            "csp-report": {
                "blocked-uri": blocked_uri,
                "violated-directive": "frame-src",
                "document-uri": "https://app.example/detalle?vista=mapa",
                "source-file": "https://app.example/main.js",
            }
        },
    )
    assert respuesta.status_code == 204, respuesta.text


def test_cu20_el_administrador_gobierna_los_accesos_y_ve_lo_que_la_csp_bloquea(client, api_db):
    """CU-20 — concede, revoca, ve quién concedió, vuelve a conceder, y lee la CSP."""
    from unittest.mock import patch

    admin = abrir_sesion("admin-cu20@example.com", client, nombre="Ana Admin")
    _hacer_admin(admin.user_id)
    solicitud_id = _solicitud_de("nueva@empresa.example")

    # Conceder al atender la solicitud: la concesión nace con su autor.
    with patch("api.routes.admin_solicitudes.notificar_acceso_concedido", return_value=True):
        atendida = admin.patch(
            f"/admin/solicitudes-acceso/{solicitud_id}",
            json={"estado": "atendida", "conceder": "email", "notificar": True},
        )
    assert atendida.status_code == 200, atendida.text
    grant_id = atendida.json()["grant_id"]
    assert grant_id is not None

    activas = admin.get("/admin/solicitudes-acceso/grants")
    assert activas.status_code == 200, activas.text
    assert [(g["id"], g["granted_by_nombre"]) for g in activas.json()] == [(grant_id, "Ana Admin")]

    # Revocar la saca de las activas, pero el panel la sigue viendo con su fecha.
    revocada = admin.delete(f"/admin/solicitudes-acceso/grants/{grant_id}")
    assert revocada.status_code == 200, revocada.text
    assert admin.get("/admin/solicitudes-acceso/grants").json() == []
    todas = admin.get("/admin/solicitudes-acceso/grants", params={"include_inactive": "true"})
    assert [(g["id"], g["active"], g["revoked_at"] is not None) for g in todas.json()] == [
        (grant_id, False, True)
    ]

    # Volver a conceder, sin esperar a una solicitud nueva.
    reactivada = admin.post(f"/admin/solicitudes-acceso/grants/{grant_id}/reactivar")
    assert reactivada.status_code == 200, reactivada.text
    assert reactivada.json()["active"] is True
    assert reactivada.json()["granted_by_nombre"] == "Ana Admin"
    assert [g["id"] for g in admin.get("/admin/solicitudes-acceso/grants").json()] == [grant_id]

    # El navegador de alguien informa de dos bloqueos del mismo origen; el
    # administrador los ve como un grupo, con la página sin su query string.
    _informe_csp(client, "https://www.youtube.com/embed/a")
    _informe_csp(client, "https://www.youtube.com/embed/b")
    csp = admin.get("/security/csp-violations", params={"dias": 1})
    assert csp.status_code == 200, csp.text
    assert csp.json()["dias"] == 1
    assert [
        (f["directiva"], f["origen"], f["ocurrencias"], f["documento"]) for f in csp.json()["items"]
    ] == [("frame-src", "https://www.youtube.com", 2, "https://app.example/detalle")]

    # Quien no administra no ve ni los accesos ni la CSP.
    otra = abrir_sesion("miembro-cu20@example.com", nombre="Bea")
    assert otra.get("/admin/solicitudes-acceso/grants").status_code == 403
    assert otra.get("/security/csp-violations").status_code == 403
