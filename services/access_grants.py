"""Criterio de las concesiones dinámicas de acceso OAuth (RFC 242).

Aquí vive **qué no se puede conceder**. El SQL y la transacción están en
``db/access_grants.py``, que consulta este criterio antes de escribir.

Hoy la regla es una: el dominio de un proveedor de correo público no se concede
como dominio. El formulario de solicitud es público y anónimo
(``api/routes/publico_solicitudes.py``) y el panel concede el dominio de la
solicitud con un clic; sin esta regla, una petición enviada desde
``quien-sea@gmail.com`` y ese clic dejaban entrar a cualquier cuenta de Gmail.
Lo que el administrador aprueba ahí es a una persona, así que lo que se concede
es su email.
"""

from __future__ import annotations

from typing import Final

from db.access_grants import AccessGrantKind, ConcesionInvalida

__all__ = ["DOMINIOS_DE_CORREO_PUBLICO", "validar_concesion"]

#: Proveedores de correo abiertos al público: cualquiera puede darse de alta.
#:
#: Lista **explícita y cerrada**, no una heurística: lo que se compara es el
#: dominio exacto, de modo que ``gmail.com.empresa.example`` o un subdominio
#: propio no caen aquí por parecerse. Ampliarla es añadir una línea; tiene un
#: test que la fija (``tests/test_services_access_grants.py``) para que quitar
#: una no pase desapercibido.
DOMINIOS_DE_CORREO_PUBLICO: Final[frozenset[str]] = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "outlook.es",
        "hotmail.com",
        "hotmail.es",
        "live.com",
        "msn.com",
        "yahoo.com",
        "yahoo.es",
        "icloud.com",
        "me.com",
        "proton.me",
        "protonmail.com",
        "gmx.com",
        "gmx.es",
        "aol.com",
        "zoho.com",
        "yandex.com",
        "mail.com",
        "telefonica.net",
        "movistar.es",
        "orange.es",
        "ono.com",
    }
)


def validar_concesion(kind: AccessGrantKind, value: str) -> None:
    """Lanza :class:`ConcesionInvalida` si esa concesión no se debe escribir.

    ``value`` llega ya normalizado (``db.access_grants.normalize_grant``). La
    concesión por **email** de una dirección de esos mismos proveedores sigue
    siendo válida: es justo la alternativa que propone el mensaje.
    """
    if kind == "domain" and value in DOMINIOS_DE_CORREO_PUBLICO:
        raise ConcesionInvalida(
            f"{value} es un proveedor de correo público: conceder el dominio dejaría "
            "entrar a cualquiera que tenga una cuenta ahí. Concede el email de la persona."
        )
