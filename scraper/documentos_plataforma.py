"""Documentos de las convocatorias que no los traen en su feed (TED y PSCP).

PLACSP mete las referencias a los pliegos en cada entry del ATOM y
``run_connector`` las persiste al ingerir. TED y la plataforma catalana no:
medido el 2026-10-02, ninguna de las ~2.600 filas TED ni de las PSCP tenía un
solo documento, así que una oportunidad abierta sobre ellas se quedaba sin
ficha del pliego, sin páginas que citar y sin guion. Este módulo cierra ese
hueco con tres caminos, todos sobre datos abiertos:

- **Anuncio TED** (:func:`referencia_anuncio_ted`). TED nunca publica pliegos,
  pero el PDF del anuncio sí describe el contrato —objeto, lotes, criterios de
  adjudicación, plazos—. Es el mínimo que toda convocatoria TED sin pareja
  recibe como documento propio.
- **Pliegos de PLACSP rescatados del ATOM** (:class:`RescatePliegosPlacsp`).
  Un aviso TED cuyo expediente de PLACSP no está en BD es uno que el filtro de
  tecnología del ATOM descartó: TED entra por cualquier CPV 48/72 del aviso,
  PLACSP por el principal y las palabras clave. La entry descartada sigue
  trayendo sus pliegos, y PLACSP la re-emite al registrar la publicación en el
  DOUE (93 de 94 pares medidos se actualizaron el día del anuncio TED o
  después). Cuando pasa, sus referencias se guardan en la fila TED.

  La ficha HTML del expediente **no** se usa: ``robots.txt`` de
  contrataciondelestado.es es ``Disallow: /`` y la ficha devuelve la página sin
  documentos a cualquier User-Agent que se identifique como bot (comprobado el
  2026-10-02). Leerla exigiría disfrazar el nuestro.
- **Ficha de la PSCP** (:func:`documentos_de_pscp`). El portal catalán sirve el
  detalle de cada publicación como JSON público —el mismo que pinta su web—,
  con los pliegos (``plecsDeClausulesAdministratives``,
  ``plecsDePrescripcionsTecniques``…) y la descarga directa de cada uno. El JSON
  cita además el anuncio TED del mismo contrato (``publicacionsOficials``),
  que es la referencia exacta para emparejarlos: el BT-15 de esos avisos apunta
  al perfil del comprador, no al expediente, y el BT-22 falta en muchos.

Los dos pasos que se ejecutan tras cada ingesta —:func:`completar_documentos_ted`
y :func:`completar_documentos_pscp`— los llaman los conectores desde
``_post_ingestion``, con presupuesto de tiempo: corren dentro del step de 10
minutos de ``scrape-daily.yml``.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

from config import USER_AGENT, settings
from db.upsert import DocumentoReferencia
from observability import get_logger
from services.dedupe import id_evl_de_url
from shared.outbound_http import pinned_https_request

log = get_logger(__name__)

_PREFIJO_TED = "ted:"
#: ``publication-number`` de TED: ``678766-2026``.
_NUMERO_TED = re.compile(r"\d{1,8}-\d{4}")
#: Enlace a un anuncio en la web de TED, en cualquiera de sus formas
#: (``/es/notice/678766-2026/pdf``, ``/en/notice/-/detail/678766-2026``).
_ENLACE_ANUNCIO_TED = re.compile(r"ted\.europa\.eu/[^\s\"']*?notice/(?:-/detail/)?(\d{1,8}-\d{4})")
_URL_ANUNCIO_TED = "https://ted.europa.eu/es/notice/{numero}/pdf"

_HOST_PSCP = "contractaciopublica.cat"
_API_PSCP = f"https://{_HOST_PSCP}/portal-api"
#: ``/ca/detall-publicacio/{uuid del expediente}/{id de la publicación}``: la
#: forma de ``licitaciones.url`` en todas las filas PSCP con convocatoria.
_RUTA_DETALLE_PSCP = re.compile(r"/detall-publicacio/([0-9a-fA-F-]{36})/(\d{1,12})(?:/|$)")
_ID_DOCUMENTO_PSCP = re.compile(r"\d{1,15}")
_HASH_DOCUMENTO_PSCP = re.compile(r"[0-9A-Za-z]{8,128}")
#: Apartado del JSON → ``documentos.tipo``. El resto (memoria justificativa,
#: aprobación, «altres documents», anexos por lote) son ``additional``.
_TIPO_POR_APARTADO_PSCP = {
    "plecsDeClausulesAdministratives": "legal",
    "plecsDePrescripcionsTecniques": "technical",
}

#: Tras tantos fallos seguidos se da la plataforma por caída en esta pasada:
#: seguir pidiendo solo gasta el presupuesto y la cortesía con su servidor.
_FALLOS_SEGUIDOS_MAX = 5


# ── Anuncio TED ──────────────────────────────────────────────────────────────


def numero_publicacion_ted(id_externo: str) -> str | None:
    """El ``publication-number`` de una fila TED (``ted:678766-2026``), o ``None``."""
    if not id_externo.startswith(_PREFIJO_TED):
        return None
    numero = id_externo[len(_PREFIJO_TED) :]
    return numero if _NUMERO_TED.fullmatch(numero) else None


def referencia_anuncio_ted(id_externo: str) -> DocumentoReferencia | None:
    """El PDF del anuncio TED como documento de la propia fila.

    ``tipo='additional'`` porque ``documentos.tipo`` solo admite ``legal``,
    ``technical`` y ``additional`` (CHECK de ``v56``), y el anuncio no es
    ninguno de los dos pliegos: queda detrás de ellos en todo orden por tipo, y
    la interfaz lo reconoce por el host de la URI.

    ``source_hash`` es el número de publicación y no un hash del contenido: un
    anuncio publicado en TED no cambia nunca (una corrección es otro anuncio
    con otro número), así que identifica el fichero igual de bien. Y sin él la
    fila contaría como «legacy» para ``upsert_meta``, que podría adoptarla para
    el primer adjunto ``additional`` con hash que llegara después.
    """
    numero = numero_publicacion_ted(id_externo)
    if numero is None:
        return None
    return DocumentoReferencia(
        tipo="additional",
        uri=_URL_ANUNCIO_TED.format(numero=numero),
        filename=f"Anuncio TED {numero}.pdf",
        source_hash=f"ted-{numero}",
    )


def numeros_ted_citados(nodo: Any) -> list[str]:
    """Números de anuncio TED enlazados en cualquier punto de *nodo* (JSON ya decodificado)."""
    vistos: dict[str, None] = {}

    def recorrer(valor: Any) -> None:
        if isinstance(valor, str):
            for numero in _ENLACE_ANUNCIO_TED.findall(valor):
                vistos.setdefault(numero, None)
        elif isinstance(valor, dict):
            for hijo in valor.values():
                recorrer(hijo)
        elif isinstance(valor, list):
            for hijo in valor:
                recorrer(hijo)

    recorrer(nodo)
    return list(vistos)


# ── PSCP ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DetallePscp:
    """Lo que la ficha de una publicación de la PSCP dice de sus documentos."""

    documentos: list[DocumentoReferencia]
    #: ``publication-number`` de los anuncios TED del mismo contrato.
    anuncios_ted: list[str]


def url_api_pscp(url_ficha: str | None) -> str | None:
    """La URL del JSON de detalle para la ficha pública de una publicación, o ``None``."""
    if not url_ficha:
        return None
    partes = urlparse(url_ficha)
    if (partes.hostname or "").lower() != _HOST_PSCP:
        return None
    coincidencia = _RUTA_DETALLE_PSCP.search(partes.path)
    if coincidencia is None:
        return None
    expediente, publicacion = coincidencia.groups()
    return f"{_API_PSCP}/detall-publicacio-expedient/{expediente}/{publicacion}"


def parse_detalle_pscp(datos: Any) -> DetallePscp:
    """Documentos y anuncios TED del JSON de ``detall-publicacio-expedient``.

    Los documentos cuelgan de apartados con una lista ``docs`` (``{id, titol,
    hash, mida, idioma}``), en la publicación y en cada lote. Se recorre todo el
    árbol de ``dades.publicacio`` en vez de nombrar los apartados: cambian según
    la fase y el tipo de procedimiento, y un apartado desconocido es un adjunto
    ``additional`` más, no un motivo para perderlo.

    La descarga es ``/portal-api/descarrega-document/{id}/{hash}``, la misma
    que usa su web. ``hash`` identifica el contenido, así que va a
    ``source_hash``: es la identidad con la que ``upsert_meta`` refresca la fila
    en vez de duplicarla.
    """
    dades = datos.get("dades") if isinstance(datos, dict) else None
    publicacion = dades.get("publicacio") if isinstance(dades, dict) else None
    if not isinstance(publicacion, dict):
        return DetallePscp(documentos=[], anuncios_ted=[])

    documentos: list[DocumentoReferencia] = []
    vistos: set[str] = set()

    def recorrer(valor: Any, apartado: str) -> None:
        if isinstance(valor, dict):
            docs = valor.get("docs")
            if isinstance(docs, list):
                for doc in docs:
                    referencia = _referencia_pscp(doc, apartado)
                    if referencia is not None and referencia.uri not in vistos:
                        vistos.add(referencia.uri)
                        documentos.append(referencia)
            for clave, hijo in valor.items():
                if clave != "docs":
                    recorrer(hijo, clave)
        elif isinstance(valor, list):
            for hijo in valor:
                recorrer(hijo, apartado)

    recorrer(publicacion, "")
    return DetallePscp(documentos=documentos, anuncios_ted=numeros_ted_citados(publicacion))


def _referencia_pscp(doc: Any, apartado: str) -> DocumentoReferencia | None:
    if not isinstance(doc, dict):
        return None
    identificador = str(doc.get("id") or "")
    huella = str(doc.get("hash") or "")
    # Los dos van a la ruta de la URL: solo se aceptan si tienen la forma que
    # sirve el portal, para que un valor raro no pueda componer otra ruta.
    if not _ID_DOCUMENTO_PSCP.fullmatch(identificador) or not _HASH_DOCUMENTO_PSCP.fullmatch(
        huella
    ):
        return None
    titulo = doc.get("titol")
    return DocumentoReferencia(
        tipo=_TIPO_POR_APARTADO_PSCP.get(apartado, "additional"),
        uri=f"{_API_PSCP}/descarrega-document/{identificador}/{huella}",
        filename=(titulo.strip() or None) if isinstance(titulo, str) else None,
        source_hash=huella,
    )


def _obtener(url: str, *, host: str) -> bytes:
    """GET de *url*, que tiene que estar en *host*, con las guardas del descargador.

    Sin reintentos ni circuito: es una consulta de metadatos que la pasada
    siguiente repite sola, y el circuito de la plataforma es para la descarga
    de los pliegos, que no debe abrirse porque una ficha concreta dé 404.
    """
    respuesta = pinned_https_request(
        "GET",
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout_seconds=float(settings.REQUEST_TIMEOUT),
        allowed_hosts=frozenset({host}),
    )
    with respuesta:
        respuesta.raise_for_status()
        trozos: list[bytes] = []
        total = 0
        for trozo in respuesta.iter_content(chunk_size=8192):
            total += len(trozo)
            if total > settings.MAX_DOCUMENT_SIZE_BYTES:
                raise ValueError(f"Respuesta de {host} por encima del límite de tamaño")
            trozos.append(trozo)
    return b"".join(trozos)


def documentos_de_pscp(
    url_ficha: str | None, *, obtener: Callable[[str], bytes] | None = None
) -> DetallePscp | None:
    """El detalle de una publicación de la PSCP, o ``None`` si la URL no es una ficha.

    *obtener* existe para los tests: por defecto descarga de verdad.
    """
    api = url_api_pscp(url_ficha)
    if api is None:
        return None
    cuerpo = (obtener or (lambda url: _obtener(url, host=_HOST_PSCP)))(api)
    return parse_detalle_pscp(json.loads(cuerpo))


# ── PLACSP: rescate desde el ATOM ────────────────────────────────────────────


class RescatePliegosPlacsp:
    """Pliegos de entries descartadas del ATOM que un aviso TED sin pareja espera.

    El mapa ``idEvl → filas TED`` se carga una vez, perezosamente, con la
    primera entry descartada: así un run sin descartes —o un test que parsea
    una entry suelta— no toca la BD. Si la carga falla, el rescate se apaga
    para el resto de la pasada; nunca puede tumbar el parseo.
    """

    def __init__(
        self, cargar: Callable[[], Iterable[tuple[str, str | None]]] | None = None
    ) -> None:
        self._cargar = cargar or _ted_sin_pareja_con_id_evl
        self._esperadas: dict[str, list[str]] | None = None
        self.rescatados: dict[str, list[DocumentoReferencia]] = {}
        #: ``<updated>`` de la versión guardada para cada fila TED.
        self._version: dict[str, str] = {}

    def _mapa(self) -> Mapping[str, list[str]]:
        if self._esperadas is None:
            esperadas: dict[str, list[str]] = {}
            try:
                for id_externo, url in self._cargar():
                    if (evl := id_evl_de_url(url)) is not None:
                        esperadas.setdefault(evl, []).append(id_externo)
            except Exception as e:
                log.warning("placsp_rescate_ted_no_disponible", error=str(e))
                esperadas = {}
            self._esperadas = esperadas
        return self._esperadas

    def considerar(
        self,
        url_entry: str | None,
        documentos: list[DocumentoReferencia],
        actualizado: str | None = None,
    ) -> int:
        """Guarda *documentos* para las filas TED que esperan esta entry. Devuelve cuántas.

        El mismo expediente puede pasar varias veces en una pasada —el ATOM va
        de más nuevo a más viejo; el ZIP mensual, al revés— y una rectificación
        cambia los pliegos: gana la versión con el ``<updated>`` más reciente
        (texto ISO de PLACSP, comparable tal cual).
        """
        if not documentos:
            return 0
        evl = id_evl_de_url(url_entry)
        if evl is None:
            return 0
        filas = self._mapa().get(evl, [])
        version = actualizado or ""
        for id_externo in filas:
            if id_externo in self.rescatados and version < self._version.get(id_externo, ""):
                continue
            self.rescatados[id_externo] = list(documentos)
            self._version[id_externo] = version
        return len(filas)

    def persistir(self) -> int:
        """Escribe lo rescatado. Fail-open por fila, como ``_persist_documentos``."""
        if not self.rescatados:
            return 0
        from db.repositories.documentos import DocumentosRepository

        repo = DocumentosRepository()
        escritas = 0
        for id_externo, refs in self.rescatados.items():
            try:
                repo.upsert_meta(id_externo, refs)
                escritas += 1
            except Exception as e:
                log.warning(
                    "placsp_rescate_ted_persist_failed", licitacion_id=id_externo, error=str(e)
                )
        log.info("placsp_rescate_ted", filas=escritas, total=len(self.rescatados))
        self.rescatados = {}
        self._version = {}
        return escritas


def _ted_sin_pareja_con_id_evl() -> list[tuple[str, str | None]]:
    from db.repositories import dedupe as dedupe_repo

    return [(str(f["id_externo"]), f.get("url")) for f in dedupe_repo.ted_sin_pareja_con_id_evl()]


# ── Pasos tras la ingesta ────────────────────────────────────────────────────


@dataclass
class ResumenDocumentos:
    """Contadores de una pasada, para el log y para los tests."""

    candidatas: int = 0
    con_documentos: int = 0
    referencias: int = 0
    emparejadas: int = 0
    fallidas: int = 0
    sin_presupuesto: bool = False
    errores: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        datos = asdict(self)
        datos["errores"] = datos["errores"][:5]
        return datos


def completar_documentos_ted(*, limite: int = 300) -> ResumenDocumentos:
    """Da el anuncio TED como documento a las convocatorias TED vigentes sin pareja.

    Solo a las que no tienen ningún documento: una fila con pliegos rescatados
    de PLACSP, o con el anuncio ya puesto, no necesita nada. Y solo sin pareja
    ``confirmed``: la ficha de una republicación lee los pliegos de su canónica
    (``services.dedupe.expediente_del_pliego``), así que un documento propio
    sería invisible y solo costaría descargarlo y extraerlo. No hay red: es
    escribir una referencia por fila.
    """
    from db.repositories.documentos import DocumentosRepository

    repo = DocumentosRepository()
    resumen = ResumenDocumentos()
    for id_externo in repo.ted_vigentes_sin_documentos(limit=limite):
        resumen.candidatas += 1
        referencia = referencia_anuncio_ted(id_externo)
        if referencia is None:
            continue
        try:
            repo.upsert_meta(id_externo, [referencia])
        except Exception as e:
            resumen.fallidas += 1
            resumen.errores.append(f"{id_externo}: {e}")
            continue
        resumen.con_documentos += 1
        resumen.referencias += 1
    return resumen


def completar_documentos_pscp(
    *,
    limite: int = 200,
    presupuesto_s: float = 120.0,
    pausa_s: float = 0.3,
    obtener: Callable[[str], bytes] | None = None,
) -> ResumenDocumentos:
    """Pliegos de las convocatorias vigentes de la PSCP, y su anuncio TED.

    Las candidatas son las que aún no tienen documentos y, entre las que sí,
    las publicadas hace poco (``DocumentosRepository.pscp_vigentes_para_documentos``):
    una rectificación añade pliegos, y el anuncio TED que el JSON cita llega días
    después de la publicación en la plataforma. Cada ficha es una petición; el
    presupuesto de tiempo y el corte por fallos seguidos acotan la pasada.

    El anuncio TED citado se marca como republicación si la fila PSCP se
    publica; si no, recibe él los mismos pliegos
    (``services.dedupe.marcar_republicaciones_ted``).
    """
    from db.repositories.documentos import DocumentosRepository
    from services.dedupe import marcar_republicaciones_ted

    repo = DocumentosRepository()
    resumen = ResumenDocumentos()
    inicio = time.monotonic()
    fallos_seguidos = 0
    for fila in repo.pscp_vigentes_para_documentos(limit=limite):
        if time.monotonic() - inicio > presupuesto_s:
            resumen.sin_presupuesto = True
            break
        if fallos_seguidos >= _FALLOS_SEGUIDOS_MAX:
            break
        resumen.candidatas += 1
        id_externo = str(fila["id_externo"])
        try:
            detalle = documentos_de_pscp(fila.get("url"), obtener=obtener)
        except Exception as e:
            fallos_seguidos += 1
            resumen.fallidas += 1
            resumen.errores.append(f"{id_externo}: {e}")
            continue
        finally:
            if pausa_s:
                time.sleep(pausa_s)
        fallos_seguidos = 0
        if detalle is None:
            continue
        if detalle.documentos:
            try:
                repo.upsert_meta(id_externo, detalle.documentos)
            except Exception as e:
                resumen.fallidas += 1
                resumen.errores.append(f"{id_externo}: {e}")
            else:
                resumen.con_documentos += 1
                resumen.referencias += len(detalle.documentos)
        if detalle.anuncios_ted:
            try:
                republicaciones = marcar_republicaciones_ted(id_externo, detalle.anuncios_ted)
                resumen.emparejadas += len(republicaciones.marcadas)
                for id_ted in republicaciones.sin_canonica_visible:
                    if detalle.documentos:
                        repo.upsert_meta(id_ted, detalle.documentos)
                        resumen.con_documentos += 1
                        resumen.referencias += len(detalle.documentos)
            except Exception as e:
                resumen.errores.append(f"{id_externo}: {e}")
    return resumen
