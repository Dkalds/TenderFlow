"""Persistencia de concesiones dinámicas de acceso OAuth."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypedDict, cast

from db.database import connect, connect_read
from shared.auth_core import oauth_email_parts

AccessGrantKind = Literal["email", "domain"]


class ConcesionInvalida(ValueError):
    """La concesión pedida no se puede escribir.

    Su mensaje está escrito para el administrador: la ruta lo devuelve tal cual
    en un 422. Es un ``ValueError`` con nombre propio justo por eso —el
    manejador global de ``ValueError`` (``api/errors.py``) enmascara el mensaje
    a propósito, y aquí publicarlo es una decisión, no un descuido—.
    """


class AccessGrant(TypedDict):
    id: int
    kind: AccessGrantKind
    value: str
    active: bool
    granted_by: int | None
    #: Nombre visible (o, sin él, el correo) de quien concedió, resuelto contra
    #: ``users``. ``None`` si lo concedió el bootstrap, si la cuenta ya no
    #: existe, o cuando la fila viene de un ``RETURNING`` sin el join.
    granted_by_nombre: str | None
    created_at: str
    updated_at: str
    revoked_at: str | None


class GrantedAccessRequest(TypedDict):
    grant: AccessGrant
    email: str
    empresa: str | None
    previous_state: str


def normalize_grant(kind: AccessGrantKind, value: str) -> str:
    normalized = value.strip().lower()
    if kind == "domain":
        normalized = normalized.removeprefix("@")
    if kind == "email" and oauth_email_parts(normalized) is None:
        raise ConcesionInvalida("El email de la concesión no es una dirección válida.")
    if kind == "domain" and (not normalized or "@" in normalized or "." not in normalized):
        raise ConcesionInvalida("El dominio de la concesión no es válido.")
    return normalized


def _valor_concedible(kind: AccessGrantKind, value: str) -> str:
    """Valor normalizado de una concesión que sí se puede escribir.

    El criterio de qué no se concede (hoy: el dominio de un proveedor de correo
    público) vive en ``services/access_grants.py``; aquí solo se le pregunta. Se
    le pregunta en las dos funciones que escriben, y no en la ruta, para que
    ningún llamador pueda saltárselo.
    """
    # Diferido: `services.access_grants` importa este módulo.
    from services.access_grants import validar_concesion

    normalized = normalize_grant(kind, value)
    validar_concesion(kind, normalized)
    return normalized


def is_access_granted(email: str) -> bool:
    partes = oauth_email_parts(email)
    if partes is None:
        # Sin forma de dirección no hay nada que buscar: ni como email ni,
        # sobre todo, como dominio.
        return False
    normalized, domain = partes
    with connect_read() as connection:
        row = connection.execute(
            "SELECT 1 FROM access_grants "
            "WHERE active = TRUE AND ((kind = 'email' AND value = %s) "
            "OR (kind = 'domain' AND value = %s)) LIMIT 1",
            (normalized, domain),
        ).fetchone()
    return row is not None


def grant_access(
    kind: AccessGrantKind,
    value: str,
    *,
    granted_by: int | None,
) -> AccessGrant:
    normalized = _valor_concedible(kind, value)
    with connect() as connection:
        cursor = connection.execute(
            "INSERT INTO access_grants (kind, value, active, granted_by) "
            "VALUES (%s, %s, TRUE, %s) "
            "ON CONFLICT(kind, value) DO UPDATE SET "
            "active = TRUE, granted_by = excluded.granted_by, "
            "updated_at = NOW(), revoked_at = NULL "
            "RETURNING id, kind, value, active, granted_by, created_at, updated_at, revoked_at",
            (kind, normalized, granted_by),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("No se pudo persistir la concesión")
    return _row_to_grant(row)


def grant_access_request(
    solicitud_id: int,
    kind: AccessGrantKind,
    *,
    granted_by: int | None,
) -> GrantedAccessRequest | None:
    """Concede y marca la solicitud atendida en una única transacción.

    Lanza :class:`ConcesionInvalida` si la solicitud no da para esa concesión
    (su correo no tiene forma de dirección, o el dominio no es concedible). La
    transacción se deshace entera: ni concesión ni cambio de estado.
    """
    with connect() as connection:
        request_row = connection.execute(
            "SELECT email, empresa, estado FROM solicitudes_acceso WHERE id = %s FOR UPDATE",
            (solicitud_id,),
        ).fetchone()
        if request_row is None:
            return None
        email = str(request_row[0]).strip().lower()
        empresa = str(request_row[1]) if request_row[1] else None
        previous_state = str(request_row[2])
        partes = oauth_email_parts(email)
        if partes is None:
            # El dominio se deriva de la dirección: de una que no lo es no se
            # saca ninguno («lo que va tras el último @» sería el de otro).
            raise ConcesionInvalida("El email de la solicitud no es una dirección válida.")
        value = _valor_concedible(kind, partes[0] if kind == "email" else partes[1])
        grant_row = connection.execute(
            "INSERT INTO access_grants (kind, value, active, granted_by) "
            "VALUES (%s, %s, TRUE, %s) "
            "ON CONFLICT(kind, value) DO UPDATE SET "
            "active = TRUE, granted_by = excluded.granted_by, "
            "updated_at = NOW(), revoked_at = NULL "
            "RETURNING id, kind, value, active, granted_by, created_at, updated_at, revoked_at",
            (kind, value, granted_by),
        ).fetchone()
        if grant_row is None:
            raise RuntimeError("No se pudo persistir la concesión")
        connection.execute(
            "UPDATE solicitudes_acceso SET estado = 'atendida' WHERE id = %s",
            (solicitud_id,),
        )
    return GrantedAccessRequest(
        grant=_row_to_grant(grant_row),
        email=email,
        empresa=empresa,
        previous_state=previous_state,
    )


#: La lectura que ve el panel: la concesión con quien la concedió. El join es
#: ``LEFT``: ``granted_by`` es nulo en las del bootstrap y puede apuntar a una
#: cuenta desactivada o anonimizada, y esas filas se siguen listando.
_SELECT_CON_AUTOR = (
    "SELECT g.id, g.kind, g.value, g.active, g.granted_by, g.created_at, g.updated_at, "
    "g.revoked_at, COALESCE(u.display_name, u.email) AS granted_by_nombre "
    "FROM access_grants g LEFT JOIN users u ON u.id = g.granted_by"
)


def revoke_access(grant_id: int) -> AccessGrant | None:
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE access_grants SET active = FALSE, revoked_at = NOW(), updated_at = NOW() "
            "WHERE id = %s AND active = TRUE "
            "RETURNING id, kind, value, active, granted_by, created_at, updated_at, revoked_at",
            (grant_id,),
        )
        row = cursor.fetchone()
    return _row_to_grant(row) if row is not None else None


def reactivate_access(grant_id: int, *, granted_by: int | None) -> AccessGrant | None:
    """Vuelve a activar una concesión revocada, con quien lo hace como autor.

    Es la misma fila (``UNIQUE(kind, value)``), no una nueva: conserva su
    ``created_at`` y pasa a tener por autor a quien la reactiva. Devuelve
    ``None`` si no existe o sigue activa —reactivar lo activo no es un evento—.

    Pasa por la misma regla que una concesión nueva (``_valor_concedible``): un
    dominio que dejó de ser concedible después de concederse (hoy, el de un
    proveedor de correo público) no vuelve por aquí, y la transacción se deshace
    sin tocar la fila.
    """
    with connect() as connection:
        row = connection.execute(
            "SELECT kind, value FROM access_grants WHERE id = %s AND active = FALSE FOR UPDATE",
            (grant_id,),
        ).fetchone()
        if row is None:
            return None
        _valor_concedible(cast("AccessGrantKind", row[0]), str(row[1]))
        connection.execute(
            "UPDATE access_grants SET active = TRUE, revoked_at = NULL, granted_by = %s, "
            "updated_at = NOW() WHERE id = %s",
            (granted_by, grant_id),
        )
        fila = connection.execute(f"{_SELECT_CON_AUTOR} WHERE g.id = %s", (grant_id,)).fetchone()
    return _row_to_grant(fila) if fila is not None else None


def list_access_grants(*, include_inactive: bool = False) -> list[AccessGrant]:
    where = "" if include_inactive else "WHERE g.active = TRUE"
    with connect_read() as connection:
        rows = connection.execute(
            f"{_SELECT_CON_AUTOR} {where} ORDER BY g.active DESC, g.updated_at DESC, g.id DESC"
        ).fetchall()
    return [_row_to_grant(row) for row in rows]


def _row_to_grant(row: Sequence[object]) -> AccessGrant:
    # Las escrituras devuelven la fila con `RETURNING` (ocho columnas, sin el
    # nombre); la lectura del panel la trae con el join (nueve).
    nombre = row[8] if len(row) > 8 else None
    return AccessGrant(
        id=int(cast("int", row[0])),
        kind=cast("AccessGrantKind", row[1]),
        value=str(row[2]),
        active=bool(row[3]),
        granted_by=int(cast("int", row[4])) if row[4] is not None else None,
        granted_by_nombre=str(nombre) if nombre is not None else None,
        created_at=str(row[5]),
        updated_at=str(row[6]),
        revoked_at=str(row[7]) if row[7] is not None else None,
    )
