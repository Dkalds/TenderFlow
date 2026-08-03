"""Regresiones del review de seguridad sobre identidad, sesión y autorización.

Cubre cuatro arreglos:

- El gate de MFA vive en ``get_current_session_user`` (antes solo lo aplicaba
  ``dual_auth.require_any_auth``, así que analytics y ``/exports/download`` se
  lo saltaban) y las tres rutas que deben funcionar con MFA pendiente.
- ``require_api_key`` rechaza las keys de un usuario desactivado, y la baja
  administrativa revoca sesiones y keys.
- ``rotate_my_key`` exige step-up de sesión y ``key_id`` propio.
- ``_sync_oauth_admin`` refleja ``OAUTH_ADMIN_EMAILS`` en ambos sentidos.

Los tests no tocan Postgres: monkeypatchean la capa ``db`` para poder correr en
entornos sin base de datos.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import api.auth as api_auth
import api.routes.admin_users as admin_users
import api.routes.auth as auth_routes
import api.routes.me as me_routes
from config import settings

_SESSION_TOKEN = "tok-de-prueba"  # pragma: allowlist secret
_USER_ID = 7


def _stub_session(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mfa_required: bool,
    mfa_verified_at: str | None = None,
) -> None:
    """Sustituye la capa db que consulta ``_session_principal``."""
    monkeypatch.setattr(
        auth_routes,
        "validate_session",
        lambda token: {
            "user_id": _USER_ID,
            "authenticated_at": "2026-08-02T00:00:00+00:00",
            "mfa_verified_at": mfa_verified_at,
        },
    )
    monkeypatch.setattr(
        auth_routes,
        "get_user_by_id",
        lambda user_id, **kwargs: {
            "id": _USER_ID,
            "email": "usuario@example.com",
            "display_name": "Usuario",
            "is_admin": False,
        },
    )
    monkeypatch.setattr("db.totp.is_totp_required", lambda user_id: mfa_required)


# ---------------------------------------------------------------------------
# A1 — el gate de MFA vive en la dependencia base
# ---------------------------------------------------------------------------


def test_sesion_con_mfa_pendiente_es_rechazada(monkeypatch: pytest.MonkeyPatch) -> None:
    """MFA exigido y sin verificar → 403 en la dependencia base."""
    _stub_session(monkeypatch, mfa_required=True)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth_routes.get_current_session_user(_SESSION_TOKEN))

    assert exc.value.status_code == 403


def test_sesion_con_mfa_verificado_pasa_el_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con el segundo factor ya verificado la dependencia devuelve el principal."""
    _stub_session(monkeypatch, mfa_required=True, mfa_verified_at="2026-08-02T00:05:00+00:00")

    principal = asyncio.run(auth_routes.get_current_session_user(_SESSION_TOKEN))

    assert principal["user_id"] == _USER_ID


def test_sesion_sin_mfa_configurado_pasa_el_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un usuario sin TOTP confirmado no se ve afectado por el gate."""
    _stub_session(monkeypatch, mfa_required=False)

    principal = asyncio.run(auth_routes.get_current_session_user(_SESSION_TOKEN))

    assert principal["mfa_required"] is False


def test_variante_pending_mfa_no_aplica_el_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """La variante explícita devuelve el principal aunque falte el segundo factor."""
    _stub_session(monkeypatch, mfa_required=True)

    principal = asyncio.run(auth_routes.get_session_user_pending_mfa(_SESSION_TOKEN))

    assert principal["mfa_required"] is True
    assert principal["mfa_verified_at"] is None


def test_pending_mfa_no_es_un_parametro_de_la_dependencia() -> None:
    """El bypass no debe poder invocarse desde la query string.

    Si ``allow_pending_mfa`` fuese un parámetro de la dependencia, FastAPI lo
    expondría como query param y ``?allow_pending_mfa=true`` desactivaría el
    gate desde fuera.
    """
    params = inspect.signature(auth_routes.get_current_session_user).parameters

    assert list(params) == ["session"]


def _mini_app(*routers: Any) -> TestClient:
    """App mínima con routers reales, sin el middleware ni la BD de api.app."""
    app = FastAPI()
    for router in routers:
        app.include_router(router, prefix="/api/v1")
    client = TestClient(app)
    client.cookies.set("session", _SESSION_TOKEN)
    return client


def test_analytics_con_mfa_pendiente_da_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un endpoint de analytics ya no es alcanzable con solo la contraseña."""
    from api.routes.analytics import router as analytics_router

    _stub_session(monkeypatch, mfa_required=True)
    client = _mini_app(analytics_router)

    assert client.get("/api/v1/analytics/overview").status_code == 403


def test_export_descarga_con_mfa_pendiente_da_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """El corpus completo tampoco se descarga con la sesión a medio autenticar."""
    from api.routes.exports import router as exports_router

    _stub_session(monkeypatch, mfa_required=True)
    client = _mini_app(exports_router)

    assert client.get("/api/v1/exports/download?format=csv").status_code == 403


def test_auth_me_funciona_con_mfa_pendiente(monkeypatch: pytest.MonkeyPatch) -> None:
    """El SPA necesita /auth/me para saber que debe pedir el TOTP."""
    _stub_session(monkeypatch, mfa_required=True)
    client = _mini_app(auth_routes.router)

    resp = client.get("/api/v1/auth/me")

    assert resp.status_code == 200
    assert resp.json()["mfa_required"] is True


def test_logout_funciona_con_mfa_pendiente(monkeypatch: pytest.MonkeyPatch) -> None:
    """Abandonar un login a medias no puede exigir completarlo."""
    revocadas: list[str] = []
    _stub_session(monkeypatch, mfa_required=True)
    monkeypatch.setattr(auth_routes, "revoke_session", revocadas.append)
    client = _mini_app(auth_routes.router)

    resp = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": auth_routes._csrf_for_session(_SESSION_TOKEN)},
    )

    assert resp.status_code == 200
    assert revocadas == [_SESSION_TOKEN]


def test_totp_verify_funciona_con_mfa_pendiente(monkeypatch: pytest.MonkeyPatch) -> None:
    """Es la ruta donde se verifica el segundo factor: gatearla cerraría el login."""
    verificadas: list[str] = []
    _stub_session(monkeypatch, mfa_required=True)
    monkeypatch.setattr("db.rate_limits.is_mfa_locked_out", lambda *a, **kw: (False, 0.0))
    monkeypatch.setattr("db.rate_limits.clear_mfa_attempts", lambda user_id: None)
    monkeypatch.setattr(
        "db.totp.get_totp_secret",
        lambda user_id: {"secret": "JBSWY3DPEHPK3PXP", "confirmed": True},
    )
    monkeypatch.setattr("db.totp.verify_totp", lambda secret, code: True)
    monkeypatch.setattr("db.sessions.mark_session_mfa_verified", verificadas.append)
    client = _mini_app(auth_routes.router)

    resp = client.post(
        "/api/v1/auth/totp/verify",
        json={"code": "123456"},
        headers={"X-CSRF-Token": auth_routes._csrf_for_session(_SESSION_TOKEN)},
    )

    assert resp.status_code == 200
    assert verificadas == [_SESSION_TOKEN]


def test_totp_verify_sigue_exigiendo_csrf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Relajar el gate de MFA no relaja el CSRF de la mutación."""
    _stub_session(monkeypatch, mfa_required=True)
    client = _mini_app(auth_routes.router)

    resp = client.post("/api/v1/auth/totp/verify", json={"code": "123456"})

    assert resp.status_code == 403
    assert "CSRF" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# A2 — desactivar un usuario revoca sus credenciales
# ---------------------------------------------------------------------------


def _stub_api_key(
    monkeypatch: pytest.MonkeyPatch,
    *,
    owner: dict[str, Any] | None,
    user_id: int | None = 9,
) -> None:
    """Deja una key válida en la capa de servicio y fija a su propietario."""
    record = SimpleNamespace(key_id=3, user_id=user_id, expires_at=None, scopes="*")
    monkeypatch.setattr(api_auth.auth_service, "lookup_active_key", lambda key_hash: record)
    monkeypatch.setattr(
        api_auth.auth_service, "get_stored_hash", lambda key_id: api_auth.hash_api_key("raw-key")
    )
    monkeypatch.setattr(api_auth.auth_service, "update_last_used", lambda key_id: None)
    monkeypatch.setattr(api_auth, "get_user_by_id", lambda uid, **kwargs: owner)


def test_api_key_de_usuario_desactivado_da_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_user_by_id`` filtra desactivados: sin propietario activo, 401."""
    _stub_api_key(monkeypatch, owner=None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_auth.require_api_key("raw-key"))

    assert exc.value.status_code == 401


def test_api_key_de_usuario_activo_sigue_valida(monkeypatch: pytest.MonkeyPatch) -> None:
    """La comprobación nueva no rompe el camino feliz."""
    _stub_api_key(monkeypatch, owner={"id": 9, "email": "activo@example.com"})

    ctx = asyncio.run(api_auth.require_api_key("raw-key"))

    assert ctx.user_id == 9
    assert ctx.key_id == 3


def test_api_key_sin_propietario_no_consulta_usuarios(monkeypatch: pytest.MonkeyPatch) -> None:
    """Las keys sin ``user_id`` (dev/tests) no pasan por la comprobación."""

    def _explota(uid: int, **kwargs: Any) -> dict[str, Any] | None:
        raise AssertionError("no debe consultarse el usuario de una key sin user_id")

    _stub_api_key(monkeypatch, owner=None, user_id=None)
    monkeypatch.setattr(api_auth, "get_user_by_id", _explota)
    monkeypatch.setattr(settings, "ENV", "dev")

    ctx = asyncio.run(api_auth.require_api_key("raw-key"))

    assert ctx.user_id is None


def _stub_admin_deactivate(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Registra las llamadas de ``admin_deactivate_user`` sin tocar la BD."""
    calls: dict[str, list[Any]] = {
        "deactivate": [],
        "reactivate": [],
        "anonymize": [],
        "sessions": [],
        "keys": [],
        "events": [],
    }
    monkeypatch.setattr(admin_users, "get_user_by_id", lambda uid, **kwargs: {"id": uid})
    monkeypatch.setattr(admin_users, "deactivate_user", calls["deactivate"].append)
    monkeypatch.setattr(admin_users, "reactivate_user", calls["reactivate"].append)
    monkeypatch.setattr(admin_users, "anonymize_user", calls["anonymize"].append)
    monkeypatch.setattr(
        admin_users,
        "revoke_all_sessions",
        lambda uid: (calls["sessions"].append(uid), 2)[1],
    )
    monkeypatch.setattr(
        admin_users,
        "revoke_all_api_keys_for_user",
        lambda uid: (calls["keys"].append(uid), 3)[1],
    )
    monkeypatch.setattr(admin_users, "log_event", lambda **kw: calls["events"].append(kw))
    return calls


def test_deactivate_revoca_sesiones_y_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """La baja administrativa cierra también las credenciales ya emitidas."""
    calls = _stub_admin_deactivate(monkeypatch)

    resultado = admin_users.admin_deactivate_user(
        5, admin_users.DeactivateBody(action="deactivate"), admin={"user_id": 1}
    )

    assert resultado["status"] == "ok"
    assert calls["deactivate"] == [5]
    assert calls["sessions"] == [5]
    assert calls["keys"] == [5]
    assert calls["events"][0]["detail"] == {
        "action": "deactivate",
        "sessions_revoked": 2,
        "api_keys_revoked": 3,
    }


def test_anonymize_revoca_sesiones_y_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anonimizar es una baja: mismas revocaciones."""
    calls = _stub_admin_deactivate(monkeypatch)

    admin_users.admin_deactivate_user(
        5, admin_users.DeactivateBody(action="anonymize"), admin={"user_id": 1}
    )

    assert calls["anonymize"] == [5]
    assert calls["sessions"] == [5]
    assert calls["keys"] == [5]


def test_reactivate_no_revoca_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    """No hay credencial que invalidar al restaurar una cuenta."""
    calls = _stub_admin_deactivate(monkeypatch)

    admin_users.admin_deactivate_user(
        5, admin_users.DeactivateBody(action="reactivate"), admin={"user_id": 1}
    )

    assert calls["reactivate"] == [5]
    assert calls["sessions"] == []
    assert calls["keys"] == []


# ---------------------------------------------------------------------------
# A3 — rotar una API key exige step-up de sesión
# ---------------------------------------------------------------------------


def test_rotate_exige_key_id_explicito() -> None:
    """Con sesión no hay key de origen implícita: hay que indicar cuál rotar."""
    with pytest.raises(HTTPException) as exc:
        me_routes.rotate_my_key(ctx={"user_id": 4, "auth_method": "session"}, key_id=None)

    assert exc.value.status_code == 400


def test_rotate_rechaza_key_de_otro_usuario(monkeypatch: pytest.MonkeyPatch) -> None:
    """El step-up prueba quién pide la rotación, no que la key sea suya."""
    monkeypatch.setattr(me_routes, "_get_user_id_from_key_id", lambda key_id: 99)

    with pytest.raises(HTTPException) as exc:
        me_routes.rotate_my_key(ctx={"user_id": 4, "auth_method": "session"}, key_id=11)

    assert exc.value.status_code == 404


def test_rotate_usa_step_up_de_sesion() -> None:
    """La ruta cuelga de ``require_recent_session``, no del scope de la key."""
    ctx_param = inspect.signature(me_routes.rotate_my_key).parameters["ctx"]

    assert ctx_param.default.dependency.__name__ == "require_recent_session"


def test_rotate_rota_la_key_propia(monkeypatch: pytest.MonkeyPatch) -> None:
    """Camino feliz: expira la key indicada y emite una nueva para el usuario."""
    expiries: list[tuple[int, str]] = []
    creadas: list[dict[str, Any]] = []
    monkeypatch.setattr(me_routes, "_get_user_id_from_key_id", lambda key_id: 4)
    monkeypatch.setattr(me_routes, "get_key_name_and_scopes", lambda key_id: ("mi-key", "read"))
    monkeypatch.setattr(
        me_routes, "set_key_expiry", lambda key_id, expires: expiries.append((key_id, expires))
    )
    monkeypatch.setattr(
        me_routes,
        "create_api_key",
        lambda **kw: (creadas.append(kw), "token-nuevo")[1],
    )
    monkeypatch.setattr(me_routes, "log_event", lambda **kw: None)

    # ``grace_days`` hay que pasarlo explícito: llamando a la función fuera de
    # FastAPI el default sigue siendo el objeto ``Query``, no el 7.
    resultado = me_routes.rotate_my_key(
        ctx={"user_id": 4, "auth_method": "session", "email": "u@example.com"},
        key_id=11,
        grace_days=7,
    )

    assert resultado["new_token"] == "token-nuevo"
    assert expiries[0][0] == 11
    assert creadas[0]["user_id"] == 4
    assert creadas[0]["scopes"] == "read"


# ---------------------------------------------------------------------------
# A4 — is_admin de OAuth sincroniza en ambos sentidos
# ---------------------------------------------------------------------------


def test_oauth_admin_promueve_si_esta_en_la_lista(monkeypatch: pytest.MonkeyPatch) -> None:
    """Email en OAUTH_ADMIN_EMAILS → is_admin True."""
    llamadas: list[tuple[int, bool]] = []
    monkeypatch.setattr(settings, "OAUTH_ADMIN_EMAILS", "jefe@example.com")
    monkeypatch.setattr(auth_routes, "set_admin", lambda uid, value: llamadas.append((uid, value)))

    auth_routes._sync_oauth_admin(3, "jefe@example.com")

    assert llamadas == [(3, True)]


def test_oauth_admin_degrada_si_salio_de_la_lista(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sacar a alguien de la lista sí le quita admin en su próximo login."""
    llamadas: list[tuple[int, bool]] = []
    monkeypatch.setattr(settings, "OAUTH_ADMIN_EMAILS", "jefe@example.com")
    monkeypatch.setattr(auth_routes, "set_admin", lambda uid, value: llamadas.append((uid, value)))

    auth_routes._sync_oauth_admin(3, "exjefe@example.com")

    assert llamadas == [(3, False)]


def test_oauth_admin_no_toca_nada_si_la_lista_esta_vacia(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lista vacía significa "OAuth no gobierna el flag", no "nadie es admin"."""
    llamadas: list[tuple[int, bool]] = []
    monkeypatch.setattr(settings, "OAUTH_ADMIN_EMAILS", "")
    monkeypatch.setattr(auth_routes, "set_admin", lambda uid, value: llamadas.append((uid, value)))

    auth_routes._sync_oauth_admin(3, "quien@example.com")

    assert llamadas == []
