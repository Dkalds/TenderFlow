"""RSS oficial de la Plataforma de Contratos Públicos de Galicia.

Cobertura: publicaciones recientes del RSS, no histórico completo ni cambios
posteriores de una licitación. El runner registra frescura por ``galicia_rss``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scraper.connectors.regional_rss import RegionalRssConnector

if TYPE_CHECKING:
    from scraper.connectors.base import ConnectorRunResult


class GaliciaRssConnector(RegionalRssConnector):
    source_id = "galicia_rss"
    feed_url = "https://www.contratosdegalicia.gal/rss/ultimas-publicacions.rss"
    ccaa = "Galicia"
    analysis_universe = "galicia_rss_recent_technology_observed"


def ejecutar(*, feed_url: str | None = None) -> ConnectorRunResult:
    """Una pasada incremental del RSS de Galicia.

    La usan ``main`` y el carril diario del worker
    (``scheduler/jobs/daily_atom.py``). No abre ni cierra la BD: el worker
    comparte el pool con la cola, y ``close_pool()`` se la llevaría por delante.
    """
    from scraper.connectors.base import run_connector

    return run_connector(GaliciaRssConnector(feed_url=feed_url))


def main(argv: list[str] | None = None) -> int:
    """Ejecuta la ingesta incremental del RSS oficial de Galicia."""
    import argparse

    parser = argparse.ArgumentParser(description="Ingesta RSS de contratacion de Galicia")
    parser.add_argument("--url", help="URL RSS alternativa para diagnostico o backfill")
    args = parser.parse_args(argv)

    from db.database import close_pool, init_db

    init_db()
    try:
        result = ejecutar(feed_url=args.url)
    finally:
        close_pool()
    print(
        f"Galicia RSS: {result.fetched} avisos · {result.nuevas} nuevas · "
        f"{result.actualizadas} actualizadas · {result.descartadas} descartadas · "
        f"{result.errores} errores"
    )
    return 0 if result.errores == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
