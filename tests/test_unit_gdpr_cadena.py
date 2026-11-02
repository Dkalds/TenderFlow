"""El derecho al olvido y el de acceso, sin BD (hallazgos ``privacidad-logs-gdpr-*``).

Cubre el orden de la cadena de borrado que ejecuta un administrador (gdpr-2), el
bloqueo del borrado del único owner de una organización compartida (gdpr-11) y
que el export de ``GET /me/data`` entrega los ficheros que faltaban y avisa de
las secciones truncadas (gdpr-7). Las consultas SQL que respaldan esto —nombre
de la organización personal, export de ex-miembros, retención— están en
``tests/test_gdpr_cadena.py`` (necesitan Postgres).
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pytest
from fastapi import HTTPException

import services.gdpr as gdpr
from api.routes import me
from shared.identity import user_key_from_email

# ── Cadena de borrado del administrador (gdpr-2) ───────────────────────────


def test_la_baja_del_panel_borra_los_datos_antes_de_anonimizar_la_cuenta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`anonymize_user` borra el correo; las invitaciones y la clave se sacan de él."""
    llamadas: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(
        gdpr,
        "anonymize_user_data",
        lambda *a, **k: llamadas.append(("datos", a, k)),
    )
    monkeypatch.setattr("db.users.anonymize_user", lambda *a: llamadas.append(("cuenta", a, {})))

    gdpr.anonymize_account(7, "Persona@Example.test")

    assert [nombre for nombre, _, _ in llamadas] == ["datos", "cuenta"]
    _, args, kwargs = llamadas[0]
    assert args == (user_key_from_email("persona@example.test", 7),)
    assert kwargs == {"user_id": 7}
    assert llamadas[1][1] == (7,)


def test_la_cadena_de_borrado_alcanza_tareas_y_segundo_factor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`PursuitTasksRepository.anonymize_user_references` era código muerto."""
    hecho: list[str] = []

    class Repo:
        def __getattr__(self, nombre: str) -> Any:
            return lambda *a, **k: hecho.append(nombre)

    for atributo in (
        "_watchlist_repo",
        "_feedback_repo",
        "_pursuit_repo",
        "_pursuit_comment_repo",
        "_pursuit_task_repo",
        "_organization_repo",
        "_api_key_repo",
    ):
        monkeypatch.setattr(gdpr, atributo, Repo())
    monkeypatch.setattr(gdpr, "delete_totp", lambda uid: hecho.append(f"delete_totp:{uid}"))
    monkeypatch.setattr(gdpr.radar_dismissals, "delete_all_for_user", lambda *a, **k: 0)
    for modulo, funcion in (
        ("services.watchlist_rules", "delete_all_for_user"),
        ("db.saved_filters", "delete_all_for_user"),
        ("services.notifications", "delete_all_alerts"),
        ("services.notifications", "delete_email_prefs"),
        ("db.repositories.follows", "borrar_de_usuario"),
        ("db.repositories.asistente_feedback", "borrar_de_usuario"),
        ("db.repositories.notification_preferences", "borrar_de_usuario"),
    ):
        monkeypatch.setattr(f"{modulo}.{funcion}", lambda *a, **k: 0)
    monkeypatch.setattr(gdpr, "delete_user_profile", lambda *a, **k: None)

    gdpr.anonymize_user_data("clave", user_id=9)

    assert "delete_totp:9" in hecho
    # `anonymize_user_references` de pursuits Y de tareas.
    assert hecho.count("anonymize_user_references") == 2
    assert "remove_memberships_for_user" in hecho


# ── Único owner (gdpr-11) ──────────────────────────────────────────────────


def _ctx(user_id: int = 42) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "user_key": "clave-opaca",
        "email": "yo@example.test",
        "auth_method": "session",
    }


def test_no_se_borra_la_cuenta_del_unico_owner_de_una_organizacion_compartida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(me, "organizaciones_con_unico_owner", lambda uid: [12, 31])
    borrado: list[str] = []
    monkeypatch.setattr(me, "anonymize_user_data", lambda *a, **k: borrado.append("datos"))

    with pytest.raises(HTTPException) as exc:
        me.delete_my_data(me.DeleteMyDataRequest(confirmation="DELETE"), _ctx())

    assert exc.value.status_code == 409
    assert "12, 31" in str(exc.value.detail)
    assert borrado == []


def test_sin_organizaciones_huerfanas_el_borrado_sigue_adelante(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pasos: list[str] = []
    monkeypatch.setattr(me, "organizaciones_con_unico_owner", lambda uid: [])
    monkeypatch.setattr(me, "anonymize_user_data", lambda *a, **k: pasos.append("datos"))
    monkeypatch.setattr("db.users.anonymize_user", lambda uid: pasos.append("cuenta"))
    monkeypatch.setattr(me, "revoke_all_sessions", lambda uid: pasos.append("sesiones") or 0)
    monkeypatch.setattr(me, "revoke_all_api_keys_for_user", lambda uid: pasos.append("keys") or 0)
    monkeypatch.setattr(me, "log_event", lambda **k: None)

    me.delete_my_data(me.DeleteMyDataRequest(confirmation="DELETE"), _ctx())

    assert pasos == ["datos", "cuenta", "sesiones", "keys"]


# ── Export completo y límites declarados (gdpr-7) ──────────────────────────


def test_secciones_truncadas_solo_lista_las_que_llegan_al_tope() -> None:
    secciones = {
        "audit": [{}] * gdpr.EXPORT_TOPES["audit"],
        "pursuits": [{}] * (gdpr.EXPORT_TOPES["pursuits"] - 1),
        "accesos": [],
        "organization_memberships": [{}] * 10_000,  # sin tope declarado
    }

    assert gdpr.secciones_truncadas(secciones) == {"audit": gdpr.EXPORT_TOPES["audit"]}


def test_la_sesion_se_exporta_con_su_id_publico_y_sin_el_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("db.users.export_account", lambda uid: [{"id": uid}])
    monkeypatch.setattr("db.users.export_access_log", lambda uid: [])
    monkeypatch.setattr(
        "db.sessions.list_active_sessions",
        lambda uid: [{"token_hash": "a" * 64, "ip": "10.0.0.1", "created_at": "2026-01-01"}],
    )
    monkeypatch.setattr("db.repositories.notification_preferences.listar", lambda uid: [])
    monkeypatch.setattr(gdpr.radar_dismissals, "list_detalle", lambda *a, **k: [])
    monkeypatch.setattr("db.repositories.asistente_feedback.exportar_de_usuario", lambda uid: [])
    monkeypatch.setattr(gdpr._pursuit_task_repo, "export_for_user", lambda uid: [])

    cuenta = gdpr.export_account_data(3, "clave")

    assert set(cuenta) == {
        "cuenta",
        "accesos",
        "sesiones",
        "preferencias_notificacion",
        "descartes_radar",
        "asistente_feedback",
        "pursuit_tasks",
    }
    (sesion,) = cuenta["sesiones"]
    assert "token_hash" not in sesion
    assert sesion["ip"] == "10.0.0.1"
    assert sesion["id"] and sesion["id"] != "a" * 64


def test_el_export_incluye_los_ficheros_nuevos_y_avisa_de_los_topes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for nombre in (
        "export_watchlist",
        "export_watchlist_items",
        "export_follows",
        "export_watchlist_rules",
        "export_saved_filters",
        "export_user_notifications",
    ):
        monkeypatch.setattr(me, nombre, lambda *a, **k: [])
    monkeypatch.setattr(me, "export_user_profile", lambda *a, **k: None)
    monkeypatch.setattr(me, "export_feedback", lambda uid: [])
    monkeypatch.setattr(me, "export_audit_log", lambda *a, **k: [{}] * gdpr.EXPORT_TOPES["audit"])
    monkeypatch.setattr(
        me, "export_collaboration_data", lambda uid: {"organization_memberships": []}
    )
    monkeypatch.setattr(
        me, "export_account_data", lambda uid, key: {"cuenta": [{"id": uid}], "accesos": []}
    )
    monkeypatch.setattr(me._key_repo, "get_all_for_user", lambda uid: [])
    monkeypatch.setattr(me, "log_event", lambda **k: None)

    respuesta = me.export_my_data(_ctx(5))

    with zipfile.ZipFile(io.BytesIO(bytes(respuesta.body))) as zf:
        nombres = set(zf.namelist())
        meta = json.loads(zf.read("metadata.json"))
        cuenta = json.loads(zf.read("cuenta.json"))
    assert {"cuenta.json", "accesos.json", "audit.json", "metadata.json"} <= nombres
    assert cuenta == [{"id": 5}]
    assert meta["truncated_sections"] == {"audit": gdpr.EXPORT_TOPES["audit"]}


# ── client_errors: texto de un anónimo (gdpr-10) ───────────────────────────


def test_el_mensaje_de_un_error_de_cliente_se_redacta_antes_de_persistirse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routes import security

    recibidos: list[dict[str, Any]] = []
    monkeypatch.setattr(security, "registrar_client_error", lambda **k: recibidos.append(k))
    monkeypatch.setattr(
        security,
        "get_rate_limiter",
        lambda: type("Limitador", (), {"check": lambda self, *a, **k: True})(),
    )
    app = FastAPI()
    app.include_router(security.router, prefix="/api/v1")

    resp = TestClient(app).post(
        "/api/v1/security/client-error",
        json={"message": "No se pudo cargar el perfil de ana@example.test"},
    )

    assert resp.status_code == 204
    (registro,) = recibidos
    assert "ana@example.test" not in registro["mensaje"]
    assert "perfil" in registro["mensaje"]
