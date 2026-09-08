"""Autorización de organizaciones independiente del frontend."""

from __future__ import annotations

import hashlib
import html
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

from db.repositories.organizations import OrganizationRepository
from db.users import get_active_user_by_email_ci
from observability.logging import get_logger
from shared.dto import (
    OrganizationInvitationOut,
    OrganizationMembershipOut,
    OrganizationMembershipUpsert,
    OrganizationSettings,
    OrganizationSettingsOut,
    OrganizationSummary,
)
from shared.signing import sign, verify

log = get_logger(__name__)

_repo = OrganizationRepository()

#: Vida del enlace de invitación. Siete días es lo que el plan fija y lo que
#: aguanta un fin de semana largo sin obligar a reenviar.
INVITATION_TTL_DAYS = 7


log = get_logger(__name__)


class OrganizationAccessError(PermissionError):
    """El usuario no es miembro activo de la organización."""


class OrganizationPermissionError(PermissionError):
    """La membresía existe, pero su rol no permite la operación."""


class OrganizationMemberNotFoundError(LookupError):
    """No existe una cuenta activa con el correo indicado."""


class OrganizationInvitationNotFoundError(LookupError):
    """El token no corresponde a ninguna invitación viva: usado, caducado o falso."""


def resolve_organization(
    user_id: int,
    organization_id: int | None,
    *,
    write: bool = False,
) -> tuple[int, str]:
    """Resuelve organización explícita o personal y valida el rol."""
    if organization_id is None:
        personal = _repo.ensure_personal_organization(user_id)
        return int(personal["id"]), str(personal["role"])

    membership = _repo.get_active_membership(organization_id, user_id)
    if membership is None:
        raise OrganizationAccessError("No perteneces a esta organización.")
    role = str(membership["role"])
    if write and role == "viewer":
        raise OrganizationPermissionError("El rol viewer es de solo lectura.")
    return organization_id, role


def require_active_member(organization_id: int, user_id: int) -> None:
    """Valida que un responsable pertenezca activamente al equipo."""
    if _repo.get_active_membership(organization_id, user_id) is None:
        raise OrganizationAccessError(
            "La persona responsable debe ser miembro activo de la organización."
        )


def list_organizations(user_id: int) -> list[OrganizationSummary]:
    """Lista scopes activos; garantiza que el personal exista."""
    _repo.ensure_personal_organization(user_id)
    return [OrganizationSummary.model_validate(row) for row in _repo.list_for_user(user_id)]


def create_organization(user_id: int, name: str) -> OrganizationSummary:
    return OrganizationSummary.model_validate(_repo.create_organization(name.strip(), user_id))


def get_active_organization(user_id: int, organization_id: int | None) -> OrganizationSummary:
    resolved_id, _ = resolve_organization(user_id, organization_id)
    row = _repo.get_for_user(resolved_id, user_id)
    if row is None:
        raise OrganizationAccessError("No perteneces a esta organización.")
    return OrganizationSummary.model_validate(row)


def list_members(user_id: int, organization_id: int) -> list[OrganizationMembershipOut]:
    resolve_organization(user_id, organization_id)
    return [
        OrganizationMembershipOut.model_validate(row) for row in _repo.list_members(organization_id)
    ]


def _guard_owner_row(organization_id: int, target_user_id: int) -> None:
    """Impide degradar o revocar una fila owner desde este flujo.

    La transferencia de propiedad queda fuera de alcance a propósito; el
    único camino para dejar de ser owner sigue siendo uno no expuesto aquí.
    """
    existing = _repo.get_active_membership(organization_id, target_user_id)
    if existing is not None and str(existing["role"]) == "owner":
        raise OrganizationPermissionError(
            "El owner no puede degradarse ni revocarse desde este flujo."
        )


def upsert_membership(
    user_id: int,
    organization_id: int,
    body: OrganizationMembershipUpsert,
) -> OrganizationMembershipOut:
    _, role = resolve_organization(user_id, organization_id)
    if role not in {"owner", "admin"}:
        raise OrganizationPermissionError("Solo owner o admin puede gestionar miembros.")
    if body.role == "owner" and role != "owner":
        raise OrganizationPermissionError("Solo un owner puede asignar otro owner.")
    _guard_owner_row(organization_id, body.user_id)
    row = _repo.add_membership(
        organization_id,
        body.user_id,
        body.role,
        invited_by_user_id=user_id,
        status=body.status,
    )
    return OrganizationMembershipOut.model_validate(row)


def add_member_by_email(
    user_id: int,
    organization_id: int,
    email: str,
    role: str,
) -> OrganizationMembershipOut:
    """Incorpora a un usuario ya registrado a una organización compartida.

    Solo admite ``admin``, ``member`` o ``viewer`` (ver
    :class:`shared.dto.OrganizationMemberInvite`): asignar ``owner`` por este
    camino queda fuera de alcance a propósito.
    """
    _, acting_role = resolve_organization(user_id, organization_id)
    if acting_role not in {"owner", "admin"}:
        raise OrganizationPermissionError("Solo owner o admin puede gestionar miembros.")
    target = get_active_user_by_email_ci(email)
    if target is None:
        raise OrganizationMemberNotFoundError(
            "No existe una cuenta activa con ese correo. La persona debe registrarse primero."
        )
    _guard_owner_row(organization_id, int(target["id"]))
    row = _repo.add_membership(
        organization_id,
        int(target["id"]),
        role,
        invited_by_user_id=user_id,
        status="active",
    )
    return OrganizationMembershipOut.model_validate(row)


def claim_legacy_scope(user_id: int, user_key: str) -> None:
    _repo.claim_legacy_rows(user_id, user_key)


# ── Invitaciones a correos sin cuenta (S1.1) ───────────────────────────────


def _invitation_token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _issue_invitation_token() -> tuple[str, str]:
    """Genera ``(token_bruto, hash)``. El bruto solo viaja en el correo.

    Formato ``{nonce}.{kid}.{sig}``: la firma de :mod:`shared.signing` lleva el
    ``kid``, así que rotar ``SIGNING_KEY`` no invalida los enlaces ya enviados
    mientras la clave anterior siga registrada. La firma **no** es lo que hace
    el token de un solo uso —eso es la fila de ``organization_invitations``—:
    es lo que permite descartar basura sin ir a la BD y lo que impide que
    alguien fabrique un token con un nonce inventado.
    """
    nonce = secrets.token_urlsafe(32)
    raw = f"{nonce}.{sign(nonce.encode('utf-8'))}"
    return raw, _invitation_token_hash(raw)


def _invitation_signature_valid(raw: str) -> bool:
    nonce, separador, firma = raw.partition(".")
    if not separador or not nonce:
        return False
    return verify(nonce.encode("utf-8"), firma)


def _invitation_status(row: dict[str, Any]) -> str:
    """Estado derivado de las tres marcas de tiempo de la fila."""
    if row.get("accepted_at") is not None:
        return "accepted"
    if row.get("revoked_at") is not None:
        return "revoked"
    expires_at = row.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at <= datetime.now(UTC):
        return "expired"
    return "invited"


def _to_invitation_dto(row: dict[str, Any]) -> OrganizationInvitationOut:
    """Proyección explícita, campo a campo.

    Antes volcaba la fila entera (``{**row, ...}``) y eso fallaba con
    ``extra_forbidden``: ``organization_invitations`` guarda además
    ``accepted_user_id`` y ``revoked_at``, contabilidad interna que el estado
    derivado ya resume y que el contrato no publica. El ``extra="forbid"`` del
    DTO hizo su trabajo —falló en vez de publicar de más—, pero la red no es el
    sitio donde se arregla esto: se enumera lo que sale.

    Enumerar también protege del caso que importa. ``db/repositories``
    proyecta con ``_INVITATION_COLUMNS`` y no con ``SELECT *`` precisamente
    para que ``token_hash`` no salga de ``db/``; si algún día esa proyección
    creciera, aquí no se colaría por arrastre.
    """
    return OrganizationInvitationOut.model_validate(
        {
            "id": row["id"],
            "organization_id": row["organization_id"],
            "email": row["email"],
            "role": row["role"],
            "status": _invitation_status(row),
            "invited_by_user_id": row.get("invited_by_user_id"),
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "accepted_at": row.get("accepted_at"),
        }
    )


def _require_manager(user_id: int, organization_id: int) -> None:
    """Solo owner o admin gestionan invitaciones; un ``member`` recibe 403."""
    _, role = resolve_organization(user_id, organization_id)
    if role not in {"owner", "admin"}:
        raise OrganizationPermissionError("Solo owner o admin puede gestionar miembros.")


def _send_invitation_email(email: str, organization_name: str, token: str) -> bool:
    """Entrega el enlace sin escribir el token en logs ni en ningún otro sitio.

    Va en la misma llamada que crea la fila (y por tanto en el hilo de
    ``run_db``, con el techo de 15 s del SMTP) y no en un ``BackgroundTask``
    como el correo de recuperación de contraseña. La diferencia es el volumen:
    invitar es una acción puntual de un administrador, mientras que la
    recuperación la dispara cualquiera desde una pantalla anónima y sí puede
    llegar en ráfagas. Si el envío falla, la invitación queda creada y
    «Reenviar» en ``/equipo`` es el reintento.
    """
    from observability.alerts import enviar_email_transaccional
    from services.solicitudes_acceso import url_de_login

    login_url = url_de_login()
    if not login_url:
        log.error("organization_invite_frontend_url_unavailable")
        return False
    invite_url = f"{login_url}?invitacion={quote(token)}"

    texto = "\n".join(
        [
            f"Te han invitado a unirte a «{organization_name}» en TenderFlow.",
            "",
            f"El enlace caduca en {INVITATION_TTL_DAYS} días y solo puede usarse una vez.",
            "",
            invite_url,
            "",
            "Si no esperabas esta invitación, ignora este correo.",
        ]
    )
    cuerpo_html = (
        "<!DOCTYPE html><html><body>"
        f"<p>Te han invitado a unirte a «{html.escape(organization_name)}» en TenderFlow.</p>"
        f"<p>El enlace caduca en {INVITATION_TTL_DAYS} días y solo puede usarse una vez.</p>"
        f'<p><a href="{html.escape(invite_url)}">Aceptar la invitación</a></p>'
        "<p>Si no esperabas esta invitación, ignora este correo.</p>"
        "</body></html>"
    )
    enviado = enviar_email_transaccional(
        to_addr=email,
        subject=f"Te han invitado a {organization_name} en TenderFlow",
        texto=texto,
        html=cuerpo_html,
    )
    # Dominio y no dirección: basta para diagnosticar entregas y no deja PII
    # en los logs, igual que en `services/password_reset.py`.
    log.info("organization_invite_email", sent=enviado, domain=email.rpartition("@")[2] or "?")
    return enviado


def invite_member_by_email(
    user_id: int,
    organization_id: int,
    email: str,
    role: str,
) -> OrganizationMembershipOut | OrganizationInvitationOut:
    """Incorpora a alguien al equipo: en el acto si tiene cuenta, invitado si no.

    Es la composición que sirve ``POST /organizations/{id}/members``, y por eso
    no está dentro de :func:`add_member_by_email`: esa función sigue siendo el
    camino «esta persona ya existe», con su contrato intacto para quien lo
    llame directamente.
    """
    try:
        return add_member_by_email(user_id, organization_id, email, role)
    except OrganizationMemberNotFoundError:
        return create_invitation(user_id, organization_id, email, role)


def create_invitation(
    user_id: int,
    organization_id: int,
    email: str,
    role: str,
) -> OrganizationInvitationOut:
    """Crea (o renueva) la invitación pendiente de un correo sin cuenta."""
    _require_manager(user_id, organization_id)
    if role not in {"admin", "member", "viewer"}:
        raise ValueError("Rol de invitación no admitido.")
    organization = _repo.get_for_user(organization_id, user_id)
    if organization is None:
        raise OrganizationAccessError("No perteneces a esta organización.")

    token, token_hash = _issue_invitation_token()
    row = _repo.create_invitation(
        organization_id,
        email,
        role,
        token_hash=token_hash,
        invited_by_user_id=user_id,
        expires_at=datetime.now(UTC) + timedelta(days=INVITATION_TTL_DAYS),
    )
    _send_invitation_email(email, str(organization["name"]), token)
    return _to_invitation_dto(row)


def list_invitations(user_id: int, organization_id: int) -> list[OrganizationInvitationOut]:
    """Invitaciones pendientes del equipo. Solo owner/admin: son correos ajenos."""
    _require_manager(user_id, organization_id)
    return [_to_invitation_dto(row) for row in _repo.list_invitations(organization_id)]


def resend_invitation(
    user_id: int, organization_id: int, invitation_id: int
) -> OrganizationInvitationOut:
    """Emite un token nuevo para la misma persona y vuelve a mandar el correo.

    El token anterior deja de valer: reenviar es «este enlace no le llegó», y
    dejar vivos los dos multiplicaría las ventanas de uso sin ninguna ventaja.
    """
    _require_manager(user_id, organization_id)
    existente = _repo.get_invitation(organization_id, invitation_id)
    if existente is None or _invitation_status(existente) not in {"invited", "expired"}:
        raise OrganizationInvitationNotFoundError("La invitación ya no está pendiente.")
    return create_invitation(
        user_id, organization_id, str(existente["email"]), str(existente["role"])
    )


def revoke_invitation(user_id: int, organization_id: int, invitation_id: int) -> None:
    _require_manager(user_id, organization_id)
    if not _repo.revoke_invitation(organization_id, invitation_id, user_id):
        raise OrganizationInvitationNotFoundError("La invitación ya no está pendiente.")


def accept_invitations_for_email(user_id: int, email: str | None) -> int:
    """Activa las invitaciones vivas del correo con el que alguien acaba de entrar.

    Se llama desde el alta local y desde el callback OAuth. Nunca propaga: una
    invitación que no se pudo canjear no puede dejar a nadie sin poder entrar en
    su propia cuenta, y el siguiente inicio de sesión lo reintenta.
    """
    if not email:
        return 0
    try:
        aceptadas = _repo.accept_invitations_for_email(email, user_id)
    except Exception:
        log.exception("organization_invite_autoaccept_failed", user_id=user_id)
        return 0
    if aceptadas:
        log.info("organization_invite_accepted", user_id=user_id, count=len(aceptadas))
    return len(aceptadas)


def accept_invitation_token(user_id: int, email: str | None, token: str) -> OrganizationSummary:
    """Canjea el enlace del correo desde una sesión ya iniciada.

    El token solo vale para la persona a la que se invitó: sin esa comprobación
    un enlace reenviado por error metería a un tercero en el equipo.
    """
    if not _invitation_signature_valid(token):
        raise OrganizationInvitationNotFoundError("El enlace no es válido o ha caducado.")
    row = _repo.get_pending_invitation_by_token(_invitation_token_hash(token))
    if row is None:
        raise OrganizationInvitationNotFoundError("El enlace no es válido o ha caducado.")
    if not email or str(row["email"]).lower() != email.strip().lower():
        raise OrganizationPermissionError(
            "Esta invitación es para otra dirección de correo. Inicia sesión con ella."
        )
    _repo.accept_invitations_for_email(email, user_id)
    organization = _repo.get_for_user(int(row["organization_id"]), user_id)
    if organization is None:
        raise OrganizationInvitationNotFoundError("La invitación ya no está pendiente.")
    return OrganizationSummary.model_validate(organization)


# ── Configuración de producto de la organización ───────────────────────────


def _tecnologias_disponibles() -> list[str]:
    from config.keywords import TECHNOLOGY_KEYWORDS

    return sorted(TECHNOLOGY_KEYWORDS.keys())


def ajustes_guardados(raw: dict[str, Any], organization_id: int) -> OrganizationSettings:
    """Los ajustes persistidos, sin dejar que una clave rara tire el resto.

    ``settings_json`` es JSON libre y ``OrganizationSettings`` declara
    ``extra="forbid"``: validar el blob entero haría que una clave de otra
    versión —o de una que se retire— tirase la configuración completa,
    tecnologías incluidas. Se validan las claves que este build conoce y las
    demás se ignoran **al leer**; siguen guardadas, porque el repositorio
    fusiona en vez de reemplazar.
    """
    # Un `null` guardado se trata como «no está»: la clave existía con valor
    # nulo en filas viejas, y validarla tiraría toda la configuración por un
    # campo que sólo significaba «sin definir».
    conocidas = {
        k: v for k, v in raw.items() if k in OrganizationSettings.model_fields and v is not None
    }
    try:
        return OrganizationSettings.model_validate(conocidas)
    except ValidationError:
        log.warning(
            "organization_settings_invalidos", organization_id=organization_id, exc_info=True
        )
        return OrganizationSettings()


def get_settings(user_id: int, organization_id: int) -> OrganizationSettingsOut:
    """Configuración de la organización; cualquier miembro activo puede leerla."""
    resolve_organization(user_id, organization_id)
    parsed = ajustes_guardados(_repo.get_settings(organization_id), organization_id)
    return OrganizationSettingsOut(
        organization_id=organization_id,
        **parsed.model_dump(),
        tecnologias_disponibles=_tecnologias_disponibles(),
    )


def update_settings(
    user_id: int, organization_id: int, body: OrganizationSettings
) -> OrganizationSettingsOut:
    """Escribe la configuración. Sólo owner/admin: es la estrategia del equipo.

    Las familias se validan contra el diccionario (``config/keywords.py``): una
    familia que no existe no filtraría nada y dejaría el Radar vacío sin que
    nadie supiera por qué.
    """
    _, role = resolve_organization(user_id, organization_id, write=True)
    if role not in {"owner", "admin"}:
        raise OrganizationPermissionError(
            "Solo owner o admin pueden cambiar la configuración de la organización."
        )
    disponibles = set(_tecnologias_disponibles())
    desconocidas = sorted(set(body.tecnologias) - disponibles)
    if desconocidas:
        raise ValueError(f"Tecnologías desconocidas: {', '.join(desconocidas)}.")
    # Se escribe el cuerpo entero, no sólo `tecnologias`: el DTO declara el
    # ámbito de mercado (F6.1) y las probabilidades por etapa (F4.1), y
    # guardar una sola clave devolvía 200 habiendo tirado el resto en
    # silencio —el administrador veía su configuración aceptada y el Radar
    # seguía sin acotar—.
    merged = _repo.update_settings(organization_id, body.model_dump(mode="json"))
    guardados = ajustes_guardados(merged, organization_id)
    return OrganizationSettingsOut(
        organization_id=organization_id,
        **guardados.model_dump(),
        tecnologias_disponibles=sorted(disponibles),
    )


# ── Ciclo de vida de la organización (C2.2, ADR-030 §D) ─────────────────────
#
# Hasta 2026-09 no había traspaso de owner ni borrado de organización: cero
# coincidencias de `transfer` y `delete_organization` (hecho 8 del plan), y el
# propio `_guard_owner_row` lo reconocía en su docstring — «la transferencia de
# propiedad queda fuera de alcance a propósito».
#
# La consecuencia práctica: una organización cuyo owner se va queda sin nadie
# que pueda administrarla, y una que ya no se usa no se puede cerrar. Las dos
# son situaciones que ocurren solas con el tiempo.

#: Texto que el owner tiene que escribir para borrar una organización.
#:
#: El nombre de la propia organización, no un «SÍ» genérico: obliga a mirar cuál
#: se está borrando. Con dos pestañas abiertas y dos organizaciones parecidas,
#: un «¿seguro?» no distingue nada.
CONFIRMACION_BORRADO = "BORRAR"


class OrganizationLifecycleError(ValueError):
    """Una transición del ciclo de vida que no se puede hacer."""


def transferir_propiedad(
    *, organization_id: int, actor_user_id: int, nuevo_owner_user_id: int
) -> None:
    """Traspasa la propiedad a otro miembro activo (C2.2).

    Reglas, y cada una responde a un modo de fallo concreto:

    - **Solo el owner traspasa.** Un admin que pudiera hacerlo se autoascendería.
    - **El destino tiene que ser miembro activo.** Invitar y traspasar son cosas
      distintas: hacerlas de una convertiría un error de tipeo en el email en
      una organización cuyo owner no existe.
    - **La personal no se traspasa.** Es el contenedor por defecto de una
      cuenta; regalarla dejaría al usuario sin sitio donde escribir.
    - El owner saliente queda como `admin`, no fuera: quien monta un equipo no
      debería perder el acceso al traspasarlo.
    """
    if actor_user_id == nuevo_owner_user_id:
        raise OrganizationLifecycleError("El owner ya eres tú.")

    membresia = _repo.get_active_membership(organization_id, actor_user_id)
    if membresia is None or str(membresia["role"]) != "owner":
        raise OrganizationPermissionError("Solo el owner puede traspasar la propiedad.")

    if _repo.es_personal(organization_id):
        raise OrganizationLifecycleError(
            "La organización personal no se puede traspasar: es el contenedor "
            "por defecto de tu cuenta."
        )

    if not _repo.traspasar_propiedad(
        organization_id, de_user_id=actor_user_id, a_user_id=nuevo_owner_user_id
    ):
        raise OrganizationMemberNotFoundError(
            "El destinatario no es miembro activo de esta organización. Invitalo primero."
        )
    log.info(
        "organization_ownership_transferred",
        organization_id=organization_id,
        de=actor_user_id,
        a=nuevo_owner_user_id,
    )


def salir_de_organizacion(*, organization_id: int, user_id: int) -> None:
    """Salida voluntaria de un miembro (C2.2).

    El owner **no puede irse sin traspasar**: dejar una organización sin owner la
    deja sin nadie que pueda administrarla, y el estado no tiene salida desde el
    producto. El mensaje lo dice en vez de devolver un 403 mudo.
    """
    membresia = _repo.get_active_membership(organization_id, user_id)
    if membresia is None:
        raise OrganizationMemberNotFoundError("No eres miembro de esta organización.")

    if str(membresia["role"]) == "owner":
        raise OrganizationLifecycleError(
            "Sos el owner: traspasá la propiedad a otro miembro antes de salir, "
            "o borrá la organización."
        )

    if _repo.es_personal(organization_id):
        raise OrganizationLifecycleError("No podés salir de tu organización personal.")

    _repo.salir(organization_id, user_id)
    log.info("organization_member_left", organization_id=organization_id, user_id=user_id)


def resumen_de_borrado(*, organization_id: int, actor_user_id: int) -> dict[str, int]:
    """Qué se llevaría por delante el borrado. Lo enseña la confirmación.

    «Vas a borrar 14 oportunidades y 37 comentarios» es una advertencia;
    «¿seguro?» no es nada.
    """
    membresia = _repo.get_active_membership(organization_id, actor_user_id)
    if membresia is None or str(membresia["role"]) != "owner":
        raise OrganizationPermissionError("Solo el owner puede borrar la organización.")
    return _repo.contar_dato_corporativo(organization_id)


def borrar_organizacion(
    *, organization_id: int, actor_user_id: int, confirmacion: str
) -> dict[str, int]:
    """Borra la organización y su dato corporativo (C2.2, ADR-030 §D).

    Exige que el owner escriba :data:`CONFIRMACION_BORRADO`. Una confirmación
    literal y no un botón porque la acción no tiene deshacer y se lleva trabajo
    de otras personas.

    **Qué se borra y qué no** lo fija ADR-030 §D: el dato corporativo
    —oportunidades, comentarios, capacidades, claves de organización— muere con
    ella, porque sin la organización no tiene dueño. El dato personal de cada
    miembro —perfil, favoritos, reglas, notas privadas— cuelga del usuario y
    sobrevive.

    Devuelve el recuento de lo borrado, para el registro de auditoría.
    """
    if confirmacion.strip() != CONFIRMACION_BORRADO:
        raise OrganizationLifecycleError(f"Para borrar hay que escribir «{CONFIRMACION_BORRADO}».")

    conteos = resumen_de_borrado(organization_id=organization_id, actor_user_id=actor_user_id)

    if _repo.es_personal(organization_id):
        raise OrganizationLifecycleError(
            "La organización personal no se borra: borrá la cuenta con "
            "`DELETE /me` si es lo que querés."
        )

    # Los binarios de los adjuntos propios (C6.3) se purgan ANTES de borrar la
    # fila: después, el `ON DELETE CASCADE` ya se ha llevado las claves y el
    # bucket se queda con objetos que nadie puede volver a nombrar. Es la única
    # parte del dato corporativo que no vive en Postgres, así que es la única
    # que el cascade no alcanza.
    _purgar_adjuntos_de_organizacion(organization_id)

    if not _repo.borrar(organization_id):
        raise OrganizationMemberNotFoundError("La organización no existe.")

    log.info("organization_deleted", organization_id=organization_id, **conteos)
    return conteos


def _purgar_adjuntos_de_organizacion(organization_id: int) -> None:
    """Quita del almacén los binarios de los adjuntos propios de la organización.

    Best-effort y con su propio log: un bucket caído no puede impedir que el
    owner cierre su organización —eso convertiría un derecho en un trámite
    dependiente de un tercero—, pero tampoco puede pasar en silencio, porque lo
    que queda es dato del cliente en un sistema del que ya se fue.
    """
    from db.repositories.pursuit_attachments import PursuitAttachmentRepository
    from shared.object_store import purge_keys

    try:
        filas = PursuitAttachmentRepository().de_organizacion(organization_id)
        claves = [str(f["blob_key"]) for f in filas if f.get("blob_key")]
        borrados = purge_keys(claves) if claves else 0
        log.info(
            "organization_adjuntos_purgados",
            organization_id=organization_id,
            candidatos=len(claves),
            borrados=borrados,
        )
    except Exception:
        log.warning(
            "organization_adjuntos_purge_failed",
            organization_id=organization_id,
            exc_info=True,
        )
