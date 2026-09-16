"""Sesiones deslizantes (Ola 1): renovación, techo absoluto y «recordar este equipo».

Fija el modelo de ``db/sessions.py``:

* ``expires_at`` es el plazo de inactividad y se renueva a ``now + ventana``
  con cada petición validada que pase el throttle, en el mismo ``UPDATE`` que
  ``last_seen_at``;
* ``created_at + SESSION_ABSOLUTE_DAYS`` es el techo que ninguna renovación
  supera y pasado el cual la sesión se rechaza aunque esté fresca;
* ``remember`` alarga la ventana de inactividad con el mismo techo, y la
  renovación reconoce esa ventana sin columna propia;
* y lo que NO cambia: ``require_recent_session`` sigue mirando ``created_at``
  y ``mfa_verified_at``, que la renovación no toca.

Las filas se «envejecen» reescribiendo sus marcas de tiempo: es lo que dejaría
una sesión real tras días de uso o de abandono, sin esperar días en el test.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from config.settings import settings
from db.database import connect

_VALID_PASSWORD = "P@ssw0rd1234"  # pragma: allowlist secret


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_user(email: str = "user@example.com") -> int:
    from db.users import create_user

    return create_user(
        email=email,
        password_hash="hash-irrelevante",  # pragma: allowlist secret
        display_name="Nombre Visible",
    )


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _row(token: str) -> tuple[datetime, datetime, datetime | None, int, str | None]:
    """``(created_at, expires_at, last_seen_at, revoked, mfa_verified_at)`` de la fila."""
    from db.sessions import _hash_token

    with connect() as c:
        row = c.execute(
            "SELECT created_at, expires_at, last_seen_at, revoked, mfa_verified_at "
            "FROM sessions WHERE token_hash = %s",
            (_hash_token(token),),
        ).fetchone()
    assert row is not None
    created, expires, last_seen, revoked, mfa = row
    return (
        _parse(created),
        _parse(expires),
        (_parse(last_seen) if last_seen else None),
        revoked,
        mfa,
    )


def _age_row(
    token: str,
    *,
    created: datetime | None = None,
    expires: datetime | None = None,
    last_seen: datetime | None = None,
) -> None:
    """Reescribe las marcas indicadas (las demás se conservan)."""
    from db.sessions import _hash_token

    with connect() as c:
        c.execute(
            "UPDATE sessions SET "
            "created_at = COALESCE(%s, created_at), "
            "expires_at = COALESCE(%s, expires_at), "
            "last_seen_at = COALESCE(%s, last_seen_at) "
            "WHERE token_hash = %s",
            (
                created.isoformat() if created else None,
                expires.isoformat() if expires else None,
                last_seen.isoformat() if last_seen else None,
                _hash_token(token),
            ),
        )


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


def test_create_session_nace_con_la_ventana_de_inactividad(tmp_db: object) -> None:
    from db.sessions import create_session

    token = create_session(_make_user())
    created, expires, last_seen, _, _ = _row(token)

    assert expires - created == timedelta(hours=settings.SESSION_IDLE_HOURS)
    assert expires < created + timedelta(days=settings.SESSION_ABSOLUTE_DAYS)
    assert last_seen == created


def test_remember_alarga_la_ventana_sin_mover_el_techo(tmp_db: object) -> None:
    """Con los defaults (90 d > 30 d) la ventana recordada queda en el techo."""
    from db.sessions import create_session

    token = create_session(_make_user(), remember=True)
    created, expires, _, _, _ = _row(token)

    assert expires - created > timedelta(hours=settings.SESSION_IDLE_HOURS)
    assert expires == created + timedelta(days=settings.SESSION_ABSOLUTE_DAYS)


def test_remember_usa_su_propia_ventana_si_cabe_bajo_el_techo(
    tmp_db: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from db.sessions import create_session

    monkeypatch.setattr(settings, "SESSION_REMEMBER_DAYS", 7)
    monkeypatch.setattr(settings, "SESSION_ABSOLUTE_DAYS", 30)

    token = create_session(_make_user(), remember=True)
    created, expires, _, _, _ = _row(token)

    assert expires - created == timedelta(days=7)


# ---------------------------------------------------------------------------
# renovación
# ---------------------------------------------------------------------------


def test_renovacion_extiende_expires_at(tmp_db: object) -> None:
    """Pasado el throttle, ``expires_at`` vuelve a ``now + ventana``."""
    from db.sessions import create_session, validate_session_principal

    token = create_session(_make_user())
    now = datetime.now(UTC)
    _age_row(token, last_seen=now - timedelta(minutes=10), expires=now + timedelta(hours=1))

    principal = validate_session_principal(token)

    assert principal is not None
    _, expires, last_seen, _, _ = _row(token)
    assert expires >= now + timedelta(hours=settings.SESSION_IDLE_HOURS)
    assert last_seen is not None and last_seen >= now
    # La respuesta lleva el plazo ya renovado, no el que se leyó.
    assert _parse(principal["expires_at"]) == expires


def test_renovacion_tambien_en_validate_session(tmp_db: object) -> None:
    """El camino legado aplica el mismo modelo que el principal."""
    from db.sessions import create_session, validate_session

    token = create_session(_make_user())
    now = datetime.now(UTC)
    _age_row(token, last_seen=now - timedelta(minutes=10), expires=now + timedelta(hours=1))

    result = validate_session(token)

    assert result is not None
    _, expires, _, _, _ = _row(token)
    assert expires >= now + timedelta(hours=settings.SESSION_IDLE_HOURS)
    assert _parse(result["expires_at"]) == expires


def test_renovacion_respeta_el_throttle(tmp_db: object) -> None:
    """Dentro del minuto de throttle no se escribe: ni ``last_seen_at`` ni ``expires_at``."""
    from db.sessions import create_session, validate_session_principal

    token = create_session(_make_user())
    _, expires_antes, last_seen_antes, _, _ = _row(token)

    assert validate_session_principal(token) is not None

    _, expires_despues, last_seen_despues, _, _ = _row(token)
    assert expires_despues == expires_antes
    assert last_seen_despues == last_seen_antes


def test_renovacion_no_supera_el_techo(tmp_db: object) -> None:
    """A una hora del techo, ``now + 24 h`` se recorta a ``created_at + techo``."""
    from db.sessions import create_session, validate_session_principal

    token = create_session(_make_user())
    now = datetime.now(UTC)
    created = now - timedelta(days=settings.SESSION_ABSOLUTE_DAYS) + timedelta(hours=1)
    _age_row(
        token,
        created=created,
        last_seen=now - timedelta(minutes=10),
        expires=now + timedelta(minutes=30),
    )

    assert validate_session_principal(token) is not None

    created_db, expires, _, _, _ = _row(token)
    assert created_db == created
    assert expires == created + timedelta(days=settings.SESSION_ABSOLUTE_DAYS)
    assert expires < now + timedelta(hours=settings.SESSION_IDLE_HOURS)


def test_remember_renueva_con_su_propia_ventana(
    tmp_db: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La ventana recordada se reconoce en la fila y se vuelve a aplicar al renovar."""
    from db.sessions import create_session, validate_session_principal

    monkeypatch.setattr(settings, "SESSION_REMEMBER_DAYS", 7)
    monkeypatch.setattr(settings, "SESSION_ABSOLUTE_DAYS", 30)

    token = create_session(_make_user(), remember=True)
    now = datetime.now(UTC)
    # Un día sin usarla: la distancia expires_at - last_seen_at sigue siendo 7 d.
    _age_row(token, last_seen=now - timedelta(days=1), expires=now + timedelta(days=6))

    assert validate_session_principal(token) is not None

    _, expires, _, _, _ = _row(token)
    assert expires >= now + timedelta(days=7)


def test_filas_anteriores_al_modelo_renuevan_con_la_ventana_corta(tmp_db: object) -> None:
    """Una sesión creada con el TTL fijo de 24 h pasa a deslizante sin migración."""
    from db.sessions import create_session, validate_session_principal

    token = create_session(_make_user())
    now = datetime.now(UTC)
    created = now - timedelta(hours=20)
    _age_row(
        token,
        created=created,
        last_seen=now - timedelta(hours=2),
        expires=created + timedelta(hours=24),
    )

    assert validate_session_principal(token) is not None

    _, expires, _, _, _ = _row(token)
    assert expires >= now + timedelta(hours=settings.SESSION_IDLE_HOURS)


# ---------------------------------------------------------------------------
# rechazo por techo o por inactividad
# ---------------------------------------------------------------------------


def test_sesion_mas_alla_del_techo_se_rechaza_aunque_este_fresca(tmp_db: object) -> None:
    from db.sessions import create_session, validate_session_principal

    token = create_session(_make_user())
    now = datetime.now(UTC)
    _age_row(
        token,
        created=now - timedelta(days=settings.SESSION_ABSOLUTE_DAYS + 1),
        last_seen=now - timedelta(seconds=5),
        expires=now + timedelta(hours=12),
    )

    assert validate_session_principal(token) is None

    _, _, _, revoked, _ = _row(token)
    assert revoked, "una sesión pasada de techo queda revocada, no solo rechazada"


def test_validate_session_tambien_aplica_el_techo(tmp_db: object) -> None:
    from db.sessions import create_session, validate_session

    token = create_session(_make_user())
    now = datetime.now(UTC)
    _age_row(
        token,
        created=now - timedelta(days=settings.SESSION_ABSOLUTE_DAYS + 1),
        last_seen=now,
        expires=now + timedelta(hours=12),
    )

    assert validate_session(token) is None
    assert _row(token)[3]


def test_sesion_inactiva_se_rechaza_aunque_no_llegue_al_techo(tmp_db: object) -> None:
    from db.sessions import create_session, validate_session_principal

    token = create_session(_make_user())
    now = datetime.now(UTC)
    _age_row(token, last_seen=now - timedelta(days=2), expires=now - timedelta(days=1))

    assert validate_session_principal(token) is None
    assert _row(token)[3]


# ---------------------------------------------------------------------------
# lo que no cambia: created_at, mfa_verified_at y require_recent_session
# ---------------------------------------------------------------------------


def test_renovacion_no_toca_created_at_ni_mfa_verified_at(tmp_db: object) -> None:
    from db.sessions import create_session, mark_session_mfa_verified, validate_session_principal

    token = create_session(_make_user())
    mark_session_mfa_verified(token)
    created_antes, _, _, _, mfa_antes = _row(token)
    assert mfa_antes
    _age_row(token, last_seen=datetime.now(UTC) - timedelta(minutes=10))

    principal = validate_session_principal(token)

    assert principal is not None
    created_despues, _, _, _, mfa_despues = _row(token)
    assert created_despues == created_antes
    assert mfa_despues == mfa_antes
    assert _parse(principal["authenticated_at"]) == created_antes
    assert principal["mfa_verified_at"] == mfa_antes


def test_require_recent_session_sigue_exigiendo_login_reciente(tmp_db: object) -> None:
    """Una sesión viva por renovación no es una sesión recién autenticada."""
    from api.routes.dual_auth import require_recent_session
    from db.sessions import create_session, validate_session_principal

    dependency = require_recent_session()

    fresca = create_session(_make_user("fresca@example.com"))
    principal = validate_session_principal(fresca)
    assert principal is not None
    ctx = asyncio.run(dependency({**principal, "auth_method": "session"}))
    assert ctx["user_id"] == principal["user_id"]

    vieja = create_session(_make_user("vieja@example.com"))
    now = datetime.now(UTC)
    _age_row(
        vieja,
        created=now - timedelta(seconds=settings.SENSITIVE_ACTION_MAX_AGE_SECONDS + 60),
        last_seen=now - timedelta(minutes=10),
        expires=now + timedelta(hours=1),
    )
    principal_vieja = validate_session_principal(vieja)
    assert principal_vieja is not None, "sigue siendo una sesión válida"

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(dependency({**principal_vieja, "auth_method": "session"}))
    assert excinfo.value.status_code == 403
    assert "Reauthenticate" in str(excinfo.value.detail)


# ---------------------------------------------------------------------------
# purga, cookie y ruta de login
# ---------------------------------------------------------------------------


def test_purge_borra_sesiones_mas_alla_del_techo(tmp_db: object) -> None:
    from db.sessions import _hash_token, create_session, purge_expired_sessions

    token = create_session(_make_user())
    now = datetime.now(UTC)
    _age_row(
        token,
        created=now - timedelta(days=settings.SESSION_ABSOLUTE_DAYS + 31),
        expires=now + timedelta(days=1),  # fecha retocada: el techo manda igual
    )

    assert purge_expired_sessions() >= 1
    with connect() as c:
        row = c.execute(
            "SELECT 1 FROM sessions WHERE token_hash = %s", (_hash_token(token),)
        ).fetchone()
    assert row is None


def test_session_max_age_seconds_es_el_techo(monkeypatch: pytest.MonkeyPatch) -> None:
    from db.sessions import session_max_age_seconds

    assert session_max_age_seconds() == settings.SESSION_ABSOLUTE_DAYS * 86_400
    monkeypatch.setattr(settings, "SESSION_ABSOLUTE_DAYS", 2)
    assert session_max_age_seconds() == 2 * 86_400


def _ultima_sesion(email: str) -> tuple[datetime, datetime]:
    with connect() as c:
        row = c.execute(
            "SELECT s.created_at, s.expires_at FROM sessions s "
            "JOIN users u ON u.id = s.user_id "
            "WHERE u.email = %s ORDER BY s.id DESC LIMIT 1",
            (email,),
        ).fetchone()
    assert row is not None
    return _parse(row[0]), _parse(row[1])


def _max_age_de_la_cookie_session(headers: list[str]) -> int:
    for header in headers:
        if not header.startswith("session="):
            continue
        for attr in header.split(";"):
            nombre, _, valor = attr.strip().partition("=")
            if nombre.lower() == "max-age":
                return int(valor)
    raise AssertionError(f"sin Max-Age en la cookie de sesión: {headers}")


def test_login_remember_alarga_la_sesion_y_la_cookie_dura_el_techo(client) -> None:
    """``remember`` es opcional (compatible hacia atrás) y alarga la ventana."""
    email = "recordar@example.com"
    r_reg = client.post("/api/v1/auth/register", json={"email": email, "password": _VALID_PASSWORD})
    assert r_reg.status_code == 201, r_reg.text

    r_normal = client.post("/api/v1/auth/login", json={"email": email, "password": _VALID_PASSWORD})
    assert r_normal.status_code == 200, r_normal.text
    created, expires = _ultima_sesion(email)
    assert expires - created == timedelta(hours=settings.SESSION_IDLE_HOURS)

    r_remember = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _VALID_PASSWORD, "remember": True},
    )
    assert r_remember.status_code == 200, r_remember.text
    created, expires = _ultima_sesion(email)
    assert expires - created > timedelta(hours=settings.SESSION_IDLE_HOURS)
    assert expires <= created + timedelta(days=settings.SESSION_ABSOLUTE_DAYS)

    # La cookie dura lo máximo que la sesión podría durar en ambos casos.
    techo = settings.SESSION_ABSOLUTE_DAYS * 86_400
    assert _max_age_de_la_cookie_session(r_normal.headers.get_list("set-cookie")) == techo
    assert _max_age_de_la_cookie_session(r_remember.headers.get_list("set-cookie")) == techo
