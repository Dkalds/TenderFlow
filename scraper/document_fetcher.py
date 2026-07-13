"""Descarga transitoria + extracción de texto de adjuntos (pliegos).

Plan Pliegos+RAG, fase A3 (F7). Decisión de producto v1: el PDF se descarga
**en memoria**, se extrae el texto y el binario se descarta — no hay blob
storage (``documentos.storage_key`` queda ``NULL``, columna reservada para
añadir persistencia de binarios en el futuro sin otra migración).

Solo se soportan ``application/pdf`` y ``text/plain`` en v1; cualquier otro
content-type marca el documento como ``error`` sin romper el resto del batch
(F8 sigue procesando el resto de la cola).
"""

from __future__ import annotations

import hashlib
import io
import urllib.parse
from typing import Any

import requests

from config import USER_AGENT, settings
from observability.logging import get_logger
from scraper.resilience import http_retry, placsp_breaker
from shared.ssrf import resolve_and_validate

log = get_logger(__name__)

_SUPPORTED_CONTENT_TYPES = frozenset({"application/pdf", "text/plain"})
_MAX_ERROR_DETAIL_LEN = 2000


class DocumentFetchError(RuntimeError):
    """Fallo recuperable de extracción (content-type no soportado, PDF corrupto,
    PDF sin texto extraíble). Distinto de fallos de descarga (red/SSRF/tamaño),
    que se propagan como la excepción original del transporte."""


@placsp_breaker
@http_retry
def _download_bytes(uri: str) -> tuple[bytes, str | None]:
    """Descarga ``uri`` en memoria con guardas SSRF + tamaño.

    DNS-pinning (mismo helper que webhooks, ``shared/ssrf.py``): resuelve y
    valida la IP en cada intento (no solo al parsear el CODICE), cerrando la
    ventana TOCTOU. Guardas de tamaño replican el patrón de
    ``scraper/bulk_downloader.py`` (Content-Length + contador de bytes en
    streaming, por si el header miente).
    """
    pinned_url = resolve_and_validate(uri)
    original_host = urllib.parse.urlparse(uri).hostname or ""
    headers = {"User-Agent": USER_AGENT, "Host": original_host}

    with requests.get(
        pinned_url,
        headers=headers,
        stream=True,
        timeout=settings.REQUEST_TIMEOUT,
        verify=True,
    ) as r:
        r.raise_for_status()
        content_type = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower() or None

        content_length = r.headers.get("Content-Length")
        if content_length is not None and int(content_length) > settings.MAX_DOCUMENT_SIZE_BYTES:
            raise ValueError(
                f"Content-Length {int(content_length):,} bytes supera el límite "
                f"de {settings.MAX_DOCUMENT_SIZE_BYTES:,} bytes."
            )

        chunks: list[bytes] = []
        total = 0
        for chunk in r.iter_content(chunk_size=8192):
            total += len(chunk)
            if total > settings.MAX_DOCUMENT_SIZE_BYTES:
                raise ValueError(
                    f"Descarga abortada: tamaño real supera "
                    f"{settings.MAX_DOCUMENT_SIZE_BYTES:,} bytes."
                )
            chunks.append(chunk)

    return b"".join(chunks), content_type


def _extract_pdf_text(content: bytes) -> str:
    """Extrae texto de un PDF con pypdf. Import diferido — [pliegos] es opcional."""
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise DocumentFetchError("pypdf no está instalado (extra [pliegos] ausente)") from e

    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise DocumentFetchError("PDF cifrado — extracción no soportada en v1")
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except DocumentFetchError:
        raise
    except Exception as e:
        # pypdf lanza tipos variados (PdfReadError y otros) ante PDFs corruptos;
        # cualquier fallo aquí es "no se pudo extraer", no un bug de nuestro código.
        raise DocumentFetchError(f"PDF corrupto o ilegible: {e}") from e

    texto = "\n".join(pages_text).strip()
    if not texto:
        raise DocumentFetchError("PDF sin texto extraíble (posible escaneado sin OCR)")
    return texto


def _extract_text(content: bytes, content_type: str | None) -> str:
    """Despacha la extracción según content-type. v1: PDF + text/plain."""
    if content_type == "text/plain":
        texto = content.decode("utf-8", errors="replace").strip()
        if not texto:
            raise DocumentFetchError("text/plain vacío tras decodificar")
        return texto
    if content_type in (None, "application/pdf"):
        return _extract_pdf_text(content)
    raise DocumentFetchError(f"content-type no soportado: {content_type!r}")


def fetch_and_extract(documento: dict[str, Any]) -> str:
    """Descarga ``documento['uri']`` transitoriamente, extrae su texto y
    persiste el resultado vía ``DocumentosRepository``.

    ``documento`` es una fila de ``DocumentosRepository.list_pendientes()``
    (dict con al menos ``id``/``uri``). El binario nunca se persiste.

    Devuelve ``"extracted"`` o ``"error"`` — para que el llamador (job de
    embeddings, F8) instrumente métricas sin releer la fila.
    """
    from db.repositories.documentos import DocumentosRepository

    repo = DocumentosRepository()
    documento_id = int(documento["id"])
    uri = str(documento["uri"])

    try:
        content, content_type = _download_bytes(uri)
    except Exception as e:
        log.warning("document_fetch_download_failed", documento_id=documento_id, error=str(e))
        repo.mark_error(documento_id, error_detail=f"descarga fallida: {e}"[:_MAX_ERROR_DETAIL_LEN])
        return "error"

    sha256 = hashlib.sha256(content).hexdigest()
    size_bytes = len(content)

    try:
        texto = _extract_text(content, content_type)
    except DocumentFetchError as e:
        log.warning("document_fetch_extract_failed", documento_id=documento_id, error=str(e))
        # Persistimos lo que sí se supo (descarga OK) antes de marcar error —
        # útil para diagnóstico (¿fue la red o el contenido lo que falló?).
        repo.mark_downloaded(
            documento_id,
            filename=documento.get("filename"),
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
        )
        repo.mark_error(documento_id, error_detail=str(e)[:_MAX_ERROR_DETAIL_LEN])
        return "error"

    repo.mark_extracted(documento_id, texto=texto, sha256=sha256)
    log.info(
        "document_fetch_extracted",
        documento_id=documento_id,
        size_bytes=size_bytes,
        texto_len=len(texto),
    )
    return "extracted"
