"""Ingesta prospectiva de adjudicaciones PLACSP para empresas vigiladas.

Este carril no aplica el filtro tecnológico del radar. Recorre el feed ATOM
oficial y conserva únicamente expedientes cuya adjudicación incluya uno de los
NIF canónicos vigilados. Su namespace evita que una observación de empresa
sobrescriba la misma licitación ya persistida por el radar de tecnología.

No es una búsqueda por NIF en PLACSP ni pretende cubrir el histórico completo:
la cobertura empieza cuando se ejecuta el conector y se limita a las entradas
que todavía estén disponibles desde su cursor en el feed.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from observability import get_logger
from scraper.connectors.base import ParsedTender, RawNotice
from services.normalization import normalize_nif

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

log = get_logger(__name__)

SOURCE_ID = "placsp_watched_company_awards"
ANALYSIS_UNIVERSE = "watched_company_awards_observed"
INCLUSION_REASON = "watched_company_award_nif_match"


class PlacspWatchedCompanyAwardsConnector:
    """Conector incremental ATOM de adjudicaciones para NIF vigilados."""

    def __init__(self, watched_nifs: Iterable[str]) -> None:
        self._source_id = SOURCE_ID
        self._watched_nifs = frozenset(
            normalized for nif in watched_nifs if (normalized := normalize_nif(nif)) is not None
        )
        self._meta: dict[str, Any] = {}
        self._last_seen_updated: str | None = None

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def watched_nif_count(self) -> int:
        """Número de NIF distintos que delimitan la ingesta de esta ejecución."""
        return len(self._watched_nifs)

    def fetch(self, cursor: dict[str, Any] | None) -> Iterator[RawNotice]:
        """Emite entradas nuevas del ATOM, sin descargar nada si no hay NIFs."""
        if not self._watched_nifs:
            log.info("watched_company_awards_no_watched_nifs")
            return

        from scraper.atom_live import iter_live_entries

        last_seen_updated = str((cursor or {}).get("last_seen_updated") or "") or None
        self._last_seen_updated = last_seen_updated
        entries, self._meta = iter_live_entries(last_seen_updated=last_seen_updated)
        for entry_elem, updated_str in entries:
            yield RawNotice(
                natural_id=updated_str or "unknown",
                payload=(entry_elem, updated_str),
            )

    def parse(self, raw: RawNotice) -> ParsedTender | None:
        """Persiste solo si alguna adjudicación coincide por NIF normalizado."""
        from scraper.codice_parser import parse_adjudicaciones, parse_entry_unfiltered

        entry_elem, updated_str = raw.payload
        lic = parse_entry_unfiltered(entry_elem)
        if lic is None:
            return None

        adjudicaciones = parse_adjudicaciones(entry_elem, lic.id_externo)
        if not any(normalize_nif(adj.nif) in self._watched_nifs for adj in adjudicaciones):
            return None

        original_id = lic.id_externo
        persisted_id = f"{self.source_id}:{original_id}"
        lic.id_externo = persisted_id
        lic.fuente = self.source_id
        lic.analysis_universe = ANALYSIS_UNIVERSE
        lic.inclusion_reason = INCLUSION_REASON
        if updated_str:
            lic.fecha_actualizacion_fuente = updated_str

        persisted_awards = [
            replace(adjudicacion, licitacion_id=persisted_id) for adjudicacion in adjudicaciones
        ]
        return ParsedTender(licitacion=lic, adjudicaciones=persisted_awards)

    def new_cursor(self) -> dict[str, Any] | None:
        """Cursor propio de este carril, separado del radar tecnológico."""
        newest = self._meta.get("newest_updated") or self._last_seen_updated
        if newest is None and not self._meta.get("etag"):
            return None
        return {
            "last_seen_updated": newest,
            "etag": self._meta.get("etag"),
            "last_modified": self._meta.get("last_modified"),
        }


class PlacspWatchedCompanyAwardsBulkConnector(PlacspWatchedCompanyAwardsConnector):
    """Backfill manual de un mes PLACSP para los NIF vigilados actuales.

    No guarda cursor porque el mes es un parámetro explícito y el runner es
    idempotente. Es una ayuda operacional, no una declaración de cobertura
    histórica completa.
    """

    def __init__(
        self,
        year: int,
        month: int,
        watched_nifs: Iterable[str],
        *,
        force: bool = False,
    ) -> None:
        if not 1 <= month <= 12:
            raise ValueError(f"month must be 1-12, got {month}")
        if year < 2000:
            raise ValueError(f"year must be >= 2000, got {year}")
        super().__init__(watched_nifs)
        self.year = year
        self.month = month
        self.force = force
        self._source_id = f"{SOURCE_ID}_bulk_{year}{month:02d}"

    def fetch(self, cursor: dict[str, Any] | None) -> Iterator[RawNotice]:
        """Descarga el ZIP mensual solo cuando existe al menos un NIF vigilado."""
        if not self._watched_nifs:
            log.info("watched_company_awards_no_watched_nifs")
            return

        from scraper.bulk_downloader import download_month, iter_xml_files
        from scraper.connectors.placsp import _iter_atom_entries

        zip_path = download_month(self.year, self.month, force=self.force)
        if zip_path is None:
            log.info("watched_company_awards_bulk_not_published", year=self.year, month=self.month)
            return
        for _filename, content in iter_xml_files(zip_path):
            for entry_elem, _ in _iter_atom_entries(content):
                yield RawNotice(
                    natural_id=f"{self.year}{self.month:02d}", payload=(entry_elem, None)
                )

    def new_cursor(self) -> dict[str, Any] | None:
        return None


def main(argv: list[str] | None = None) -> int:
    """Ejecuta la fuente incremental o un backfill mensual manual."""
    import argparse

    parser = argparse.ArgumentParser(description="Ingesta PLACSP por NIF de empresas vigiladas")
    parser.add_argument(
        "--bulk",
        nargs=2,
        type=int,
        metavar=("YEAR", "MONTH"),
        help="backfill manual de un mes; no declara cobertura histórica completa",
    )
    parser.add_argument("--force", action="store_true", help="re-descarga el ZIP mensual")
    args = parser.parse_args(argv)

    from db.database import close_pool, init_db
    from db.repositories.watched_companies import WatchedCompanyRepository
    from scraper.connectors.base import run_connector

    init_db()
    watched_nifs = WatchedCompanyRepository().list_canonical_nifs()
    if not watched_nifs:
        print("Empresas vigiladas: 0 NIF canónicos; no se descarga PLACSP.")
        return 0

    try:
        if args.bulk:
            year, month = args.bulk
            connector: PlacspWatchedCompanyAwardsConnector = (
                PlacspWatchedCompanyAwardsBulkConnector(year, month, watched_nifs, force=args.force)
            )
        else:
            connector = PlacspWatchedCompanyAwardsConnector(watched_nifs)
        result = run_connector(connector)
    finally:
        close_pool()
    print(
        f"Adjudicaciones de empresas vigiladas: {result.fetched} avisos · "
        f"{result.nuevas} nuevas · {result.actualizadas} actualizadas · "
        f"{result.adjudicaciones} adjudicaciones · {result.descartadas} descartadas · "
        f"{result.errores} errores"
    )
    return 0 if result.errores == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
