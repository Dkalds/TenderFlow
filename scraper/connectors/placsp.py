"""Conectores PLACSP sobre el contrato Connector (ADR-009, F2).

Dos conectores independientes que comparten _PlacspParseCore:

- PlacspAtomConnector  : feed ATOM en vivo (incremental por cursor etag/updated)
- PlacspBulkConnector  : descarga ZIPs mensuales (paramétrico por mes, cursor=None)

``id_externo`` **sin prefijo** para preservar paridad de datos con el pipeline
legacy (los IDs ya existen en BD sin namespace). ``fuente = "placsp"`` o
``"bulk_YYYYMM"`` según el conector (misma convención que pipeline.py).

Ver docs/rfc/2026-06-30-rfc-retrofit-pipeline-placsp-connector.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from db.upsert import Adjudicacion, Licitacion
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
    """

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
        from scraper.codice_parser import parse_adjudicaciones, parse_entry
        from scraper.pipeline import _ml_classify_entry

        try:
            lic: Licitacion | None = parse_entry(entry_elem)
            if lic is None:
                # Fallback ML para entradas TI (CPV 48/72) sin keywords
                lic = _ml_classify_entry(entry_elem)
            if lic is None:
                return None

            # Anotar fecha_actualizacion_fuente desde el <updated> del feed
            if updated_str:
                lic.fecha_actualizacion_fuente = updated_str

            # La fuente se sobreescribe para que coincida con el conector
            lic.fuente = fuente

            adjs: list[Adjudicacion] = parse_adjudicaciones(entry_elem, lic.id_externo)
            return ParsedTender(licitacion=lic, adjudicaciones=adjs)

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
    """

    def __init__(self, year: int, month: int, *, force: bool = False) -> None:
        if not (1 <= month <= 12):
            raise ValueError(f"month must be 1-12, got {month}")
        if year < 2000:
            raise ValueError(f"year must be >= 2000, got {year}")
        self.year = year
        self.month = month
        self.force = force
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
        fuente = self.source_id
        return self._core.parse_entry_elem(
            entry_elem,
            fuente=fuente,
            updated_str=updated_str,
        )

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
