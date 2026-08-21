"""Descarga + extracción trazable de texto de adjuntos (pliegos).

El binario se procesa en memoria, pero el resultado conserva el texto por
página y sus offsets (``documento_pages``). Eso permite citas verificables y
reprocesado de la extracción estructurada aunque el PDF de origen deje de
estar disponible, sin introducir un blob store obligatorio.

Solo se soportan ``application/pdf`` y ``text/plain`` en v1; cualquier otro
content-type marca el documento como ``error`` sin romper el resto del batch
(F8 sigue procesando el resto de la cola).
"""

from __future__ import annotations

import hashlib
import io
import multiprocessing
import re
from typing import Any

import pybreaker
import requests

from config import USER_AGENT, settings
from observability.logging import get_logger
from scraper.resilience import http_retry, placsp_breaker
from shared.outbound_http import pinned_https_request

log = get_logger(__name__)

_SUPPORTED_CONTENT_TYPES = frozenset({"application/pdf", "text/plain"})
_MAX_ERROR_DETAIL_LEN = 2000


def _status_de(exc: requests.HTTPError) -> int | None:
    """Código HTTP de un ``HTTPError``, venga de donde venga.

    ``PinnedHttpsResponse.raise_for_status`` (shared/outbound_http.py) construye
    el error **sin** ``response=``, así que ``exc.response`` es ``None`` en toda
    la ruta de descarga de documentos y leer ``exc.response.status_code`` a
    secas no detecta nada. Se cae entonces al texto del mensaje, cuyo formato
    fija esa misma función; ``test_document_fetcher`` ejercita el
    ``raise_for_status`` real para que un cambio de redacción rompa el test en
    vez de dejar la clasificación muda.
    """
    respuesta = getattr(exc, "response", None)
    codigo = getattr(respuesta, "status_code", None)
    if isinstance(codigo, int):
        return codigo
    match = re.search(r"\b(\d{3})\b", str(exc))
    return int(match.group(1)) if match else None


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
    allowed_hosts = (
        frozenset(
            host.strip() for host in settings.DOCUMENT_ALLOWED_HOSTS.split(",") if host.strip()
        )
        if settings.ENV in ("prod", "staging")
        else frozenset()
    )
    headers = {"User-Agent": USER_AGENT}

    with pinned_https_request(
        "GET",
        uri,
        headers=headers,
        timeout_seconds=float(settings.REQUEST_TIMEOUT),
        allowed_hosts=allowed_hosts or None,
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


def _extract_pdf_pages_local(content: bytes, *, max_pages: int, max_text_chars: int) -> list[str]:
    """Extrae texto por página. Import diferido — ``[pliegos]`` es opcional."""
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise DocumentFetchError("pypdf no está instalado (extra [pliegos] ausente)") from e

    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise DocumentFetchError("PDF cifrado — extracción no soportada en v1")
        if len(reader.pages) > max_pages:
            raise DocumentFetchError(f"PDF excede el máximo de {max_pages} páginas")
        pages_text: list[str] = []
        total_chars = 0
        for page in reader.pages:
            page_text = page.extract_text() or ""
            total_chars += len(page_text)
            if total_chars > max_text_chars:
                raise DocumentFetchError("PDF excede el máximo de texto extraíble permitido")
            pages_text.append(page_text.strip())
    except DocumentFetchError:
        raise
    except Exception as e:
        # pypdf lanza tipos variados (PdfReadError y otros) ante PDFs corruptos;
        # cualquier fallo aquí es "no se pudo extraer", no un bug de nuestro código.
        raise DocumentFetchError(f"PDF corrupto o ilegible: {e}") from e

    texto = "\n".join(pages_text).strip()
    if not texto:
        raise DocumentFetchError("PDF sin texto extraíble (posible escaneado sin OCR)")
    return pages_text


def _extract_pdf_text_local(content: bytes, *, max_pages: int, max_text_chars: int) -> str:
    """Compatibilidad: devuelve el texto agregado del PDF."""
    return "\n".join(
        _extract_pdf_pages_local(
            content,
            max_pages=max_pages,
            max_text_chars=max_text_chars,
        )
    ).strip()


def _pdf_extraction_worker(
    content: bytes,
    max_pages: int,
    max_text_chars: int,
    result_connection: Any,
) -> None:
    """Ejecuta el parser en un proceso aislado y devuelve solo texto o error.

    pypdf procesa estructuras controladas por terceros. Aislarlo permite
    terminar un parser bloqueado o excesivamente costoso sin comprometer al
    worker que procesa el lote completo.
    """
    try:
        result_connection.send(
            (
                "ok",
                _extract_pdf_pages_local(
                    content, max_pages=max_pages, max_text_chars=max_text_chars
                ),
            )
        )
    except Exception as exc:  # El padre convierte el error en DocumentFetchError.
        result_connection.send(("error", str(exc)))
    finally:
        result_connection.close()


def _extract_pdf_pages(content: bytes) -> list[str]:
    """Extrae páginas de PDF con límites de recursos también en tiempo.

    En producción y staging se usa un proceso desechable: si un PDF malicioso
    bloquea el parser, se corta al vencer el presupuesto configurado. En local
    se conserva la ejecución directa para que el ciclo de desarrollo y los
    tests no dependan del mecanismo spawn de cada sistema operativo.
    """
    max_pages = settings.MAX_DOCUMENT_PAGES
    max_text_chars = settings.MAX_DOCUMENT_TEXT_CHARS
    timeout_seconds = float(settings.DOCUMENT_EXTRACTION_TIMEOUT_SECONDS)

    if settings.ENV not in ("prod", "staging") or timeout_seconds <= 0:
        return _extract_pdf_pages_local(
            content,
            max_pages=max_pages,
            max_text_chars=max_text_chars,
        )

    context = multiprocessing.get_context("spawn")
    receive_connection, send_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_pdf_extraction_worker,
        args=(content, max_pages, max_text_chars, send_connection),
        daemon=True,
    )

    try:
        process.start()
        # El padre consume antes de hacer join: el texto puede ocupar varios MB
        # y bloquear el pipe si se esperase a que el hijo terminase primero.
        send_connection.close()
        if not receive_connection.poll(timeout_seconds):
            process.terminate()
            process.join(timeout=1)
            raise DocumentFetchError(
                f"PDF excede el tiempo máximo de extracción ({timeout_seconds:g} segundos)"
            )

        try:
            outcome, payload = receive_connection.recv()
        except EOFError as exc:
            raise DocumentFetchError(
                "El proceso de extracción de PDF terminó inesperadamente"
            ) from exc

        process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)

        if outcome != "ok":
            raise DocumentFetchError(str(payload))
        if not isinstance(payload, list) or not all(isinstance(page, str) for page in payload):
            raise DocumentFetchError("El extractor devolvió un resultado de páginas inválido")
        return payload
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
        receive_connection.close()
        send_connection.close()


def _extract_pdf_text(content: bytes) -> str:
    """Compatibilidad: texto agregado a partir de las páginas extraídas."""
    return "\n".join(_extract_pdf_pages(content)).strip()


def _extract_pages(content: bytes, content_type: str | None) -> list[str]:
    """Despacha extracción preservando límites de página."""
    if content_type == "text/plain":
        texto = content.decode("utf-8", errors="replace").strip()
        if len(texto) > settings.MAX_DOCUMENT_TEXT_CHARS:
            raise DocumentFetchError("text/plain excede el máximo de texto permitido")
        if not texto:
            raise DocumentFetchError("text/plain vacío tras decodificar")
        return [texto]
    if content_type in (None, "application/pdf"):
        return _extract_pdf_pages(content)
    raise DocumentFetchError(f"content-type no soportado: {content_type!r}")


def _extract_text(content: bytes, content_type: str | None) -> str:
    """Despacha la extracción según content-type. v1: PDF + text/plain."""
    return "\n".join(_extract_pages(content, content_type)).strip()


def fetch_and_extract(documento: dict[str, Any]) -> str:
    """Descarga ``documento['uri']`` transitoriamente, extrae su texto y
    persiste el resultado vía ``DocumentosRepository``.

    ``documento`` es una fila de ``DocumentosRepository.list_pendientes()``
    (dict con al menos ``id``/``uri``). El binario nunca se persiste.

    Devuelve ``"extracted"``, ``"error"`` o ``"skipped"`` — para que el llamador
    (job de embeddings, F8) instrumente métricas sin releer la fila.
    ``"skipped"`` significa que no se llegó a intentar nada (breaker abierto):
    la fila se queda en ``pending`` y entra en el lote siguiente.
    """
    from db.repositories.documentos import DocumentosRepository

    repo = DocumentosRepository()
    documento_id = int(documento["id"])
    uri = str(documento["uri"])

    try:
        content, content_type = _download_bytes(uri)
    except pybreaker.CircuitBreakerError as e:
        # El breaker abierto no dice nada de ESTE documento: dice que PLACSP
        # está rechazando ahora mismo. Marcarlo 'error' lo sacaría de
        # ``list_pendientes`` para siempre por una condición transitoria — así
        # se perdieron 1.702 documentos (el 66% de los errores acumulados en
        # producción a 2026-08-18) antes de que existiera esta rama. La fila se
        # queda ``pending`` y el lote siguiente la reintenta.
        log.info("document_fetch_skipped_breaker_open", documento_id=documento_id, error=str(e))
        return "skipped"
    except requests.HTTPError as e:
        # El servlet de PLACSP contesta 500 (NullPointerException), no 404,
        # cuando el token rotativo de la URI ha caducado. Se marca error como
        # cualquier otro fallo de descarga —conservando el prefijo, que es lo
        # que distingue "falló la red" de "falló la extracción"— pero nombrando
        # la causa: estos son justo los que un token nuevo del CODICE resucita.
        detalle = (
            f"descarga fallida: token caducado (500): {e}"
            if _status_de(e) == 500
            else f"descarga fallida: {e}"
        )
        log.warning("document_fetch_download_failed", documento_id=documento_id, error=str(e))
        repo.mark_error(documento_id, error_detail=detalle[:_MAX_ERROR_DETAIL_LEN])
        return "error"
    except Exception as e:
        log.warning("document_fetch_download_failed", documento_id=documento_id, error=str(e))
        repo.mark_error(documento_id, error_detail=f"descarga fallida: {e}"[:_MAX_ERROR_DETAIL_LEN])
        return "error"

    sha256 = hashlib.sha256(content).hexdigest()
    size_bytes = len(content)

    try:
        pages = _extract_pages(content, content_type)
        texto = "\n".join(pages).strip()
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

    repo.mark_extracted(documento_id, texto=texto, sha256=sha256, pages=pages)
    log.info(
        "document_fetch_extracted",
        documento_id=documento_id,
        size_bytes=size_bytes,
        texto_len=len(texto),
    )
    return "extracted"
