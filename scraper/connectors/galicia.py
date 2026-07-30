"""RSS oficial de la Plataforma de Contratos Públicos de Galicia.

Cobertura: publicaciones recientes del RSS, no histórico completo ni cambios
posteriores de una licitación. El runner registra frescura por ``galicia_rss``.
"""

from scraper.connectors.regional_rss import RegionalRssConnector


class GaliciaRssConnector(RegionalRssConnector):
    source_id = "galicia_rss"
    feed_url = "https://www.contratosdegalicia.gal/rss/ultimas-publicacions.rss"
    ccaa = "Galicia"
    analysis_universe = "galicia_rss_recent_technology_observed"


def main(argv: list[str] | None = None) -> int:
    """Ejecuta la ingesta incremental del RSS oficial de Galicia."""
    import argparse

    parser = argparse.ArgumentParser(description="Ingesta RSS de contratacion de Galicia")
    parser.add_argument("--url", help="URL RSS alternativa para diagnostico o backfill")
    args = parser.parse_args(argv)

    from db.database import init_db
    from scraper.connectors.base import run_connector

    init_db()
    result = run_connector(GaliciaRssConnector(feed_url=args.url))
    print(
        f"Galicia RSS: {result.fetched} avisos · {result.nuevas} nuevas · "
        f"{result.actualizadas} actualizadas · {result.descartadas} descartadas · "
        f"{result.errores} errores"
    )
    return 0 if result.errores == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
