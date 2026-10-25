"""Criterio de las concesiones dinámicas de acceso OAuth (RFC 242).

Aquí vive **quién puede entrar por OAuth** (:func:`acceso_oauth_permitido`) y
**qué no se puede conceder** (:func:`validar_concesion`, que se define en
``shared/concesiones_acceso.py`` porque ``db/access_grants.py`` la consulta
antes de escribir y la persistencia no importa de esta capa). El SQL y la
transacción están en ``db/access_grants.py``.

Hoy la regla es una: el dominio de un proveedor de correo público no se concede
como dominio. El formulario de solicitud es público y anónimo
(``api/routes/publico_solicitudes.py``) y el panel concede el dominio de la
solicitud con un clic; sin esta regla, una petición enviada desde
``quien-sea@gmail.com`` y ese clic dejaban entrar a cualquier cuenta de Gmail.
Lo que el administrador aprueba ahí es a una persona, así que lo que se concede
es su email.
"""

from __future__ import annotations

from db import access_grants as _concesiones
from observability.logging import get_logger
from shared.auth_core import oauth_email_allowed
from shared.concesiones_acceso import DOMINIOS_DE_CORREO_PUBLICO, validar_concesion

__all__ = ["DOMINIOS_DE_CORREO_PUBLICO", "acceso_oauth_permitido", "validar_concesion"]

log = get_logger(__name__)


def acceso_oauth_permitido(email: str) -> bool:
    """Allowlist estática o concesión dinámica; cualquier fallo dinámico deniega.

    Es la única definición de «esta dirección puede entrar por OAuth»: la usan
    el callback de la API (``api/routes/auth.py::_oauth_access_allowed``, y a
    través de ella ``admin_solicitudes``) y el login del MCP interno. Síncrona:
    la mitad dinámica consulta ``access_grants`` en Postgres, así que se llama
    desde un hilo.
    """
    if oauth_email_allowed(email):
        return True
    try:
        # Por el módulo, no por una referencia capturada: los tests sustituyen
        # `db.access_grants.is_access_granted`.
        return bool(_concesiones.is_access_granted(email))
    except Exception:
        log.exception("oauth_dynamic_allowlist_unavailable")
        return False
