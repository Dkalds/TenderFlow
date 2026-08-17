"""Conector TED — Search API v3 (contratos UE sobre umbrales armonizados).

API pública sin autenticación: ``POST https://api.ted.europa.eu/v3/notices/search``
con sintaxis de expert query. Filtra por país de ejecución España y familias
CPV configurables (por defecto 48 software y 72 servicios TI).

Mapeo eForms → modelo canónico:
- ``id_externo`` = ``ted:{publication-number}`` (namespacing ADR-009).
- Campos multilingües (notice-title, buyer-name…): preferencia spa → eng →
  primer idioma disponible.
- ``notice-type``: cn-* (convocatoria) → estado PUB; can-* (adjudicación/
  resultado) → RES, con Adjudicacion si trae winner-name; pin-* → PRE.
- ``place-of-performance``: primer código NUTS provincial → ccaa vía
  shared.geo.
- ``url``: enlace de acceso a los pliegos del comprador (BT-15/BT-615) cuando
  lleva a algún sitio concreto; si no, el PDF del anuncio en TED.

Cursor: ``last_seen_updated`` guarda el máximo ``publication-date`` visto, pero
cada run consulta desde ``watermark - _OVERLAP_DAYS``. Sin ese solapamiento, lo
que TED añada al índice con fecha anterior al watermark no se vuelve a
consultar nunca. Ver ``_OVERLAP_DAYS``.

Uso directo (backfill o cron):
    python -m scraper.connectors.ted                 # incremental desde cursor
    python -m scraper.connectors.ted --desde 20250101 --cpv 48,72
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import requests

from db.upsert import Adjudicacion, Licitacion
from observability import get_logger
from scraper.connectors.base import ParsedTender, RawNotice
from scraper.filters import matches_technology
from shared.geo import nuts_to_ccaa

if TYPE_CHECKING:
    from collections.abc import Iterator

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
    "result-value-notice",
    "winner-name",
    "place-of-performance",
    "contract-nature",
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
        cpv_families: tuple[str, ...] = ("48", "72"),
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
            resp = self._session.post(
                _API_URL,
                json={
                    "query": query,
                    "fields": _FIELDS,
                    "page": page,
                    "limit": _PAGE_SIZE,
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
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

        titulo = _first_lang(n.get("notice-title")) or f"TED {raw.natural_id}"
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
        importe = _to_float(n.get("estimated-value-proc")) or _to_float(
            n.get("result-value-notice")
        )
        naturalezas = n.get("contract-nature") or []
        tipo = str(naturalezas[0]) if isinstance(naturalezas, list) and naturalezas else None

        _, tech_matches = matches_technology(titulo, descripcion)
        tecnologias = sorted(tech_matches)
        keywords = sorted({kw for kws in tech_matches.values() for kw in kws})

        lic = Licitacion(
            id_externo=f"{SOURCE_ID}:{raw.natural_id}",
            titulo=titulo[:500],
            descripcion=descripcion,
            organo_contratacion=organo,
            importe=importe,
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
        return ParsedTender(licitacion=lic, adjudicaciones=adjudicaciones)

    # ── cursor ───────────────────────────────────────────────────────────

    def new_cursor(self) -> dict[str, Any] | None:
        if self._max_pub_date is None:
            return None
        return {"last_seen_updated": self._max_pub_date}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Ingesta TED (Search API v3)")
    parser.add_argument("--desde", help="Fecha inicial YYYYMMDD (ignora el cursor)")
    parser.add_argument("--cpv", default="48,72", help="Familias CPV separadas por coma")
    args = parser.parse_args(argv)

    from db.database import close_pool, init_db
    from scraper.connectors.base import run_connector

    init_db()
    try:
        connector = TedConnector(cpv_families=tuple(args.cpv.split(",")))
        if args.desde:
            connector._since = lambda cursor: args.desde  # type: ignore[method-assign]
        result = run_connector(connector)
    finally:
        close_pool()
    print(
        f"TED: {result.fetched} avisos · {result.nuevas} nuevas · "
        f"{result.actualizadas} actualizadas · {result.adjudicaciones} adjudicaciones · "
        f"{result.descartadas} descartadas · {result.errores} errores"
    )
    return 0 if result.errores == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
