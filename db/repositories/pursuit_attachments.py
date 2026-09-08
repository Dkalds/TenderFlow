"""Adjuntos propios de una oportunidad (C6.3, v127).

TID251: el SQL de `pursuit_attachments` vive solo aquí. Los bytes no pasan por
este módulo — los guarda `shared/object_store.py` y aquí solo viaja la clave.

Toda consulta lleva `organization_id` en el `WHERE`, no como comodidad sino como
frontera: un adjunto es la propuesta que el equipo va a presentar, y es el dato
más sensible que guarda el producto.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

_SELECT = (
    "SELECT a.id, a.pursuit_id, a.organization_id, a.blob_key, a.filename, "
    "a.content_type, a.size_bytes, a.sha256, a.uploaded_by_user_id, "
    "u.display_name AS uploaded_by_name, a.indexable, a.created_at "
    "FROM pursuit_attachments a "
    "LEFT JOIN users u ON u.id = a.uploaded_by_user_id "
)


class PursuitAttachmentExists(Exception):
    """Ese fichero ya está en esa oportunidad (misma huella)."""


class PursuitAttachmentsRepository:
    """Acceso a ``pursuit_attachments``."""

    def create(
        self,
        *,
        pursuit_id: int,
        organization_id: int,
        blob_key: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
        uploaded_by_user_id: int | None,
    ) -> dict[str, Any] | None:
        """Registra un adjunto en una oportunidad **de esa organización**.

        Devuelve ``None`` si el pursuit no es de la organización. Igual que en
        `pursuit_tasks`, la comprobación va dentro del `INSERT ... SELECT` para
        que no exista ventana entre comprobar y escribir.

        Lanza :class:`PursuitAttachmentExists` si la clave ya estaba: como la
        clave incorpora la huella del contenido, eso significa exactamente «ese
        mismo fichero ya está subido aquí».
        """
        ahora = now_utc_iso()
        with connect() as c:
            cur = c.execute(
                "INSERT INTO pursuit_attachments "
                "(pursuit_id, organization_id, blob_key, filename, content_type, "
                " size_bytes, sha256, uploaded_by_user_id, indexable, created_at) "
                "SELECT p.id, p.organization_id, %s, %s, %s, %s, %s, %s, false, %s "
                "FROM pursuits p WHERE p.id = %s AND p.organization_id = %s "
                "ON CONFLICT (blob_key) DO NOTHING "
                "RETURNING id",
                (
                    blob_key,
                    filename,
                    content_type,
                    size_bytes,
                    sha256,
                    uploaded_by_user_id,
                    ahora,
                    pursuit_id,
                    organization_id,
                ),
            )
            fila = cur.fetchone()
            if fila is None:
                # Dos causas posibles y hay que distinguirlas: el pursuit no es
                # de esta organización (404 para quien pregunta) o la clave ya
                # existía (409). Sin esta consulta, un reintento legítimo se
                # leería como «no existe».
                ya = c.execute(
                    "SELECT 1 FROM pursuit_attachments WHERE blob_key = %s",
                    (blob_key,),
                ).fetchone()
                if ya is not None:
                    raise PursuitAttachmentExists(blob_key)
                return None
            nuevo_id = int(fila[0] if not isinstance(fila, dict) else fila["id"])
        return self.get(nuevo_id, organization_id=organization_id)

    def get(self, attachment_id: int, *, organization_id: int) -> dict[str, Any] | None:
        """Un adjunto por id, acotado a su organización."""
        with connect_read() as c:
            filas = rows_to_dicts(
                c.execute(
                    _SELECT + "WHERE a.id = %s AND a.organization_id = %s",
                    (attachment_id, organization_id),
                )
            )
        return filas[0] if filas else None

    def list_for_pursuit(
        self, pursuit_id: int, *, organization_id: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Adjuntos de una oportunidad, recientes primero."""
        with connect_read() as c:
            return rows_to_dicts(
                c.execute(
                    _SELECT + "WHERE a.pursuit_id = %s AND a.organization_id = %s "
                    "ORDER BY a.id DESC LIMIT %s",
                    (pursuit_id, organization_id, limit),
                )
            )

    def delete(self, attachment_id: int, *, organization_id: int) -> str | None:
        """Borra la fila y devuelve la ``blob_key`` que quedó huérfana.

        Devuelve la clave —en vez de borrar el objeto aquí— para que el orden
        sea siempre «primero la fila, después el binario»: si el borrado del
        objeto falla, queda basura en el bucket, que es recuperable. Al revés
        quedaría una fila apuntando a un objeto que ya no está, y eso lo ve el
        usuario como una descarga rota.
        """
        with connect() as c:
            cur = c.execute(
                "DELETE FROM pursuit_attachments "
                "WHERE id = %s AND organization_id = %s RETURNING blob_key",
                (attachment_id, organization_id),
            )
            fila = cur.fetchone()
        if fila is None:
            return None
        return str(fila[0] if not isinstance(fila, dict) else fila["blob_key"])

    def set_indexable(
        self, attachment_id: int, *, organization_id: int, indexable: bool
    ) -> dict[str, Any] | None:
        """Levanta o baja el opt-in de indexación del RAG para UN adjunto."""
        with connect() as c:
            cur = c.execute(
                "UPDATE pursuit_attachments SET indexable = %s "
                "WHERE id = %s AND organization_id = %s RETURNING id",
                (indexable, attachment_id, organization_id),
            )
            if cur.fetchone() is None:
                return None
        return self.get(attachment_id, organization_id=organization_id)

    def keys_de_organizacion(self, organization_id: int) -> list[str]:
        """Todas las claves de una organización, para purgarlas al borrarla.

        ADR-030 §D: borrar una organización borra su dato corporativo, y un
        adjunto lo es. El `ON DELETE CASCADE` se lleva las filas; los objetos
        del almacén hay que enumerarlos **antes** para poder borrarlos después.
        """
        with connect_read() as c:
            filas = c.execute(
                "SELECT blob_key FROM pursuit_attachments WHERE organization_id = %s",
                (organization_id,),
            ).fetchall()
        return [str(f[0] if not isinstance(f, dict) else f["blob_key"]) for f in filas]

    def ocupacion(self, organization_id: int) -> dict[str, int]:
        """``{n, bytes}`` de lo que ocupa una organización.

        Es lo que permite poner un tope por cliente sin listar el bucket, que
        en S3 es una operación paginada y cara.
        """
        with connect_read() as c:
            fila = c.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS bytes "
                "FROM pursuit_attachments WHERE organization_id = %s",
                (organization_id,),
            ).fetchone()
        if fila is None:
            return {"n": 0, "bytes": 0}
        if isinstance(fila, dict):
            return {"n": int(fila["n"]), "bytes": int(fila["bytes"])}
        return {"n": int(fila[0]), "bytes": int(fila[1])}
