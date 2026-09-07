"""Errores de JavaScript del navegador, agregados por huella (C2.6, D26).

``POST /security/client-error`` terminaba en un ``log.warning``. Un log de
Render no es un destino: nadie lo mira salvo durante un incidente, no se puede
agregar y se rota a los pocos días.

**La fila lleva huella, no identidad.** Sin IP, sin email, sin id de usuario,
sin query string. Es el mismo criterio que ya aplica ``csp_violation``, y el
motivo por el que D26 eligió tabla propia antes que un SDK externo: un SDK
recibiría trazas del navegador de cada visitante y añadiría un destinatario al
registro de tratamientos.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

#: Tope del mensaje guardado. Un stack entero puede llevar la URL de un script
#: con parámetros, y no hay caso de uso que necesite más para agrupar.
MAX_MENSAJE = 500

#: Números, hexadecimales y UUID que cambian entre ocurrencias del MISMO error.
#: Sin normalizarlos, «Cannot read x of undefined at line 4211» y la misma línea
#: con otro número serían dos errores, y la agregación no agregaría nada.
_VOLATIL = re.compile(r"\b(?:0x)?[0-9a-f]{6,}\b|\b\d+\b", re.IGNORECASE)


def fingerprint(*, mensaje: str | None, ruta: str | None, origen: str | None) -> str:
    """Huella estable de un error, insensible a los números que cambian."""
    normalizado = _VOLATIL.sub("#", (mensaje or "").strip().lower())[:MAX_MENSAJE]
    crudo = f"{origen or ''}|{ruta or ''}|{normalizado}"
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:32]


def registrar(
    *,
    mensaje: str | None,
    ruta: str | None,
    origen: str | None,
    build: str | None,
) -> None:
    """Suma una ocurrencia del error, o crea la fila si es la primera.

    Idempotente por huella: mil ocurrencias del mismo fallo son **una fila con
    `ocurrencias = 1000`**, no mil filas. Esa es la diferencia con el log que
    esto sustituye.
    """
    huella = fingerprint(mensaje=mensaje, ruta=ruta, origen=origen)
    ahora = now_utc_iso()
    with connect() as c:
        c.execute(
            "INSERT INTO client_errors "
            "(fingerprint, origen, ruta, mensaje, build, ocurrencias, primera_vez, ultima_vez) "
            "VALUES (%s, %s, %s, %s, %s, 1, %s, %s) "
            "ON CONFLICT (fingerprint) DO UPDATE SET "
            "  ocurrencias = client_errors.ocurrencias + 1, "
            "  ultima_vez = excluded.ultima_vez, "
            # El build se actualiza: interesa saber en cuál se vio por última
            # vez, que es la pregunta al decidir si un despliegue lo arregló.
            "  build = COALESCE(excluded.build, client_errors.build)",
            (huella, origen, ruta, (mensaje or "")[:MAX_MENSAJE] or None, build, ahora, ahora),
        )


def listar(*, limit: int = 100) -> list[dict[str, Any]]:
    """Errores más recientes primero, para la vista de `/ops`."""
    with connect_read() as c:
        return rows_to_dicts(
            c.execute(
                "SELECT fingerprint, origen, ruta, mensaje, build, ocurrencias, "
                "       primera_vez, ultima_vez "
                "FROM client_errors ORDER BY ultima_vez DESC LIMIT %s",
                (limit,),
            )
        )


def purgar(*, antes_de: str) -> int:
    """Borra los errores cuya última ocurrencia es anterior a *antes_de*.

    Lo llama `retention_cleanup` con el plazo de `RETENTION_CLIENT_ERRORS_DAYS`.
    """
    with connect() as c:
        cur = c.execute("DELETE FROM client_errors WHERE ultima_vez < %s", (antes_de,))
        return int(getattr(cur, "rowcount", 0) or 0)
