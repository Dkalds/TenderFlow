"""Claves de API para los tests: siempre con dueño y con caducidad.

``api.auth.create_api_key`` exige ``user_id`` desde 2026-10 (backlog,
«Inventariar las claves de API sin dueño»): una clave sin dueño ya no se puede
emitir en ningún entorno. Los tests que solo necesitan *una* clave válida y no
les importa de quién sea la piden aquí, que le crea un usuario propio con un
correo único. Sin ese usuario la clave caía en la compatibilidad de desarrollo
de ``dual_auth`` (``user_id = key_id``): una identidad que no existe en
``users`` y que ningún camino de producción produce.

Necesita Postgres (``tmp_db``/``api_db``): crea filas en ``users`` y ``api_keys``.
"""

from __future__ import annotations

from uuid import uuid4

#: ``password_hash`` sintético: estas cuentas no inician sesión por contraseña.
_HASH_DE_PRUEBA = "-".join(("hash", "de", "prueba"))


def dueno_de_prueba(etiqueta: str = "clave", *, admin: bool = False) -> int:
    """Crea un usuario activo con un correo único y devuelve su ``users.id``."""
    from db.users import create_user, set_admin

    user_id = create_user(
        email=f"{etiqueta}-{uuid4().hex[:12]}@example.test",
        password_hash=_HASH_DE_PRUEBA,
    )
    if admin:
        set_admin(user_id, True)
    return user_id


def clave_de_prueba(
    nombre: str,
    *,
    scopes: str | None = None,
    user_id: int | None = None,
    expires_days: int | None = None,
) -> str:
    """Emite una clave por ``create_api_key`` y devuelve el token en bruto.

    Sin ``user_id``, la clave es de un usuario nuevo creado para ella.
    """
    from api.auth import create_api_key

    return create_api_key(
        nombre,
        user_id=user_id if user_id is not None else dueno_de_prueba("clave"),
        scopes=scopes,
        expires_days=expires_days,
    )
