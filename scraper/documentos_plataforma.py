"""Documentos de las convocatorias que no los traen en su feed (TED, PSCP y Andalucía).

PLACSP mete las referencias a los pliegos en cada entry del ATOM y
``run_connector`` las persiste al ingerir. TED y la plataforma catalana no:
medido el 2026-10-02, ninguna de las ~2.600 filas TED ni de las PSCP tenía un
solo documento, así que una oportunidad abierta sobre ellas se quedaba sin
ficha del pliego, sin páginas que citar y sin guion. Este módulo cierra ese
hueco sobre datos abiertos:

- **Anuncio TED** (:func:`referencia_anuncio_ted`). TED nunca publica pliegos,
  pero el PDF del anuncio sí describe el contrato —objeto, lotes, criterios de
  adjudicación, plazos—. Es el mínimo que toda convocatoria TED sin pareja
  recibe como documento propio.
- **El expediente de PLACSP que el aviso TED enlaza.** No es de este módulo:
  el conector de PLACSP ingiere entera la entry que su filtro de tecnología
  descartaría si un aviso TED sin pareja la enlaza por ``idEvl``
  (``scraper.connectors.placsp.EsperadasPorTed``), y el emparejamiento la hace
  canónica. Hasta el 2026-11-04 solo se copiaban sus pliegos a la fila TED, y
  el contrato se quedaba sin lotes, criterios ni importes por lote.

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

  El JSON es **por publicación**, no por expediente: cada fase (anuncio,
  evaluación, adjudicación, formalización, ejecución…) es otra publicación, y
  solo la del anuncio de licitación trae los pliegos. Un expediente cerrado
  guarda en ``licitaciones.url`` la de su última fase, así que leerla sola no
  daba nada; su ``navegacioFases`` enlaza la del anuncio, que es la que se lee.
  Medido el 2026-11-09 sobre 36 expedientes cerrados sin documentos: 32 tenían
  anuncio con pliegos; los otros cuatro no lo tuvieron en la plataforma
  (negociados sin publicidad, contratos basados en un acuerdo marco).
- **Perfil de Contratante de la Junta de Andalucía**
  (:func:`documentos_de_andalucia`). Sus expedientes llegan por la sindicación
  de agregadas de PLACSP sin una sola referencia a documentos (383 de 383 el
  2026-11-09), pero la ficha pública de cada uno, que enlaza su ``url``
  (``detalle-licitacion?idExpediente=…``), los lista en el JSON del buscador
  que pinta su web: categoría (PCAP, PPT, documento adicional…), ``sha256`` del
  fichero y descarga directa. Se pide como lo pide esa web, por el
  ``idExpediente``; su ``robots.txt`` no restringe esas rutas. Solo los
  expedientes vigentes: en uno adjudicado la ficha ya solo trae la resolución
  de adjudicación. Un aviso TED emparejado con la agregada lee estos pliegos.

Los tres pasos que se ejecutan tras cada ingesta —:func:`completar_documentos_ted`,
:func:`completar_documentos_pscp` y :func:`completar_documentos_andalucia`— los
llama ``run_connector`` a través del ``completar_documentos`` de cada conector
(el último, el de agregadas), con presupuesto de tiempo: corren dentro del step
de 10 minutos de ``scrape-daily.yml``. El de TED va dentro de
``_post_ingestion``, tras los dedupes, porque necesita sus marcas; los otros dos
van antes de ese cierre (``completar_documentos_primero``), porque no las
necesitan y detrás de la resolución de empresas el step se cortaba antes de
llegar. Sin lote se llaman igual, porque leen de la BD y no de lo que trajo la
pasada.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

from config import USER_AGENT, settings
from db.upsert import DocumentoReferencia
from observability import get_logger
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
_ID_PUBLICACION_PSCP = re.compile(r"\d{1,12}")
#: ``fase`` de la publicación del anuncio de licitación, la única con pliegos.
#: Las demás (evaluación 1008286, adjudicación 1000042, formalización 1000043,
#: ejecución 1000045, anulación 1000041…) traen actas, resoluciones y contratos.
_FASE_ANUNCI_PSCP = "1000040"
#: Apartado del JSON → ``documentos.tipo``. El resto (memoria justificativa,
#: aprobación, «altres documents», anexos por lote) son ``additional``.
_TIPO_POR_APARTADO_PSCP = {
    "plecsDeClausulesAdministratives": "legal",
    "plecsDePrescripcionsTecniques": "technical",
}

_HOST_ANDALUCIA = "www.juntadeandalucia.es"
_APL_ANDALUCIA = f"https://{_HOST_ANDALUCIA}/haciendayadministracionpublica/apl"
#: El buscador con el que la web del Perfil de Contratante pinta cada expediente.
_API_ANDALUCIA = f"{_APL_ANDALUCIA}/pdc-front-publico/elastic/sirec_pdc_expedientes_details/_search"
_DESCARGA_ANDALUCIA = f"{_APL_ANDALUCIA}/pdc_sirec_documentacion/rest/descargar/documento/{{id}}"
_ID_ANDALUCIA = re.compile(r"\d{1,15}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
#: Prefijo de la categoría → ``documentos.tipo``. El resto (documento
#: adicional, memoria justificativa, aprobación del expediente…) es ``additional``.
_TIPO_POR_CATEGORIA_ANDALUCIA = (("PCAP", "legal"), ("PPT", "technical"))
#: Lo que cuelga del expediente sin ser pliego: actas de la mesa y adjudicación.
_NO_PLIEGO_ANDALUCIA = re.compile(r"\bacta\b|adjudicaci", re.IGNORECASE)

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

    Solo la publicación del anuncio de licitación aporta documentos y avisos
    TED. Las de otras fases traen actas de la mesa, resoluciones y contratos:
    guardarlos como ``additional`` los metería en la descarga nocturna, el RAG y
    la ficha como si fueran pliego. Y su cita a TED no está comprobada como la
    del mismo contrato, que es lo que la marca ``confirmed`` de
    ``marcar_republicaciones_ted`` da por hecho: un contrato basado en un
    acuerdo marco podría citar el aviso del acuerdo.
    """
    dades = datos.get("dades") if isinstance(datos, dict) else None
    publicacion = dades.get("publicacio") if isinstance(dades, dict) else None
    if not isinstance(publicacion, dict) or not _es_anunci_pscp(datos):
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


def _es_anunci_pscp(datos: object) -> bool:
    """¿Es *datos* la publicación del anuncio de licitación?

    Sin ``fase`` se da por tal: es lo que se hacía antes de mirarla, y el JSON
    real la trae siempre.
    """
    fase = datos.get("fase") if isinstance(datos, dict) else None
    return fase is None or str(fase) == _FASE_ANUNCI_PSCP


def _urls_del_anunci_pscp(api: str, datos: object) -> list[str]:
    """El JSON de la publicación del anuncio, si *datos* es de otra fase del expediente.

    Lo da ``navegacioFases`` (``[{fase, publicacioId, …}]``), que lista la
    última versión de cada fase. Sin anuncio (un negociado sin publicidad, un
    contrato basado en un acuerdo marco) no hay nada que pedir.
    """
    if _es_anunci_pscp(datos):
        return []
    fases = datos.get("navegacioFases") if isinstance(datos, dict) else None
    expediente = api.rsplit("/", 1)[0]
    urls: list[str] = []
    for fase in fases if isinstance(fases, list) else []:
        if not isinstance(fase, dict) or str(fase.get("fase")) != _FASE_ANUNCI_PSCP:
            continue
        publicacion = str(fase.get("publicacioId") or "")
        url = f"{expediente}/{publicacion}"
        # Va a la ruta de la URL, como el id de un documento: solo dígitos.
        if _ID_PUBLICACION_PSCP.fullmatch(publicacion) and url not in urls:
            urls.append(url)
    return urls


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


def _obtener(
    url: str, *, host: str, timeout_s: float | None = None, cuerpo: bytes | None = None
) -> bytes:
    """GET de *url* —POST si lleva *cuerpo* JSON—, que tiene que estar en *host*, con
    las guardas del descargador.

    Sin reintentos ni circuito: es una consulta de metadatos que la pasada
    siguiente repite sola, y el circuito de la plataforma es para la descarga
    de los pliegos, que no debe abrirse porque una ficha concreta dé 404.

    *timeout_s* lo fija quien tiene un presupuesto que cuidar; sin él manda el
    ``REQUEST_TIMEOUT`` global.
    """
    cabeceras = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if cuerpo is not None:
        cabeceras["Content-Type"] = "application/json"
    respuesta = pinned_https_request(
        "GET" if cuerpo is None else "POST",
        url,
        headers=cabeceras,
        body=cuerpo,
        timeout_seconds=float(timeout_s if timeout_s is not None else settings.REQUEST_TIMEOUT),
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


#: Suelo del tope por petición: por debajo, ni la negociación TLS cabe y la
#: petición fallaría siempre, contando como fallo de la plataforma.
_TOPE_MINIMO_S = 1.0


def _obtener_pscp_con_tope(restante_s: Callable[[], float]) -> Callable[[str], bytes]:
    """Descarga de la ficha con un timeout que no pasa de lo que queda de presupuesto.

    *restante_s* se consulta en cada petición: un expediente cerrado pide dos
    (su fase y la del anuncio), y la segunda solo tiene lo que dejó la primera.
    """

    def obtener(url: str) -> bytes:
        tope = max(_TOPE_MINIMO_S, min(float(settings.REQUEST_TIMEOUT), restante_s()))
        return _obtener(url, host=_HOST_PSCP, timeout_s=tope)

    return obtener


def documentos_de_pscp(
    url_ficha: str | None, *, obtener: Callable[[str], bytes] | None = None
) -> DetallePscp | None:
    """El detalle de una publicación de la PSCP, o ``None`` si la URL no es una ficha.

    Si la publicación es de una fase posterior al anuncio, los pliegos salen de
    la del anuncio que enlaza su ``navegacioFases``: una petición más. Si esa
    falla, falla la ficha entera: cuenta como fallo de la plataforma y la fila
    sigue candidata para la pasada siguiente.

    *obtener* existe para los tests: por defecto descarga de verdad.
    """
    api = url_api_pscp(url_ficha)
    if api is None:
        return None
    pedir = obtener or (lambda url: _obtener(url, host=_HOST_PSCP))
    datos = json.loads(pedir(api))
    detalle = parse_detalle_pscp(datos)
    for url in _urls_del_anunci_pscp(api, datos):
        del_anunci = parse_detalle_pscp(json.loads(pedir(url)))
        detalle = DetallePscp(
            documentos=detalle.documentos + del_anunci.documentos,
            anuncios_ted=list(dict.fromkeys(detalle.anuncios_ted + del_anunci.anuncios_ted)),
        )
    return detalle


# ── Andalucía ────────────────────────────────────────────────────────────────


def id_expediente_andalucia(url_ficha: str | None) -> str | None:
    """El ``idExpediente`` de la ficha de un expediente en el Perfil de Contratante, o ``None``.

    Las agregadas guardan la ficha vieja (``pdc_sirec/…/detalle-licitacion.jsf``)
    y la web la redirige a la nueva (``pdc-front-publico/…/detalle-licitacion``):
    sirven las dos.
    """
    if not url_ficha:
        return None
    partes = urlparse(url_ficha)
    host = (partes.hostname or "").lower()
    if host != _HOST_ANDALUCIA or "/detalle-licitacion" not in partes.path:
        return None
    valores = parse_qs(partes.query).get("idExpediente") or []
    return valores[0] if len(valores) == 1 and _ID_ANDALUCIA.fullmatch(valores[0]) else None


def parse_detalle_andalucia(datos: Any) -> list[DocumentoReferencia]:
    """Los pliegos del JSON del buscador para un expediente (``hits.hits[0]._source``).

    Solo los ``Activo``: los ``Inactivo`` son versiones sustituidas, que la web
    enseña aparte. La descarga se compone con el ``id`` y la identidad es el
    ``sha256`` del fichero, que publica la propia Junta: con él ``upsert_meta``
    refresca la fila en vez de duplicarla.
    """
    hits = datos.get("hits") if isinstance(datos, dict) else None
    encontrados = hits.get("hits") if isinstance(hits, dict) else None
    if not isinstance(encontrados, list) or len(encontrados) != 1:
        return []
    fuente = encontrados[0].get("_source") if isinstance(encontrados[0], dict) else None
    documentos = fuente.get("documentos") if isinstance(fuente, dict) else None
    referencias: dict[str, DocumentoReferencia] = {}
    for doc in documentos if isinstance(documentos, list) else []:
        referencia = _referencia_andalucia(doc)
        if referencia is not None:
            referencias.setdefault(referencia.uri, referencia)
    return list(referencias.values())


def _referencia_andalucia(doc: Any) -> DocumentoReferencia | None:
    if not isinstance(doc, dict) or doc.get("estado") != "Activo":
        return None
    categoria = str(doc.get("categoria") or "")
    identificador = str(doc.get("id") or "")
    huella = str(doc.get("sha256") or "").lower()
    # El id va a la ruta de la descarga y el hash a la identidad del documento:
    # solo con la forma que sirve la Junta, para que un valor raro no componga otra.
    if (
        _NO_PLIEGO_ANDALUCIA.search(categoria)
        or not _ID_ANDALUCIA.fullmatch(identificador)
        or not _SHA256.fullmatch(huella)
    ):
        return None
    tipo = next(
        (
            t
            for prefijo, t in _TIPO_POR_CATEGORIA_ANDALUCIA
            if categoria.upper().startswith(prefijo)
        ),
        "additional",
    )
    nombre = doc.get("nombre")
    return DocumentoReferencia(
        tipo=tipo,
        uri=_DESCARGA_ANDALUCIA.format(id=identificador),
        filename=(nombre.strip() or None) if isinstance(nombre, str) else None,
        source_hash=huella,
    )


def _obtener_andalucia_con_tope(restante_s: Callable[[], float]) -> Callable[[str, bytes], bytes]:
    """La consulta al buscador con un timeout que no pasa de lo que queda de presupuesto."""

    def obtener(url: str, cuerpo: bytes) -> bytes:
        tope = max(_TOPE_MINIMO_S, min(float(settings.REQUEST_TIMEOUT), restante_s()))
        return _obtener(url, host=_HOST_ANDALUCIA, timeout_s=tope, cuerpo=cuerpo)

    return obtener


def documentos_de_andalucia(
    url_ficha: str | None, *, obtener: Callable[[str, bytes], bytes] | None = None
) -> list[DocumentoReferencia] | None:
    """Los pliegos de un expediente de la Junta, o ``None`` si la URL no es su ficha.

    Una petición: la misma que hace su web al abrir la ficha. *obtener* existe
    para los tests: por defecto pide de verdad.
    """
    identificador = id_expediente_andalucia(url_ficha)
    if identificador is None:
        return None
    cuerpo = json.dumps({"query": {"match": {"_id": identificador}}}).encode()
    pedir = obtener or (lambda url, datos: _obtener(url, host=_HOST_ANDALUCIA, cuerpo=datos))
    return parse_detalle_andalucia(json.loads(pedir(_API_ANDALUCIA, cuerpo)))


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
    por_fila: dict[str, list[DocumentoReferencia]] = {}
    for id_externo in repo.ted_vigentes_sin_documentos(limit=limite):
        resumen.candidatas += 1
        referencia = referencia_anuncio_ted(id_externo)
        if referencia is not None:
            por_fila[id_externo] = [referencia]
    try:
        fallos = repo.upsert_meta_batch(por_fila)
    except Exception as e:
        fallos = dict.fromkeys(por_fila, e)
    for id_externo, error in fallos.items():
        resumen.fallidas += 1
        resumen.errores.append(f"{id_externo}: {error}")
    resumen.con_documentos = resumen.referencias = len(por_fila) - len(fallos)
    return resumen


def completar_documentos_pscp(
    *,
    limite: int = 200,
    presupuesto_s: float = 120.0,
    pausa_s: float = 0.3,
    dias_cambio: int | None = 7,
    obtener: Callable[[str], bytes] | None = None,
    reloj: Callable[[], float] = time.monotonic,
) -> ResumenDocumentos:
    """Pliegos de los expedientes de la PSCP, y su anuncio TED.

    Las candidatas (``DocumentosRepository.pscp_para_documentos``) son las
    vigentes que aún no tienen documentos y, entre las que sí, las publicadas
    hace poco: una rectificación añade pliegos, y el anuncio TED que el JSON
    cita llega días después de la publicación en la plataforma. Detrás, los
    expedientes ya cerrados sin documentos que cambiaron en origen en los
    últimos *dias_cambio* días; con ``None``, todos (es el backfill,
    ``scripts/backfill_documentos_pscp.py``). Cada ficha es una petición, dos si
    hay que saltar al anuncio; el presupuesto de tiempo y el corte por fallos
    seguidos acotan la pasada.

    El presupuesto acota también **cada petición**: sin eso solo se miraba
    antes de pedir la ficha, y la que estaba en vuelo tenía el
    ``REQUEST_TIMEOUT`` entero por delante. Corre dentro del step de 10 minutos
    de ``scrape-daily.yml`` y antes del cierre del lote (ver
    ``PscpConnector.completar_documentos_primero``), así que lo que se pase de
    su presupuesto se lo quita a la resolución de empresas. *reloj* existe para
    los tests.

    El anuncio TED citado se marca como republicación si la fila PSCP se
    publica; si no, recibe él los mismos pliegos
    (``services.dedupe.marcar_republicaciones_ted``).
    """
    from db.repositories.documentos import DocumentosRepository
    from services.dedupe import marcar_republicaciones_ted

    repo = DocumentosRepository()
    resumen = ResumenDocumentos()
    inicio = reloj()
    pedir = obtener or _obtener_pscp_con_tope(lambda: presupuesto_s - (reloj() - inicio))
    fallos_seguidos = 0
    for fila in repo.pscp_para_documentos(limit=limite, dias_cambio=dias_cambio):
        if presupuesto_s - (reloj() - inicio) <= 0:
            resumen.sin_presupuesto = True
            break
        if fallos_seguidos >= _FALLOS_SEGUIDOS_MAX:
            break
        resumen.candidatas += 1
        id_externo = str(fila["id_externo"])
        try:
            detalle = documentos_de_pscp(fila.get("url"), obtener=pedir)
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


def completar_documentos_andalucia(
    *,
    limite: int = 60,
    presupuesto_s: float = 60.0,
    pausa_s: float = 0.5,
    obtener: Callable[[str, bytes], bytes] | None = None,
    reloj: Callable[[], float] = time.monotonic,
) -> ResumenDocumentos:
    """Pliegos de las convocatorias vigentes de la Junta de Andalucía agregadas en PLACSP.

    Candidatas (``DocumentosRepository.andalucia_para_documentos``): las que aún
    no tienen documentos y, de las que sí, las publicadas hace poco, que es
    cuando llegan las rectificaciones de pliegos. Una petición por expediente,
    con el mismo presupuesto, tope por petición y corte por fallos seguidos que
    :func:`completar_documentos_pscp`. *obtener* y *reloj* existen para los tests.
    """
    from db.repositories.documentos import DocumentosRepository

    repo = DocumentosRepository()
    resumen = ResumenDocumentos()
    inicio = reloj()
    pedir = obtener or _obtener_andalucia_con_tope(lambda: presupuesto_s - (reloj() - inicio))
    fallos_seguidos = 0
    for fila in repo.andalucia_para_documentos(limit=limite):
        if presupuesto_s - (reloj() - inicio) <= 0:
            resumen.sin_presupuesto = True
            break
        if fallos_seguidos >= _FALLOS_SEGUIDOS_MAX:
            break
        resumen.candidatas += 1
        id_externo = str(fila["id_externo"])
        try:
            documentos = documentos_de_andalucia(fila.get("url"), obtener=pedir)
        except Exception as e:
            fallos_seguidos += 1
            resumen.fallidas += 1
            resumen.errores.append(f"{id_externo}: {e}")
            continue
        finally:
            if pausa_s:
                time.sleep(pausa_s)
        fallos_seguidos = 0
        if not documentos:
            continue
        try:
            # shortcut: una versión que la Junta pasa a `Inactivo` y ya se guardó
            # sigue como documento (como en PSCP y PLACSP); retirarla cuando
            # `upsert_meta` sepa dar de baja lo que la fuente ya no lista.
            repo.upsert_meta(id_externo, documentos)
        except Exception as e:
            resumen.fallidas += 1
            resumen.errores.append(f"{id_externo}: {e}")
        else:
            resumen.con_documentos += 1
            resumen.referencias += len(documentos)
    return resumen
