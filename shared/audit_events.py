"""Catálogo cerrado de tipos de evento del registro de auditoría.

Hasta 2026-09 cada llamador de ``db.audit.log_event`` inventaba su propio
literal (``"feature_flag.set"``, ``"api_key.created"``…) y nada impedía que
dos rutas describieran la misma acción con dos nombres, ni que un tipo
escrito con una errata pasara desapercibido hasta que alguien filtrase por
él. Este módulo es la única lista: ``log_event`` avisa (no rompe) cuando le
llega un tipo que no está aquí, y el export por organización
(``GET /organizations/{id}/audit``) y ``docs/SECURITY.md`` enumeran lo mismo.

Convenciones
------------
* ``familia.accion``: la familia es el sujeto (``org``, ``auth``, ``api_key``,
  ``export``, ``gdpr``…) y la acción va en pasado.
* Los eventos de organización se escriben con ``resource="org:<id>"`` y el
  ``detail`` lleva **ids** —``user_id``, ``invitation_id``— y nunca correos
  (ADR-030 §D): el registro tiene que sobrevivir a un cambio de dirección y a
  una anonimización sin quedarse con dato personal.
* Los nombres que ya estaban persistidos antes del catálogo se conservan tal
  cual —``auth.session_revoked``, ``api_key.*``, ``gdpr.export``,
  ``gdpr.delete``— aunque el plan los nombrara de otra forma: renombrarlos
  partiría el rastro histórico en dos y cambiaría la etiqueta
  ``event_type`` de ``audit_events_total`` sin ganar nada.

No importa nada de ``db/`` ni de ``api/``: es una hoja del grafo a propósito,
para que ``db/audit.py`` pueda consultarlo sin ciclos.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

# ── org.* — ciclo de vida, pertenencia y configuración de la organización ──
ORG_CREATED: Final = "org.created"
ORG_DELETED: Final = "org.deleted"
ORG_SETTINGS_UPDATED: Final = "org.settings_updated"
ORG_NIFS_UPDATED: Final = "org.nifs_updated"
ORG_CAPABILITIES_UPDATED: Final = "org.capabilities_updated"
ORG_MEMBER_ADDED: Final = "org.member_added"
ORG_MEMBER_ROLE_CHANGED: Final = "org.member_role_changed"
ORG_MEMBER_REMOVED: Final = "org.member_removed"
ORG_OWNERSHIP_TRANSFERRED: Final = "org.ownership_transferred"
ORG_LEFT: Final = "org.left"
ORG_INVITATION_SENT: Final = "org.invitation_sent"
ORG_INVITATION_RESENT: Final = "org.invitation_resent"
ORG_INVITATION_REVOKED: Final = "org.invitation_revoked"
ORG_INVITATION_ACCEPTED: Final = "org.invitation_accepted"

# ── auth.* — sesión, credenciales locales y segundo factor ─────────────────
AUTH_LOGIN_SUCCESS: Final = "auth.login_success"
AUTH_LOGIN_FAILED: Final = "auth.login_failed"
AUTH_LOGOUT: Final = "auth.logout"
AUTH_LOGOUT_ALL: Final = "auth.logout_all"
# `noqa: S105`: son nombres de evento, no contraseñas; bandit se dispara por
# la palabra en el identificador.
AUTH_PASSWORD_RESET_REQUESTED: Final = "auth.password_reset_requested"  # noqa: S105
AUTH_PASSWORD_RESET_COMPLETED: Final = "auth.password_reset_completed"  # noqa: S105
AUTH_TOTP_ENABLED: Final = "auth.totp_enabled"
AUTH_TOTP_DISABLED: Final = "auth.totp_disabled"
#: Revocación de UNA sesión propia (``DELETE /me/sessions/{id}``). Ya se
#: persistía con este nombre antes del catálogo (ver docstring del módulo).
AUTH_SESSION_REVOKED: Final = "auth.session_revoked"

# ── api_key.* — credenciales de máquina ────────────────────────────────────
API_KEY_CREATED: Final = "api_key.created"
API_KEY_ROTATED: Final = "api_key.rotated"
API_KEY_REVOKED: Final = "api_key.revoked"

# ── export.* — salida de datos ─────────────────────────────────────────────
EXPORT_DOWNLOADED: Final = "export.downloaded"
EXPORT_CALENDAR_LINK_CREATED: Final = "export.calendar_link_created"

# ── gdpr.* — derechos del interesado ───────────────────────────────────────
GDPR_EXPORT: Final = "gdpr.export"
GDPR_DELETE: Final = "gdpr.delete"

# ── user.* — moderación de cuentas desde administración ────────────────────
USER_ADMIN_CHANGED: Final = "user.admin_changed"
USER_DEACTIVATE: Final = "user.deactivate"
USER_REACTIVATE: Final = "user.reactivate"
USER_ANONYMIZE: Final = "user.anonymize"

# ── acceso — solicitudes de acceso y concesiones OAuth ─────────────────────
SOLICITUD_ACCESO_ESTADO: Final = "solicitud_acceso.estado"
ACCESS_GRANT_GRANTED: Final = "access_grant.granted"
ACCESS_GRANT_REVOKED: Final = "access_grant.revoked"

# ── webhook.* ──────────────────────────────────────────────────────────────
WEBHOOK_CREATED: Final = "webhook.created"
WEBHOOK_UPDATED: Final = "webhook.updated"
WEBHOOK_DELETED: Final = "webhook.deleted"
WEBHOOK_SECRET_ROTATED: Final = "webhook.secret_rotated"  # noqa: S105 — nombre de evento

# ── configuración de producto (solo administración) ────────────────────────
FEATURE_FLAG_SET: Final = "feature_flag.set"
TECNOLOGIAS_KEYWORD_ADDED: Final = "tecnologias_keyword.added"
TECNOLOGIAS_KEYWORD_REMOVED: Final = "tecnologias_keyword.removed"
TECNOLOGIAS_KEYWORD_SEEDED: Final = "tecnologias_keyword.seeded"
EMPRESA_REVIEW_RESOLVED: Final = "empresa.review_resolved"

# ── producto — acciones de negocio que dejan rastro ────────────────────────
FEEDBACK_SUBMITTED: Final = "feedback.submitted"
PURSUIT_WEIGHTS_PROPOSAL_APPLIED: Final = "pursuit.weights_proposal_applied"
GO_NO_GO_WEIGHTS_UPDATED: Final = "go_no_go.weights_updated"


#: Catálogo por familia. Es lo que documenta ``docs/SECURITY.md`` y lo que
#: recorre el test de unicidad: cada valor aparece en una sola familia.
FAMILIAS: Final[Mapping[str, frozenset[str]]] = {
    "org": frozenset(
        {
            ORG_CREATED,
            ORG_DELETED,
            ORG_SETTINGS_UPDATED,
            ORG_NIFS_UPDATED,
            ORG_CAPABILITIES_UPDATED,
            ORG_MEMBER_ADDED,
            ORG_MEMBER_ROLE_CHANGED,
            ORG_MEMBER_REMOVED,
            ORG_OWNERSHIP_TRANSFERRED,
            ORG_LEFT,
            ORG_INVITATION_SENT,
            ORG_INVITATION_RESENT,
            ORG_INVITATION_REVOKED,
            ORG_INVITATION_ACCEPTED,
        }
    ),
    "auth": frozenset(
        {
            AUTH_LOGIN_SUCCESS,
            AUTH_LOGIN_FAILED,
            AUTH_LOGOUT,
            AUTH_LOGOUT_ALL,
            AUTH_PASSWORD_RESET_REQUESTED,
            AUTH_PASSWORD_RESET_COMPLETED,
            AUTH_TOTP_ENABLED,
            AUTH_TOTP_DISABLED,
            AUTH_SESSION_REVOKED,
        }
    ),
    "api_key": frozenset({API_KEY_CREATED, API_KEY_ROTATED, API_KEY_REVOKED}),
    "export": frozenset({EXPORT_DOWNLOADED, EXPORT_CALENDAR_LINK_CREATED}),
    "gdpr": frozenset({GDPR_EXPORT, GDPR_DELETE}),
    "user": frozenset({USER_ADMIN_CHANGED, USER_DEACTIVATE, USER_REACTIVATE, USER_ANONYMIZE}),
    "acceso": frozenset({SOLICITUD_ACCESO_ESTADO, ACCESS_GRANT_GRANTED, ACCESS_GRANT_REVOKED}),
    "webhook": frozenset(
        {WEBHOOK_CREATED, WEBHOOK_UPDATED, WEBHOOK_DELETED, WEBHOOK_SECRET_ROTATED}
    ),
    "configuracion": frozenset(
        {
            FEATURE_FLAG_SET,
            TECNOLOGIAS_KEYWORD_ADDED,
            TECNOLOGIAS_KEYWORD_REMOVED,
            TECNOLOGIAS_KEYWORD_SEEDED,
            EMPRESA_REVIEW_RESOLVED,
        }
    ),
    "producto": frozenset(
        {FEEDBACK_SUBMITTED, PURSUIT_WEIGHTS_PROPOSAL_APPLIED, GO_NO_GO_WEIGHTS_UPDATED}
    ),
}

#: Todos los tipos admitidos, sin familia. Es contra lo que valida ``log_event``.
EVENTOS: Final[frozenset[str]] = frozenset().union(*FAMILIAS.values())


def es_evento_conocido(event_type: str) -> bool:
    """¿Está ``event_type`` en el catálogo?

    La validación es *blanda* a propósito: ``log_event`` registra el evento
    igual y avisa por log. Un tipo desconocido es un bug del llamante, no un
    motivo para perder el rastro de lo que acaba de pasar.
    """
    return event_type in EVENTOS
