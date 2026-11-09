"""Conector TED — Search API v3 (contratos UE sobre umbrales armonizados).

API pública sin autenticación: ``POST https://api.ted.europa.eu/v3/notices/search``
con sintaxis de expert query. Filtra por país de ejecución España y familias
CPV configurables (por defecto el universo de ingesta, ``CPV_PREFIXES_UNIVERSO``:
48 software, 72 servicios TI y 32 telecomunicaciones).

Mapeo eForms → modelo canónico:
- ``id_externo`` = ``ted:{publication-number}`` (namespacing ADR-009).
- ``titulo`` = BT-21 (``title-proc``), el título que publicó el comprador, y
  no el ``notice-title`` que compone TED. Ver ``_titulo``.
- Campos multilingües (title-proc, buyer-name…): preferencia spa → eng →
  primer idioma disponible.
- ``notice-type``: cn-* (convocatoria) → estado PUB; can-* (adjudicación/
  resultado) → RES, con Adjudicacion si trae winner-name; pin-* → PRE.
- ``place-of-performance``: primer código NUTS provincial → ccaa vía
  shared.geo.
- ``url``: enlace de acceso a los pliegos del comprador (BT-15/BT-615) cuando
  lleva a algún sitio concreto; si no, el PDF del anuncio en TED.

Dedupe: casi todo lo que publica TED es un contrato que el comprador ya publicó
en PLACSP o PSCP. El conector no puede saberlo al parsear, pero sí recoge lo que
el aviso dice del expediente original —BT-22 y el ``idEvl`` del deeplink de
PLACSP— y lo expone con ``referencias_cruzadas()``; el runner se lo pasa a
``services.dedupe.detect_duplicados_por_referencia`` tras persistir el lote.
Esas referencias no se guardan: las convocatorias vigentes que siguen sin
pareja pasada su ventana se releen en la API cada pasada
(``TedConnector.reemparejar_vigentes``), para emparejarlas en cuanto llegue su
expediente.

Cursor: ``last_seen_updated`` guarda el máximo ``publication-date`` visto, pero
cada run consulta desde ``watermark - _OVERLAP_DAYS``. Sin ese solapamiento, lo
que TED añada al índice con fecha anterior al watermark no se vuelve a
consultar nunca. Ver ``_OVERLAP_DAYS``.

Uso directo (backfill o cron):
    python -m scraper.connectors.ted                 # incremental desde cursor
    python -m scraper.connectors.ted --desde 20250101 --cpv 48,72,32
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import requests

from config import CPV_PREFIXES_UNIVERSO
from config.keywords import etiquetas_con_senal_firme
from db.upsert import Adjudicacion, Licitacion
from observability import get_logger
from scraper.connectors.base import ParsedTender, RawNotice
from scraper.filters import matches_technology
from scraper.resilience import pedir_con_reintentos
from services.dedupe import DedupeResult, ReferenciaCruzada, id_evl_de_url
from shared.geo import nuts_to_ccaa

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from scraper.connectors.base import ConnectorRunResult

log = get_logger(__name__)

SOURCE_ID = "ted"
_API_URL = "https://api.ted.europa.eu/v3/notices/search"
_PAGE_SIZE = 100
_TIMEOUT = 60
_PAGE_PAUSE_S = 0.5  # cortesía con la API pública

# Días que se re-consultan POR DETRÁS del watermark en cada run.
#
# El fallo que corrige: el cursor guarda el MÁXIMO `publication-date` visto y
# la query era `publication-date >= watermark` sin restar nada, así que el
# único día que se volvía a mirar era el propio watermark, y solo mientras no
# avanzase. En cuanto entraba un aviso del día D+1 el watermark saltaba y
# cualquier aviso del día D que TED publicase en el índice más tarde dejaba de
# consultarse PARA SIEMPRE. Con el cron cada 4 h
# (.github/workflows/scrape-daily.yml) ese salto ocurre a las pocas horas.
# Síntoma (2026-08-16): la ventana `>= 2026-06-10` tenía 1.307 filas en BD y un
# backfill manual sobre la misma ventana insertó 362 nuevas (22 %).
#
# Lo que SÍ está medido contra la API (2026-08-16, ventana ESP + CPV 48/72
# desde el 2026-06-10, 1.674 avisos): los `publication-number` se asignan de
# forma estrictamente creciente por fecha de publicación y sin huecos — la
# banda de cada día acaba justo donde empieza la del siguiente (densidad 100 %,
# 25 días comprobados). Es decir, el índice CONVERGE a completo: re-consultar
# un día ya cerrado devuelve todo lo suyo. Eso es lo que hace correcto un
# solapamiento fijo, sea cual sea el retraso exacto de indexación.
#
# Lo que NO se pudo medir en una sola sesión es ese retraso: haría falta
# comparar dos fotos de la API separadas por días, o `created_at` vs
# `fecha_publicacion` en producción. Por eso `fetch` emite `en_solapamiento` en
# `ted_fetch_done`: cuántos avisos vienen por detrás del watermark anterior, o
# sea el conjunto que la estrategia vieja no podía ver. Si en régimen normal es
# >0 de forma sostenida, la fuga queda confirmada con datos de producción.
#
# 14 días es holgado frente a cualquier retraso plausible y sigue siendo
# barato: ~35,6 avisos/día de media en esta ventana ≈ 500 avisos ≈ 5 páginas
# por run, y el upsert es idempotente (AGENTS.md §3, invariante 2), así que
# re-ingerir lo ya visto no duplica nada.
_OVERLAP_DAYS = 14

_FIELDS = [
    "publication-number",
    "notice-title",
    # BT-21: el título del procedimiento. Ver _titulo.
    "title-proc",
    # BT-22: el expediente en la plataforma del comprador. Ver referencias_cruzadas.
    "internal-identifier-proc",
    # BT-22 del lote: hay avisos que solo lo publican ahí. Ver _expediente.
    "internal-identifier-lot",
    # BT-04: en lo que envía la plataforma catalana, el UUID de su ficha. Ver _procedimiento.
    "procedure-identifier",
    "description-proc",
    "buyer-name",
    "classification-cpv",
    "publication-date",
    "deadline-receipt-tender-date-lot",
    "notice-type",
    "links",
    # BT-15 / BT-615: dónde publica el comprador los pliegos. Ver _documents_url.
    "document-url-lot",
    "document-restricted-url-lot",
    "estimated-value-proc",
    # BT-27 del lote: hay avisos que solo lo dan ahí. Ver `parse`.
    "estimated-value-lot",
    "result-value-notice",
    "winner-name",
    "place-of-performance",
    "contract-nature",
]

#: Lo que ``reemparejar_vigentes`` relee de cada aviso: sus referencias al expediente.
_FIELDS_REFERENCIAS = [
    "publication-number",
    "internal-identifier-proc",
    "internal-identifier-lot",
    "procedure-identifier",
    "document-url-lot",
    "document-restricted-url-lot",
]

# notice-type eForms → estado canónico (códigos PLACSP)
_ESTADO_MAP = {
    "pin": "PRE",  # prior information notice
    "cn": "PUB",  # contract notice
    "can": "RES",  # contract award notice (incl. can-modif)
}


def _cursor_date(value: Any) -> date | None:
    """Interpreta ``last_seen_updated`` como ``date``.

    Tolera todo lo que puede haber quedado guardado en ``ingestion_cursors``:
    ISO (``2026-08-14``), timestamp (``2026-08-14 00:00:00+00:00``),
    ``date``/``datetime`` devueltos por psycopg, o el formato compacto que
    escribe ``--desde`` (``20260814``). Devuelve None si no hay forma de
    leerlo: caer al lookback por defecto es preferible a tumbar el run entero
    por un cursor corrupto.
    """
    if value is None:
        return None
    # datetime antes que date: datetime es subclase de date.
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for candidato, fmt in ((text[:10], "%Y-%m-%d"), (text[:8], "%Y%m%d")):
        try:
            return datetime.strptime(candidato, fmt).date()
        except ValueError:
            continue
    log.warning("ted_cursor_ilegible", valor=text[:32])
    return None


def _first_lang(value: Any) -> str | None:
    """Extrae el texto de un campo multilingüe eForms (spa → eng → primero)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return str(value[0]) if value else None
    if isinstance(value, dict):
        for lang in ("spa", "eng"):
            if lang in value:
                return _first_lang(value[lang])
        for v in value.values():
            return _first_lang(v)
    return None


#: Separador de los tramos del ``notice-title``: «España \u2013 {CPV} \u2013 {BT-21}». Es
#: un guion largo (U+2013) entre espacios; el corto aparece dentro de títulos
#: reales («Servicio de X - Lote 1») y cortar por él mutilaría el título.
_SEPARADOR_NOTICE_TITLE = " \u2013 "


def _titulo(notice: dict[str, Any], natural_id: str) -> str:
    """Título del procedimiento (BT-21), sin el prefijo que TED le pone delante.

    ``notice-title`` no es un campo del comprador: lo compone TED como
    «España \u2013 {etiqueta del CPV} \u2013 {BT-21}». Medido el 2026-09-24 sobre 300
    avisos (ESP, CPV 48/72): prefijo en el 100 %, y el tercer tramo es BT-21
    byte a byte. Guardarlo entero tenía dos efectos:

    - la fila TED no podía colapsar nunca con la de PLACSP o PSCP del mismo
      contrato —la clave canónica compara el título—, así que la superficie
      pública servía los dos;
    - la etiqueta del CPV entraba en el filtro de tecnología: la de 72000000
      dice «desarrollo de software», y 52 de esos 300 avisos (17 %) salían
      etiquetados ``DESARROLLO`` solo por ella.

    ``title-proc`` venía en todos los avisos medidos; si faltara, se recorta el
    prefijo del ``notice-title``, y solo si tampoco se reconoce se guarda tal
    cual.
    """
    propio = (_first_lang(notice.get("title-proc")) or "").strip()
    if propio:
        return propio
    compuesto = (_first_lang(notice.get("notice-title")) or "").strip()
    tramos = compuesto.split(_SEPARADOR_NOTICE_TITLE, 2)
    if len(tramos) == 3 and tramos[2].strip():
        return tramos[2].strip()
    return compuesto or f"TED {natural_id}"


def _expediente(notice: dict[str, Any]) -> str | None:
    """BT-22 limpio, o ``None``. La API lo sirve como cadena o como lista.

    Primero el del procedimiento. Hay avisos que solo lo publican en el lote
    (``ProcurementProjectLot/ProcurementProject/cbc:ID[@schemeName="InternalID"]``:
    el 752237-2026 de Radio Televisión Madrid, 2026-11-05); sin él la TED se
    quedaba sin referencia y no se emparejaba con su expediente. El del lote se
    toma solo si todos los lotes traen el mismo: con varios distintos no hay un
    expediente del procedimiento que elegir.
    """
    for campo in ("internal-identifier-proc", "internal-identifier-lot"):
        valor = notice.get(campo)
        valores = [valor] if isinstance(valor, str) else valor
        if not isinstance(valores, list):
            continue
        limpios = {v.strip() for v in valores if isinstance(v, str) and v.strip()}
        if len(limpios) == 1:
            return limpios.pop()
        if limpios:
            return None
    return None


def _id_evl(notice: dict[str, Any]) -> str | None:
    """``idEvl`` del primer deeplink de PLACSP entre los enlaces de pliegos del aviso.

    Se mira en todos los candidatos de BT-15/BT-615 y no solo en el que acaba
    en ``url``: aunque hoy ``_documents_url`` prefiere el deeplink, el
    emparejamiento no debe depender de esa preferencia de presentación.
    """
    for campo in ("document-url-lot", "document-restricted-url-lot"):
        valor = notice.get(campo)
        candidatos = [valor] if isinstance(valor, str) else valor
        if not isinstance(candidatos, list):
            continue
        for candidato in candidatos:
            if isinstance(candidato, str) and (evl := id_evl_de_url(candidato)):
                return evl
    return None


def _procedimiento(notice: Mapping[str, object]) -> str | None:
    """BT-04 en minúsculas, o ``None``. La API lo sirve como cadena (o lista de una).

    Lo genera quien envía el aviso al DOUE. Cuando es la plataforma catalana,
    es el UUID de su ficha (``contractaciopublica.cat/…/detall-publicacio/<uuid>/``):
    los avisos de la Agència de Ciberseguretat 559302-2026 y 621898-2026 no traen
    BT-22 ni deeplink, pero sí ``df345a38-…``, la ficha de su fila PSCP (2026-11-07).
    """
    valor = notice.get("procedure-identifier")
    valores = [valor] if isinstance(valor, str) else valor
    if not isinstance(valores, list):
        return None
    limpios = {v.strip().lower() for v in valores if isinstance(v, str) and v.strip()}
    return limpios.pop() if len(limpios) == 1 else None


def _first_date(value: Any) -> str | None:
    """Normaliza fechas eForms ('2026-06-01+02:00' o lista) a YYYY-MM-DD."""
    if isinstance(value, list):
        value = value[0] if value else None
    if not value or not isinstance(value, str):
        return None
    return str(value)[:10]


def _to_float(value: Any) -> float | None:
    if isinstance(value, list):
        value = value[0] if value else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _suma(value: object) -> float | None:
    """Suma de un campo por lote (la API lo sirve como lista), o ``None``.

    Si algún valor no se lee, ``None``: una suma parcial daría por bueno un
    importe menor que el real.
    """
    valores = value if isinstance(value, list) else [value]
    numeros = [_to_float(v) for v in valores if v is not None]
    if not numeros or any(v is None for v in numeros):
        return None
    return sum(v for v in numeros if v is not None)


def _nuts_provincial(value: Any) -> str | None:
    """Primer código NUTS por debajo de país (p. ej. ES703); ignora 'ESP'."""
    if not isinstance(value, list):
        value = [value] if value else []
    for code in value:
        if isinstance(code, str) and len(code) > 3 and code.upper().startswith("ES"):
            return code.upper()
    return None


def _usable_url(value: str) -> str | None:
    """Normaliza una URL de BT-15/BT-615 y descarta las que no llevan a nada.

    Sobre una muestra de 300 anuncios españoles (CPV 48/72), 8 de las 83 URLs
    distintas eran la raíz de la plataforma (``https://www.contratacion.euskadi.eus``,
    ``https://portalcontratacion.navarra.es/es/``): no acercan al pliego y son
    peores que el PDF del anuncio, que al menos describe el expediente. El
    filtro exige query string o dos segmentos de ruta. Algunos valores llegan
    sin esquema (``www.contractaciopublica.cat``).
    """
    url = value.strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    parsed = urlparse(url)
    if not parsed.netloc:
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not parsed.query and len(segments) < 2:
        return None
    return url


def _documents_url(notice: dict[str, Any]) -> str | None:
    """Enlace de acceso a los pliegos publicado por el comprador (BT-15; BT-615
    cuando el acceso es restringido).

    Es una página de la plataforma del comprador, no el adjunto en sí: TED
    nunca publica ficheros de pliego. Solo la traen las convocatorias
    (``cn-*``) — las adjudicaciones no publican pliegos y caen al PDF del
    anuncio. Cuando hay varias (una por lote), gana el deeplink de PLACSP: es
    el único que lleva al expediente concreto en vez de al perfil del
    contratante.
    """
    candidatos: list[str] = []
    for campo in ("document-url-lot", "document-restricted-url-lot"):
        valor = notice.get(campo)
        if isinstance(valor, str):
            candidatos.append(valor)
        elif isinstance(valor, list):
            candidatos.extend(v for v in valor if isinstance(v, str))

    mejor: str | None = None
    for candidato in candidatos:
        url = _usable_url(candidato)
        if url is None:
            continue
        if "idevl=" in url.lower():
            return url
        mejor = mejor or url
    return mejor


class TedConnector:
    """Implementación del contrato Connector para la Search API v3 de TED."""

    source_id = SOURCE_ID

    def __init__(
        self,
        *,
        cpv_families: tuple[str, ...] = tuple(CPV_PREFIXES_UNIVERSO),
        country: str = "ESP",
        default_lookback_days: int = 30,
        overlap_days: int = _OVERLAP_DAYS,
        session: requests.Session | None = None,
    ) -> None:
        self.cpv_families = cpv_families
        self.country = country
        self.default_lookback_days = default_lookback_days
        self.overlap_days = overlap_days
        self._session = session or requests.Session()
        self._max_pub_date: str | None = None
        self._referencias: dict[str, ReferenciaCruzada] = {}

    # ── fetch ────────────────────────────────────────────────────────────

    def _build_query(self, since_yyyymmdd: str) -> str:
        cpv_clause = " OR ".join(f"classification-cpv IN ({fam}*)" for fam in self.cpv_families)
        return (
            f"place-of-performance IN ({self.country}) "
            f"AND publication-date >= {since_yyyymmdd} "
            f"AND ({cpv_clause})"
        )

    def _since(self, cursor: dict[str, Any] | None) -> str:
        """Fecha inicial (YYYYMMDD) de la consulta, a partir del cursor.

        Retrocede ``overlap_days`` desde el watermark en vez de arrancar en él:
        el watermark es el máximo `publication-date` visto, y lo que TED aún no
        había indexado de los días anteriores no se volvería a consultar nunca
        (ver ``_OVERLAP_DAYS``). El upsert idempotente absorbe lo re-leído.

        ``main()`` sustituye este método para el flag ``--desde``: mantener la
        firma (cursor → YYYYMMDD) es parte del contrato.
        """
        watermark = _cursor_date((cursor or {}).get("last_seen_updated"))
        if watermark is not None:
            return (watermark - timedelta(days=self.overlap_days)).strftime("%Y%m%d")
        start = datetime.now(UTC).date() - timedelta(days=self.default_lookback_days)
        return start.strftime("%Y%m%d")

    def fetch(self, cursor: dict[str, Any] | None) -> Iterator[RawNotice]:
        previo = _cursor_date((cursor or {}).get("last_seen_updated"))
        watermark = previo.isoformat() if previo else None
        query = self._build_query(self._since(cursor))
        page = 1
        total: int | None = None
        seen = 0
        # Avisos por detrás del watermark anterior: exactamente el conjunto que
        # la estrategia previa (`>= watermark`) no podía volver a consultar. Se
        # emite en `ted_fetch_done` para poder medir en producción cuánto está
        # recuperando el solapamiento en vez de tener que suponerlo.
        tras_watermark = 0
        while True:
            cuerpo = {"query": query, "fields": _FIELDS, "page": page, "limit": _PAGE_SIZE}
            resp = pedir_con_reintentos(
                partial(self._session.post, _API_URL, json=cuerpo, timeout=_TIMEOUT)
            )
            data = resp.json()
            notices = data.get("notices") or []
            if total is None:
                total = int(data.get("totalNoticeCount") or 0)
                log.info("ted_fetch_start", query=query, total=total)
            log.info("ted_fetch_page", page=page, records=len(notices), seen=seen)
            for notice in notices:
                pub_number = notice.get("publication-number")
                if not pub_number:
                    continue
                pub_date = _first_date(notice.get("publication-date"))
                if pub_date:
                    if self._max_pub_date is None or pub_date > self._max_pub_date:
                        self._max_pub_date = pub_date
                    if watermark is not None and pub_date < watermark:
                        tras_watermark += 1
                seen += 1
                yield RawNotice(natural_id=str(pub_number), payload=notice)
            if not notices or seen >= total:
                break
            page += 1
            time.sleep(_PAGE_PAUSE_S)
        log.info(
            "ted_fetch_done",
            seen=seen,
            total=total,
            watermark_previo=watermark,
            en_solapamiento=tras_watermark,
        )

    # ── parse ────────────────────────────────────────────────────────────

    def parse(self, raw: RawNotice) -> ParsedTender | None:
        n = raw.payload
        notice_type = str(n.get("notice-type") or "")
        estado = _ESTADO_MAP.get(notice_type.split("-")[0])
        if estado is None:
            return None  # tipos no relevantes (sanciones, perfiles, etc.)

        titulo = _titulo(n, raw.natural_id)
        descripcion = _first_lang(n.get("description-proc"))
        organo = _first_lang(n.get("buyer-name"))
        cpvs = n.get("classification-cpv") or []
        cpv = str(cpvs[0]) if isinstance(cpvs, list) and cpvs else None
        nuts = _nuts_provincial(n.get("place-of-performance"))
        links = n.get("links") or {}
        anuncio_url = (links.get("pdf") or {}).get("SPA") or (links.get("xml") or {}).get("MUL")
        # El enlace del comprador manda sobre el PDF del anuncio: es el que
        # lleva a los adjuntos. No se pierde nada al desplazarlo — el PDF se
        # reconstruye desde el id (ted:{pub} → ted.europa.eu/es/notice/{pub}/pdf).
        url = _documents_url(n) or anuncio_url
        # La base del importe (ADR-032, D21). En eForms el valor estimado
        # (BT-27) se publica **sin IVA** por definición, así que es `sin_iva` —
        # pero es valor estimado, no presupuesto base: va a `valor_estimado` y
        # `importe_base_sin_iva` queda vacío, para que bajas y pricing no lo
        # comparen contra lo adjudicado. Hay avisos que solo lo dan por lote
        # (99 de 1.494 avisos ESP/TI desde el 2026-07, medido el 2026-11-07):
        # el del procedimiento es la suma de los lotes.
        #
        # Sin valor estimado, el importe cae al valor de los contratos
        # adjudicados (BT-161), también sin IVA: de 1.117 avisos TED con su
        # duplicado PLACSP adjudicado, 1.021 coincidían con el adjudicado sin
        # IVA de PLACSP y 1 con él más el 21 %. Va como `sin_iva` y tampoco a
        # `importe_base_sin_iva`: lo adjudicado no es un presupuesto.
        valor_estimado = _to_float(n.get("estimated-value-proc")) or _suma(
            n.get("estimated-value-lot")
        )
        importe = valor_estimado or _to_float(n.get("result-value-notice"))
        importe_tipo = "sin_iva" if importe is not None else None
        naturalezas = n.get("contract-nature") or []
        tipo = str(naturalezas[0]) if isinstance(naturalezas, list) and naturalezas else None

        _, tech_matches = matches_technology(titulo, descripcion)
        tech_matches = etiquetas_con_senal_firme(tech_matches)
        tecnologias = sorted(tech_matches)
        keywords = sorted({kw for kws in tech_matches.values() for kw in kws})

        lic = Licitacion(
            id_externo=f"{SOURCE_ID}:{raw.natural_id}",
            titulo=titulo[:500],
            descripcion=descripcion,
            organo_contratacion=organo,
            importe=importe,
            valor_estimado=valor_estimado or None,
            importe_tipo=importe_tipo,
            cpv=cpv,
            tipo_contrato=tipo,
            estado=estado,
            fecha_publicacion=_first_date(n.get("publication-date")),
            fecha_limite=_first_date(n.get("deadline-receipt-tender-date-lot")),
            url=url,
            raw_keywords=",".join(keywords) or None,
            tecnologia=",".join(tecnologias) or None,
            nuts_code=nuts,
            ccaa=nuts_to_ccaa(nuts) if nuts else None,
            inclusion_reason="source_cpv_query",
            analysis_universe="technology_observed",
            fuente=SOURCE_ID,
        )

        adjudicaciones: list[Adjudicacion] = []
        winner = _first_lang(n.get("winner-name"))
        if winner and estado == "RES":
            adjudicaciones.append(
                Adjudicacion(
                    licitacion_id=lic.id_externo,
                    nombre=winner,
                    importe_adjudicado=_to_float(n.get("result-value-notice")),
                    fecha_adjudicacion=lic.fecha_publicacion,
                    nuts_code=nuts,
                    ccaa=lic.ccaa,
                )
            )

        referencia = ReferenciaCruzada(
            expediente=_expediente(n), id_evl=_id_evl(n), procedimiento=_procedimiento(n)
        )
        if not referencia.vacia:
            self._referencias[lic.id_externo] = referencia
        return ParsedTender(licitacion=lic, adjudicaciones=adjudicaciones)

    # ── dedupe ───────────────────────────────────────────────────────────

    def referencias_cruzadas(self) -> dict[str, ReferenciaCruzada]:
        """BT-22 e ``idEvl`` de cada aviso parseado en esta pasada, por ``id_externo``.

        No son columnas de ``licitaciones``: solo existen mientras el aviso está
        en memoria, y por eso las recoge el conector y no una consulta. Las
        consume ``scraper.connectors.base._post_ingestion``.
        """
        return dict(self._referencias)

    # ── documentos ───────────────────────────────────────────────────────

    def reemparejar_vigentes(self, *, limite: int = 300) -> DedupeResult:
        """Empareja las convocatorias vigentes sin pareja que esta pasada no releyó.

        Su BT-22, su BT-04 y su ``idEvl`` solo viven en el aviso, así que se le
        piden de nuevo a la API (una petición por cada ``_PAGE_SIZE``). Es lo que
        empareja una convocatoria cuyo expediente llega pasada su ventana de 14
        días (las agregadas entraron el 2026-11-04) o que una regla nueva ya
        reconoce. Las que releyó esta pasada ya se evaluaron en el cierre del lote.
        """
        from db.repositories import dedupe as dedupe_repo
        from scraper.documentos_plataforma import numero_publicacion_ted
        from services.dedupe import detect_duplicados_por_referencia

        numeros = [
            numero
            for id_externo in dedupe_repo.ted_vigentes_sin_pareja(limit=limite)
            if id_externo not in self._referencias
            and (numero := numero_publicacion_ted(id_externo)) is not None
        ]
        referencias: dict[str, ReferenciaCruzada] = {}
        for inicio in range(0, len(numeros), _PAGE_SIZE):
            lote = numeros[inicio : inicio + _PAGE_SIZE]
            cuerpo = {
                "query": f"publication-number IN ({' '.join(lote)})",
                "fields": _FIELDS_REFERENCIAS,
                "limit": len(lote),
            }
            resp = pedir_con_reintentos(
                partial(self._session.post, _API_URL, json=cuerpo, timeout=_TIMEOUT)
            )
            for notice in resp.json().get("notices") or []:
                referencia = ReferenciaCruzada(
                    expediente=_expediente(notice),
                    id_evl=_id_evl(notice),
                    procedimiento=_procedimiento(notice),
                )
                if notice.get("publication-number") and not referencia.vacia:
                    referencias[f"{SOURCE_ID}:{notice['publication-number']}"] = referencia
            time.sleep(_PAGE_PAUSE_S)
        return detect_duplicados_por_referencia(fuente=SOURCE_ID, referencias=referencias)

    def completar_documentos(self) -> None:
        """Tras la ingesta y el dedupe: pliegos para los avisos que no los tienen.

        Tres pasos, en este orden y cada uno fail-open:

        1. Re-emparejar por ``idEvl`` los avisos antiguos que siguen sin pareja
           (``services.dedupe.reemparejar_ted_por_id_evl``): emparejados, su
           ficha lee los pliegos del expediente de PLACSP.
        2. Re-emparejar las convocatorias vigentes que siguen sin pareja con las
           referencias que se releen de su aviso (:meth:`reemparejar_vigentes`):
           BT-22 y BT-04 casan con las agregadas y la PSCP, que ``idEvl`` no ve.
        3. Dar el PDF del anuncio como documento a las convocatorias vigentes
           que, aun así, se quedan sin pareja ni documentos
           (``scraper.documentos_plataforma.completar_documentos_ted``).

        Un expediente de PLACSP que la puerta del ATOM descartaría lo ingiere
        entero el propio conector de PLACSP si un aviso TED lo espera
        (``scraper.connectors.placsp.EsperadasPorTed``); el paso 1 lo empareja.
        """
        from scraper.documentos_plataforma import completar_documentos_ted
        from services.dedupe import reemparejar_ted_por_id_evl

        try:
            reemparejo = reemparejar_ted_por_id_evl()
            log.info("ted_reemparejo_id_evl", **reemparejo.as_dict())
        except Exception as e:
            log.warning("ted_reemparejo_id_evl_failed", error=str(e))
        try:
            vigentes = self.reemparejar_vigentes()
            log.info("ted_reemparejo_vigentes", **vigentes.as_dict())
        except Exception as e:
            log.warning("ted_reemparejo_vigentes_failed", error=str(e))
        try:
            resumen = completar_documentos_ted()
            log.info("ted_documentos_completados", **resumen.as_dict())
        except Exception as e:
            log.warning("ted_documentos_completados_failed", error=str(e))

    # ── cursor ───────────────────────────────────────────────────────────

    def new_cursor(self) -> dict[str, Any] | None:
        if self._max_pub_date is None:
            return None
        return {"last_seen_updated": self._max_pub_date}


def ejecutar(
    *, cpv_families: tuple[str, ...] = tuple(CPV_PREFIXES_UNIVERSO), desde: str | None = None
) -> ConnectorRunResult:
    """Una pasada incremental de TED.

    La usan ``main`` y el carril diario del worker
    (``scheduler/jobs/daily_atom.py``). No abre ni cierra la BD: el worker
    comparte el pool con la cola, y ``close_pool()`` se la llevaría por delante.
    """
    from scraper.connectors.base import run_connector

    connector = TedConnector(cpv_families=cpv_families)
    if desde:
        connector._since = lambda cursor: desde  # type: ignore[method-assign]  # --desde sustituye _since por contrato (ver su docstring)
    return run_connector(connector)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Ingesta TED (Search API v3)")
    parser.add_argument("--desde", help="Fecha inicial YYYYMMDD (ignora el cursor)")
    parser.add_argument(
        "--cpv",
        default=",".join(CPV_PREFIXES_UNIVERSO),
        help="Familias CPV separadas por coma (un backfill de una familia nueva: --cpv 32)",
    )
    args = parser.parse_args(argv)

    from db.database import close_pool, init_db

    init_db()
    try:
        result = ejecutar(cpv_families=tuple(args.cpv.split(",")), desde=args.desde)
    finally:
        close_pool()
    # El resumen de la pasada ya lo deja `run_connector` en el log
    # (`connector_run_done`, con las mismas cifras).
    return 0 if result.errores == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
