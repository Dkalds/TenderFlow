"""Descarga + extracción trazable de texto de adjuntos (pliegos).

El resultado conserva el texto por página y sus offsets (``documento_pages``),
lo que permite citas verificables y reprocesado de la extracción estructurada.

Desde el stream S8 del plan 2026-09 v2 el **binario también se conserva**, en el
almacén de objetos de ``shared/object_store.py`` (clave
``documentos/{source_hash}``, columna ``documentos.blob_key`` de ``v103``).
Importa porque los enlaces de PLACSP llevan un token rotativo que caduca: hasta
ahora, re-extraer exigía volver a la fuente y el 82% de las URIs antiguas ya no
respondía. Si la descarga falla y hay binario guardado, se extrae de él y el
documento termina en ``extracted`` igual. Si no hay almacén configurado, todo
se comporta como antes de S8 (``NullObjectStore``).

Formatos soportados
-------------------
- ``application/pdf`` — texto por página real. Un PDF **sin** texto extraíble
  (escaneado) pasa por OCR (``ocrmypdf``) si el binario está disponible, y sus
  páginas quedan marcadas ``ocr = true`` en ``documento_pages``. Un PDF que sí
  trae texto **nunca** pasa por OCR: el OCR sólo se invoca en la rama de fallo.
- ``text/plain`` — una sola página.
- Office Open XML (``.docx``) y OpenDocument (``.odt``).
- ``application/zip`` — se expande y se procesan los PDF y DOCX de dentro.

**Convención de página lógica en DOCX y ODT**: ninguno de los dos formatos
tiene páginas — la paginación la decide el motor de renderizado al imprimir, y
no está en el fichero. Se agrupan los párrafos no vacíos en bloques de
:data:`_PARRAFOS_POR_PAGINA_LOGICA`, en orden documental, y cada bloque es una
«página». Los offsets salen entonces
igual que en un PDF (``mark_extracted`` los calcula sobre el texto agregado),
así que una cita de la ficha sigue anclando a una región concreta y verificable
del documento; lo que no puede hacer es decir «página 3 de la impresión». Es
estable frente a re-extracciones porque sólo depende del orden de los párrafos.

**Zip bomb**: el número de entradas y el tamaño descomprimido acumulado están
acotados (:data:`_ZIP_MAX_ENTRADAS` y ``MAX_DOCUMENT_SIZE_BYTES``), y la lectura
de cada entrada se hace con un tope explícito en vez de fiarse de ``file_size``
de la cabecera, que la escribe quien construyó el ZIP. No hay recursión: un ZIP
dentro de un ZIP se ignora.

Un content-type que no sepamos leer —o cuya dependencia opcional no esté
instalada— marca el documento como ``unsupported`` **con su content-type**
(``v103``), no como ``error``: son cosas distintas y sólo separadas se puede
medir cuánta cobertura falta y de qué formato.

Configuración del OCR (variables de entorno, leídas aquí y no en
``config/settings.py`` porque sólo las usa este módulo y sólo en el runner de
``pliegos.yml``)::

    DOCUMENT_OCR_ENABLED           1 (defecto) | 0
    DOCUMENT_OCR_LANGUAGES         idiomas de tesseract (defecto: spa+eng)
    DOCUMENT_OCR_TIMEOUT_SECONDS   presupuesto por documento (defecto: 600)

El tope de páginas del OCR es ``MAX_DOCUMENT_PAGES``, el mismo que el del
extractor de texto.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import multiprocessing
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pybreaker
import requests

from config import USER_AGENT, settings
from observability.logging import get_logger
from scraper.resilience import http_retry, placsp_breaker
from shared.object_store import ObjectStoreError, document_blob_key, get_object_store
from shared.outbound_http import pinned_https_request

log = get_logger(__name__)

CONTENT_TYPE_PDF = "application/pdf"
CONTENT_TYPE_TEXT = "text/plain"
CONTENT_TYPE_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
CONTENT_TYPE_ODT = "application/vnd.oasis.opendocument.text"
CONTENT_TYPE_ZIP = "application/zip"

#: Los servidores de PLACSP no son consistentes con el content-type del ZIP;
#: estos tres son la misma cosa.
_ZIP_ALIASES = frozenset({CONTENT_TYPE_ZIP, "application/x-zip-compressed", "multipart/x-zip"})

_SUPPORTED_CONTENT_TYPES = frozenset(
    {
        CONTENT_TYPE_PDF,
        CONTENT_TYPE_TEXT,
        CONTENT_TYPE_DOCX,
        CONTENT_TYPE_ODT,
        *_ZIP_ALIASES,
    }
)

_MAX_ERROR_DETAIL_LEN = 2000


def supported_content_types() -> frozenset[str]:
    """Content-types que este módulo sabe extraer.

    Se expone para que el despacho de :func:`_extraer_paginas_de_tipo` y la
    lista declarada no puedan divergir sin que un test lo note: hasta S8 la
    lista era una constante que nadie comparaba con el código que la
    implementaba.
    """
    return _SUPPORTED_CONTENT_TYPES


#: Párrafos por página lógica en DOCX/ODT. Ver la convención del docstring del
#: módulo. 40 párrafos es del orden de una página impresa de pliego y mantiene
#: los fragmentos dentro de lo que el chunker y el selector de páginas de la
#: ficha (``services/rag/fact_sheet.py``) manejan sin cortar contexto útil.
_PARRAFOS_POR_PAGINA_LOGICA = 40

#: Entradas máximas de un ZIP. Un pliego real trae unidades de ficheros; cien
#: entradas ya no es un expediente, es un intento de agotar el runner.
_ZIP_MAX_ENTRADAS = 50

#: Extensiones que se procesan dentro de un ZIP. Sin recursión: un ``.zip``
#: dentro de otro se ignora a propósito.
_ZIP_EXTENSIONES = {".pdf": CONTENT_TYPE_PDF, ".docx": CONTENT_TYPE_DOCX}

#: Marca del fallo «este PDF no tiene texto». Se compara por texto y no por
#: tipo de excepción porque el parser aislado (``_pdf_extraction_worker``)
#: devuelve el error por un ``Pipe`` como cadena: el tipo no sobrevive al
#: cruce de procesos, y es justo en producción donde ese camino se usa.
_MSG_PDF_SIN_TEXTO = "PDF sin texto extraíble (posible escaneado sin OCR)"


@dataclass(frozen=True)
class PaginaExtraida:
    """Una página lógica y si su texto lo produjo el OCR.

    Gemela de ``db.repositories.documentos.DocumentoPagina``, que es el tipo
    que persiste el repositorio. Se duplica el par de campos —y no se importa
    aquel— para no meter un import de ``db/`` en el árbol de módulos de
    ``scraper/`` en tiempo de carga: el fetcher difiere ese import hasta el
    momento de escribir, como ya hacía antes de S8. La conversión es una línea
    en :func:`fetch_and_extract`.
    """

    texto: str
    ocr: bool = False


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
    """Fallo recuperable de extracción (PDF corrupto, PDF sin texto ni OCR,
    ZIP que excede los límites). Distinto de fallos de descarga (red/SSRF/
    tamaño), que se propagan como la excepción original del transporte."""


class UnsupportedDocumentError(DocumentFetchError):
    """El formato no se sabe leer: no es un fallo, es cobertura que falta.

    Lleva el ``content_type`` para que la fila quede contabilizada por formato
    (``documentos.status = 'unsupported'``, ``v103``) y el día que se añada el
    soporte se sepa exactamente cuántas filas resucitar.
    """

    def __init__(self, mensaje: str, *, content_type: str | None) -> None:
        super().__init__(mensaje)
        self.content_type = content_type


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
        raise DocumentFetchError(_MSG_PDF_SIN_TEXTO)
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


# ── OCR de PDF escaneados (S8.3) ───────────────────────────────────────────


def _entorno_bool(nombre: str, *, por_defecto: bool) -> bool:
    crudo = os.environ.get(nombre, "").strip().lower()
    if not crudo:
        return por_defecto
    return crudo not in {"0", "false", "no", "off"}


def ocr_binario() -> str | None:
    """Ruta absoluta de ``ocrmypdf``, o ``None`` si no está en el runner.

    Se resuelve con ``shutil.which`` y se invoca por ruta absoluta: llamar a
    ``"ocrmypdf"`` a secas dejaría que el ``PATH`` del proceso decidiera qué
    binario se ejecuta.
    """
    if not _entorno_bool("DOCUMENT_OCR_ENABLED", por_defecto=True):
        return None
    return shutil.which("ocrmypdf")


def _ocr_pdf(content: bytes) -> bytes | None:
    """Devuelve el PDF con capa de texto, o ``None`` si el OCR no se pudo hacer.

    Degradación limpia y deliberada: si ``ocrmypdf`` no está instalado, falla o
    se pasa de tiempo, se devuelve ``None`` y el llamante vuelve al error de
    siempre («escaneado sin OCR»). El OCR es una mejora de cobertura; su
    ausencia no puede convertir un lote entero en rojo.
    """
    binario = ocr_binario()
    if binario is None:
        log.info("document_ocr_no_disponible")
        return None

    timeout = float(os.environ.get("DOCUMENT_OCR_TIMEOUT_SECONDS", "600") or 600)
    idiomas = os.environ.get("DOCUMENT_OCR_LANGUAGES", "spa+eng").strip() or "spa+eng"

    with tempfile.TemporaryDirectory(prefix="tf-ocr-") as tmp:
        entrada = Path(tmp) / "entrada.pdf"
        salida = Path(tmp) / "salida.pdf"
        entrada.write_bytes(content)
        comando = [
            binario,
            "--force-ocr",
            "--output-type",
            "pdf",
            "--optimize",
            "0",
            "--quiet",
            # El mismo tope que el extractor de texto: el OCR es caro por
            # página y un pliego de 400 páginas escaneadas se comería el
            # presupuesto del lote entero.
            "--pages",
            f"1-{settings.MAX_DOCUMENT_PAGES}",
            "-l",
            idiomas,
            str(entrada),
            str(salida),
        ]
        try:
            # Comando fijo y ruta absoluta resuelta por ``shutil.which``: nada
            # de lo que va aquí lo controla el documento descargado.
            proceso = subprocess.run(
                comando,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.warning("document_ocr_failed", error=str(exc))
            return None
        if proceso.returncode != 0 or not salida.is_file():
            log.warning(
                "document_ocr_failed",
                returncode=proceso.returncode,
                stderr=proceso.stderr[-500:].decode("utf-8", errors="replace"),
            )
            return None
        return salida.read_bytes()


def _es_pdf_sin_texto(exc: DocumentFetchError) -> bool:
    return _MSG_PDF_SIN_TEXTO in str(exc)


def _extract_pdf_paginas_con_ocr(content: bytes) -> list[PaginaExtraida]:
    """Páginas de un PDF, cayendo al OCR **sólo** si no había texto.

    El orden importa y es el criterio de aceptación de S8.3: un PDF con capa de
    texto no pasa nunca por ``ocrmypdf``, porque el OCR sólo se intenta desde
    la rama de excepción. Además de ahorrar minutos de CPU por documento, el
    texto real del PDF es siempre mejor que su transcripción.
    """
    try:
        return [PaginaExtraida(texto=texto) for texto in _extract_pdf_pages(content)]
    except DocumentFetchError as exc:
        if not _es_pdf_sin_texto(exc):
            raise
        con_texto = _ocr_pdf(content)
        if con_texto is None:
            raise
        paginas = _extract_pdf_pages(con_texto)
        log.info("document_ocr_extracted", paginas=len(paginas))
        return [PaginaExtraida(texto=texto, ocr=True) for texto in paginas]


# ── DOCX y ODT (S8.2) ──────────────────────────────────────────────────────


def _importar_opcional(modulo: str, *, content_type: str, paquete: str) -> Any:
    """Importa una dependencia opcional o declara el formato ``unsupported``.

    ``importlib`` y no ``import x`` para que el tipo sea ``Any`` sin un
    ``# type: ignore``: ni ``python-docx`` ni ``odfpy`` publican stubs, y este
    módulo pasa mypy strict como el resto de producción.
    """
    try:
        return importlib.import_module(modulo)
    except ImportError as exc:
        raise UnsupportedDocumentError(
            f"content-type {content_type!r} soportado pero {paquete} no está "
            "instalado (extra [pliegos] ausente)",
            content_type=content_type,
        ) from exc


def _agrupar_en_paginas_logicas(parrafos: list[str]) -> list[str]:
    """Agrupa párrafos en páginas lógicas (ver la convención del módulo)."""
    utiles = [p.strip() for p in parrafos if p and p.strip()]
    if not utiles:
        return []
    paginas: list[str] = []
    for inicio in range(0, len(utiles), _PARRAFOS_POR_PAGINA_LOGICA):
        paginas.append("\n".join(utiles[inicio : inicio + _PARRAFOS_POR_PAGINA_LOGICA]))
        if len(paginas) >= settings.MAX_DOCUMENT_PAGES:
            break
    total = sum(len(p) for p in paginas)
    if total > settings.MAX_DOCUMENT_TEXT_CHARS:
        raise DocumentFetchError("El documento excede el máximo de texto extraíble permitido")
    return paginas


def _extract_docx_paginas(content: bytes) -> list[str]:
    """Párrafos y celdas de tabla de un ``.docx``, agrupados en páginas lógicas.

    Las tablas van detrás de los párrafos y no intercaladas: ``python-docx`` no
    expone el orden real entre ambos en su API pública, y fabricar un orden
    inventado haría que los offsets de una cita apuntaran a otro sitio en
    cuanto la librería cambiara. En un pliego las tablas son criterios y
    presupuestos —contenido que la ficha necesita— así que perderlas sería
    peor que ponerlas al final.
    """
    docx = _importar_opcional("docx", content_type=CONTENT_TYPE_DOCX, paquete="python-docx")
    try:
        documento = docx.Document(io.BytesIO(content))
        parrafos = [str(p.text) for p in documento.paragraphs]
        for tabla in documento.tables:
            for fila in tabla.rows:
                celdas = [str(celda.text).strip() for celda in fila.cells]
                parrafos.append(" | ".join(c for c in celdas if c))
    except Exception as exc:
        raise DocumentFetchError(f"DOCX corrupto o ilegible: {exc}") from exc

    paginas = _agrupar_en_paginas_logicas(parrafos)
    if not paginas:
        raise DocumentFetchError("DOCX sin texto extraíble")
    return paginas


def _extract_odt_paginas(content: bytes) -> list[str]:
    """Párrafos de un ``.odt``, agrupados con la misma convención que el DOCX."""
    opendocument = _importar_opcional(
        "odf.opendocument", content_type=CONTENT_TYPE_ODT, paquete="odfpy"
    )
    odf_text = _importar_opcional("odf.text", content_type=CONTENT_TYPE_ODT, paquete="odfpy")
    teletype = _importar_opcional("odf.teletype", content_type=CONTENT_TYPE_ODT, paquete="odfpy")
    try:
        documento = opendocument.load(io.BytesIO(content))
        parrafos = [
            str(teletype.extractText(nodo)) for nodo in documento.getElementsByType(odf_text.P)
        ]
    except Exception as exc:
        raise DocumentFetchError(f"ODT corrupto o ilegible: {exc}") from exc

    paginas = _agrupar_en_paginas_logicas(parrafos)
    if not paginas:
        raise DocumentFetchError("ODT sin texto extraíble")
    return paginas


# ── ZIP (S8.2) ─────────────────────────────────────────────────────────────


def _extract_zip_paginas(content: bytes) -> list[PaginaExtraida]:
    """Expande el ZIP y concatena las páginas de los PDF y DOCX de dentro.

    Las entradas se procesan en orden alfabético para que el resultado sea
    reproducible entre corridas: los offsets de ``documento_pages`` —y por
    tanto las citas ya persistidas— dependen del orden en que se concatenan.
    """
    try:
        archivo = zipfile.ZipFile(io.BytesIO(content))
    except Exception as exc:
        raise DocumentFetchError(f"ZIP corrupto o ilegible: {exc}") from exc

    with archivo:
        entradas = [info for info in archivo.infolist() if not info.is_dir()]
        if len(entradas) > _ZIP_MAX_ENTRADAS:
            raise DocumentFetchError(
                f"ZIP con {len(entradas)} entradas supera el máximo de {_ZIP_MAX_ENTRADAS}"
            )

        presupuesto = int(settings.MAX_DOCUMENT_SIZE_BYTES)
        paginas: list[PaginaExtraida] = []
        procesadas = 0
        for info in sorted(entradas, key=lambda i: i.filename):
            extension = Path(info.filename).suffix.lower()
            tipo_interno = _ZIP_EXTENSIONES.get(extension)
            if tipo_interno is None:
                continue
            # Lectura acotada: ``info.file_size`` lo escribe quien creó el ZIP
            # y una bomba lo declara pequeño. Se pide un byte más que el
            # presupuesto para poder detectar el exceso sin materializarlo.
            with archivo.open(info) as fh:
                datos = fh.read(presupuesto + 1)
            if len(datos) > presupuesto:
                raise DocumentFetchError(
                    "El contenido descomprimido del ZIP supera "
                    f"{settings.MAX_DOCUMENT_SIZE_BYTES:,} bytes"
                )
            presupuesto -= len(datos)
            procesadas += 1
            try:
                paginas.extend(_extraer_paginas_de_tipo(datos, tipo_interno))
            except DocumentFetchError as exc:
                # Un adjunto roto dentro del ZIP no invalida los demás: mismo
                # criterio fail-open que el lote diario.
                log.info("document_zip_entry_skipped", entry=info.filename, error=str(exc))

    if not paginas:
        raise UnsupportedDocumentError(
            f"ZIP sin PDF ni DOCX procesables ({procesadas} entradas candidatas)",
            content_type=CONTENT_TYPE_ZIP,
        )
    return paginas


# ── Despacho ───────────────────────────────────────────────────────────────


def _extraer_paginas_de_tipo(content: bytes, content_type: str) -> list[PaginaExtraida]:
    """Extrae páginas de un binario de ``content_type`` ya normalizado."""
    if content_type == CONTENT_TYPE_TEXT:
        texto = content.decode("utf-8", errors="replace").strip()
        if len(texto) > settings.MAX_DOCUMENT_TEXT_CHARS:
            raise DocumentFetchError("text/plain excede el máximo de texto permitido")
        if not texto:
            raise DocumentFetchError("text/plain vacío tras decodificar")
        return [PaginaExtraida(texto=texto)]
    if content_type == CONTENT_TYPE_PDF:
        return _extract_pdf_paginas_con_ocr(content)
    if content_type == CONTENT_TYPE_DOCX:
        return [PaginaExtraida(texto=t) for t in _extract_docx_paginas(content)]
    if content_type == CONTENT_TYPE_ODT:
        return [PaginaExtraida(texto=t) for t in _extract_odt_paginas(content)]
    if content_type in _ZIP_ALIASES:
        return _extract_zip_paginas(content)
    raise UnsupportedDocumentError(
        f"content-type no soportado: {content_type!r}", content_type=content_type
    )


def _extract_paginas(content: bytes, content_type: str | None) -> list[PaginaExtraida]:
    """Despacha extracción preservando límites de página.

    ``None`` sigue significando PDF: hay servidores de PLACSP que no declaran
    content-type y el PDF es, con diferencia, el caso mayoritario.
    """
    return _extraer_paginas_de_tipo(content, content_type or CONTENT_TYPE_PDF)


def _extract_pages(content: bytes, content_type: str | None) -> list[str]:
    """Compatibilidad: sólo el texto de cada página."""
    return [pagina.texto for pagina in _extract_paginas(content, content_type)]


def _extract_text(content: bytes, content_type: str | None) -> str:
    """Despacha la extracción según content-type y devuelve el texto agregado."""
    return "\n".join(_extract_pages(content, content_type)).strip()


# ── Almacén de objetos (S8.1) ──────────────────────────────────────────────


def _guardar_binario(
    source_hash: str | None,
    documento_id: int,
    content: bytes,
    content_type: str | None,
    sha256: str,
) -> str | None:
    """Guarda el binario y devuelve su clave, o ``None`` si no se guardó.

    Best-effort **a propósito**: un bucket caído o mal configurado no puede
    impedir que se extraiga el texto, que es lo que el producto necesita hoy.
    Lo que se pierde en ese caso es la posibilidad de re-extraer mañana sin
    volver a PLACSP, y eso queda en el log.
    """
    clave = document_blob_key(source_hash, fallback=sha256)
    if clave is None:
        return None
    try:
        almacen = get_object_store()
        if not almacen.enabled:
            return None
        almacen.put(clave, content, content_type=content_type)
    except (ObjectStoreError, OSError, RuntimeError) as exc:
        log.warning("document_blob_put_failed", documento_id=documento_id, error=str(exc))
        return None
    return clave


def _contenido_desde_blob(
    documento_id: int, fila: dict[str, Any] | None
) -> tuple[bytes, str | None] | None:
    """Recupera el binario guardado de un documento, si lo hay.

    Es lo que convierte «la fuente ya no responde» en un problema recuperable:
    con el binario en el bucket, la re-extracción no necesita a PLACSP.
    """
    if not fila:
        return None
    clave = fila.get("blob_key")
    if not clave:
        return None
    try:
        almacen = get_object_store()
        if not almacen.enabled:
            return None
        datos = almacen.get(str(clave))
    except Exception as exc:
        log.warning("document_blob_get_failed", documento_id=documento_id, error=str(exc))
        return None
    if datos is None:
        return None
    log.info("document_fetch_desde_blob", documento_id=documento_id, bytes=len(datos))
    return datos, (str(fila["content_type"]) if fila.get("content_type") else None)


def fetch_and_extract(documento: dict[str, Any]) -> str:
    """Descarga ``documento['uri']``, extrae su texto y persiste el resultado
    vía ``DocumentosRepository``.

    ``documento`` es una fila de ``DocumentosRepository.list_pendientes()``
    (dict con al menos ``id``/``uri``). El binario se conserva en el almacén de
    objetos cuando hay uno configurado, y es de ahí de donde se re-extrae si la
    fuente deja de responder.

    Devuelve ``"extracted"``, ``"error"``, ``"unsupported"`` o ``"skipped"`` —
    para que el llamador (job de embeddings, F8) instrumente métricas sin releer
    la fila. ``"skipped"`` significa que no se llegó a intentar nada (breaker
    abierto): la fila se queda en ``pending`` y entra en el lote siguiente.
    ``"unsupported"`` es cobertura que falta, no un fallo.
    """
    from db.repositories.documentos import DocumentosRepository

    repo = DocumentosRepository()
    documento_id = int(documento["id"])
    uri = str(documento["uri"])

    # ``list_pendientes`` trae ``source_hash`` y ``blob_key``; ``list_by_licitacion``
    # —el camino bajo demanda de la ficha— no, porque su forma la consume además
    # la UI. Cuando faltan se releen: sin ``source_hash`` el binario se guardaría
    # bajo una clave distinta a la canónica en cada pasada, y sin ``blob_key`` la
    # recuperación desde el bucket no se intentaría nunca.
    if "blob_key" not in documento or "source_hash" not in documento:
        documento = {**documento, **(repo.get(documento_id) or {})}

    desde_blob = False
    try:
        content, content_type = _download_bytes(uri)
    except pybreaker.CircuitBreakerError as e:
        # El breaker abierto no dice nada de ESTE documento: dice que PLACSP
        # está rechazando ahora mismo. Marcarlo 'error' lo sacaría de
        # ``list_pendientes`` para siempre por una condición transitoria — así
        # se perdieron 1.702 documentos (el 66% de los errores acumulados en
        # producción a 2026-08-18) antes de que existiera esta rama. La fila se
        # queda ``pending`` y el lote siguiente la reintenta.
        recuperado = _contenido_desde_blob(documento_id, documento)
        if recuperado is None:
            log.info("document_fetch_skipped_breaker_open", documento_id=documento_id, error=str(e))
            return "skipped"
        content, content_type = recuperado
        desde_blob = True
    except requests.HTTPError as e:
        recuperado = _contenido_desde_blob(documento_id, documento)
        if recuperado is None:
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
        content, content_type = recuperado
        desde_blob = True
    except Exception as e:
        recuperado = _contenido_desde_blob(documento_id, documento)
        if recuperado is None:
            log.warning("document_fetch_download_failed", documento_id=documento_id, error=str(e))
            repo.mark_error(
                documento_id, error_detail=f"descarga fallida: {e}"[:_MAX_ERROR_DETAIL_LEN]
            )
            return "error"
        content, content_type = recuperado
        desde_blob = True

    sha256 = hashlib.sha256(content).hexdigest()
    size_bytes = len(content)

    if not desde_blob:
        clave = _guardar_binario(
            documento.get("source_hash"), documento_id, content, content_type, sha256
        )
        if clave is not None and clave != documento.get("blob_key"):
            repo.mark_blob(documento_id, blob_key=clave)

    try:
        paginas = _extract_paginas(content, content_type)
        texto = "\n".join(p.texto for p in paginas).strip()
    except UnsupportedDocumentError as e:
        log.info(
            "document_fetch_unsupported",
            documento_id=documento_id,
            content_type=e.content_type or content_type,
        )
        repo.mark_downloaded(
            documento_id,
            filename=documento.get("filename"),
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
        )
        repo.mark_unsupported(
            documento_id,
            content_type=e.content_type or content_type,
            error_detail=str(e)[:_MAX_ERROR_DETAIL_LEN],
        )
        return "unsupported"
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

    from db.repositories.documentos import DocumentoPagina

    # El content-type viaja con el éxito, no solo con el fallo: el camino feliz
    # nunca pasa por ``mark_downloaded``, así que sin esto el desglose por
    # formato (S8.2) contaba los `unsupported` con su tipo y los `extracted`
    # como «desconocido» — el numerador de la cobertura era invisible.
    repo.mark_extracted(
        documento_id,
        texto=texto,
        sha256=sha256,
        pages=[DocumentoPagina(texto=p.texto, ocr=p.ocr) for p in paginas],
        content_type=content_type,
        size_bytes=size_bytes,
        filename=documento.get("filename"),
    )
    log.info(
        "document_fetch_extracted",
        documento_id=documento_id,
        size_bytes=size_bytes,
        texto_len=len(texto),
        desde_blob=desde_blob,
        ocr=any(p.ocr for p in paginas),
    )
    return "extracted"


def reextract_from_blob(documento_id: int) -> str:
    """Re-extrae un documento **sin tocar la fuente**, leyendo el binario guardado.

    Es lo que S8.1 hace posible: cambiar de parser, añadir OCR o cambiar la
    convención de página lógica ya no obliga a volver a PLACSP con enlaces que
    han caducado. Devuelve el mismo vocabulario que :func:`fetch_and_extract`
    más ``"missing"`` cuando no hay binario conservado para esa fila.
    """
    from db.repositories.documentos import DocumentoPagina, DocumentosRepository

    repo = DocumentosRepository()
    fila = repo.get(documento_id)
    recuperado = _contenido_desde_blob(documento_id, fila)
    if recuperado is None or fila is None:
        return "missing"
    content, content_type = recuperado

    try:
        paginas = _extract_paginas(content, content_type)
        texto = "\n".join(p.texto for p in paginas).strip()
    except UnsupportedDocumentError as e:
        repo.mark_unsupported(
            documento_id,
            content_type=e.content_type or content_type,
            error_detail=str(e)[:_MAX_ERROR_DETAIL_LEN],
        )
        return "unsupported"
    except DocumentFetchError as e:
        repo.mark_error(documento_id, error_detail=str(e)[:_MAX_ERROR_DETAIL_LEN])
        return "error"

    repo.mark_extracted(
        documento_id,
        texto=texto,
        sha256=hashlib.sha256(content).hexdigest(),
        pages=[DocumentoPagina(texto=p.texto, ocr=p.ocr) for p in paginas],
        # Re-extraer una fila que estaba en ``unsupported`` la devuelve a
        # ``extracted``: el desglose por formato tiene que moverse con ella.
        content_type=content_type,
        size_bytes=len(content),
    )
    return "extracted"
