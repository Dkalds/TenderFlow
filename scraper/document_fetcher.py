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
- Office Open XML (``.docx``), con ``python-docx``.
- OpenDocument (``.odt``, ``.ods``, ``.odp``), con la biblioteca estándar:
  ``zipfile`` + ``expat`` sobre ``content.xml``, rechazando cualquier DOCTYPE.
  No depende de ningún extra, así que también se lee en la imagen de la API.
- ``application/zip`` — se expande y se procesan los PDF, DOCX y OpenDocument
  de dentro; cada entrada abre su primera página con una línea separadora que
  dice de qué fichero sale (``── nombre ──``).

El formato lo decide la **firma del contenido** (:func:`_resolver_content_type`),
no el ``Content-Type`` del servidor, que en PLACSP llega mal escrito o genérico.

**Convención de página lógica en DOCX y OpenDocument**: ninguno de los dos formatos
tiene páginas — la paginación la decide el motor de renderizado al imprimir, y
no está en el fichero. Se agrupan los párrafos no vacíos en bloques de
:data:`_PARRAFOS_POR_PAGINA_LOGICA`, en orden documental, y cada bloque es una
«página». Los offsets salen entonces
igual que en un PDF (``mark_extracted`` los calcula sobre el texto agregado),
así que una cita de la ficha sigue anclando a una región concreta y verificable
del documento; lo que no puede hacer es decir «página 3 de la impresión». Es
estable frente a re-extracciones porque sólo depende del orden de los párrafos.

**Zip bomb**: están acotados el número de entradas (:data:`_ZIP_MAX_ENTRADAS`),
el tamaño descomprimido por entrada (:data:`_ZIP_MAX_BYTES_POR_ENTRADA`) y
acumulado (``MAX_DOCUMENT_SIZE_BYTES``) y el ratio de compresión
(:data:`_ZIP_RATIO_MAX`); la lectura de cada entrada se hace por bloques con
un tope explícito en vez de fiarse de ``file_size`` de la cabecera, que la
escribe quien construyó el ZIP. El ``content.xml`` de un OpenDocument pasa por
la misma lectura acotada. No hay recursión: un ZIP dentro de un ZIP se ignora,
y una entrada con ``..`` o ruta absoluta tampoco se lee.

Un content-type que no sepamos leer marca el documento como ``unsupported``
**con su content-type** (``v103``), no como ``error``: son cosas distintas y
sólo separadas se puede medir cuánta cobertura falta y de qué formato.

Un content-type que sí sabemos leer pero cuya dependencia opcional falta **en
este proceso** no es ninguna de las dos: la fila se queda ``pending``
(:class:`ExtractorAusenteError`). Pasa en la imagen de la API, que extrae la
ficha bajo demanda sin ``python-docx`` (trae ``lxml``, fuera de
``requirements-api.in``); marcarla ``unsupported`` allí la sacaría para siempre
del lote nocturno, que sí lo tiene. Desde 2026-10 OpenDocument ya no pasa por
aquí: se lee con la biblioteca estándar y ``odfpy`` no se importa.

Configuración del OCR (variables de entorno, leídas aquí y no en
``config/settings.py`` porque sólo las usa este módulo y sólo en el runner de
``pliegos.yml``)::

    DOCUMENT_OCR_ENABLED           1 (defecto) | 0
    DOCUMENT_OCR_LANGUAGES         idiomas de tesseract (defecto: spa+eng; solo
                                   spa, cat, glg, eus y eng, ver _IDIOMAS_OCR)
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
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn
from urllib.parse import urlparse
from xml.parsers import expat  # nosemgrep -- se rechaza el DOCTYPE, ver «OpenDocument»

import pybreaker
import requests
import urllib3

from config import USER_AGENT, settings
from observability.logging import get_logger
from scraper.resilience import RecursoNoServidoError, breaker_para_host, http_retry, status_de
from shared.object_store import ObjectStoreError, document_blob_key, get_object_store
from shared.outbound_http import PinnedHttpsResponse, pinned_https_request

log = get_logger(__name__)

CONTENT_TYPE_PDF = "application/pdf"
CONTENT_TYPE_TEXT = "text/plain"
CONTENT_TYPE_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
CONTENT_TYPE_ODT = "application/vnd.oasis.opendocument.text"
CONTENT_TYPE_ODS = "application/vnd.oasis.opendocument.spreadsheet"
CONTENT_TYPE_ODP = "application/vnd.oasis.opendocument.presentation"
CONTENT_TYPE_ZIP = "application/zip"

#: OpenDocument que se lee de ``content.xml`` con la biblioteca estándar. Los
#: tres comparten estructura (párrafos ``text:p``/``text:h`` y tablas), así que
#: los lee el mismo código: lo que cambia es dónde vive el texto, no cómo.
_ODF_TIPOS = frozenset({CONTENT_TYPE_ODT, CONTENT_TYPE_ODS, CONTENT_TYPE_ODP})

#: Los servidores de PLACSP no son consistentes con el content-type del ZIP;
#: estos tres son la misma cosa.
_ZIP_ALIASES = frozenset({CONTENT_TYPE_ZIP, "application/x-zip-compressed", "multipart/x-zip"})

_SUPPORTED_CONTENT_TYPES = frozenset(
    {
        CONTENT_TYPE_PDF,
        CONTENT_TYPE_TEXT,
        CONTENT_TYPE_DOCX,
        *_ODF_TIPOS,
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


#: Párrafos por página lógica en DOCX/OpenDocument. Ver la convención del docstring del
#: módulo. 40 párrafos es del orden de una página impresa de pliego y mantiene
#: los fragmentos dentro de lo que el chunker y el selector de páginas de la
#: ficha (``services/rag/fact_sheet.py``) manejan sin cortar contexto útil.
_PARRAFOS_POR_PAGINA_LOGICA = 40

#: Entradas máximas de un ZIP. Un pliego real trae unidades de ficheros; cien
#: entradas ya no es un expediente, es un intento de agotar el runner.
_ZIP_MAX_ENTRADAS = 50

#: Bytes descomprimidos máximos de UNA entrada (y del ``content.xml`` de un
#: OpenDocument). El total del ZIP lo acota ``MAX_DOCUMENT_SIZE_BYTES``; este
#: tope por entrada impide que un solo anexo se coma el presupuesto entero de
#: los demás.
_ZIP_MAX_BYTES_POR_ENTRADA = 25 * 1024 * 1024

#: Ratio máximo descomprimido/comprimido de una entrada. Un PDF o un DOCX ya
#: vienen comprimidos (ratio cercano a 1) y un XML de OpenDocument ronda 5-20;
#: una bomba de deflate llega a ~1.000. 100 deja margen a lo legítimo y corta lo
#: otro mucho antes de materializarlo.
_ZIP_RATIO_MAX = 100

#: Por debajo de este tamaño descomprimido el ratio no se mira: un fichero
#: pequeño y repetitivo comprime mucho sin ser peligroso, y lo que importa de
#: una bomba es cuánto ocupa al expandirse, no el ratio en sí.
_ZIP_RATIO_UMBRAL_BYTES = 1024 * 1024

#: Tamaño de cada lectura al descomprimir una entrada. El ratio se comprueba
#: tras cada bloque, así que una bomba se corta al primer MiB sospechoso.
_ZIP_BLOQUE_LECTURA = 1024 * 1024

#: Extensiones que se procesan dentro de un ZIP. Sin recursión: un ``.zip``
#: dentro de otro se ignora a propósito. La extensión solo **preselecciona**
#: (no se descomprime lo que no se va a leer); el formato lo decide después la
#: firma del contenido, igual que en una descarga directa.
_ZIP_EXTENSIONES = {
    ".pdf": CONTENT_TYPE_PDF,
    ".docx": CONTENT_TYPE_DOCX,
    ".odt": CONTENT_TYPE_ODT,
    ".ods": CONTENT_TYPE_ODS,
    ".odp": CONTENT_TYPE_ODP,
}

#: Bandera de la cabecera ZIP que declara el nombre en UTF-8 (bit 11).
_ZIP_FLAG_UTF8 = 0x800

#: Marca del fallo «este PDF no tiene texto». Se compara por texto y no por
#: tipo de excepción porque el parser aislado (``_pdf_extraction_worker``)
#: devuelve el error por un ``Pipe`` como cadena: el tipo no sobrevive al
#: cruce de procesos, y es justo en producción donde ese camino se usa.
_MSG_PDF_SIN_TEXTO = "PDF sin texto extraíble (posible escaneado sin OCR)"

#: Letras mínimas para dar un PDF por «con capa de texto» (ver
#: :func:`_tiene_texto`).
_MIN_LETRAS_CON_TEXTO = 8


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


class DocumentFetchError(RuntimeError):
    """Fallo recuperable de extracción (PDF corrupto, PDF sin texto ni OCR,
    ZIP que excede los límites). Distinto de fallos de descarga (red/SSRF/
    tamaño), que se propagan como la excepción original del transporte."""


class PdfSinTextoError(DocumentFetchError):
    """PDF sin capa de texto (escaneado) que el OCR no pudo leer.

    Tiene estado propio (``documentos.status = 'sin_texto'``, ``v159``) en vez
    de caer en ``error``: no es una descarga fallida ni un PDF roto, es un
    documento que existe y se lee en el navegador pero del que este proceso no
    sabe sacar texto. Quien lo cuenta (la ficha, ``/analytics/quality``, el
    informe nocturno) tiene que poder decirlo así.

    Punto de extensión del OCR: :func:`_ocr_pdf`. Hoy usa ``ocrmypdf`` si está
    en el ``PATH`` (el runner de ``pliegos.yml`` lo instala; la imagen de la
    API no). Una fila ``sin_texto`` con binario conservado (``blob_key``) se
    re-extrae con :func:`reextract_from_blob` el día que el proceso tenga OCR,
    sin volver a la fuente.
    """


class UnsupportedDocumentError(DocumentFetchError):
    """El formato no se sabe leer: no es un fallo, es cobertura que falta.

    Lleva el ``content_type`` para que la fila quede contabilizada por formato
    (``documentos.status = 'unsupported'``, ``v103``) y el día que se añada el
    soporte se sepa exactamente cuántas filas resucitar.
    """

    def __init__(self, mensaje: str, *, content_type: str | None) -> None:
        super().__init__(mensaje)
        self.content_type = content_type


class ExtractorAusenteError(UnsupportedDocumentError):
    """El formato se sabe leer, pero no en este proceso: falta su dependencia.

    Subclase de :class:`UnsupportedDocumentError` porque para quien solo extrae
    (``_extract_paginas``) es lo mismo: no hay páginas. Para quien persiste no:
    ``fetch_and_extract`` deja la fila ``pending`` en vez de ``unsupported``.
    """


#: Servlet con el que PLACSP sirve los adjuntos de sus expedientes.
_SERVLET_PLACSP = "/FileSystem/servlet/GetDocumentByIdServlet"

#: Lo que ese servlet escribe en el cuerpo de su 500 cuando no sirve un
#: documento concreto. Entero son 42 bytes: ``Error 500: java.lang.NullPointerException``.
_FIRMA_NO_SERVIDO = b"java.lang.NullPointerException"

#: Cuánto cuerpo de un 500 se lee para buscar la firma.
_MAX_CUERPO_DE_ERROR = 512


def _no_sirve_el_documento(uri: str, respuesta: PinnedHttpsResponse) -> bool:
    """¿Es el 500 con el que el servlet de PLACSP dice que no sirve ESTE documento?

    Lo contesta por un enlace muerto, un token caducado o un pliego anunciado y
    aún sin publicar, y es una respuesta del documento, no una caída: llega en
    ~0,2 s y los demás documentos de PLACSP —hasta los del mismo expediente—
    responden 200 en ese momento. Tratarla como un 5xx cualquiera costaba cuatro
    intentos (~19 s) por documento, y cinco seguidos abrían el circuito y el
    resto del lote se saltaba: 536 documentos en tres noches del 2026-09-04 al
    2026-10-04, sin que PLACSP estuviera caído ninguna.

    La regla es estrecha porque solo eso está medido: el servlet, un 500 y esa
    firma en el cuerpo. Un 500 distinto (la plataforma rota de verdad) o esa
    firma en otro servidor siguen el camino de siempre.
    """
    if respuesta.status_code != 500 or _SERVLET_PLACSP not in urlparse(uri).path:
        return False
    leido = b""
    try:
        for trozo in respuesta.iter_content(chunk_size=_MAX_CUERPO_DE_ERROR):
            leido += trozo
            if len(leido) >= _MAX_CUERPO_DE_ERROR:
                break
    except Exception:
        # El cuerpo es un indicio, no un requisito: si no se deja leer, el 500
        # se queda en lo que era antes de mirarlo.
        return False
    return _FIRMA_NO_SERVIDO in leido


def _download_bytes(uri: str) -> tuple[bytes, str | None]:
    """Descarga ``uri`` en memoria con guardas SSRF + tamaño.

    Detrás del circuito de la plataforma que la sirve (``breaker_para_host``):
    PLACSP, TED y la plataforma catalana fallan por separado, y el lote de una
    no puede parar el de las otras. El circuito envuelve a los reintentos, como
    cuando era un decorador: cuenta un fallo por descarga, no por intento.
    """
    breaker = breaker_para_host(urlparse(uri).hostname)
    resultado: tuple[bytes, str | None] = breaker.call(_download_bytes_con_reintentos, uri)
    return resultado


@http_retry
def _download_bytes_con_reintentos(uri: str) -> tuple[bytes, str | None]:
    """El cuerpo de :func:`_download_bytes`, sin el circuito.

    Cada intento es :func:`_descargar_un_intento`; lo que se añade aquí es la
    traducción de sus fallos de red a lo que ``http_retry`` sabe reintentar. El
    transporte fijado no habla ese idioma: cuando urllib3 se queda sin
    respuesta lanza un ``RequestException`` a secas —con el error de urllib3
    como causa—, y lo que se corta con el cuerpo a medias sale como el error de
    urllib3 tal cual. Ninguno es ``ConnectionError`` ni ``Timeout``, así que un
    corte de red dejaba el documento en ``error`` al primer intento.

    Se traduce aquí y no en ``shared/outbound_http.py`` porque ese transporte
    lo comparten los webhooks, el correo y la descarga de modelos, y ninguno
    decide por el tipo del error: capturan ``RequestException`` y reintentan,
    o no, con sus propias reglas.
    """
    try:
        return _descargar_un_intento(uri)
    except urllib3.exceptions.HTTPError as exc:
        # Sin envolver solo llega lo que falla con la respuesta ya empezada:
        # ``iter_content`` deja pasar el error de urllib3.
        raise _error_de_red("Pinned HTTPS response body failed", exc) from exc
    except requests.RequestException as exc:
        causa = exc.__cause__
        if not isinstance(causa, urllib3.exceptions.HTTPError):
            raise
        raise _error_de_red(str(exc), causa) from causa


def _error_de_red(mensaje: str, causa: urllib3.exceptions.HTTPError) -> requests.ConnectionError:
    """El fallo de urllib3 *causa*, como el error de red que ``http_retry`` reintenta.

    El mensaje conserva el principio del que da el transporte, que es por lo
    que se reconocen estas filas en ``error_detail``, y le añade la clase del
    fallo: sin ella, «Pinned HTTPS request failed» no dice si fue un timeout o
    una conexión rechazada. Solo la clase, porque el texto de urllib3 lleva la
    IP y la dirección en memoria de la conexión.

    Siempre ``ConnectionError``, también para un timeout: aquí nadie los trata
    distinto, y separarlos por la jerarquía de urllib3 engaña (su
    ``NewConnectionError``, una conexión rechazada, hereda de
    ``ConnectTimeoutError``).
    """
    return requests.ConnectionError(f"{mensaje} ({type(causa).__name__})")


def _descargar_un_intento(uri: str) -> tuple[bytes, str | None]:
    """Una petición de ``uri``, con los errores tal y como los da el transporte.

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
        if _no_sirve_el_documento(uri, r):
            # El mensaje empieza como el de ``raise_for_status`` a propósito:
            # ``status_de`` saca el código de ahí.
            raise RecursoNoServidoError(
                f"Pinned HTTPS response status {r.status_code}: el servlet de PLACSP "
                "no sirve este documento (NullPointerException)"
            )
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

    if not _tiene_texto(pages_text):
        raise PdfSinTextoError(_MSG_PDF_SIN_TEXTO)
    return pages_text


def _tiene_texto(paginas: list[str]) -> bool:
    """¿El PDF tiene capa de texto? Detección de escaneado.

    No basta con «la cadena no está vacía»: un escaneado sale a menudo con
    restos sin contenido —saltos de página, guiones o puntos de la máquina que
    lo digitalizó, un número de página suelto en una cabecera estampada—. Se
    exigen al menos :data:`_MIN_LETRAS_CON_TEXTO` **letras** en el
    documento entero (las cifras no cuentan: la paginación estampada de un
    escaneo de cien páginas son doscientas cifras y ninguna palabra).
    """
    letras = 0
    for texto in paginas:
        letras += sum(1 for letra in texto if letra.isalpha())
        if letras >= _MIN_LETRAS_CON_TEXTO:
            return True
    return False


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
            # El tipo no cruza el ``Pipe``: se reconstruye por el mensaje.
            if _MSG_PDF_SIN_TEXTO in str(payload):
                raise PdfSinTextoError(str(payload))
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


#: Idiomas de tesseract que admite ``DOCUMENT_OCR_LANGUAGES``: el castellano,
#: las otras lenguas cooficiales —hay plataformas autonómicas que publican los
#: pliegos en ellas— y el inglés. Lista cerrada porque el valor acaba en la
#: línea de comandos de ``ocrmypdf``. Admitir un código no instala su paquete:
#: el runner de ``pliegos.yml`` solo trae ``spa`` y ``eng``, y pedir otro sin
#: instalarlo hace fallar el OCR con la degradación limpia de siempre.
_IDIOMAS_OCR = ("spa", "cat", "glg", "eus", "eng")
_IDIOMAS_OCR_DEFECTO = "spa+eng"


def _idiomas_ocr() -> str:
    """``DOCUMENT_OCR_LANGUAGES`` reducida a :data:`_IDIOMAS_OCR`, en el orden pedido.

    El orden se respeta porque tesseract toma el primero como idioma principal.
    Un código fuera de la lista se descarta con aviso en vez de llegar a
    ``argv``, y si no queda ninguno se usa el defecto: la variable es
    configuración del despliegue, pero lo que se pasa a un binario externo se
    valida igual.
    """
    crudo = os.environ.get("DOCUMENT_OCR_LANGUAGES", "")
    pedidos = [codigo.strip() for codigo in crudo.split("+") if codigo.strip()]
    descartados = [codigo for codigo in pedidos if codigo not in _IDIOMAS_OCR]
    if descartados:
        log.warning("document_ocr_idioma_descartado", idiomas=descartados)
    validos = [codigo for codigo in pedidos if codigo in _IDIOMAS_OCR]
    return "+".join(dict.fromkeys(validos)) or _IDIOMAS_OCR_DEFECTO


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
    idiomas = _idiomas_ocr()

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
    return isinstance(exc, PdfSinTextoError) or _MSG_PDF_SIN_TEXTO in str(exc)


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
            if isinstance(exc, PdfSinTextoError):
                raise
            raise PdfSinTextoError(str(exc)) from exc
        paginas = _extract_pdf_pages(con_texto)
        log.info("document_ocr_extracted", paginas=len(paginas))
        return [PaginaExtraida(texto=texto, ocr=True) for texto in paginas]


# ── DOCX (S8.2) ────────────────────────────────────────────────────────────


def _importar_opcional(modulo: str, *, content_type: str, paquete: str) -> Any:
    """Importa una dependencia opcional o declara el formato ``unsupported``.

    ``importlib`` y no ``import x`` para que el tipo sea ``Any`` sin un
    ``# type: ignore``: ``python-docx`` no publica stubs, y este
    módulo pasa mypy strict como el resto de producción.
    """
    try:
        return importlib.import_module(modulo)
    except ImportError as exc:
        raise ExtractorAusenteError(
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


# ── OpenDocument con la biblioteca estándar (ODT, ODS, ODP) ────────────────
#
# Hasta 2026-10 el ODT se leía con ``odfpy``, que trae ``lxml`` y por eso no
# está en la imagen de la API: un ODT descargado allí se quedaba ``pending``
# hasta el lote nocturno. ``content.xml`` es XML plano dentro de un ZIP y no
# necesita nada más que ``zipfile`` y ``expat`` para leerse, así que ahora se
# lee igual en todos los procesos.
#
# **XML hostil.** ``defusedxml`` no es dependencia de producción (solo está en
# ``requirements-dev.txt``), y la mitigación que usa el resto del repo es el
# parser endurecido de ``lxml``, que aquí es justo lo que se quiere evitar. Se
# usa ``expat`` directamente y se **rechaza cualquier DOCTYPE**: un
# ``content.xml`` de OpenDocument no declara DTD nunca, y sin DTD no hay
# entidades que expandir («billion laughs») ni externas que resolver (XXE).
# El manejador salta al abrir el DOCTYPE, antes de procesar su subconjunto
# interno. ``expat`` además no resuelve entidades externas por sí mismo.

_NS_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_NS_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
_NS_OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"

#: Separador de espacio de nombres que se le pide a expat: los nombres llegan
#: como ``"{uri} {local}"`` y se comparan con las tuplas de abajo.
_SEP_NS = " "

_ODF_PARRAFOS = frozenset({f"{_NS_TEXT} p", f"{_NS_TEXT} h"})
_ODF_FILA = f"{_NS_TABLE} table-row"
_ODF_CELDAS = frozenset({f"{_NS_TABLE} table-cell", f"{_NS_TABLE} covered-table-cell"})
_ODF_ESPACIO = f"{_NS_TEXT} s"
_ODF_TAB = f"{_NS_TEXT} tab"
_ODF_SALTO = f"{_NS_TEXT} line-break"
_ODF_ATRIBUTO_REPETICION = f"{_NS_TEXT} c"
#: Subárboles cuyo texto no es contenido del documento: lo borrado del control
#: de cambios (seguiría «diciendo» el importe que se corrigió) y los
#: comentarios de revisión.
_ODF_IGNORADOS = frozenset(
    {
        f"{_NS_TEXT} tracked-changes",
        f"{_NS_OFFICE} annotation",
        f"{_NS_OFFICE} annotation-end",
    }
)
#: Tope de ``text:s text:c``: el atributo lo escribe quien hizo el fichero y un
#: ``c="999999999"`` no puede convertirse en un gigabyte de espacios.
_ODF_MAX_ESPACIOS = 1000


class _LectorOdf:
    """Recorre ``content.xml`` y deja los párrafos en orden documental.

    Convenciones (las mismas que el DOCX, para que la página lógica signifique
    lo mismo en los dos formatos):

    - Cada ``text:p`` y ``text:h`` es un párrafo. ``odfpy`` solo devolvía los
      ``text:p`` y perdía los encabezados, que en un pliego son los títulos de
      cláusula.
    - Una fila de tabla es **una** línea con sus celdas no vacías unidas por
      `` | `` (como el DOCX); los párrafos de una celda se unen con espacio.
      En una hoja de cálculo (ODS) eso es una fila por línea.
    - Un párrafo anidado (el de un cuadro de texto dentro de otro párrafo) se
      emite como párrafo propio al cerrarse.
    """

    def __init__(self) -> None:
        self.parrafos: list[str] = []
        self._buffers: list[list[str]] = []
        self._filas: list[list[str]] = []
        self._celdas: list[list[str]] = []
        self._ignorando = 0

    def _emitir(self, texto: str) -> None:
        texto = texto.strip()
        if not texto:
            return
        if self._celdas:
            self._celdas[-1].append(texto)
        else:
            self.parrafos.append(texto)

    def inicio(self, nombre: str, atributos: dict[str, str]) -> None:
        if self._ignorando or nombre in _ODF_IGNORADOS:
            self._ignorando += 1
            return
        if nombre in _ODF_PARRAFOS:
            self._buffers.append([])
        elif nombre == _ODF_FILA:
            self._filas.append([])
        elif nombre in _ODF_CELDAS:
            self._celdas.append([])
        elif self._buffers and nombre == _ODF_ESPACIO:
            try:
                repeticiones = int(atributos.get(_ODF_ATRIBUTO_REPETICION, "1"))
            except ValueError:
                repeticiones = 1
            self._buffers[-1].append(" " * max(1, min(repeticiones, _ODF_MAX_ESPACIOS)))
        elif self._buffers and nombre == _ODF_TAB:
            self._buffers[-1].append("\t")
        elif self._buffers and nombre == _ODF_SALTO:
            self._buffers[-1].append("\n")

    def fin(self, nombre: str) -> None:
        if self._ignorando:
            self._ignorando -= 1
            return
        if nombre in _ODF_PARRAFOS and self._buffers:
            self._emitir("".join(self._buffers.pop()))
        elif nombre in _ODF_CELDAS and self._celdas:
            celda = " ".join(self._celdas.pop())
            if self._filas:
                self._filas[-1].append(celda)
        elif nombre == _ODF_FILA and self._filas:
            self._emitir(" | ".join(c for c in self._filas.pop() if c))

    def texto(self, datos: str) -> None:
        if not self._ignorando and self._buffers:
            self._buffers[-1].append(datos)


def _rechazar_dtd(*_args: object) -> NoReturn:
    raise DocumentFetchError(
        "OpenDocument con DOCTYPE en content.xml: rechazado (ODF no declara DTD; "
        "solo serviría para expandir entidades)"
    )


def _parrafos_de_content_xml(xml: bytes) -> list[str]:
    """Párrafos de un ``content.xml`` (ver :class:`_LectorOdf`)."""
    lector = _LectorOdf()
    parser = expat.ParserCreate(namespace_separator=_SEP_NS)
    parser.buffer_text = True
    parser.StartDoctypeDeclHandler = _rechazar_dtd
    parser.EntityDeclHandler = _rechazar_dtd
    parser.ExternalEntityRefHandler = _rechazar_dtd
    parser.StartElementHandler = lector.inicio
    parser.EndElementHandler = lector.fin
    parser.CharacterDataHandler = lector.texto
    try:
        parser.Parse(xml, True)
    except expat.ExpatError as exc:
        raise DocumentFetchError(f"ODT corrupto o ilegible: {exc}") from exc
    return lector.parrafos


def _extract_odf_paginas(content: bytes, content_type: str = CONTENT_TYPE_ODT) -> list[str]:
    """Párrafos de un OpenDocument, agrupados con la misma convención que el DOCX.

    ``content_type`` solo da nombre al formato en los mensajes de error; ODT,
    ODS y ODP se leen igual.
    """
    formato = {CONTENT_TYPE_ODS: "ODS", CONTENT_TYPE_ODP: "ODP"}.get(content_type, "ODT")
    try:
        archivo = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocumentFetchError(f"{formato} corrupto o ilegible: {exc}") from exc
    with archivo:
        try:
            info = archivo.getinfo("content.xml")
        except KeyError as exc:
            raise DocumentFetchError(f"{formato} sin content.xml") from exc
        xml = _leer_entrada_acotada(
            archivo,
            info,
            tope=min(_ZIP_MAX_BYTES_POR_ENTRADA, int(settings.MAX_DOCUMENT_SIZE_BYTES)),
            que=f"content.xml del {formato}",
        )

    paginas = _agrupar_en_paginas_logicas(_parrafos_de_content_xml(xml))
    if not paginas:
        raise DocumentFetchError(f"{formato} sin texto extraíble")
    return paginas


# ── ZIP (S8.2) ─────────────────────────────────────────────────────────────


def _leer_entrada_acotada(
    archivo: zipfile.ZipFile, info: zipfile.ZipInfo, *, tope: int, que: str
) -> bytes:
    """Descomprime una entrada sin fiarse de lo que declara su cabecera.

    ``file_size`` lo escribe quien construyó el ZIP: si ya confiesa el exceso
    se rechaza sin descomprimir, pero si miente la lectura misma va acotada
    (se pide un byte más que el tope, para detectar el exceso sin
    materializarlo). El ratio se mide contra ``compress_size``, que sí es lo
    que ``zipfile`` consume del fichero: con la lectura a medias ya es una cota
    inferior del ratio final, así que superarlo pronto es motivo suficiente.
    """
    if info.file_size > tope:
        raise DocumentFetchError(
            f"{que}: el tamaño descomprimido declarado ({info.file_size:,} bytes) "
            f"supera {tope:,} bytes"
        )
    comprimido = max(int(info.compress_size), 1)
    bloques: list[bytes] = []
    leidos = 0
    with archivo.open(info) as fh:
        while True:
            bloque = fh.read(min(_ZIP_BLOQUE_LECTURA, tope + 1 - leidos))
            if not bloque:
                break
            bloques.append(bloque)
            leidos += len(bloque)
            if leidos > tope:
                raise DocumentFetchError(f"{que}: el contenido descomprimido supera {tope:,} bytes")
            if leidos > _ZIP_RATIO_UMBRAL_BYTES and leidos / comprimido > _ZIP_RATIO_MAX:
                raise DocumentFetchError(
                    f"{que}: ratio de compresión superior a {_ZIP_RATIO_MAX}:1 (posible zip bomb)"
                )
    return b"".join(bloques)


def _nombre_de_entrada(info: zipfile.ZipInfo) -> str:
    """El nombre real de la entrada, también cuando el ZIP no declara UTF-8.

    Sin la bandera UTF-8, ``zipfile`` decodifica el nombre como CP437, que es
    lo que manda la especificación; pero muchos compresores de Windows
    escriben UTF-8 sin marcarlo, y «Pliego técnico.odt» salía como
    «Pliego tÃ©cnico.odt» en el separador de páginas.
    """
    nombre = info.filename
    if info.flag_bits & _ZIP_FLAG_UTF8:
        return nombre
    try:
        return nombre.encode("cp437").decode("utf-8")
    except UnicodeError:
        return nombre


def _ruta_segura(nombre: str) -> bool:
    """¿Es una ruta relativa normal, sin ``..``, absoluta ni de unidad?

    Aquí nada se escribe a disco, pero una entrada así es la firma de un ZIP
    fabricado para escaparse del directorio al expandirse: no es un anexo de
    pliego y no se lee. Tampoco los restos de macOS (``__MACOSX/``, ``._*``),
    que repiten el nombre del fichero real con un contenido que no lo es.
    """
    # Los compresores viejos de Windows escriben las carpetas con «\»: se
    # normaliza antes de mirar, para que «Pliegos\PPT.pdf» se lea y
    # «..\..\x» o «C:\x» sigan rechazándose.
    nombre = nombre.replace("\\", "/")
    if not nombre or nombre.startswith("/"):
        return False
    partes = PurePosixPath(nombre).parts
    if not partes or ":" in partes[0]:
        return False
    if any(parte == ".." for parte in partes):
        return False
    return partes[0] != "__MACOSX" and not partes[-1].startswith("._")


def _separador_de_entrada(nombre: str) -> str:
    """Línea que abre las páginas de cada entrada del ZIP.

    Va dentro del texto de la primera página de la entrada —no en una página
    aparte— para no cambiar el contrato de «una página = texto de una página
    del documento» que usan los offsets y las citas: la cita sigue anclando a
    la página de verdad, y quien la lee sabe de qué anexo sale.
    """
    return f"── {nombre} ──"


def _extract_zip_paginas(content: bytes) -> list[PaginaExtraida]:
    """Expande el ZIP y concatena las páginas de los documentos de dentro.

    Las entradas se procesan en orden alfabético para que el resultado sea
    reproducible entre corridas: los offsets de ``documento_pages`` —y por
    tanto las citas ya persistidas— dependen del orden en que se concatenan.

    Límites (todos lanzan :class:`DocumentFetchError`, que deja la fila en
    ``error`` y no ``unsupported``: un ZIP hostil no es cobertura que falte):
    número de entradas (:data:`_ZIP_MAX_ENTRADAS`), tamaño descomprimido por
    entrada (:data:`_ZIP_MAX_BYTES_POR_ENTRADA`) y total
    (``MAX_DOCUMENT_SIZE_BYTES``), y ratio de compresión
    (:data:`_ZIP_RATIO_MAX`). Profundidad 1: un ZIP dentro se ignora. Las
    rutas con ``..``, absolutas o de unidad se ignoran (:func:`_ruta_segura`).
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
        escaneados = 0
        for info in sorted(entradas, key=lambda i: i.filename):
            nombre = _nombre_de_entrada(info)
            if not _ruta_segura(nombre):
                log.info("document_zip_entry_ruta_insegura", entry=nombre)
                continue
            tipo_por_extension = _ZIP_EXTENSIONES.get(PurePosixPath(nombre).suffix.lower())
            if tipo_por_extension is None:
                continue
            if presupuesto <= 0:
                raise DocumentFetchError(
                    "El contenido descomprimido del ZIP supera "
                    f"{settings.MAX_DOCUMENT_SIZE_BYTES:,} bytes"
                )
            datos = _leer_entrada_acotada(
                archivo,
                info,
                tope=min(_ZIP_MAX_BYTES_POR_ENTRADA, presupuesto),
                que=f"Entrada {nombre!r} del ZIP",
            )
            presupuesto -= len(datos)
            # La firma decide, como en una descarga directa: un «.docx» que en
            # realidad es un ZIP cualquiera no se abre (eso sería recursión).
            tipo_interno = _resolver_content_type(datos, tipo_por_extension)
            if tipo_interno not in _TIPOS_DENTRO_DE_ZIP:
                continue
            procesadas += 1
            try:
                de_la_entrada = _extraer_paginas_de_tipo(datos, tipo_interno)
            except ExtractorAusenteError:
                # No es un adjunto roto: saltarlo dejaría el ZIP `extracted`
                # sin el DOCX de dentro, y ninguna pasada volvería a por él.
                raise
            except DocumentFetchError as exc:
                # Un adjunto roto dentro del ZIP no invalida los demás: mismo
                # criterio fail-open que el lote diario.
                if _es_pdf_sin_texto(exc):
                    escaneados += 1
                log.info("document_zip_entry_skipped", entry=nombre, error=str(exc))
                continue
            if de_la_entrada:
                primera = de_la_entrada[0]
                de_la_entrada[0] = PaginaExtraida(
                    texto=f"{_separador_de_entrada(nombre)}\n{primera.texto}", ocr=primera.ocr
                )
            paginas.extend(de_la_entrada)

    if not paginas and escaneados:
        # Lo único legible del ZIP eran escaneados: es el mismo caso que un
        # PDF escaneado suelto, no un formato que falte.
        raise PdfSinTextoError(
            f"{_MSG_PDF_SIN_TEXTO}: {escaneados} de {procesadas} entradas del ZIP"
        )
    if not paginas:
        raise UnsupportedDocumentError(
            f"ZIP sin documentos procesables ({procesadas} entradas candidatas)",
            content_type=CONTENT_TYPE_ZIP,
        )
    return paginas


#: Formatos que se extraen de dentro de un ZIP. Sin ZIP (profundidad 1) ni
#: ``text/plain`` (un ``léeme.txt`` no es un pliego).
_TIPOS_DENTRO_DE_ZIP = frozenset({CONTENT_TYPE_PDF, CONTENT_TYPE_DOCX, *_ODF_TIPOS})


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
    if content_type in _ODF_TIPOS:
        return [PaginaExtraida(texto=t) for t in _extract_odf_paginas(content, content_type)]
    if content_type in _ZIP_ALIASES:
        return _extract_zip_paginas(content)
    raise UnsupportedDocumentError(
        f"content-type no soportado: {content_type!r}", content_type=content_type
    )


#: Firma de un contenedor ZIP (``.zip``, ``.docx``, ``.odt``, ``.xlsx``…).
_FIRMA_ZIP = b"PK\x03\x04"
_FIRMA_PDF = b"%PDF-"


def _resolver_content_type(content: bytes, declarado: str | None) -> str | None:
    """El formato **real** del binario, no el que declara el servidor.

    El ``Content-Type`` de PLACSP no es fiable, y hasta 2026-09-28 era lo único
    que se miraba. Medido en producción ese día sobre ~3.100 documentos
    ``unsupported``/``error``:

    - 1.964 DOCX llegaban como
      ``application/vnd.openxmlformatsofficedocument.wordprocessingml.document``
      —sin el guion—, y se descartaban como formato desconocido. Es el mayor
      agujero de cobertura que había: más que todos los PDF rotos juntos.
    - Servidores que mandan un PDF como ``application/octet-stream`` o sin tipo.

    La firma del contenido manda; el tipo declarado solo decide cuando el
    contenido no tiene una firma reconocible (``text/plain``). Dentro de un ZIP
    se distingue DOCX (``word/document.xml``) y OpenDocument —ODT, ODS, ODP,
    por su fichero ``mimetype``— de un ZIP de verdad; un XLSX u otro contenedor se deja con su tipo declarado, que sigue
    cayendo en ``unsupported`` como antes.
    """
    if content.startswith(_FIRMA_PDF):
        return CONTENT_TYPE_PDF
    if content.startswith(_FIRMA_ZIP):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archivo:
                nombres = set(archivo.namelist())
                if "word/document.xml" in nombres:
                    return CONTENT_TYPE_DOCX
                if "mimetype" in nombres:
                    with archivo.open("mimetype") as fh:
                        mimetype = fh.read(100).decode("ascii", errors="replace").strip()
                    if mimetype in _ODF_TIPOS:
                        return mimetype
                if any(nombre.startswith(("xl/", "ppt/")) for nombre in nombres):
                    return declarado
        except (zipfile.BadZipFile, OSError, KeyError):
            # Firma ZIP pero ilegible: que lo diga el extractor de ZIP con su
            # propio error, no esta detección.
            return CONTENT_TYPE_ZIP
        return CONTENT_TYPE_ZIP
    return declarado


def _extract_paginas(content: bytes, content_type: str | None) -> list[PaginaExtraida]:
    """Despacha extracción preservando límites de página.

    ``None`` sigue significando PDF: hay servidores de PLACSP que no declaran
    content-type y el PDF es, con diferencia, el caso mayoritario.
    """
    return _extraer_paginas_de_tipo(content, content_type or CONTENT_TYPE_PDF)


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

    Devuelve ``"extracted"``, ``"error"``, ``"unsupported"``, ``"sin_texto"``,
    ``"skipped"`` o ``"skipped_no_extra"`` — para que el llamador (job de embeddings, F8)
    instrumente métricas sin releer la fila. ``"skipped"`` significa que no se
    llegó a intentar nada (breaker abierto) y ``"skipped_no_extra"`` que el
    formato se sabe leer pero no en este proceso (:class:`ExtractorAusenteError`):
    en los dos casos la fila se queda en ``pending`` y entra en el lote siguiente.
    ``"unsupported"`` es cobertura que falta, no un fallo, y ``"sin_texto"``
    un PDF escaneado que el OCR de este proceso no pudo leer
    (:class:`PdfSinTextoError`).
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
        # El breaker abierto no dice nada de ESTE documento: dice que su
        # plataforma (PLACSP, TED o la catalana) está rechazando ahora mismo. Marcarlo 'error' lo sacaría de
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
    except RecursoNoServidoError as e:
        # Va antes que ``HTTPError``, de la que hereda: la plataforma ha dicho
        # que no sirve ESTE documento, y el mensaje ya trae la causa. Etiquetarlo
        # «token caducado» mandaría a esperar un enlace nuevo que puede no llegar.
        #
        # Es también lo que contesta por un pliego anunciado y aún sin publicar.
        # Esos no deberían llegar aquí: ``list_pendientes`` y la extracción bajo
        # demanda los apartan antes (``sin_publicar``), y su URI no cambia al
        # publicarse.
        recuperado = _contenido_desde_blob(documento_id, documento)
        if recuperado is None:
            log.warning("document_fetch_download_failed", documento_id=documento_id, error=str(e))
            repo.mark_error(
                documento_id, error_detail=f"descarga fallida: {e}"[:_MAX_ERROR_DETAIL_LEN]
            )
            return "error"
        content, content_type = recuperado
        desde_blob = True
    except requests.HTTPError as e:
        recuperado = _contenido_desde_blob(documento_id, documento)
        if recuperado is None:
            # Un 500 sin la firma con la que el servlet de PLACSP dice «este
            # documento no lo sirvo» (ese va en la rama de arriba). Se marca error
            # como cualquier otro fallo de descarga —conservando el prefijo, que es
            # lo que distingue "falló la red" de "falló la extracción"— y con la
            # etiqueta con la que se venían contando los 500, aunque de estos ya
            # no consta que sean por el token.
            detalle = (
                f"descarga fallida: token caducado (500): {e}"
                if status_de(e) == 500
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

    content_type = _resolver_content_type(content, content_type)
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
    except ExtractorAusenteError as e:
        # Mismo trato que el breaker abierto: nada que decir de ESTE documento,
        # solo de este proceso. La fila sigue ``pending`` para el lote nocturno
        # (y el binario, si se guardó arriba, le ahorra la descarga).
        log.info(
            "document_fetch_skipped_extractor_ausente",
            documento_id=documento_id,
            content_type=e.content_type or content_type,
            error=str(e),
        )
        return "skipped_no_extra"
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
    except PdfSinTextoError as e:
        log.info("document_fetch_sin_texto", documento_id=documento_id, error=str(e))
        repo.mark_downloaded(
            documento_id,
            filename=documento.get("filename"),
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
        )
        repo.mark_sin_texto(
            documento_id,
            content_type=content_type,
            error_detail=str(e)[:_MAX_ERROR_DETAIL_LEN],
        )
        return "sin_texto"
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
    content_type = _resolver_content_type(content, content_type)

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
    except PdfSinTextoError as e:
        repo.mark_sin_texto(
            documento_id,
            content_type=content_type,
            error_detail=str(e)[:_MAX_ERROR_DETAIL_LEN],
        )
        return "sin_texto"
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
