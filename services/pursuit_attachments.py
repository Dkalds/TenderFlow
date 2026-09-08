"""Adjuntos propios de una oportunidad: reglas, almacén y enlace firmado (C6.3).

La pestaña Expediente enseñaba los documentos del pliego y ninguno de los que el
equipo escribe para responderlo. Aquí viven las tres decisiones que hacen que
subir un fichero al producto no sea una vía de entrada:

1. **Qué se acepta.** Lista blanca de tipos y tope de tamaño. Una lista negra
   —«todo menos .exe»— es una carrera que se pierde: basta un formato nuevo.
2. **Cómo se descarga.** Un enlace **firmado y caducado**, no una URL adivinable.
   El binario nunca se sirve desde una ruta que solo dependa del id.
3. **Qué NO se hace con él.** El RAG no lo indexa. La columna `indexable` de
   `v127` existe para que ese permiso pueda levantarse por fichero, y nace en
   `false`.

El binario va al almacén de objetos de v2 S8.1; la fila, a `pursuit_attachments`.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Final

from db.repositories.pursuit_attachments import (
    PursuitAttachmentExists,
    PursuitAttachmentsRepository,
)
from db.repositories.pursuits import PursuitRepository
from observability.logging import get_logger
from services.organizations import resolve_organization
from services.pursuits import PursuitNotFoundError
from shared.object_store import get_object_store

log = get_logger(__name__)


class AttachmentError(Exception):
    """Rechazo de negocio: el llamante lo traduce a 4xx."""


class AttachmentTooLarge(AttachmentError):
    """Supera el tope de tamaño."""


class AttachmentTypeRejected(AttachmentError):
    """El tipo no está en la lista blanca."""


class AttachmentStoreUnavailable(AttachmentError):
    """No hay almacén configurado: sin bucket no se acepta la subida."""


#: Tope por fichero. 25 MiB cubre una propuesta con anexos maquetados; por
#: encima, el sitio de un fichero no es una petición HTTP. Duplicado como CHECK
#: en `v127`, a propósito: una ruta nueva que olvide validar choca con la base.
MAX_BYTES: Final = 25 * 1024 * 1024

#: Tope por organización. Sin él, el coste del bucket lo fija un cliente.
#: Se mide con `PursuitAttachmentsRepository.ocupacion`, que es una fila, no un
#: listado del bucket.
MAX_BYTES_POR_ORGANIZACION: Final = 2 * 1024 * 1024 * 1024

#: Lista BLANCA de tipos. Lo que se sube a una oportunidad es una propuesta y
#: sus anexos: documentos, hojas, presentaciones, imágenes y el comprimido con
#: el que se presenta. Nada ejecutable, nada con macros por defecto, nada de
#: SVG —que es XML con scripts— y nada de HTML.
TIPOS_PERMITIDOS: Final[dict[str, tuple[str, ...]]] = {
    "application/pdf": (".pdf",),
    "application/msword": (".doc",),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (".docx",),
    "application/vnd.ms-excel": (".xls",),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (".xlsx",),
    "application/vnd.ms-powerpoint": (".ppt",),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (".pptx",),
    "application/vnd.oasis.opendocument.text": (".odt",),
    "application/vnd.oasis.opendocument.spreadsheet": (".ods",),
    "application/zip": (".zip",),
    "text/plain": (".txt", ".md"),
    "text/csv": (".csv",),
    "image/png": (".png",),
    "image/jpeg": (".jpg", ".jpeg"),
}

#: Prefijo de los adjuntos propios en el bucket. Separado del de los pliegos
#: (`documentos/`) porque su ciclo de vida es el contrario: un pliego es dato
#: público que la retención purga a los 24 meses; esto es dato corporativo que
#: vive mientras viva la organización, y mezclarlos haría que una purga de
#: pliegos pudiera llevarse una propuesta.
DEFAULT_PREFIX: Final = "adjuntos/"

#: Vida del enlace de descarga. Diez minutos: lo que tarda un navegador en
#: abrirlo, no lo que tarda en reenviarse por correo.
TTL_DESCARGA_SEGUNDOS: Final = 600

_PREFIJO_FIRMA: Final = b"pursuit-attachment:v1:"

_NOMBRE_INSEGURO = re.compile(r"[^\w .\-()\[\]áéíóúÁÉÍÓÚñÑüÜ]", re.UNICODE)


def attachments_prefix() -> str:
    """Prefijo configurado para los adjuntos propios."""
    prefijo = os.environ.get("PURSUIT_ATTACHMENT_PREFIX", DEFAULT_PREFIX).strip()
    if prefijo and not prefijo.endswith("/"):
        prefijo += "/"
    return prefijo or DEFAULT_PREFIX


def blob_key(*, organization_id: int, pursuit_id: int, sha256: str) -> str:
    """``adjuntos/{org}/{pursuit}/{sha256}``.

    La organización va **en la clave** y no solo en la fila: si algún día hay
    que borrar todo lo de un cliente sin base de datos delante —una petición de
    supresión del GDPR con la base ya purgada—, el prefijo es la respuesta.

    La huella como nombre deduplica: subir el mismo fichero dos veces a la misma
    oportunidad choca con la unicidad de `blob_key` en vez de gastar el doble.
    """
    return f"{attachments_prefix()}{int(organization_id)}/{int(pursuit_id)}/{sha256}"


def sanear_nombre(filename: str) -> str:
    """Nombre seguro para `Content-Disposition`, sin rutas ni caracteres raros.

    Se queda solo con el nombre base: `../../etc/passwd` y `C:\\algo\\x.pdf` se
    reducen a `passwd` y `x.pdf`. Lo que viaja en una cabecera HTTP no puede
    llevar separadores ni saltos de línea.
    """
    base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    base = _NOMBRE_INSEGURO.sub("_", base)
    base = base.lstrip(".") or "adjunto"
    return base[:255]


def _extension(nombre: str) -> str:
    _, _, ext = nombre.rpartition(".")
    return f".{ext.lower()}" if ext and ext != nombre else ""


def validar(*, filename: str, content_type: str, size_bytes: int) -> tuple[str, str]:
    """Aplica lista blanca y topes. Devuelve ``(nombre_saneado, content_type)``.

    El tipo **y** la extensión tienen que concordar. Aceptar un `.exe` porque el
    cliente dijo `application/pdf` sería confiar en la parte de la petición que
    controla quien sube el fichero.
    """
    if size_bytes <= 0:
        raise AttachmentError("El fichero está vacío.")
    if size_bytes > MAX_BYTES:
        raise AttachmentTooLarge(
            f"El fichero ocupa {size_bytes} bytes y el tope es {MAX_BYTES} "
            f"({MAX_BYTES // (1024 * 1024)} MiB)."
        )

    tipo = (content_type or "").split(";", 1)[0].strip().lower()
    extensiones = TIPOS_PERMITIDOS.get(tipo)
    if extensiones is None:
        raise AttachmentTypeRejected(
            f"Tipo no admitido: {tipo or 'desconocido'}. "
            f"Admitidos: {', '.join(sorted(TIPOS_PERMITIDOS))}."
        )

    nombre = sanear_nombre(filename)
    ext = _extension(nombre)
    if ext not in extensiones:
        raise AttachmentTypeRejected(
            f"La extensión {ext or '(ninguna)'} no corresponde a {tipo}. "
            f"Esperada: {' o '.join(extensiones)}."
        )
    return nombre, tipo


@dataclass(frozen=True, slots=True)
class EnlaceDescarga:
    """Ruta firmada y el instante en que deja de valer."""

    path: str
    expira_en: int


def firmar_descarga(attachment_id: int, *, ttl: int = TTL_DESCARGA_SEGUNDOS) -> EnlaceDescarga:
    """Enlace de descarga firmado que caduca.

    La caducidad va **dentro de lo firmado**, no como parámetro aparte: si
    viajara suelta, cambiarla en la URL bastaría para revivir un enlace muerto.
    """
    from shared.signing import sign

    expira = int(time.time()) + int(ttl)
    payload = _payload(attachment_id, expira)
    token = sign(payload)
    return EnlaceDescarga(
        path=(f"/api/v1/pursuits/adjuntos/{int(attachment_id)}/descargar?exp={expira}&t={token}"),
        expira_en=expira,
    )


def verificar_descarga(attachment_id: int, *, exp: int, token: str) -> bool:
    """``True`` si la firma es válida **y** no ha caducado."""
    from shared.signing import verify

    if int(exp) < int(time.time()):
        return False
    return verify(_payload(attachment_id, int(exp)), token)


def _payload(attachment_id: int, expira: int) -> bytes:
    return _PREFIJO_FIRMA + f"{int(attachment_id)}:{int(expira)}".encode("ascii")


def _require_pursuit(organization_id: int, pursuit_id: int) -> None:
    if PursuitRepository().get(organization_id, pursuit_id) is None:
        raise PursuitNotFoundError("Oportunidad no encontrada.")


def listar(
    user_id: int, pursuit_id: int, *, organization_id: int | None = None
) -> list[dict[str, Any]]:
    """Adjuntos de la oportunidad, recientes primero."""
    resuelta, _role = resolve_organization(user_id, organization_id)
    _require_pursuit(resuelta, pursuit_id)
    return PursuitAttachmentsRepository().list_for_pursuit(pursuit_id, organization_id=resuelta)


def obtener(
    user_id: int, attachment_id: int, *, organization_id: int | None = None
) -> dict[str, Any] | None:
    """Un adjunto por id, resolviendo aquí la organización.

    Existe para que la ruta no importe `resolve_organization`: el repo obliga a
    que la resolución viva en un servicio o en `api/tenancy.py`, y no repartida
    por los handlers (`tests/test_organization_sql_isolation.py`).
    """
    resuelta, _role = resolve_organization(user_id, organization_id)
    return PursuitAttachmentsRepository().get(attachment_id, organization_id=resuelta)


def marcar_indexable(
    user_id: int,
    attachment_id: int,
    *,
    indexable: bool,
    organization_id: int | None = None,
) -> dict[str, Any] | None:
    """Levanta o baja el opt-in del RAG para UN adjunto. `viewer` no escribe."""
    resuelta, _role = resolve_organization(user_id, organization_id, write=True)
    return PursuitAttachmentsRepository().set_indexable(
        attachment_id, organization_id=resuelta, indexable=indexable
    )


def subir(
    user_id: int,
    pursuit_id: int,
    *,
    filename: str,
    content_type: str,
    data: bytes,
    organization_id: int | None = None,
) -> dict[str, Any] | None:
    """Valida, guarda el binario y registra la fila. ``None`` si el pursuit no es suyo.

    El orden es **binario primero, fila después**. Al revés, un fallo del bucket
    dejaría una fila apuntando a un objeto que no existe, que es lo que el
    usuario vive como una descarga rota; así, lo peor que puede pasar es un
    objeto sin fila, que `purge_keys` recoge.
    """
    # `write=True`: un `viewer` no sube ficheros, igual que no crea tareas.
    resuelta, _role = resolve_organization(user_id, organization_id, write=True)
    _require_pursuit(resuelta, pursuit_id)
    organization_id_resuelta = resuelta

    nombre, tipo = validar(filename=filename, content_type=content_type, size_bytes=len(data))

    almacen = get_object_store()
    if not almacen.enabled:
        # Sin bucket, `NullObjectStore.put` no lanza y devolvería un adjunto que
        # no se puede descargar nunca. Aceptar la subida sería mentir.
        raise AttachmentStoreUnavailable(
            "No hay almacén de objetos configurado: los adjuntos propios "
            "necesitan DOCUMENT_BLOB_BUCKET o DOCUMENT_BLOB_DIR."
        )

    repo = PursuitAttachmentsRepository()
    ocupado = repo.ocupacion(organization_id_resuelta)
    if ocupado["bytes"] + len(data) > MAX_BYTES_POR_ORGANIZACION:
        raise AttachmentTooLarge(
            f"La organización ocupa {ocupado['bytes']} bytes y el tope es "
            f"{MAX_BYTES_POR_ORGANIZACION}. Borrá adjuntos antes de subir más."
        )

    huella = hashlib.sha256(data).hexdigest()
    clave = blob_key(organization_id=organization_id_resuelta, pursuit_id=pursuit_id, sha256=huella)
    almacen.put(clave, data, content_type=tipo)
    try:
        fila = repo.create(
            pursuit_id=pursuit_id,
            organization_id=organization_id_resuelta,
            blob_key=clave,
            filename=nombre,
            content_type=tipo,
            size_bytes=len(data),
            sha256=huella,
            uploaded_by_user_id=user_id,
        )
    except PursuitAttachmentExists:
        # El objeto ya estaba y el `put` lo ha reescrito con los mismos bytes
        # (misma huella): no hay nada que limpiar.
        raise
    if fila is None:
        # El pursuit no era de esta organización: el objeto que acabamos de
        # escribir no lo referencia nadie, y dejarlo sería filtrar bytes de un
        # intento rechazado en el bucket del cliente.
        almacen.delete(clave)
        return None
    log.info(
        "pursuit_attachment_subido",
        pursuit_id=pursuit_id,
        organization_id=organization_id_resuelta,
        bytes=len(data),
        content_type=tipo,
    )
    return fila


def descargar(
    user_id: int, attachment_id: int, *, organization_id: int | None = None
) -> tuple[dict[str, Any], bytes] | None:
    """``(fila, bytes)`` del adjunto, o ``None`` si no existe o no es suyo."""
    resuelta, _role = resolve_organization(user_id, organization_id)
    repo = PursuitAttachmentsRepository()
    fila = repo.get(attachment_id, organization_id=resuelta)
    if fila is None:
        return None
    contenido = get_object_store().get(str(fila["blob_key"]))
    if contenido is None:
        log.warning(
            "pursuit_attachment_sin_binario",
            attachment_id=attachment_id,
            blob_key=fila["blob_key"],
        )
        return None
    return fila, contenido


def borrar(user_id: int, attachment_id: int, *, organization_id: int | None = None) -> bool:
    """Borra la fila y su objeto. ``False`` si no existía o no era suyo."""
    resuelta, _role = resolve_organization(user_id, organization_id, write=True)
    clave = PursuitAttachmentsRepository().delete(attachment_id, organization_id=resuelta)
    if clave is None:
        return False
    get_object_store().delete(clave)
    log.info("pursuit_attachment_borrado", attachment_id=attachment_id)
    return True


def purgar_organizacion(organization_id: int) -> int:
    """Borra del bucket todos los adjuntos de una organización (ADR-030 §D).

    Se llama **antes** de borrar la organización: el `ON DELETE CASCADE` se
    lleva las filas, y sin las filas ya no habría forma de saber qué objetos
    quedaron huérfanos.
    """
    from shared.object_store import purge_keys

    claves = PursuitAttachmentsRepository().keys_de_organizacion(organization_id)
    if not claves:
        return 0
    borrados = purge_keys(claves)
    log.info(
        "pursuit_attachments_purgados",
        organization_id=organization_id,
        claves=len(claves),
        borrados=borrados,
    )
    return borrados
