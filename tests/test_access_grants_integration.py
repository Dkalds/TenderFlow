"""RFC 242 contra Postgres: conceder, entrar, revocar y dejar rastro.

Todo lo de aquí exige base (fixtures ``api_db``/``client``), así que queda
marcado ``integration`` por el propio ``conftest`` y no corre en la suite
rápida. Es lo que solo una base real puede sostener:

- ``grant_access_request`` —la función que llama la ruta— concede y atiende la
  solicitud en una transacción, es idempotente y, si rechaza, no deja nada;
- una concesión de dominio casa con ese dominio exacto y con ningún otro;
- volver a conceder tras revocar reactiva la misma fila (``UNIQUE(kind, value)``);
- conceder y revocar desde la ruta abre y corta el login de verdad, y deja en
  ``audit_log`` quién lo hizo.

Lo que se decide sin tocar la tabla (direcciones mal formadas, la regla de los
proveedores de correo público, la traducción a 422) tiene sus tests sin BD en
``tests/test_auth_dynamic_grants.py``, ``tests/test_services_access_grants.py``
y ``tests/test_routes_admin_solicitudes.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from api.routes.dual_auth import require_any_auth
from db.access_grants import (
    ConcesionInvalida,
    grant_access,
    grant_access_request,
    is_access_granted,
    list_access_grants,
    revoke_access,
)
from db.solicitudes_acceso import crear_solicitud, obtener_solicitud

RUTA = "/api/v1/admin/solicitudes-acceso"


def _solicitud(email: str = "ana@example.com", *, empresa: str | None = None) -> int:
    return crear_solicitud(email=email, empresa=empresa, mensaje=None, origen="landing")


def _estado(solicitud_id: int) -> str:
    fila = obtener_solicitud(solicitud_id)
    assert fila is not None
    return str(fila["estado"])


def _crear_admin() -> int:
    """Un usuario real: ``granted_by`` y ``audit_log.user_id`` son FK a ``users``."""
    from db.users import create_user

    return create_user(
        email="admin-242@example.test",
        password_hash="test-hash",  # pragma: allowlist secret
        display_name="Admin 242",
    )


def _autenticar(user_id: int) -> None:
    from api.app import app

    app.dependency_overrides[require_any_auth] = lambda: {
        "user_id": user_id,
        "email": "admin-242@example.test",
        "is_admin": True,
        "auth_method": "session",
    }


def _login_permitido(email: str) -> bool:
    """Lo que decidiría el callback, con la lista estática sin esa dirección.

    En desarrollo las listas vacías dejan entrar a cualquiera; aquí se fija la
    mitad estática en «no», que es lo que pasa en producción, para que la
    respuesta dependa solo de ``access_grants``.
    """
    from api.routes.auth import _oauth_access_allowed

    with patch("api.routes.auth.oauth_email_allowed", return_value=False):
        return asyncio.run(_oauth_access_allowed(email))


def _rastro(*acciones: str) -> list[tuple[Any, ...]]:
    from db.database import connect_read

    with connect_read() as conn:
        return list(
            conn.execute(
                "SELECT action, user_id, user_key, detail FROM audit_log "
                "WHERE action = ANY(%s) ORDER BY id",
                (list(acciones),),
            ).fetchall()
        )


# ── El repositorio ──────────────────────────────────────────────────────────


def test_conceder_la_solicitud_escribe_la_concesion_y_la_atiende(api_db):
    admin = _crear_admin()
    solicitud_id = _solicitud("Ana@Example.com", empresa="Empresa SL")

    concedido = grant_access_request(solicitud_id, "email", granted_by=admin)

    assert concedido is not None
    assert concedido["previous_state"] == "pendiente"
    assert concedido["email"] == "ana@example.com"
    assert concedido["empresa"] == "Empresa SL"
    grant = concedido["grant"]
    assert (grant["kind"], grant["value"]) == ("email", "ana@example.com")
    assert grant["active"] is True
    assert grant["granted_by"] == admin
    assert grant["revoked_at"] is None
    # Las dos escrituras van juntas: la solicitud ya no espera a nadie.
    assert _estado(solicitud_id) == "atendida"
    assert is_access_granted("ANA@example.com") is True
    # Una concesión de email no abre el dominio.
    assert is_access_granted("otra@example.com") is False


def test_conceder_dos_veces_la_misma_solicitud_no_duplica_nada(api_db):
    solicitud_id = _solicitud()

    primera = grant_access_request(solicitud_id, "email", granted_by=None)
    segunda = grant_access_request(solicitud_id, "email", granted_by=None)

    assert primera is not None
    assert segunda is not None
    assert segunda["grant"]["id"] == primera["grant"]["id"]
    # La ruta usa este campo para no escribirle dos veces a la misma persona.
    assert segunda["previous_state"] == "atendida"
    assert len(list_access_grants(include_inactive=True)) == 1
    assert _estado(solicitud_id) == "atendida"


def test_conceder_una_solicitud_que_no_existe_no_escribe_nada(api_db):
    assert grant_access_request(999_999, "email", granted_by=None) is None
    assert list_access_grants(include_inactive=True) == []


def test_una_concesion_de_dominio_casa_con_ese_dominio_y_con_ningun_otro(api_db):
    solicitud_id = _solicitud("ana@example.com")

    concedido = grant_access_request(solicitud_id, "domain", granted_by=None)

    assert concedido is not None
    assert (concedido["grant"]["kind"], concedido["grant"]["value"]) == ("domain", "example.com")
    assert is_access_granted("otra.persona@example.com") is True
    assert is_access_granted("OTRA@EXAMPLE.COM") is True
    for ajeno in (
        # Un dominio que termina igual no es el mismo dominio.
        "x@evil-example.com",
        # Un subdominio tampoco: se concede `example.com`, no su árbol.
        "x@a.example.com",
        # Ni uno que lo lleva de prefijo.
        "x@example.com.evil.io",
        # «Lo que va tras el último @» sí sería `example.com`.
        "x@evil.com@example.com",
        "@example.com",
        # El dominio a secas no es la dirección de nadie.
        "example.com",
    ):
        assert is_access_granted(ajeno) is False, ajeno


def test_el_dominio_de_un_correo_publico_no_se_concede_y_no_deja_nada_a_medias(api_db):
    solicitud_id = _solicitud("quien-sea@gmail.com")

    with pytest.raises(ConcesionInvalida, match=r"gmail\.com"):
        grant_access_request(solicitud_id, "domain", granted_by=None)

    # La transacción se deshizo entera: ni concesión ni solicitud atendida.
    assert list_access_grants(include_inactive=True) == []
    assert _estado(solicitud_id) == "pendiente"
    assert is_access_granted("otro@gmail.com") is False

    # La alternativa que propone el mensaje sí funciona, y solo para esa persona.
    assert grant_access_request(solicitud_id, "email", granted_by=None) is not None
    assert is_access_granted("quien-sea@gmail.com") is True
    assert is_access_granted("otro@gmail.com") is False


def test_volver_a_conceder_tras_revocar_reactiva_la_misma_fila(api_db):
    admin = _crear_admin()
    primera = grant_access_request(_solicitud(), "email", granted_by=None)
    assert primera is not None
    grant_id = primera["grant"]["id"]

    revocada = revoke_access(grant_id)

    assert revocada is not None
    assert revocada["active"] is False
    assert revocada["revoked_at"] is not None
    assert is_access_granted("ana@example.com") is False
    assert list_access_grants() == []
    # Revocar lo ya revocado no es un segundo evento.
    assert revoke_access(grant_id) is None

    # La persona vuelve a pedir acceso: es una solicitud nueva (la anterior ya
    # no está pendiente) y la concesión es la de antes, reactivada.
    de_nuevo = grant_access_request(_solicitud(), "email", granted_by=admin)

    assert de_nuevo is not None
    assert de_nuevo["grant"]["id"] == grant_id
    assert de_nuevo["grant"]["active"] is True
    assert de_nuevo["grant"]["revoked_at"] is None
    assert de_nuevo["grant"]["granted_by"] == admin
    assert is_access_granted("ana@example.com") is True
    assert len(list_access_grants(include_inactive=True)) == 1

    # Y lo mismo por la función directa, sin solicitud de por medio.
    assert revoke_access(grant_id) is not None
    assert grant_access("email", " Ana@Example.com ", granted_by=None)["id"] == grant_id
    assert is_access_granted("ana@example.com") is True


# ── La ruta, con el login de verdad detrás ──────────────────────────────────


def test_conceder_desde_la_ruta_abre_el_login_y_deja_rastro(client, api_db):
    """Aprobar desde Admin concede acceso sin editar el entorno, y queda auditado."""
    from api.app import app

    admin = _crear_admin()
    solicitud_id = _solicitud("ana@example.com", empresa="Empresa SL")
    assert _login_permitido("ana@example.com") is False

    _autenticar(admin)
    try:
        with patch(
            "api.routes.admin_solicitudes.notificar_acceso_concedido", return_value=True
        ) as avisar:
            resp = client.patch(
                f"{RUTA}/{solicitud_id}",
                json={"estado": "atendida", "conceder": "email", "notificar": True},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["notificado"] is True
    grant_id = cuerpo["grant_id"]
    assert grant_id is not None
    avisar.assert_called_once_with(email="ana@example.com", empresa="Empresa SL")

    assert _login_permitido("ana@example.com") is True
    assert _login_permitido("otra@example.com") is False

    rastro = _rastro("solicitud_acceso.estado", "access_grant.granted")
    # Quién lo hizo va en `user_id` (ADR-030 §D), no solo como texto.
    assert [(accion, user_id, user_key) for accion, user_id, user_key, _ in rastro] == [
        ("solicitud_acceso.estado", admin, str(admin)),
        ("access_grant.granted", admin, str(admin)),
    ]
    assert f"resource=solicitud_acceso:{solicitud_id}" in rastro[0][3]
    assert f"resource=access_grant:{grant_id}" in rastro[1][3]
    # El rastro identifica la concesión por su id: la dirección no se copia.
    assert all("ana@example.com" not in str(detalle) for *_, detalle in rastro)


def test_revocar_desde_la_ruta_corta_los_logins_nuevos_y_deja_rastro(client, api_db):
    from api.app import app

    admin = _crear_admin()
    concedido = grant_access_request(_solicitud(), "email", granted_by=admin)
    assert concedido is not None
    grant_id = concedido["grant"]["id"]
    assert _login_permitido("ana@example.com") is True

    _autenticar(admin)
    try:
        resp = client.delete(f"{RUTA}/grants/{grant_id}")
        repetida = client.delete(f"{RUTA}/grants/{grant_id}")
        activas = client.get(f"{RUTA}/grants")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    assert resp.json()["active"] is False
    assert repetida.status_code == 404
    assert activas.json() == []
    assert _login_permitido("ana@example.com") is False

    # Una revocación, un evento: la repetida no añade otro.
    rastro = _rastro("access_grant.revoked")
    assert [(accion, user_id, user_key) for accion, user_id, user_key, _ in rastro] == [
        ("access_grant.revoked", admin, str(admin)),
    ]
    assert f"resource=access_grant:{grant_id}" in rastro[0][3]
    assert "ana@example.com" not in str(rastro[0][3])


def test_conceder_el_dominio_de_un_correo_publico_desde_la_ruta_es_422(client, api_db):
    from api.app import app

    admin = _crear_admin()
    solicitud_id = _solicitud("quien-sea@gmail.com")

    _autenticar(admin)
    try:
        with patch("api.routes.admin_solicitudes.notificar_acceso_concedido") as avisar:
            resp = client.patch(
                f"{RUTA}/{solicitud_id}",
                json={"estado": "atendida", "conceder": "domain", "notificar": True},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422, resp.text
    detalle = resp.json()["detail"]
    assert "gmail.com" in detalle
    assert "email" in detalle.lower()
    avisar.assert_not_called()
    # Nada cambió: la solicitud sigue esperando y nadie de Gmail entra.
    assert _estado(solicitud_id) == "pendiente"
    assert list_access_grants(include_inactive=True) == []
    assert _login_permitido("otro@gmail.com") is False
    assert _rastro("solicitud_acceso.estado", "access_grant.granted") == []


def test_avisar_sin_conceder_solo_escribe_a_quien_ya_puede_entrar(client, api_db):
    """``notificar`` a secas no habilita a nadie: el correo depende del acceso real."""
    from api.app import app

    admin = _crear_admin()
    sin_acceso = _solicitud("nadie@example.com")
    con_acceso = _solicitud("ana@empresa.example", empresa="Empresa SL")
    # Esta dirección ya entra por una concesión de dominio anterior.
    assert grant_access("domain", "empresa.example", granted_by=admin)["active"] is True

    _autenticar(admin)
    try:
        with (
            patch("api.routes.auth.oauth_email_allowed", return_value=False),
            patch(
                "api.routes.admin_solicitudes.notificar_acceso_concedido", return_value=True
            ) as avisar,
        ):
            rechazado = client.patch(
                f"{RUTA}/{sin_acceso}", json={"estado": "atendida", "notificar": True}
            )
            enviado = client.patch(
                f"{RUTA}/{con_acceso}", json={"estado": "atendida", "notificar": True}
            )
    finally:
        app.dependency_overrides.clear()

    assert rechazado.status_code == 200, rechazado.text
    assert rechazado.json() == {"status": "ok", "notificado": False, "grant_id": None}
    assert enviado.status_code == 200, enviado.text
    assert enviado.json() == {"status": "ok", "notificado": True, "grant_id": None}
    # Un solo correo, y a quien sí puede entrar.
    avisar.assert_called_once_with(email="ana@empresa.example", empresa="Empresa SL")
    # El cambio de estado se aplica en los dos casos.
    assert _estado(sin_acceso) == "atendida"
    assert _estado(con_acceso) == "atendida"
