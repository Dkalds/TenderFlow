"""Revoca todos los tokens OAuth del MCP interno de una cuenta.

Palanca manual del operador: corta el acceso sin esperar a que caduque el
access token (1 h) ni el refresh (30 días). Útil si se pierde un portátil o se
va alguien. Cierra las familias vivas del usuario (access, refresh y códigos
sin canjear); el usuario puede volver a conectarse con su login de Google si
sigue siendo admin y activo. Para cortarle el acceso del todo, quítale
``is_admin`` o desactiva la cuenta: el MCP lo re-comprueba en cada petición
(caché de 60 s).

Uso::

    python -m scripts.mcp_revocar --email alguien@empresa.es

(Desde la raíz del repo; ``python scripts/mcp_revocar.py`` no encuentra los paquetes.
Contra producción: ``ENV=prod APP_PROFILE=worker`` con ``DATABASE_URL`` y
``AUDIT_HMAC_KEY`` de producción. Nunca ``ENV=dev`` contra esa base: la auditoría
se firmaría con la clave de desarrollo y rompería la cadena.)

Salida: ``Revocados N tokens de <email>`` y código 0. Un correo desconocido
sale con 1. Cada ejecución deja ``mcp.revocacion_manual`` en ``audit_log``.
"""

from __future__ import annotations

import argparse
import sys

from db.mcp_oauth import revocar_de_usuario
from db.users import get_user_by_email
from mcp_server.auth.proveedor import auditar_oauth


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--email", required=True, help="Correo de la cuenta a revocar")
    args = parser.parse_args(argv)

    # Con `include_deactivated`: una cuenta dada de baja puede tener tokens vivos.
    usuario = get_user_by_email(args.email.strip(), include_deactivated=True)
    if usuario is None:
        print(f"ERROR: no existe ninguna cuenta con el correo {args.email}", file=sys.stderr)
        return 1

    revocados = revocar_de_usuario(int(usuario["id"]))
    # Única vía de auditoría del MCP (ruling R12); el detalle no lleva tokens ni correo.
    auditar_oauth("mcp.revocacion_manual", int(usuario["id"]), {"revocados": revocados})
    print(f"Revocados {revocados} tokens de {args.email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
