"""Tests de ``/api/v1/admin/solicitudes-acceso`` — cola de solicitudes de acceso.

Lo que importa fijar aquí es la guarda: la cola contiene datos de contacto de
personas que han escrito desde una página pública, así que un usuario sin
permisos de administración no puede ni listarla ni tocarla.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from api.app import app
from api.routes.dual_auth import require_any_auth

RUTA = "/api/v1/admin/solicitudes-acceso"


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    return TestClient(app)


def _admin():
    return {"user_id": 1, "email": "admin@test.com", "is_admin": True, "auth_method": "session"}


def _no_admin():
    return {"user_id": 2, "email": "user@test.com", "is_admin": False, "auth_method": "session"}


def _fila(**extra):
    base = {
        "id": 7,
        "email": "ana@empresa.example",
        "empresa": "Empresa SL",
        "mensaje": None,
        "origen": "landing",
        "estado": "pendiente",
        "created_at": None,
    }
    base.update(extra)
    return base


def _grant(**extra):
    base = {
        "id": 11,
        "kind": "email",
        "value": "ana@empresa.example",
        "active": True,
        "granted_by": 1,
        "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
        "revoked_at": None,
    }
    base.update(extra)
    return base


class TestListar:
    def test_exige_admin(self, client):
        app.dependency_overrides[require_any_auth] = _no_admin
        try:
            assert client.get(RUTA).status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_devuelve_la_cola(self, client):
        app.dependency_overrides[require_any_auth] = _admin
        try:
            with patch("api.routes.admin_solicitudes.listar_solicitudes", return_value=[_fila()]):
                resp = client.get(RUTA)
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        cuerpo = resp.json()
        assert len(cuerpo) == 1
        assert cuerpo[0]["email"] == "ana@empresa.example"
        assert cuerpo[0]["estado"] == "pendiente"

    def test_filtra_por_estado(self, client):
        app.dependency_overrides[require_any_auth] = _admin
        try:
            with patch(
                "api.routes.admin_solicitudes.listar_solicitudes", return_value=[]
            ) as listar:
                resp = client.get(RUTA, params={"estado": "atendida", "limit": 5})
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert listar.call_args.kwargs == {"estado": "atendida", "limit": 5}

    def test_rechaza_un_estado_inventado(self, client):
        """Un estado fuera del conjunto no puede llegar a la consulta."""
        app.dependency_overrides[require_any_auth] = _admin
        try:
            with patch("api.routes.admin_solicitudes.listar_solicitudes") as listar:
                resp = client.get(RUTA, params={"estado": "borrada"})
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 422
        listar.assert_not_called()


class TestCambiarEstado:
    def test_exige_admin(self, client):
        app.dependency_overrides[require_any_auth] = _no_admin
        try:
            assert client.patch(f"{RUTA}/7", json={"estado": "atendida"}).status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_marca_como_atendida_y_lo_audita(self, client):
        app.dependency_overrides[require_any_auth] = _admin
        try:
            with (
                patch(
                    "api.routes.admin_solicitudes.actualizar_estado", return_value=True
                ) as actualizar,
                patch("api.routes.admin_solicitudes.log_event") as auditar,
            ):
                resp = client.patch(f"{RUTA}/7", json={"estado": "atendida"})
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        actualizar.assert_called_once_with(7, "atendida")
        assert auditar.call_args.kwargs["event_type"] == "solicitud_acceso.estado"
        assert auditar.call_args.kwargs["resource"] == "solicitud_acceso:7"

    def test_una_solicitud_inexistente_da_404(self, client):
        app.dependency_overrides[require_any_auth] = _admin
        try:
            with (
                patch("api.routes.admin_solicitudes.actualizar_estado", return_value=False),
                patch("api.routes.admin_solicitudes.log_event") as auditar,
            ):
                resp = client.patch(f"{RUTA}/999", json={"estado": "atendida"})
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 404
        # Sin cambio no hay nada que auditar.
        auditar.assert_not_called()

    def test_rechaza_un_estado_inventado(self, client):
        app.dependency_overrides[require_any_auth] = _admin
        try:
            with patch("api.routes.admin_solicitudes.actualizar_estado") as actualizar:
                resp = client.patch(f"{RUTA}/7", json={"estado": "aprobada"})
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 422
        actualizar.assert_not_called()

    def test_concede_email_antes_de_notificar(self, client):
        app.dependency_overrides[require_any_auth] = _admin
        grant = {
            "id": 11,
            "kind": "email",
            "value": "ana@empresa.example",
            "active": True,
            "granted_by": 1,
            "created_at": "2026-09-01T00:00:00+00:00",
            "updated_at": "2026-09-01T00:00:00+00:00",
            "revoked_at": None,
        }
        try:
            with (
                patch(
                    "api.routes.admin_solicitudes.grant_access_request",
                    return_value={
                        "grant": grant,
                        "email": "ana@empresa.example",
                        "empresa": "Empresa SL",
                        "previous_state": "pendiente",
                    },
                ) as grant_fn,
                patch("api.routes.admin_solicitudes.log_event"),
                patch(
                    "api.routes.admin_solicitudes.notificar_acceso_concedido",
                    return_value=True,
                ),
            ):
                resp = client.patch(
                    f"{RUTA}/7",
                    json={"estado": "atendida", "conceder": "email", "notificar": True},
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "ok", "notificado": True, "grant_id": 11}
        grant_fn.assert_called_once_with(
            7,
            "email",
            granted_by=1,
        )

    def test_el_cambio_de_estado_se_audita_con_el_id_del_admin(self, client):
        """``audit_log.user_id`` es la identidad del actor (ADR-030 §D): no puede ir NULL."""
        app.dependency_overrides[require_any_auth] = _admin
        try:
            with (
                patch("api.routes.admin_solicitudes.actualizar_estado", return_value=True),
                patch("api.routes.admin_solicitudes.log_event") as auditar,
            ):
                resp = client.patch(f"{RUTA}/7", json={"estado": "descartada"})
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert [llamada.kwargs for llamada in auditar.call_args_list] == [
            {
                "event_type": "solicitud_acceso.estado",
                "actor": "1",
                "user_id": 1,
                "resource": "solicitud_acceso:7",
                "detail": "descartada",
            }
        ]

    def test_conceder_se_audita_con_actor_recurso_y_user_id(self, client):
        """Quién concedió y qué concesión, sin copiar el email al rastro."""
        app.dependency_overrides[require_any_auth] = _admin
        try:
            with (
                patch(
                    "api.routes.admin_solicitudes.grant_access_request",
                    return_value={
                        "grant": _grant(),
                        "email": "ana@empresa.example",
                        "empresa": "Empresa SL",
                        "previous_state": "pendiente",
                    },
                ),
                patch("api.routes.admin_solicitudes.log_event") as auditar,
                patch(
                    "api.routes.admin_solicitudes.notificar_acceso_concedido",
                    return_value=True,
                ),
            ):
                resp = client.patch(
                    f"{RUTA}/7",
                    json={"estado": "atendida", "conceder": "email", "notificar": True},
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        # Igualdad exacta: ni falta el `user_id` ni se cuela la dirección.
        assert [llamada.kwargs for llamada in auditar.call_args_list] == [
            {
                "event_type": "solicitud_acceso.estado",
                "actor": "1",
                "user_id": 1,
                "resource": "solicitud_acceso:7",
                "detail": "atendida",
            },
            {
                "event_type": "access_grant.granted",
                "actor": "1",
                "user_id": 1,
                "resource": "access_grant:11",
                "detail": {"kind": "email"},
            },
        ]

    def test_conceder_el_dominio_de_un_correo_publico_es_422(self, client):
        """La regla de verdad, lanzada donde la lanza la BD: antes de escribir."""
        from services.access_grants import validar_concesion

        def _rechaza(_solicitud_id, kind, *, granted_by):
            validar_concesion(kind, "gmail.com")

        app.dependency_overrides[require_any_auth] = _admin
        try:
            with (
                patch("api.routes.admin_solicitudes.grant_access_request", side_effect=_rechaza),
                patch("api.routes.admin_solicitudes.log_event") as auditar,
                patch("api.routes.admin_solicitudes.notificar_acceso_concedido") as avisar,
            ):
                resp = client.patch(
                    f"{RUTA}/7",
                    json={"estado": "atendida", "conceder": "domain", "notificar": True},
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 422, resp.text
        detalle = resp.json()["detail"]
        assert "gmail.com" in detalle
        assert "email" in detalle.lower()
        # Nada concedido: ni rastro de una concesión ni correo de bienvenida.
        auditar.assert_not_called()
        avisar.assert_not_called()

    def test_una_concesion_invalida_es_422_con_su_motivo(self, client):
        """Antes caía en el manejador global de ``ValueError``: un 400 sin motivo."""
        from db.access_grants import normalize_grant

        def _rechaza(_solicitud_id, kind, *, granted_by):
            # Lo que pasa con una solicitud cuyo correo no tiene un dominio
            # concedible (`alguien@localhost`).
            normalize_grant(kind, "localhost")

        app.dependency_overrides[require_any_auth] = _admin
        try:
            with (
                patch("api.routes.admin_solicitudes.grant_access_request", side_effect=_rechaza),
                patch("api.routes.admin_solicitudes.log_event") as auditar,
                patch("api.routes.admin_solicitudes.notificar_acceso_concedido") as avisar,
            ):
                resp = client.patch(
                    f"{RUTA}/7",
                    json={"estado": "atendida", "conceder": "domain", "notificar": True},
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 422, resp.text
        assert "dominio" in resp.json()["detail"].lower()
        auditar.assert_not_called()
        avisar.assert_not_called()


class TestSinSesion:
    """Sin cookie ni API key no se llega a nada: ni a la cola ni a las concesiones.

    Los tests de arriba cubren al usuario autenticado sin permisos (403). Este
    cubre el escalón anterior, que es el que protege la cola —datos de contacto
    de quien escribió desde una página pública— y la allowlist de acceso.
    """

    @pytest.mark.parametrize(
        ("metodo", "ruta", "cuerpo"),
        [
            ("GET", RUTA, None),
            ("PATCH", f"{RUTA}/7", {"estado": "atendida", "conceder": "email"}),
            ("GET", f"{RUTA}/grants", None),
            ("DELETE", f"{RUTA}/grants/11", None),
        ],
    )
    def test_las_cuatro_rutas_exigen_autenticacion(self, client, metodo, ruta, cuerpo):
        with (
            patch("api.routes.admin_solicitudes.listar_solicitudes") as listar,
            patch("api.routes.admin_solicitudes.actualizar_estado") as actualizar,
            patch("api.routes.admin_solicitudes.grant_access_request") as conceder,
            patch("api.routes.admin_solicitudes.list_access_grants") as listar_grants,
            patch("api.routes.admin_solicitudes.revoke_access") as revocar,
            patch("api.routes.admin_solicitudes.log_event") as auditar,
        ):
            resp = client.request(metodo, ruta, json=cuerpo)

        assert resp.status_code == 401, resp.text
        for doble in (listar, actualizar, conceder, listar_grants, revocar, auditar):
            doble.assert_not_called()


def test_el_aviso_comprueba_el_acceso_con_la_funcion_del_callback():
    """Una sola definición de «puede entrar»: la que decide el login.

    Si el PATCH tuviera su propia copia, el correo «ya tienes acceso» podría
    salir para una dirección que el callback rechaza, o al revés.
    """
    from api.routes import admin_solicitudes, auth

    assert admin_solicitudes._oauth_access_allowed is auth._oauth_access_allowed


class TestAccessGrants:
    def test_listar_y_revocar_requiere_admin(self, client):
        app.dependency_overrides[require_any_auth] = _no_admin
        try:
            assert client.get(f"{RUTA}/grants").status_code == 403
            assert client.delete(f"{RUTA}/grants/1").status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_revoca_y_audita(self, client):
        app.dependency_overrides[require_any_auth] = _admin
        grant = {
            "id": 11,
            "kind": "email",
            "value": "ana@empresa.example",
            "active": False,
            "granted_by": 1,
            "created_at": "2026-09-01T00:00:00+00:00",
            "updated_at": "2026-09-01T00:01:00+00:00",
            "revoked_at": "2026-09-01T00:01:00+00:00",
        }
        try:
            with (
                patch("api.routes.admin_solicitudes.revoke_access", return_value=grant),
                patch("api.routes.admin_solicitudes.log_event") as audit,
            ):
                resp = client.delete(f"{RUTA}/grants/11")
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        assert resp.json()["active"] is False
        assert audit.call_args.kwargs["event_type"] == "access_grant.revoked"

    def test_la_revocacion_se_audita_con_actor_recurso_y_user_id(self, client):
        """El audit log es el único sitio que guarda quién revocó: tiene que ir entero."""
        app.dependency_overrides[require_any_auth] = _admin
        revocada = _grant(
            kind="domain",
            value="empresa.example",
            active=False,
            updated_at="2026-09-01T00:01:00+00:00",
            revoked_at="2026-09-01T00:01:00+00:00",
        )
        try:
            with (
                patch("api.routes.admin_solicitudes.revoke_access", return_value=revocada),
                patch("api.routes.admin_solicitudes.log_event") as auditar,
            ):
                resp = client.delete(f"{RUTA}/grants/11")
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        # Igualdad exacta: el dominio revocado no se copia al rastro.
        assert [llamada.kwargs for llamada in auditar.call_args_list] == [
            {
                "event_type": "access_grant.revoked",
                "actor": "1",
                "user_id": 1,
                "resource": "access_grant:11",
                "detail": {"kind": "domain"},
            }
        ]

    def test_revocar_lo_que_no_existe_o_ya_estaba_revocado_no_se_audita(self, client):
        app.dependency_overrides[require_any_auth] = _admin
        try:
            with (
                patch("api.routes.admin_solicitudes.revoke_access", return_value=None),
                patch("api.routes.admin_solicitudes.log_event") as auditar,
            ):
                resp = client.delete(f"{RUTA}/grants/999")
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 404
        auditar.assert_not_called()
