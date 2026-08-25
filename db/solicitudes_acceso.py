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

    **Idempotente por email mientras la solicitud siga pendiente** (v90). Sin
    esto, cada pulsación creaba una fila: un doble clic, un reintento tras el
    303 de error o —el caso más probable— volver a darle después de agotar el
    rate limit llenaban de duplicados una cola que revisa una persona a mano.

    Al reenviar se actualiza la fila existente en vez de crear otra, y se
    conserva su ``id`` y su ``created_at``: lo que llega después es la misma
    petición mejor contada, no una nueva. ``consentimiento_at`` sí se refresca,
    porque el contenido que la fila refleja pasa a ser el del último envío y es
    ese el que la persona consintió.

    ``origen`` registra **desde qué superficie** se envió el formulario, no qué
    CTA se pulsó. La columna nació con la intención de distinguir el CTA sin
    depender de JavaScript, y eso no es alcanzable: los tres botones de la
    landing apuntan al mismo ancla del mismo ``<form>``, así que el navegador
    manda lo mismo se pulse el que se pulse. Discriminar por CTA exigiría o
    JavaScript —lo que la columna quería evitar— o volver la página dinámica
    para leer un query param, que costaría el ISR de la portada entera. La
    atribución por CTA vive donde sí es barata: el evento ``solicitar_acceso``
    de analytics, con su dimensión ``ubicacion``.
    """
    with connect() as c:
        cur = c.execute(
            "INSERT INTO solicitudes_acceso (email, empresa, mensaje, origen, consentimiento_at) "
            "VALUES (%s, %s, %s, %s, NOW()) "
            # El índice de v90 es parcial y sobre una expresión, así que el
            # arbitrador tiene que repetir las dos cosas para que Postgres lo
            # reconozca.
            "ON CONFLICT (lower(email)) WHERE estado = 'pendiente' DO UPDATE SET "
            "  empresa = COALESCE(EXCLUDED.empresa, solicitudes_acceso.empresa), "
            "  mensaje = COALESCE(EXCLUDED.mensaje, solicitudes_acceso.mensaje), "
            "  origen = COALESCE(EXCLUDED.origen, solicitudes_acceso.origen), "
            "  consentimiento_at = EXCLUDED.consentimiento_at "
            "RETURNING id",
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
