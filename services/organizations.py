"""Autorización de organizaciones independiente del frontend."""

from __future__ import annotations

from db.repositories.organizations import OrganizationRepository
from db.users import get_active_user_by_email_ci
from observability.logging import get_logger
from shared.dto import (
    OrganizationMembershipOut,
    OrganizationMembershipUpsert,
    OrganizationSettings,
    OrganizationSettingsOut,
    OrganizationSummary,
)

_repo = OrganizationRepository()


log = get_logger(__name__)


class OrganizationAccessError(PermissionError):
    """El usuario no es miembro activo de la organización."""


class OrganizationPermissionError(PermissionError):
    """La membresía existe, pero su rol no permite la operación."""


class OrganizationMemberNotFoundError(LookupError):
    """No existe una cuenta activa con el correo indicado."""


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


# ── Configuración de producto de la organización ───────────────────────────


def _tecnologias_disponibles() -> list[str]:
    from config.keywords import TECHNOLOGY_KEYWORDS

    return sorted(TECHNOLOGY_KEYWORDS.keys())


def get_settings(user_id: int, organization_id: int) -> OrganizationSettingsOut:
    """Configuración de la organización; cualquier miembro activo puede leerla."""
    resolve_organization(user_id, organization_id)
    raw = _repo.get_settings(organization_id)
    parsed = OrganizationSettings.model_validate({"tecnologias": raw.get("tecnologias") or []})
    return OrganizationSettingsOut(
        organization_id=organization_id,
        tecnologias=parsed.tecnologias,
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
    merged = _repo.update_settings(organization_id, {"tecnologias": body.tecnologias})
    return OrganizationSettingsOut(
        organization_id=organization_id,
        tecnologias=list(merged.get("tecnologias") or []),
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

    if not _repo.borrar(organization_id):
        raise OrganizationMemberNotFoundError("La organización no existe.")

    log.info("organization_deleted", organization_id=organization_id, **conteos)
    return conteos
