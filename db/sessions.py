"""Gestión de sesiones server-side con revocación.

Tabla ``sessions``:
  token_hash       TEXT PK     — SHA-256 del token raw (nunca almacenar el token)
  user_id          INTEGER     — FK a users
  created_at       TEXT        — instante del login; NUNCA se toca después
  expires_at       TEXT        — plazo de inactividad (deslizante, ver abajo)
  ip               TEXT
  user_agent       TEXT
  revoked          INTEGER     — 0/1
  revoked_at       TEXT
  last_seen_at     TEXT        — última petición validada (escritura throttled)
  mfa_verified_at  TEXT        — última elevación de segundo factor

Modelo de caducidad (Ola 1 · sesiones deslizantes)
--------------------------------------------------

Una sesión vive mientras se use, con un techo. Tres plazos, todos en
``config/settings.py``:

* **Ventana de inactividad** (``SESSION_IDLE_HOURS``): ``expires_at`` es
  ``última escritura + ventana``. Cada petición validada que pase el throttle
  vuelve a ponerlo en ``now + ventana`` en el mismo ``UPDATE`` que refresca
  ``last_seen_at`` — un solo viaje a BD, ninguna consulta extra.
* **Techo absoluto** (``SESSION_ABSOLUTE_DAYS``): ``created_at + techo``. La
  renovación nunca lo supera (``min(now + ventana, techo)``) y la validación
  rechaza toda sesión que lo haya cruzado aunque esté fresca por actividad. No
  se persiste: se deriva de ``created_at``, que no cambia nunca.
* **«Recordar este equipo»** (``SESSION_REMEMBER_DAYS``): la tabla no tiene
  columna para la elección, así que se implementa como una ventana de
  inactividad más larga (en días) **con el mismo techo absoluto** que el resto.
  Con los valores por defecto (90 d de ventana, 30 d de techo) una sesión
  recordada no caduca por inactividad: muere a los 30 días del login. Para
  saber en la renovación qué ventana aplica sin una columna, se lee la que
  dejó la última escritura: ``expires_at - last_seen_at`` (ambos salen del
  mismo ``UPDATE``). Si esa distancia supera la ventana corta, la sesión es
  «recordada». La única ambigüedad posible —una sesión recordada tan cerca del
  techo que la distancia ya no supera la ventana corta— es inocua: en ese
  tramo ``min(now + ventana, techo)`` devuelve el techo con cualquiera de las
  dos ventanas.

``require_recent_session`` (``api/routes/dual_auth.py``) sigue mirando
``created_at`` (``authenticated_at``) y ``mfa_verified_at``: la renovación no
toca ninguno de los dos, así que una sesión de hace tres semanas, por viva que
esté, sigue exigiendo reautenticación para las acciones sensibles.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from config.settings import settings
from db.database import connect, now_utc_iso
from observability.logging import get_logger

log = get_logger(__name__)

# Cada request autenticada refrescaba ``last_seen_at``. Escribir en cada
# petición no aporta precisión: solo convierte toda lectura autenticada en una
# escritura. Se refresca —y con ello se renueva ``expires_at``— como mucho una
# vez por minuto.
_LAST_SEEN_THROTTLE_SECONDS = 60


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _as_utc(value: str) -> datetime:
    """Parsea un timestamp ISO de la BD como datetime aware en UTC."""
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


# ---------------------------------------------------------------------------
# Plazos (leídos de settings en cada llamada: los tests los monkeypatchean)
# ---------------------------------------------------------------------------


def _idle_window() -> timedelta:
    """Ventana de inactividad de una sesión normal."""
    return timedelta(hours=settings.SESSION_IDLE_HOURS)


def _remember_window() -> timedelta:
    """Ventana de inactividad de una sesión «recordada»; nunca menor que la normal."""
    return max(timedelta(days=settings.SESSION_REMEMBER_DAYS), _idle_window())


def _absolute_ceiling(created_at: datetime) -> datetime:
    """Techo absoluto: pasado este instante no hay renovación posible."""
    return created_at + timedelta(days=settings.SESSION_ABSOLUTE_DAYS)


def _window_in_effect(expires_at: datetime, last_seen: datetime | None) -> timedelta:
    """Ventana que dejó la última escritura, deducida de la propia fila.

    ``expires_at`` y ``last_seen_at`` se escriben juntos, así que su distancia
    es la ventana vigente. Si supera la ventana corta, la sesión se creó con
    «recordar este equipo». Filas anteriores a este modelo (``expires_at`` fijo
    a 24 h del login, ``last_seen_at`` throttled) caen en la ventana corta.
    """
    idle = _idle_window()
    if last_seen is not None and expires_at - last_seen > idle:
        return _remember_window()
    return idle


def _renewed_expiry(now: datetime, created_at: datetime, window: timedelta) -> datetime:
    """``min(now + ventana, techo)``: el plazo tras una petición validada."""
    return min(now + window, _absolute_ceiling(created_at))


def session_max_age_seconds() -> int:
    """Vida máxima posible de una sesión, en segundos (``max_age`` de la cookie).

    La cookie tiene que sobrevivir a todas las renovaciones: si el navegador la
    tirara al cumplirse la ventana de inactividad, la renovación en servidor no
    serviría de nada. Quien decide que la sesión sigue viva es el servidor, no
    el navegador; la cookie solo dura lo que la sesión *podría* durar.
    """
    return settings.SESSION_ABSOLUTE_DAYS * 86_400


def create_session(
    user_id: int,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
    remember: bool = False,
    ttl_hours: int | None = None,
) -> str:
    """Crea una nueva sesión y devuelve el token raw (guardar en cookie).

    ``expires_at`` nace en ``now + ventana`` (la normal o, con ``remember``, la
    de «recordar este equipo»), nunca más allá del techo absoluto. ``ttl_hours``
    es un override explícito de esa ventana inicial para tests y scripts; no
    cambia el techo ni la ventana con que se renovará después.
    """
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    now = datetime.now(UTC)
    if ttl_hours is not None:
        window = timedelta(hours=ttl_hours)
    else:
        window = _remember_window() if remember else _idle_window()
    expires = _renewed_expiry(now, now, window)

    with connect() as c:
        c.execute(
            "INSERT INTO sessions "
            "(token_hash, user_id, created_at, expires_at, ip, user_agent, last_seen_at, revoked) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 0)",
            (
                token_hash,
                user_id,
                now.isoformat(),
                expires.isoformat(),
                ip,
                (user_agent or "")[:512],
                now.isoformat(),
            ),
        )
    return token


def validate_session(token: str) -> dict[str, Any] | None:
    """Verifica token, devuelve datos de sesión o None si inválida/expirada.

    Camino legado (``validate_session_principal`` es el que recorre el SPA);
    aplica el mismo modelo: rechazo por revocación, por plazo de inactividad o
    por techo absoluto, y renovación throttled de ``expires_at``.
    """
    token_hash = _hash_token(token)
    with connect() as c:
        row = c.execute(
            "SELECT user_id, created_at, expires_at, revoked, ip, last_seen_at, mfa_verified_at "
            "FROM sessions WHERE token_hash = %s",
            (token_hash,),
        ).fetchone()
    if row is None:
        return None
    user_id, created_at, expires_at, revoked, ip, last_seen_at, mfa_verified_at = row
    if revoked:
        return None
    now = datetime.now(UTC)
    try:
        created = _as_utc(created_at)
        exp = _as_utc(expires_at)
        last_seen = _as_utc(last_seen_at) if last_seen_at else None
    except Exception:
        # Camino de autenticación: sin log, un fallo de BD se presenta al
        # usuario como "sesión inválida" y nadie puede distinguirlo de un
        # token realmente caducado.
        log.warning("session_validation_failed", exc_info=True)
        return None

    if now > exp or now > _absolute_ceiling(created):
        revoke_session(token)
        return None

    if last_seen is None or (now - last_seen).total_seconds() >= _LAST_SEEN_THROTTLE_SECONDS:
        renewed = _renewed_expiry(now, created, _window_in_effect(exp, last_seen))
        with connect() as c:
            c.execute(
                "UPDATE sessions SET last_seen_at = %s, expires_at = %s "
                "WHERE token_hash = %s AND revoked = 0",
                (now.isoformat(), renewed.isoformat(), token_hash),
            )
        expires_at = renewed.isoformat()
    return {
        "user_id": user_id,
        "authenticated_at": created_at,
        "expires_at": expires_at,
        "ip": ip,
        "mfa_verified_at": mfa_verified_at,
    }


def validate_session_principal(token: str) -> dict[str, Any] | None:
    """Valida la sesión y devuelve sesión + usuario + estado MFA en UNA consulta.

    Es el camino que recorre **toda** petición autenticada por cookie del SPA.
    Componerlo con ``validate_session`` + ``get_user_by_id`` +
    ``is_totp_required`` costaba de 3 a 5 aperturas de conexión en serie, cada
    una con su transacción de escritura: a los ~80 ms de RTT contra Supabase,
    varias décimas de segundo gastadas antes de empezar el trabajo real de la
    petición. Aquí es un SELECT con dos LEFT JOIN.

    Además lee ``totp_secrets.confirmed`` sin descifrar el secreto:
    ``is_totp_required`` pasaba por ``get_totp_secret``, que descifra el TOTP
    entero para acabar mirando un booleano.

    Devuelve ``None`` si la sesión no existe, está revocada, superó su plazo de
    inactividad (``expires_at``) o el techo absoluto (en ambos casos la revoca
    en la misma transacción, para que ninguna renovación posterior la reviva)
    o su usuario está desactivado. El llamador no distingue entre esos casos a
    propósito: todos son "sesión inválida" y detallarlos filtra si la cuenta
    existe.

    Si la sesión es válida y pasó el throttle, renueva ``expires_at`` a
    ``min(now + ventana, techo)`` en el mismo ``UPDATE`` de ``last_seen_at``.
    """
    token_hash = _hash_token(token)
    now = datetime.now(UTC)

    with connect() as c:
        row = c.execute(
            "SELECT s.user_id, s.created_at, s.expires_at, s.revoked, s.ip, "
            "       s.last_seen_at, s.mfa_verified_at, "
            "       u.id, u.email, u.display_name, u.is_admin, u.deactivated_at, "
            "       COALESCE(t.confirmed, 0) "
            "FROM sessions s "
            "LEFT JOIN users u ON u.id = s.user_id "
            "LEFT JOIN totp_secrets t ON t.user_id = s.user_id "
            "WHERE s.token_hash = %s",
            (token_hash,),
        ).fetchone()
        if row is None:
            return None

        (
            user_id,
            created_at,
            expires_at,
            revoked,
            ip,
            last_seen_at,
            mfa_verified_at,
            u_id,
            email,
            display_name,
            is_admin,
            deactivated_at,
            totp_confirmed,
        ) = row

        if revoked:
            return None

        try:
            created = _as_utc(created_at)
            exp = _as_utc(expires_at)
            last_seen = _as_utc(last_seen_at) if last_seen_at else None
        except Exception:
            # Camino de autenticación: un fallo al interpretar las marcas de
            # tiempo se presenta como "sesión inválida", indistinguible para el
            # usuario de un token caducado. Queda constancia en el log.
            log.warning("session_validation_failed", exc_info=True)
            return None

        # Plazo de inactividad o techo absoluto: fuera, aunque el otro plazo
        # siga vivo. Se revoca para que la fila no pueda volver a validarse
        # nunca (una fecha se puede reescribir; la revocación es definitiva).
        if now > exp or now > _absolute_ceiling(created):
            c.execute(
                "UPDATE sessions SET revoked = 1, revoked_at = %s WHERE token_hash = %s",
                (now.isoformat(), token_hash),
            )
            return None

        # Usuario inexistente o desactivado: la sesión ya no vale.
        if u_id is None or deactivated_at is not None:
            return None

        stale = (
            last_seen is None or (now - last_seen).total_seconds() >= _LAST_SEEN_THROTTLE_SECONDS
        )
        if stale:
            renewed = _renewed_expiry(now, created, _window_in_effect(exp, last_seen))
            c.execute(
                "UPDATE sessions SET last_seen_at = %s, expires_at = %s "
                "WHERE token_hash = %s AND revoked = 0",
                (now.isoformat(), renewed.isoformat(), token_hash),
            )
            expires_at = renewed.isoformat()

    return {
        "user_id": user_id,
        "authenticated_at": created_at,
        "expires_at": expires_at,
        "ip": ip,
        "mfa_verified_at": mfa_verified_at,
        "id": u_id,
        "email": email,
        "display_name": display_name,
        "is_admin": bool(is_admin),
        "mfa_required": bool(totp_confirmed),
    }


def mark_session_mfa_verified(token: str) -> None:
    """Eleva la sesión actual tras verificar un segundo factor."""
    token_hash = _hash_token(token)
    with connect() as c:
        c.execute(
            "UPDATE sessions SET mfa_verified_at = %s WHERE token_hash = %s AND revoked = 0",
            (now_utc_iso(), token_hash),
        )


def revoke_session(token: str) -> None:
    """Revoca una sesión específica (logout)."""
    token_hash = _hash_token(token)
    with connect() as c:
        c.execute(
            "UPDATE sessions SET revoked = 1, revoked_at = %s WHERE token_hash = %s",
            (now_utc_iso(), token_hash),
        )


def revoke_all_sessions(user_id: int) -> int:
    """Revoca todas las sesiones activas de un usuario (logout-all). Devuelve N."""
    with connect() as c:
        cur = c.execute(
            "UPDATE sessions SET revoked = 1, revoked_at = %s WHERE user_id = %s AND revoked = 0",
            (now_utc_iso(), user_id),
        )
        return cur.rowcount if hasattr(cur, "rowcount") else 0


def purge_expired_sessions() -> int:
    """Elimina sesiones expiradas/revocadas. Llamar en mantenimiento periódico.

    Además de las revocadas y las que llevan 30 días caducadas por
    ``expires_at``, borra las que superaron el techo absoluto hace 30 días:
    ninguna renovación las puede revivir y ``expires_at`` no lo refleja en
    filas escritas antes de este modelo o retocadas a mano.
    """
    now = datetime.now(UTC)
    cutoff = (now - timedelta(days=30)).isoformat()
    ceiling_cutoff = (now - timedelta(days=settings.SESSION_ABSOLUTE_DAYS + 30)).isoformat()
    with connect() as c:
        cur = c.execute(
            "DELETE FROM sessions WHERE expires_at < %s OR created_at < %s OR revoked = 1",
            (cutoff, ceiling_cutoff),
        )
        return cur.rowcount if hasattr(cur, "rowcount") else 0


#: Longitud del identificador público de una sesión (C2.1).
#:
#: Un prefijo del hash SHA-256, no el token: el token abre la sesión y no puede
#: salir del navegador ni una vez. El hash tampoco se expone entero — no abre
#: nada, pero no hay razón para publicarlo y sí para no acostumbrarse a hacerlo.
#: Doce caracteres hexadecimales son 48 bits: la colisión entre las sesiones
#: activas de UN usuario es una posibilidad teórica sin consecuencia práctica, y
#: el `DELETE` valida además la pertenencia.
SESSION_PUBLIC_ID_LEN = 12


def session_public_id(token_hash: str) -> str:
    """Identificador estable y no reversible de una sesión, para la API."""
    return token_hash[:SESSION_PUBLIC_ID_LEN]


def revoke_session_by_public_id(user_id: int, public_id: str) -> bool:
    """Revoca UNA sesión del usuario por su id público (C2.1).

    Devuelve ``False`` si no existe o no es suya. El `user_id` en el `WHERE` no
    es decorativo: sin él, cualquiera con un id público cerraría la sesión de
    otro, y esos ids se pueden enumerar.

    Las demás sesiones no se tocan — es la diferencia con `revoke_all_sessions`,
    que hasta 2026-09 era la única forma de cerrar una sesión que no fuera la
    propia.
    """
    if not public_id or len(public_id) < SESSION_PUBLIC_ID_LEN:
        return False
    with connect() as c:
        cur = c.execute(
            "UPDATE sessions SET revoked = 1, revoked_at = %s "
            "WHERE user_id = %s AND revoked = 0 AND left(token_hash, %s) = %s",
            (now_utc_iso(), user_id, SESSION_PUBLIC_ID_LEN, public_id),
        )
        return bool(getattr(cur, "rowcount", 0))


def list_active_sessions(user_id: int) -> list[dict[str, Any]]:
    """Lista sesiones activas y no expiradas de un usuario.

    ``expires_at`` es el plazo de inactividad vigente (se renueva con el uso),
    no la vida máxima: esa es ``created_at`` + ``SESSION_ABSOLUTE_DAYS``.
    """
    now = datetime.now(UTC).isoformat()
    with connect() as c:
        cur = c.execute(
            "SELECT token_hash, created_at, expires_at, ip, user_agent "
            "FROM sessions "
            "WHERE user_id = %s AND revoked = 0 AND expires_at > %s "
            "ORDER BY created_at DESC",
            (user_id, now),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
