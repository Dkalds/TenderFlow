"""Conectores PLACSP sobre el contrato Connector (ADR-009, F2).

Dos conectores independientes que comparten _PlacspParseCore:

- PlacspAtomConnector  : feed ATOM en vivo (incremental por cursor etag/updated)
- PlacspBulkConnector  : descarga ZIPs mensuales (paramétrico por mes, cursor=None)

``id_externo = placsp:<órgano>:<ContractFolderID>`` (RFC
``2026-10-24-rfc-identidad-placsp-organo-expediente``, fase B; ADR-038): el
número de expediente lo teclea cada órgano y se repite entre órganos, así que
la clave lo acota con el ``ID_PLATAFORMA`` del órgano (respaldo ``NIF`` y
``DIR3``). El prefijo es de la familia, no del carril: el feed vivo y el ZIP
escriben la **misma** fila, y ``fuente = "placsp"`` o ``"bulk_YYYYMM"`` dice
cuál la refrescó por última vez (misma convención que pipeline.py). Una entrada
sin órgano se descarta y se cuenta (``placsp_sin_identificador_de_organo``).
Hasta la fase B la clave era el ``ContractFolderID`` sin prefijo y dos órganos
con el mismo número se pisaban; ``v164_identidad_placsp_rekey`` llevó las filas
escritas a la clave nueva.

Ver docs/rfc/2026-06-30-rfc-retrofit-pipeline-placsp-connector.md.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from db.upsert import Adjudicacion, DocumentoReferencia, Licitacion, Lote
from observability import get_logger
from scraper.connectors.base import ParsedTender, RawNotice

if TYPE_CHECKING:
    from collections.abc import Iterator

log = get_logger(__name__)

SOURCE_ID = "placsp"


# ── Núcleo de parseo compartido ───────────────────────────────────────────────


class _PlacspParseCore:
    """Parseo CODICE/UBL y fallback ML — compartido por Atom y Bulk.

    No tiene estado de cursor propio. Solo transforma un ``entry`` lxml en
    un ``ParsedTender`` (o None si no es relevante).

    El fallback ML (``_ml_classify_entry``) vive aquí; el contrato de
    ``parse()`` no cambia si el ML no está disponible.

    También guarda, de las entries que descarta, los pliegos que espera algún
    aviso TED sin pareja (``rescate``; ver
    ``scraper.documentos_plataforma.RescatePliegosPlacsp``). El conector los
    persiste tras la ingesta con ``completar_documentos``.

    La clave acotada por órgano se pone aquí, antes de copiar el id a las
    hijas (``scraper.codice_parser.acotar_por_organo``). ``prefijo`` y
    ``esquemas`` cambian para agregadas (``placsp_agregadas``, ``ID_OC_PLAT``).
    """

    def __init__(
        self,
        *,
        prefijo: str = SOURCE_ID,
        esquemas: tuple[str, ...] | None = None,
    ) -> None:
        from scraper.codice_parser import ESQUEMAS_ORGANO_PLACSP
        from scraper.documentos_plataforma import RescatePliegosPlacsp

        self.rescate = RescatePliegosPlacsp()
        self.prefijo = prefijo
        self.esquemas = esquemas or ESQUEMAS_ORGANO_PLACSP
        #: Descartes por falta de órgano y claves hechas con un esquema de
        #: respaldo; el conector los expone en ``contadores_de_descarte``.
        self.contadores: Counter[str] = Counter()

    def contadores_de_descarte(self) -> dict[str, int]:
        """``<prefijo>_sin_identificador_de_organo`` y ``<prefijo>_organo_por_respaldo_<esquema>``."""
        return {
            f"{self.prefijo}_sin_identificador_de_organo": self.contadores["sin_organo"],
            **{
                f"{self.prefijo}_organo_por_respaldo_{esquema.lower()}": self.contadores[esquema]
                for esquema in self.esquemas[1:]
            },
        }

    def _rescatar_pliegos(self, entry_elem: Any) -> None:
        """Ofrece al rescate los pliegos de una entry descartada. Nunca lanza.

        El rescate no puede interferir con el parseo: una entry descartada sigue
        descartada pase lo que pase aquí.
        """
        try:
            from scraper.codice_parser import NS, parse_document_references

            enlaces = entry_elem.xpath("./atom:link/@href", namespaces=NS)
            url = str(enlaces[0]) if enlaces else None
            if not self.rescate.espera(url):
                return
            fechas = entry_elem.xpath("./atom:updated/text()", namespaces=NS)
            actualizado = str(fechas[0]).strip() if fechas else None
            self.rescate.considerar(url, parse_document_references(entry_elem), actualizado)
        except Exception as exc:
            log.debug("placsp_rescate_entry_failed", error=str(exc))

    def parse_entry_elem(
        self,
        entry_elem: Any,
        *,
        fuente: str,
        updated_str: str | None = None,
    ) -> ParsedTender | None:
        """Parsea un elemento lxml ``<entry>`` ATOM.

        Retorna un ``ParsedTender`` si la entry es relevante, o ``None`` para
        descartarla. El descarte puede ser por filtro de keywords (camino
        directo) o por el clasificador ML (si el modelo no supera el umbral).
        """
        from scraper.codice_parser import (
            acotar_por_organo,
            parse_adjudicaciones,
            parse_document_references,
            parse_entry,
            parse_lotes,
        )
        from scraper.lineage import current_filter_version
        from scraper.pipeline import INCLUSION_KEYWORD, INCLUSION_ML_RESCUE, _ml_classify_entry

        try:
            lic: Licitacion | None = parse_entry(entry_elem)
            inclusion_reason = INCLUSION_KEYWORD
            if lic is None:
                # Entradas TI (CPV 48/72) sin keywords: el fallback decide si
                # el modelo las rescata o si quedan como universo CPV.
                lic = _ml_classify_entry(entry_elem)
                if lic is not None:
                    inclusion_reason = lic.inclusion_reason or INCLUSION_ML_RESCUE
            if lic is None:
                self._rescatar_pliegos(entry_elem)
                return None
            # La clave va antes de parsear adjudicaciones y lotes, que heredan el id.
            organo = acotar_por_organo(
                lic, entry_elem, prefijo=self.prefijo, esquemas=self.esquemas
            )
            if organo is None:
                self.contadores["sin_organo"] += 1
                log.warning(
                    "placsp_sin_identificador_de_organo",
                    prefijo=self.prefijo,
                    expediente=lic.id_externo,
                    organo=lic.organo_contratacion,
                )
                return None
            if organo.esquema != self.esquemas[0]:
                self.contadores[organo.esquema] += 1
            lic.filter_version = current_filter_version()
            lic.inclusion_reason = inclusion_reason
            lic.analysis_universe = "technology_observed"

            # Anotar fecha_actualizacion_fuente desde el <updated> del feed
            if updated_str:
                lic.fecha_actualizacion_fuente = updated_str

            # La fuente se sobreescribe para que coincida con el conector
            lic.fuente = fuente

            adjs: list[Adjudicacion] = parse_adjudicaciones(entry_elem, lic.id_externo)
            docs: list[DocumentoReferencia] = parse_document_references(entry_elem)
            lotes: list[Lote] = parse_lotes(
                entry_elem, lic.id_externo, fallback_fecha_limite=lic.fecha_limite
            )
            return ParsedTender(licitacion=lic, adjudicaciones=adjs, documentos=docs, lotes=lotes)

        except Exception as exc:
            log.debug("placsp_parse_entry_failed", error=str(exc))
            raise  # el caller (run_connector) lo envía a DLQ


# ── Conector ATOM live ────────────────────────────────────────────────────────


class PlacspAtomConnector:
    """Conector incremental sobre el feed ATOM en vivo de PLACE.

    Implementa el contrato ``Connector`` (ADR-009).

    ``source_id = "placsp"`` — mismo que usaba el pipeline legacy para el
    cursor diario. El runner genérico (``run_connector``) avanza el cursor
    con ``new_cursor()`` solo si la ejecución termina sin error fatal.
    """

    source_id: str = SOURCE_ID

    def __init__(self) -> None:
        self._meta: dict[str, Any] = {}
        self._last_seen_updated: str | None = None
        self._core = _PlacspParseCore()

    def fetch(self, cursor: dict[str, Any] | None) -> Iterator[RawNotice]:
        """Pagina el feed ATOM y emite entries como ``RawNotice``.

        El ``payload`` de cada ``RawNotice`` es una tupla
        ``(entry_lxml_elem, updated_str)`` para que ``parse`` pueda
        anotar ``fecha_actualizacion_fuente``.
        """
        from scraper.atom_live import iter_live_entries

        if not cursor:
            # Migración one-time post-flip (F2): el pipeline legacy avanzaba el
            # cursor bajo la clave "place_live_atom"; el conector usa "placsp".
            # Sin este fallback, el primer run tras activar el flag re-paginaría
            # el feed completo (DAILY_MAX_PAGES). Tras el primer run exitoso,
            # new_cursor() escribe "placsp" y este camino queda muerto.
            from db.database import get_cursor

            cursor = get_cursor("place_live_atom")

        last_seen_updated: str | None = None
        etag: str | None = None
        last_modified: str | None = None
        if cursor:
            last_seen_updated = cursor.get("last_seen_updated")
            etag = cursor.get("etag")
            last_modified = cursor.get("last_modified")

        self._last_seen_updated = last_seen_updated

        entries, meta = iter_live_entries(
            last_seen_updated=last_seen_updated,
        )
        self._meta = meta

        # Propagar etag/last_modified del cursor anterior si la respuesta fue 304
        if meta.get("etag") is None and etag:
            self._meta["etag"] = etag
        if meta.get("last_modified") is None and last_modified:
            self._meta["last_modified"] = last_modified

        for entry_elem, updated_str in entries:
            yield RawNotice(
                natural_id=updated_str or "unknown",
                payload=(entry_elem, updated_str),
            )

    def parse(self, raw: RawNotice) -> ParsedTender | None:
        entry_elem, updated_str = raw.payload
        return self._core.parse_entry_elem(
            entry_elem,
            fuente=SOURCE_ID,
            updated_str=updated_str or None,
        )

    def completar_documentos(self) -> None:
        """Persiste los pliegos rescatados de entries descartadas (ver ``_PlacspParseCore``)."""
        self._core.rescate.persistir()

    def contadores_de_descarte(self) -> dict[str, int]:
        """Entradas sin órgano y claves por esquema de respaldo (ver ``_PlacspParseCore``)."""
        return self._core.contadores_de_descarte()

    def new_cursor(self) -> dict[str, Any] | None:
        """Cursor con el timestamp más nuevo visto + etag/last_modified."""
        newest = self._meta.get("newest_updated") or self._last_seen_updated
        if newest is None and not self._meta.get("etag"):
            return None
        return {
            "last_seen_updated": newest,
            "etag": self._meta.get("etag"),
            "last_modified": self._meta.get("last_modified"),
        }


# ── Conector Bulk mensual ─────────────────────────────────────────────────────


class PlacspBulkConnector:
    """Conector para descarga de ZIPs mensuales de PLACE.

    Implementa el contrato ``Connector`` (ADR-009) en modo "no-cursor":
    ``new_cursor()`` devuelve ``None`` porque el bulk es idempotente por diseño
    (el upsert absorbe re-ejecuciones) y la parametrización es por mes, no por
    cursor incremental.

    Args:
        year: Año del mes a descargar.
        month: Mes (1-12) a descargar.
        force: Si True, re-descarga aunque el ZIP ya esté cacheado.
        solo_cpv: Prefijos CPV; si se dan, solo se parsean las entries con algún
            CPV del proyecto que empiece por uno de ellos. Es para el backfill
            de una familia que acaba de entrar en el universo (la 32, el
            2026-10-30): reingerir el mes entero pasa de dos horas y vuelve a
            escribir lo que ya estaba. Lo que pasa el filtro sigue la regla de
            siempre, así que no entra nada que la ingesta viva no admitiría.
        sin_pisar_posteriores: Salta los expedientes que ya escribió un mes
            posterior o el feed vivo. Es para traer meses anteriores a lo ya
            ingerido (2024 después de la reingesta de 2025-2026): sin esto el
            ZIP viejo, que no trae ``<updated>`` por aviso, devolvería cada
            expediente que reaparece después a su versión vieja. No sirve para
            una reingesta que quiere reescribirlo todo, que va en orden
            ascendente y sin esta opción.
    """

    def __init__(
        self,
        year: int,
        month: int,
        *,
        force: bool = False,
        solo_cpv: tuple[str, ...] = (),
        sin_pisar_posteriores: bool = False,
    ) -> None:
        if not (1 <= month <= 12):
            raise ValueError(f"month must be 1-12, got {month}")
        if year < 2000:
            raise ValueError(f"year must be >= 2000, got {year}")
        self.year = year
        self.month = month
        self.force = force
        self.solo_cpv = solo_cpv
        self.sin_pisar_posteriores = sin_pisar_posteriores
        self._posteriores: frozenset[str] | None = None
        self.saltadas_por_posteriores = 0
        self._core = _PlacspParseCore()

    @property
    def source_id(self) -> str:
        return f"bulk_{self.year}{self.month:02d}"

    def fetch(self, cursor: dict[str, Any] | None) -> Iterator[RawNotice]:
        """Descarga el ZIP y emite entries XML como ``RawNotice``.

        El cursor se ignora (el bulk es paramétrico, no incremental).
        El anti ZIP-bomb de ``iter_xml_files`` permanece intacto.
        """
        from scraper.bulk_downloader import download_month, iter_xml_files

        zip_path = download_month(self.year, self.month, force=self.force)
        if zip_path is None:
            log.info(
                "placsp_bulk_not_published",
                year=self.year,
                month=self.month,
            )
            return

        for filename, content in iter_xml_files(zip_path):
            log.debug("placsp_bulk_xml_start", filename=filename)
            try:
                for entry_elem, _ in _iter_atom_entries(content):
                    yield RawNotice(
                        natural_id=filename,
                        payload=(entry_elem, None),
                    )
            except Exception as exc:
                log.warning(
                    "placsp_bulk_xml_parse_error",
                    filename=filename,
                    error=str(exc),
                )
                raise

    def parse(self, raw: RawNotice) -> ParsedTender | None:
        entry_elem, updated_str = raw.payload
        if self.solo_cpv:
            from scraper.codice_parser import cpvs_del_proyecto

            if not any(c.startswith(self.solo_cpv) for c in cpvs_del_proyecto(entry_elem)):
                return None
        if self.sin_pisar_posteriores and self._escrita_despues(entry_elem):
            return None
        fuente = self.source_id
        return self._core.parse_entry_elem(
            entry_elem,
            fuente=fuente,
            updated_str=updated_str,
        )

    def _escrita_despues(self, entry_elem: Any) -> bool:
        """¿Un mes posterior o el feed vivo ya escribió este expediente?"""
        from db.repositories.identidad import ids_placsp_posteriores_a
        from scraper.codice_parser import clave_de_entry

        if self._posteriores is None:
            self._posteriores = ids_placsp_posteriores_a(self.source_id)
        if clave_de_entry(entry_elem) not in self._posteriores:
            return False
        self.saltadas_por_posteriores += 1
        return True

    def completar_documentos(self) -> None:
        """Persiste los pliegos rescatados de entries descartadas (ver ``_PlacspParseCore``)."""
        self._core.rescate.persistir()

    def contadores_de_descarte(self) -> dict[str, int]:
        """Entradas sin órgano, claves por esquema de respaldo y las saltadas por posteriores."""
        contadores = self._core.contadores_de_descarte()
        if self.sin_pisar_posteriores:
            contadores["placsp_bulk_saltada_por_posterior"] = self.saltadas_por_posteriores
        return contadores

    def new_cursor(self) -> dict[str, Any] | None:
        """Bulk no avanza cursor — la parametrización es por mes."""
        return None


# ── Helpers internos ──────────────────────────────────────────────────────────


def _iter_atom_entries(content: bytes) -> Iterator[tuple[Any, None]]:
    """Parsea un XML ATOM y emite sus ``<entry>`` como elementos lxml.

    Replica el comportamiento de ``parse_atom_bytes`` pero emitiendo
    elementos crudos (no Licitacion) para que el Connector haga el parse.
    """
    from lxml import etree

    ATOM_NS = "http://www.w3.org/2005/Atom"
    parser = etree.XMLParser(huge_tree=False, recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(content, parser=parser)
    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        yield entry, None
