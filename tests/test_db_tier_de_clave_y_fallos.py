"""Contra el SQL real: tier de una clave, fallos por cuenta y enlace de reset vigente.

Tres consultas nuevas del arreglo del rate limit y del login:

* ``tier_de_clave_por_hash``: distingue la clave que no existe (o está revocada o
  caducada) de la que existe sin tope propio. El middleware solo da cubo propio a
  la segunda.
* ``fallos_recientes``: el contador por cuenta del login.
* ``reset_token_vigente``: ``POST /auth/password-reset/confirm`` mira el enlace
  antes de calcular el argon2 de la contraseña nueva.

Usan ``tmp_db``/``client``: no se ejecutan sin Postgres (``TEST_DATABASE_URL``).
"""

from __future__ import annotations


def _clave(user_id: int) -> tuple[str, str]:
    """``(token, hash)`` de una clave recién creada."""
    from api.auth import create_api_key, hash_api_key

    raw = create_api_key("tier", user_id=user_id)
    return raw, hash_api_key(raw)


def test_una_clave_viva_se_reconoce_y_una_inexistente_no(tmp_db):
    from db.repositories.api_keys import tier_de_clave_por_hash
    from db.users import create_user

    uid = create_user(email="tier@example.test", password_hash="x")  # pragma: allowlist secret
    _, hash_viva = _clave(uid)

    viva, _limite = tier_de_clave_por_hash(hash_viva)
    assert viva is True
    assert tier_de_clave_por_hash("0" * 64) == (False, None)


def test_una_clave_revocada_o_caducada_no_cuenta_como_viva(tmp_db):
    from db.database import connect
    from db.repositories.api_keys import ApiKeyRepository, tier_de_clave_por_hash
    from db.users import create_user

    uid = create_user(email="baja@example.test", password_hash="x")  # pragma: allowlist secret
    _, revocada = _clave(uid)
    _, caducada = _clave(uid)
    ApiKeyRepository().revoke(revocada)
    with connect() as c:
        c.execute(
            "UPDATE api_keys SET expires_at = %s WHERE key_hash = %s",
            ("2000-01-01T00:00:00+00:00", caducada),
        )

    assert tier_de_clave_por_hash(revocada) == (False, None)
    assert tier_de_clave_por_hash(caducada) == (False, None)


def test_un_tier_sin_tope_es_clave_viva_con_limite_none(tmp_db):
    """``enterprise`` (``per_minute_limit = 0``) no es «clave inexistente»."""
    from db.database import connect
    from db.repositories.api_keys import tier_de_clave_por_hash
    from db.users import create_user

    uid = create_user(email="ent@example.test", password_hash="x")  # pragma: allowlist secret
    _, h = _clave(uid)
    with connect() as c:
        c.execute("UPDATE api_keys SET tier = 'enterprise' WHERE key_hash = %s", (h,))

    assert tier_de_clave_por_hash(h) == (True, None)


def test_fallos_recientes_cuenta_los_de_la_ventana_y_dice_cuanto_hace_del_ultimo(tmp_db):
    from db.rate_limits import clear_login_attempts, fallos_recientes, record_failed_login

    assert fallos_recientes("c1", bucket="login_fail_cuenta", window_seconds=3600) == (0, 3600)
    for _ in range(3):
        record_failed_login("c1", bucket="login_fail_cuenta", window_seconds=3600)
    record_failed_login("otra", bucket="login_fail_cuenta", window_seconds=3600)

    fallos, hace = fallos_recientes("c1", bucket="login_fail_cuenta", window_seconds=3600)
    assert fallos == 3
    assert 0 <= hace < 5

    clear_login_attempts("c1", bucket="login_fail_cuenta")
    assert fallos_recientes("c1", bucket="login_fail_cuenta", window_seconds=3600)[0] == 0


def test_el_lockout_lee_por_el_pool_de_lectura_y_sigue_bloqueando_a_los_cinco(tmp_db):
    from db.rate_limits import clear_login_attempts, is_login_locked_out, record_failed_login

    for _ in range(4):
        record_failed_login("ip-correo")
    assert is_login_locked_out("ip-correo")[0] is False
    record_failed_login("ip-correo")

    bloqueado, restante = is_login_locked_out("ip-correo")
    assert bloqueado is True
    assert 0 < restante <= 300
    # El tope tras apuntar (``max_attempts = 6``) deja pasar exactamente cinco.
    assert is_login_locked_out("ip-correo", max_attempts=6)[0] is False
    record_failed_login("ip-correo")
    assert is_login_locked_out("ip-correo", max_attempts=6)[0] is True

    clear_login_attempts("ip-correo")
    assert is_login_locked_out("ip-correo")[0] is False


def test_el_enlace_de_reset_vigente_se_distingue_del_gastado_y_del_inexistente(tmp_db):
    from db.password_reset import (
        consume_reset_token,
        create_reset_token_for_email,
        reset_token_vigente,
    )
    from db.users import create_user
    from services.password_reset import token_hash

    email = "vigente@example.test"
    create_user(email=email, password_hash="hash-anterior")  # pragma: allowlist secret
    digest = token_hash("token-vigente-" + "x" * 32)
    assert create_reset_token_for_email(email, digest, "2999-01-01T00:00:00+00:00") is True

    assert reset_token_vigente(digest) is True
    assert reset_token_vigente(token_hash("inventado-" + "y" * 32)) is False

    assert consume_reset_token(digest, "hash-nuevo") is not None  # pragma: allowlist secret
    assert reset_token_vigente(digest) is False, "un enlace gastado ya no es vigente"


def test_un_enlace_caducado_no_es_vigente(tmp_db):
    from db.password_reset import create_reset_token_for_email, reset_token_vigente
    from db.users import create_user
    from services.password_reset import token_hash

    email = "caducado@example.test"
    create_user(email=email, password_hash="hash-anterior")  # pragma: allowlist secret
    digest = token_hash("token-caducado-" + "x" * 32)
    create_reset_token_for_email(email, digest, "2000-01-01T00:00:00+00:00")

    assert reset_token_vigente(digest) is False


# ---------------------------------------------------------------------------
# Por HTTP, contra la BD
# ---------------------------------------------------------------------------

_LOGIN = "/api/v1/auth/login"
_CORREO = "lock@example.test"
_BUENA = "CorrectaClave2026"  # pragma: allowlist secret # gitleaks:allow


def _cuenta_con_contrasena() -> None:
    from db.users import create_user
    from shared.auth_core import hash_password

    create_user(email=_CORREO, password_hash=hash_password(_BUENA))


def test_el_sexto_intento_seguido_responde_429_aunque_la_contrasena_sea_buena(client):
    _cuenta_con_contrasena()

    for _ in range(5):
        mala = client.post(_LOGIN, json={"email": _CORREO, "password": "mala-clave-1234"})
        assert mala.status_code == 401, mala.text

    bloqueado = client.post(_LOGIN, json={"email": _CORREO, "password": _BUENA})
    assert bloqueado.status_code == 429, bloqueado.text
    assert int(bloqueado.headers["Retry-After"]) >= 1


def test_una_cuenta_con_veinte_fallos_en_la_hora_exige_pausa_entre_intentos(client):
    from api.routes import auth as auth_mod
    from db.rate_limits import record_failed_login

    _cuenta_con_contrasena()
    cuenta = auth_mod._login_account_key(_CORREO)
    for _ in range(auth_mod._LOGIN_CUENTA_UMBRAL):  # de "otras IP": ninguna es la de este cliente
        record_failed_login(
            cuenta,
            bucket=auth_mod._LOGIN_CUENTA_BUCKET,
            window_seconds=auth_mod._LOGIN_CUENTA_VENTANA_S,
        )

    pausado = client.post(_LOGIN, json={"email": _CORREO, "password": _BUENA})

    assert pausado.status_code == 429, pausado.text
    assert 1 <= int(pausado.headers["Retry-After"]) <= auth_mod._LOGIN_CUENTA_PAUSA_BASE_S
