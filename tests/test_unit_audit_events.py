"""Catálogo de eventos de auditoría y su lectura (Ola 1 · Audit log).

Sin BD a propósito: el catálogo es un módulo de constantes, el parser del
``detail`` es una función pura y la política de scopes se decide en memoria.
"""

from __future__ import annotations

import pytest

from api.scopes import has_scope, required_scope_for_request
from db.repositories.audit import descomponer_detalle
from shared import audit_events as ev

# ── Catálogo ───────────────────────────────────────────────────────────────


def test_cada_evento_pertenece_a_una_sola_familia():
    vistos: dict[str, str] = {}
    for familia, tipos in ev.FAMILIAS.items():
        for tipo in tipos:
            assert tipo not in vistos, f"{tipo} está en {vistos[tipo]} y en {familia}"
            vistos[tipo] = familia
    assert frozenset(vistos) == ev.EVENTOS


def test_los_nombres_siguen_la_forma_familia_accion():
    for tipo in ev.EVENTOS:
        familia, punto, accion = tipo.partition(".")
        assert punto and familia and accion, tipo
        assert tipo == tipo.lower(), tipo


def test_toda_constante_publica_esta_en_el_catalogo():
    """Una constante nueva que no entre en ``FAMILIAS`` no existe para nadie."""
    constantes = {v for k, v in vars(ev).items() if k.isupper() and isinstance(v, str)}
    assert constantes == set(ev.EVENTOS)


def test_los_eventos_del_plan_estan_en_el_catalogo():
    exigidos = {
        "org.created",
        "org.deleted",
        "org.settings_updated",
        "org.nifs_updated",
        "org.capabilities_updated",
        "org.member_added",
        "org.member_role_changed",
        "org.member_removed",
        "org.ownership_transferred",
        "org.left",
        "org.invitation_sent",
        "org.invitation_resent",
        "org.invitation_revoked",
        "org.invitation_accepted",
        "auth.login_success",
        "auth.login_failed",
        "auth.logout",
        "auth.logout_all",
        "auth.password_reset_requested",
        "auth.password_reset_completed",
        "auth.totp_enabled",
        "auth.totp_disabled",
        "export.downloaded",
        "export.calendar_link_created",
        # Nombres ya persistidos antes del catálogo; se conservan.
        "auth.session_revoked",
        "api_key.created",
        "api_key.rotated",
        "api_key.revoked",
        "gdpr.export",
        "gdpr.delete",
        "feature_flag.set",
        "user.admin_changed",
        "webhook.secret_rotated",
    }
    assert exigidos <= ev.EVENTOS


def test_es_evento_conocido():
    assert ev.es_evento_conocido(ev.ORG_CREATED)
    assert not ev.es_evento_conocido("org.inventado")
    assert not ev.es_evento_conocido("")


# ── Lectura del detail persistido ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("detail", "esperado"),
    [
        (
            'event=org.created | outcome=success | resource=org:7 | {"organization_id": 7}',
            {
                "event": "org.created",
                "outcome": "success",
                "resource": "org:7",
                "detail": '{"organization_id": 7}',
            },
        ),
        # Sin payload: el detalle queda vacío, no `None`.
        (
            "event=auth.logout | outcome=success",
            {"event": "auth.logout", "outcome": "success", "detail": ""},
        ),
        # Un payload con `=` (detalles de texto de admin_users/feature_flags)
        # no se confunde con una cabecera.
        (
            "event=user.admin_changed | outcome=success | resource=user:3 | is_admin=True",
            {
                "event": "user.admin_changed",
                "outcome": "success",
                "resource": "user:3",
                "detail": "is_admin=True",
            },
        ),
        # El separador dentro del payload no lo parte.
        (
            "event=x.y | outcome=success | a | resource=org:1",
            {"event": "x.y", "outcome": "success", "detail": "a | resource=org:1"},
        ),
        # `ip` es cabecera cuando `log_event` la recibe.
        (
            "event=x.y | outcome=denied | ip=10.0.0.1 | resource=org:2 | {}",
            {
                "event": "x.y",
                "outcome": "denied",
                "ip": "10.0.0.1",
                "resource": "org:2",
                "detail": "{}",
            },
        ),
        ("", {"detail": ""}),
    ],
)
def test_descomponer_detalle(detail: str, esperado: dict[str, str]):
    assert descomponer_detalle(detail) == esperado


# ── Scope propio del export ────────────────────────────────────────────────


def test_el_export_de_auditoria_tiene_scope_propio():
    assert required_scope_for_request("GET", "/api/v1/organizations/5/audit") == "audit:read"
    assert required_scope_for_request("GET", "/api/v1/organizations/5/audit/") == "audit:read"
    # El resto del subárbol no cambia.
    assert required_scope_for_request("GET", "/api/v1/organizations/5/members") == "pursuits:read"
    assert required_scope_for_request("GET", "/api/v1/organizations") == "pursuits:read"


def test_una_key_de_lectura_del_tablero_no_alcanza_la_auditoria():
    assert not has_scope(["pursuits:read"], "audit:read")
    assert not has_scope(["data:read"], "audit:read")
    assert has_scope(["audit:read"], "audit:read")
    assert has_scope(["*"], "audit:read")
