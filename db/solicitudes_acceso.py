"""CRUD de ``solicitudes_acceso`` — cola de peticiones de acceso de la landing.

El acceso a TenderFlow es por invitación y se concede editando la allowlist de
``OAUTH_ALLOWED_EMAILS``/``OAUTH_ALLOWED_DOMAINS``. Esta tabla no cambia eso:
sólo evita que la petición se pierda entre el visitante y esa decisión manual.
"""

from __future__ import annotations

from typing import Any

from db.database import connect

ESTADOS = ("pendiente", "atendida", "descartada")


def crear_solicitud(
    *,
    email: str,
    empresa: str | None,
    mensaje: str | None,
    origen: str | None,
) -> int:
    """Registra una solicitud y devuelve su id.

    ``consentimiento_at`` se sella aquí con la hora del servidor y no con un
    valor que venga del cliente: es la prueba de que hubo consentimiento en
    este envío, así que tiene que ser inmune a lo que mande el navegador.
    """
    with connect() as c:
        cur = c.execute(
            "INSERT INTO solicitudes_acceso (email, empresa, mensaje, origen, consentimiento_at) "
            "VALUES (%s, %s, %s, %s, NOW()) RETURNING id",
            (email, empresa, mensaje, origen),
        )
        fila = cur.fetchone()
        return int(fila[0])


def listar_solicitudes(*, estado: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Cola de solicitudes, las más recientes primero."""
    with connect() as c:
        where = "WHERE estado = %s " if estado else ""
        params: tuple[Any, ...] = (estado, limit) if estado else (limit,)
        cur = c.execute(
            "SELECT id, email, empresa, mensaje, origen, estado, created_at "
            "FROM solicitudes_acceso "
            f"{where}"
            "ORDER BY created_at DESC "
            "LIMIT %s",
            params,
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, fila, strict=False)) for fila in cur.fetchall()]


def actualizar_estado(solicitud_id: int, estado: str) -> bool:
    """Mueve una solicitud de estado. Devuelve ``False`` si no existe."""
    if estado not in ESTADOS:
        raise ValueError(f"estado no válido: {estado}")
    with connect() as c:
        cur = c.execute(
            "UPDATE solicitudes_acceso SET estado = %s WHERE id = %s",
            (estado, solicitud_id),
        )
        return bool(cur.rowcount)


def contar_pendientes() -> int:
    """Cuántas solicitudes esperan revisión."""
    with connect() as c:
        fila = c.execute(
            "SELECT COUNT(*) FROM solicitudes_acceso WHERE estado = 'pendiente'"
        ).fetchone()
        return int(fila[0]) if fila else 0
