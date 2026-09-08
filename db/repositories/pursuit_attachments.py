"""Adjuntos propios de una oportunidad (C6.3).

El esquema lo crea ``v127``, y su docstring explica por qué ``organization_id``
está denormalizado, por qué ``indexable`` nace en falso y por qué el adjunto es
dato corporativo y no personal.

Aquí sólo vive el acceso. La regla de permisos —qué organización— la decide
``services/pursuit_attachments.py``; lo que este módulo garantiza es que **toda**
consulta lleva ``organization_id`` en el ``WHERE``, incluidas las que ya filtran
por ``pursuit_id``: un id de oportunidad se puede enumerar, y sin esa condición
bastaría acertar un número para leerse los adjuntos de otro equipo.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

_COLUMNAS = (
    "id, pursuit_id, organization_id, blob_key, filename, content_type, "
    "bytes, sha256, indexable, uploaded_by_user_id, created_at"
)


class PursuitAttachmentRepository:
    """Acceso a ``pursuit_attachments``."""

    def crear(
        self,
        *,
        pursuit_id: int,
        organization_id: int,
        blob_key: str,
        filename: str,
        content_type: str,
        bytes_: int,
        sha256: str,
        uploaded_by_user_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Registra un adjunto. ``None`` si la oportunidad no es de esa organización.

        La comprobación de pertenencia va dentro del propio ``INSERT … SELECT``:
        hacerla antes, en una consulta aparte, deja una ventana entre el permiso
        y la escritura.

        Subir dos veces el mismo fichero devuelve la fila que ya había en vez de
        fallar. El binario es el mismo objeto en el bucket —la clave es su
        huella— así que un segundo ``POST`` idéntico no es un error del usuario,
        es un reintento.
        """
        ahora = now_utc_iso()
        with connect() as c:
            fila = c.execute(
                "INSERT INTO pursuit_attachments "
                "(pursuit_id, organization_id, blob_key, filename, content_type, "
                " bytes, sha256, uploaded_by_user_id, created_at) "
                "SELECT p.id, p.organization_id, %s, %s, %s, %s, %s, %s, %s "
                "FROM pursuits p WHERE p.id = %s AND p.organization_id = %s "
                "ON CONFLICT (pursuit_id, sha256) DO UPDATE SET filename = EXCLUDED.filename "
                f"RETURNING {_COLUMNAS}",
                (
                    blob_key,
                    filename,
                    content_type,
                    int(bytes_),
                    sha256,
                    uploaded_by_user_id,
                    ahora,
                    pursuit_id,
                    organization_id,
                ),
            ).fetchone()
            if fila is None:
                return None
            columnas = [d[0] for d in c.description] if c.description else []
        return dict(zip(columnas, fila, strict=False))

    def listar(self, *, pursuit_id: int, organization_id: int) -> list[dict[str, Any]]:
        """Adjuntos de una oportunidad, el más reciente primero."""
        with connect_read() as c:
            return rows_to_dicts(
                c.execute(
                    f"SELECT {_COLUMNAS} FROM pursuit_attachments "
                    "WHERE pursuit_id = %s AND organization_id = %s "
                    "ORDER BY created_at DESC, id DESC",
                    (pursuit_id, organization_id),
                )
            )

    def get(self, *, attachment_id: int, organization_id: int) -> dict[str, Any] | None:
        with connect_read() as c:
            filas = rows_to_dicts(
                c.execute(
                    f"SELECT {_COLUMNAS} FROM pursuit_attachments "
                    "WHERE id = %s AND organization_id = %s",
                    (attachment_id, organization_id),
                )
            )
        return filas[0] if filas else None

    def get_por_id(self, attachment_id: int) -> dict[str, Any] | None:
        """El **único** acceso sin ``organization_id``, y sólo para el enlace firmado.

        La autorización de ese camino es la firma, que ya nombra el adjunto
        concreto y su caducidad: no hay sesión de la que sacar una organización.
        Devuelve lo justo para servir el fichero —clave, nombre y tipo— y nada
        que permita enumerar: quien no tenga una firma válida no llega aquí.
        """
        with connect_read() as c:
            filas = rows_to_dicts(
                c.execute(
                    "SELECT id, pursuit_id, organization_id, blob_key, filename, content_type "
                    "FROM pursuit_attachments WHERE id = %s",
                    (int(attachment_id),),
                )
            )
        return filas[0] if filas else None

    def marcar_indexable(
        self, *, attachment_id: int, organization_id: int, indexable: bool
    ) -> dict[str, Any] | None:
        """Cambia el opt-in del RAG para un adjunto."""
        with connect() as c:
            fila = c.execute(
                "UPDATE pursuit_attachments SET indexable = %s "
                "WHERE id = %s AND organization_id = %s "
                f"RETURNING {_COLUMNAS}",
                (bool(indexable), attachment_id, organization_id),
            ).fetchone()
            if fila is None:
                return None
            columnas = [d[0] for d in c.description] if c.description else []
        return dict(zip(columnas, fila, strict=False))

    def borrar(self, *, attachment_id: int, organization_id: int) -> dict[str, Any] | None:
        """Borra la fila y devuelve la que había, para poder purgar su objeto.

        Devuelve la fila —y no un booleano— porque quien borra necesita la
        ``blob_key`` para quitar el binario del bucket. Consultarla antes en otra
        llamada dejaría la ventana en la que dos borrados concurrentes purgan el
        mismo objeto y uno de los dos cree que había fichero.
        """
        with connect() as c:
            fila = c.execute(
                "DELETE FROM pursuit_attachments WHERE id = %s AND organization_id = %s "
                f"RETURNING {_COLUMNAS}",
                (attachment_id, organization_id),
            ).fetchone()
            if fila is None:
                return None
            columnas = [d[0] for d in c.description] if c.description else []
        return dict(zip(columnas, fila, strict=False))

    def indexables(self, *, pursuit_id: int, organization_id: int) -> list[dict[str, Any]]:
        """Los que el equipo autorizó a que el asistente lea.

        Es la consulta que el RAG tiene que usar: pedir «los adjuntos» y filtrar
        en Python sería un `if` a un `import` de distancia de indexar una
        propuesta económica entera.
        """
        with connect_read() as c:
            return rows_to_dicts(
                c.execute(
                    f"SELECT {_COLUMNAS} FROM pursuit_attachments "
                    "WHERE pursuit_id = %s AND organization_id = %s AND indexable "
                    "ORDER BY id",
                    (pursuit_id, organization_id),
                )
            )

    def de_organizacion(self, organization_id: int) -> list[dict[str, Any]]:
        """Todos los de una organización: export GDPR y borrado de la cuenta."""
        with connect_read() as c:
            return rows_to_dicts(
                c.execute(
                    f"SELECT {_COLUMNAS} FROM pursuit_attachments "
                    "WHERE organization_id = %s ORDER BY id",
                    (organization_id,),
                )
            )
