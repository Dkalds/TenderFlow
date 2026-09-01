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
