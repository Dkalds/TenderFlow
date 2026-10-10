"""RSS oficial de anuncios de contratación de Euskadi.

La API REST de KontratazioA existe, pero su documentación no ofrece en este
momento un contrato de paginación estable para este cliente. Se usa el RSS
oficial publicado por Open Data Euskadi como descubrimiento reciente; no se
presenta como cobertura exhaustiva ni histórica.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scraper.connectors.regional_rss import RegionalRssConnector

if TYPE_CHECKING:
    from scraper.connectors.base import ConnectorRunResult


class EuskadiRssConnector(RegionalRssConnector):
    source_id = "euskadi_rss"
    feed_url = (
        "https://www.euskadi.eus/r01hSearchResultWar/r01hPresentationRSS.jsp?"
        "r01kLang=es&r01kQry=tC%3Aeuskadi%3BtT%3Aanuncio_contratacion%3B"
        "m%3AdocumentLanguage.EQ.es%3Bpp%3Ar01PageSize.100"
    )
    ccaa = "País Vasco"
    analysis_universe = "euskadi_rss_recent_technology_observed"


def ejecutar(*, feed_url: str | None = None) -> ConnectorRunResult:
    """Una pasada incremental del RSS de Euskadi.

    La usan ``main`` y el carril diario del worker
    (``scheduler/jobs/daily_atom.py``). No abre ni cierra la BD: el worker
    comparte el pool con la cola, y ``close_pool()`` se la llevaría por delante.
    """
    from scraper.connectors.base import run_connector

    return run_connector(EuskadiRssConnector(feed_url=feed_url))


def main(argv: list[str] | None = None) -> int:
    """Ejecuta la ingesta incremental del RSS oficial de Euskadi."""
    import argparse

    parser = argparse.ArgumentParser(description="Ingesta RSS de contratacion de Euskadi")
    parser.add_argument("--url", help="URL RSS alternativa para diagnostico o backfill")
    args = parser.parse_args(argv)

    from db.database import close_pool, init_db

    init_db()
    try:
        result = ejecutar(feed_url=args.url)
    finally:
        close_pool()
    print(
        f"Euskadi RSS: {result.fetched} avisos · {result.nuevas} nuevas · "
        f"{result.actualizadas} actualizadas · {result.descartadas} descartadas · "
        f"{result.errores} errores"
    )
    return 0 if result.errores == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
