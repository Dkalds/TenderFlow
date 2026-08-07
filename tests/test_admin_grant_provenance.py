"""Procedencia de la concesión de admin (``users.admin_granted_by``).

``users.is_admin`` era un booleano sin procedencia, y ``_sync_oauth_admin``
reflejaba ``OAUTH_ADMIN_EMAILS`` sobre él en ambos sentidos: a quien se promovía
desde el panel y además entraba con Google se le retiraba el flag en su
siguiente login. Sin saber *quién* concedió el flag no se puede decidir quién
puede retirarlo.

La migración v75 añadió la columna; estos tests fijan el comportamiento que la
hace útil: OAuth degrada solo sus propias concesiones.
"""

from __future__ import annotations

from unittest.mock import patch

from api.routes.auth import _sync_oauth_admin
from db.users import admin_granted_by, create_user, is_admin, set_admin

_LISTA = "jefa@example.test"


def _con_lista_oauth():
    """Parchea la lista de admins de OAuth con un único email."""
    return patch("api.routes.auth.settings.OAUTH_ADMIN_EMAILS", _LISTA)


def test_el_panel_registra_su_procedencia(tmp_db):
    user_id = create_user(email="panel@example.test", password_hash="h")
    set_admin(user_id, True, granted_by="panel")

    assert is_admin(user_id) is True
    assert admin_granted_by(user_id) == "panel"


def test_oauth_promueve_y_registra_su_procedencia(tmp_db):
    user_id = create_user(email=_LISTA, password_hash="h")

    with _con_lista_oauth():
        _sync_oauth_admin(user_id, _LISTA)

    assert is_admin(user_id) is True
    assert admin_granted_by(user_id) == "oauth"


def test_oauth_degrada_lo_que_concedio_oauth(tmp_db):
    """Sacar a alguien de la lista sí le revoca lo que la lista le dio."""
    user_id = create_user(email="ex-admin@example.test", password_hash="h")
    set_admin(user_id, True, granted_by="oauth")

    with _con_lista_oauth():
        _sync_oauth_admin(user_id, "ex-admin@example.test")

    assert is_admin(user_id) is False
    assert admin_granted_by(user_id) is None


def test_oauth_no_degrada_una_concesion_del_panel(tmp_db):
    """El caso que motivó la columna: promoción del panel + login con Google.

    Antes, entrar con Google con la lista configurada retiraba el flag aunque
    lo hubiera concedido un administrador desde el panel.
    """
    user_id = create_user(email="promovida@example.test", password_hash="h")
    set_admin(user_id, True, granted_by="panel")

    with _con_lista_oauth():
        _sync_oauth_admin(user_id, "promovida@example.test")

    assert is_admin(user_id) is True
    assert admin_granted_by(user_id) == "panel"


def test_oauth_no_degrada_una_concesion_de_origen_desconocido(tmp_db):
    """Concesiones anteriores a v75: nadie puede afirmar quién las hizo."""
    user_id = create_user(email="legado@example.test", password_hash="h")
    set_admin(user_id, True)  # sin granted_by → NULL

    assert admin_granted_by(user_id) is None

    with _con_lista_oauth():
        _sync_oauth_admin(user_id, "legado@example.test")

    assert is_admin(user_id) is True


def test_sin_lista_configurada_oauth_no_toca_nada(tmp_db):
    """Lista vacía significa 'OAuth no gobierna el flag', no 'nadie es admin'."""
    user_id = create_user(email="intacta@example.test", password_hash="h")
    set_admin(user_id, True, granted_by="panel")

    with patch("api.routes.auth.settings.OAUTH_ADMIN_EMAILS", ""):
        _sync_oauth_admin(user_id, "intacta@example.test")

    assert is_admin(user_id) is True
    assert admin_granted_by(user_id) == "panel"


def test_degradar_limpia_la_procedencia(tmp_db):
    """Un is_admin=0 no debe arrastrar el origen de una concesión que ya no existe."""
    user_id = create_user(email="degradada@example.test", password_hash="h")
    set_admin(user_id, True, granted_by="panel")
    set_admin(user_id, False)

    assert is_admin(user_id) is False
    assert admin_granted_by(user_id) is None
