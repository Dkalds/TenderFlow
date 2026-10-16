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
Contra producción: ``ENV=prod APP_PROFILE=mcp`` con ``DATABASE_URL`` y
``AUDIT_HMAC_KEY`` de producción. Nunca ``ENV=dev`` contra esa base: la auditoría
se firmaría con la clave de desarrollo y rompería la cadena.)

Salida: una línea ``Revocados N tokens de <email>`` por cuenta (el correo se
compara sin distinguir mayúsculas; si varias cuentas casan, se revocan todas) y
código 0. Un correo desconocido sale con 1. Con ``ENV=prod APP_PROFILE=mcp`` y
``AUDIT_HMAC_KEY`` o ``SIGNING_KEY`` ausentes o cortas, ``config.settings`` aborta
al importarse (``ValidationError``, exit 1) y no se revoca nada; el exit 2 de
abajo es una segunda red para perfiles que no validan las claves. Cada ejecución
deja ``mcp.revocacion_manual`` en ``audit_log``.
"""

from __future__ import annotations

import argparse
import sys

from config import settings
from config.settings import LONGITUD_MINIMA_CLAVE
from db.mcp_oauth import revocar_de_usuario
from db.users import get_users_by_email_ci
from mcp_server.auth.proveedor import auditar_oauth


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--email", required=True, help="Correo de la cuenta a revocar")
    args = parser.parse_args(argv)

    # No hay revocación sin rastro: sin la clave de la cadena `log_action` no
    # escribiría la fila y el operador no se enteraría.
    if settings.ENV == "prod" and (
        len(settings.AUDIT_HMAC_KEY.get_secret_value().strip()) < LONGITUD_MINIMA_CLAVE
    ):
        print(
            "ERROR: falta AUDIT_HMAC_KEY (la de producción) en el entorno; "
            "no se revoca nada sin auditoría.",
            file=sys.stderr,
        )
        return 2

    # Sin distinguir mayúsculas (como el login del MCP) y con las dadas de baja:
    # una cuenta desactivada puede conservar tokens vivos.
    usuarios = get_users_by_email_ci(args.email.strip(), include_deactivated=True)
    if not usuarios:
        print(f"ERROR: no existe ninguna cuenta con el correo {args.email}", file=sys.stderr)
        return 1

    for usuario in usuarios:
        revocados = revocar_de_usuario(int(usuario["id"]))
        # Única vía de auditoría del MCP (ruling R12); el detalle no lleva tokens ni correo.
        auditar_oauth("mcp.revocacion_manual", int(usuario["id"]), {"revocados": revocados})
        print(f"Revocados {revocados} tokens de {usuario['email']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
