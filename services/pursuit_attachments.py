"""Adjuntos propios de una oportunidad: límites, enlaces firmados y opt-in (C6.3).

El equipo ya podía leer los documentos del órgano y no podía guardar los suyos:
la memoria técnica, el DEUC, el aval y los borradores por los que pasó la oferta
vivían en un disco de red o en un correo. ``v127`` les da tabla; este módulo
pone las tres reglas que no son de esquema.

**Qué se puede subir.** Una allowlist de tipos y un tope de tamaño, los dos
comprobados aquí y no en el router: el mismo límite tiene que valer para
cualquier camino que acabe escribiendo en el bucket. La allowlist es de tipos
ofimáticos y PDF — no porque el bucket no aguante un `.zip`, sino porque un
adjunto que el producto no sabe enseñar ni indexar es un disco de red con más
pasos.

**Cómo se descarga.** Con un enlace firmado que caduca, no con la sesión. El
navegador tiene que poder pedir el fichero directamente —y una descarga que
arrastra la cookie a un dominio de almacenamiento es exactamente lo que no se
quiere—, así que la autorización viaja en la URL, acotada en el tiempo y al
adjunto concreto. Caducado responde 403, que es el criterio de aceptación.

**Qué lee el asistente.** Nada, salvo que alguien lo diga por fichero
(``indexable``). Un adjunto propio lleva precios, márgenes y nombres; indexarlo
por defecto lo metería en el contexto que el asistente cita sin que nadie lo
hubiera decidido.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Final

from db.repositories.pursuit_attachments import PursuitAttachmentRepository
from db.repositories.pursuits import PursuitRepository
from observability.logging import get_logger
from services.organizations import resolve_organization
from services.pursuits import PursuitNotFoundError
from shared.dto import PursuitAttachmentListResponse, PursuitAttachmentOut

log = get_logger(__name__)

_repo = PursuitAttachmentRepository()
_pursuits = PursuitRepository()

#: Tope por fichero. Veinticinco megas cubre una memoria técnica con planos
#: escaneados, que es el adjunto grande de verdad; por encima de eso lo que
#: llega suele ser un ZIP del expediente entero, que es lo que esta tabla no
#: quiere ser.
MAX_BYTES: Final = 25 * 1024 * 1024

#: Tipos admitidos. PDF y ofimática, más texto plano para los guiones.
#: Deliberadamente corta: se amplía cuando alguien traiga el caso, no antes.
TIPOS_ADMITIDOS: Final[frozenset[str]] = frozenset(
    {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/plain",
        "text/markdown",
        "text/csv",
        "image/png",
        "image/jpeg",
    }
)

#: Validez del enlace de descarga. Quince minutos: lo que dura pulsar el enlace
#: y que el navegador lo baje, no lo que dura una sesión de trabajo. Un enlace
#: que sobrevive a la pestaña es un enlace que acaba pegado en un chat.
DESCARGA_TTL_SEGUNDOS: Final = 900

_PREFIJO_FIRMA = b"pursuit-adjunto:"


class AttachmentError(ValueError):
    """El fichero no cumple los límites.

    Lleva el ``codigo`` HTTP que le corresponde porque el router tiene que
    distinguir «pesa demasiado» (413) de «no es un tipo admitido» (415), y
    deducirlo del texto del mensaje —que es lo que hacía— se rompe en cuanto
    alguien reescribe una frase.
    """

    def __init__(self, mensaje: str, *, codigo: int = 415) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


class AttachmentNotFoundError(LookupError):
    """El adjunto no existe dentro de la organización autorizada."""


class AttachmentStoreError(RuntimeError):
    """No hay almacén de objetos configurado, o falló."""


def _to_out(fila: dict[str, Any]) -> PursuitAttachmentOut:
    return PursuitAttachmentOut(
        id=int(fila["id"]),
        pursuit_id=int(fila["pursuit_id"]),
        organization_id=int(fila["organization_id"]),
        filename=str(fila["filename"]),
        content_type=str(fila["content_type"]),
        bytes=int(fila["bytes"]),
        sha256=str(fila["sha256"]),
        indexable=bool(fila["indexable"]),
        uploaded_by_user_id=(
            int(fila["uploaded_by_user_id"]) if fila.get("uploaded_by_user_id") else None
        ),
        created_at=fila.get("created_at"),
    )


def _validar(contenido: bytes, filename: str, content_type: str) -> tuple[str, str]:
    """Comprueba tamaño y tipo. Devuelve ``(filename_limpio, content_type)``."""
    if not contenido:
        raise AttachmentError("El fichero está vacío.", codigo=422)
    if len(contenido) > MAX_BYTES:
        raise AttachmentError(
            f"El fichero ocupa {len(contenido)} bytes y el máximo son {MAX_BYTES}.",
            codigo=413,
        )
    tipo = (content_type or "").split(";", 1)[0].strip().lower()
    if tipo not in TIPOS_ADMITIDOS:
        raise AttachmentError(
            f"Tipo no admitido: {tipo or 'sin declarar'}. "
            f"Admitidos: {', '.join(sorted(TIPOS_ADMITIDOS))}."
        )
    # El nombre viaja a una cabecera `Content-Disposition`: se le quitan las
    # rutas y los saltos de línea antes de tocar nada más.
    limpio = (filename or "").replace("\\", "/").split("/")[-1]
    limpio = " ".join(limpio.split())[:200]
    if not limpio:
        raise AttachmentError("El fichero no trae nombre.", codigo=422)
    return limpio, tipo


def firmar_descarga(attachment_id: int, *, ahora: float | None = None) -> tuple[str, int]:
    """Devuelve ``(token, expira_en_epoch)`` para descargar ese adjunto.

    El token cubre el id **y** la caducidad: sin la fecha dentro de la firma,
    cambiar el `?exp=` de la URL alargaría el permiso a voluntad.
    """
    from shared.signing import sign

    expira = int((ahora if ahora is not None else time.time()) + DESCARGA_TTL_SEGUNDOS)
    payload = _PREFIJO_FIRMA + f"{int(attachment_id)}:{expira}".encode("ascii")
    return sign(payload), expira


def verificar_descarga(
    attachment_id: int, expira: int, token: str, *, ahora: float | None = None
) -> bool:
    """``True`` si la firma es válida y no ha caducado."""
    from shared.signing import verify

    momento = ahora if ahora is not None else time.time()
    if int(expira) < momento:
        return False
    payload = _PREFIJO_FIRMA + f"{int(attachment_id)}:{int(expira)}".encode("ascii")
    return verify(payload, token or "")


def listar(
    user_id: int, pursuit_id: int, *, organization_id: int | None = None
) -> PursuitAttachmentListResponse:
    """Adjuntos de la oportunidad, el más reciente primero."""
    resolved_id, _role = resolve_organization(user_id, organization_id)
    if _pursuits.get(resolved_id, pursuit_id) is None:
        raise PursuitNotFoundError(f"La oportunidad {pursuit_id} no existe en este espacio.")
    filas = _repo.listar(pursuit_id=pursuit_id, organization_id=resolved_id)
    return PursuitAttachmentListResponse(
        pursuit_id=pursuit_id,
        organization_id=resolved_id,
        items=[_to_out(f) for f in filas],
        max_bytes=MAX_BYTES,
        tipos_admitidos=sorted(TIPOS_ADMITIDOS),
    )


def subir(
    user_id: int,
    pursuit_id: int,
    *,
    contenido: bytes,
    filename: str,
    content_type: str,
    organization_id: int | None = None,
) -> PursuitAttachmentOut:
    """Guarda el binario en el bucket y registra la fila.

    El orden importa: primero el objeto, después la fila. Al revés, un fallo del
    bucket dejaría una fila que promete un fichero que no existe — y el listado
    de la pestaña Expediente enseñaría adjuntos que no se pueden descargar. Al
    derecho, el peor caso es un objeto huérfano, que la purga por prefijo de la
    organización recoge.
    """
    from shared.object_store import ObjectStoreError, get_object_store, pursuit_attachment_key

    resolved_id, _role = resolve_organization(user_id, organization_id)
    nombre, tipo = _validar(contenido, filename, content_type)
    if _pursuits.get(resolved_id, pursuit_id) is None:
        raise PursuitNotFoundError(f"La oportunidad {pursuit_id} no existe en este espacio.")

    huella = hashlib.sha256(contenido).hexdigest()
    clave = pursuit_attachment_key(resolved_id, huella)
    if clave is None:  # pragma: no cover - la huella siempre es hex de 64
        raise AttachmentStoreError("No se pudo construir la clave del adjunto.")

    almacen = get_object_store()
    if not almacen.enabled:
        raise AttachmentStoreError(
            "No hay almacén de objetos configurado: los adjuntos propios necesitan uno."
        )
    try:
        almacen.put(clave, contenido, content_type=tipo)
    except ObjectStoreError as exc:
        raise AttachmentStoreError(str(exc)) from exc

    fila = _repo.crear(
        pursuit_id=pursuit_id,
        organization_id=resolved_id,
        blob_key=clave,
        filename=nombre,
        content_type=tipo,
        bytes_=len(contenido),
        sha256=huella,
        uploaded_by_user_id=user_id,
    )
    if fila is None:
        raise PursuitNotFoundError(f"La oportunidad {pursuit_id} no existe en este espacio.")
    log.info(
        "pursuit_attachment_subido",
        pursuit_id=pursuit_id,
        organization_id=resolved_id,
        bytes=len(contenido),
        content_type=tipo,
    )
    return _to_out(fila)


def descargar(attachment_id: int, expira: int, token: str) -> tuple[bytes, str, str]:
    """Contenido de un adjunto a partir de un enlace firmado.

    **No resuelve organización ni sesión**: la autorización es la firma, que ya
    nombra el adjunto concreto. Por eso comprueba la caducidad antes de tocar la
    base — un token caducado no debe ni revelar si el id existe.
    """
    from shared.object_store import ObjectStoreError, get_object_store

    if not verificar_descarga(attachment_id, expira, token):
        raise PermissionError("El enlace de descarga no es válido o ha caducado.")
    with_org = _repo.get_por_id(attachment_id)
    if with_org is None:
        raise AttachmentNotFoundError(f"El adjunto {attachment_id} no existe.")
    try:
        datos = get_object_store().get(str(with_org["blob_key"]))
    except ObjectStoreError as exc:
        raise AttachmentStoreError(str(exc)) from exc
    if datos is None:
        raise AttachmentNotFoundError(f"El adjunto {attachment_id} ya no está en el almacén.")
    return datos, str(with_org["filename"]), str(with_org["content_type"])


def marcar_indexable(
    user_id: int, attachment_id: int, *, indexable: bool, organization_id: int | None = None
) -> PursuitAttachmentOut:
    """Opt-in (o su retirada) para que el asistente lea este adjunto."""
    resolved_id, _role = resolve_organization(user_id, organization_id)
    fila = _repo.marcar_indexable(
        attachment_id=attachment_id, organization_id=resolved_id, indexable=indexable
    )
    if fila is None:
        raise AttachmentNotFoundError(f"El adjunto {attachment_id} no existe en este espacio.")
    log.info(
        "pursuit_attachment_indexable",
        attachment_id=attachment_id,
        organization_id=resolved_id,
        indexable=bool(indexable),
    )
    return _to_out(fila)


def borrar(user_id: int, attachment_id: int, *, organization_id: int | None = None) -> None:
    """Quita la fila y su objeto del bucket."""
    from shared.object_store import purge_keys

    resolved_id, _role = resolve_organization(user_id, organization_id)
    fila = _repo.borrar(attachment_id=attachment_id, organization_id=resolved_id)
    if fila is None:
        raise AttachmentNotFoundError(f"El adjunto {attachment_id} no existe en este espacio.")
    # Best-effort: la fila ya no está, y un objeto huérfano no es visible para
    # nadie. Fallar aquí dejaría al usuario con un error después de que el
    # adjunto desapareciera de su pantalla.
    try:
        purge_keys([str(fila["blob_key"])])
    except Exception:
        log.warning("pursuit_attachment_purge_failed", attachment_id=attachment_id, exc_info=True)
