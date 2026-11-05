"""Reproceso dirigido: los expedientes de PLACSP que esperan los avisos TED sin pareja.

Uso::

  python -m scraper.reproceso_ted --desde 2026-09 --hasta 2026-10            # cuenta
  python -m scraper.reproceso_ted --desde 2026-09 --hasta 2026-10 --aplicar  # escribe

Desde el 2026-11-04 el conector de PLACSP ingiere entera la entry que la puerta
tecnológica descartaría si un aviso TED enlaza su ``idEvl``
(``scraper.connectors.placsp.EsperadasPorTed``). Eso solo alcanza a lo que el
ATOM publica a partir de ese día: los avisos TED anteriores cuyo expediente
PLACSP ya no vuelve a publicar se quedaban sin él. Este reproceso los busca en
los ZIP mensuales.

De cada ZIP solo se parsean las entries cuyo ``idEvl`` enlaza un aviso TED sin
pareja (``db.repositories.dedupe.ted_sin_pareja_con_id_evl``), y se escriben
con el mismo camino que el bulk (``run_connector``: licitación, lotes,
adjudicaciones, documentos y el cierre del lote). Tras el último mes,
``reemparejar_ted_por_id_evl`` las hace canónicas.

**Nunca pisa una fila que ya existe.** El ZIP mensual no trae ``<updated>``, así
que su versión puede ser más vieja que la que ya trajo el ATOM; por eso una
entry cuyo expediente ya está en la BD se salta. Los meses se recorren del más
nuevo al más viejo: la primera versión que se escribe es la más reciente, y los
meses anteriores la encuentran ya escrita. Repetir el reproceso no cambia nada.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from observability import configure_logging, get_logger
from scraper.connectors.placsp import PlacspBulkConnector
from scraper.reproceso_lotes import meses_entre

if TYPE_CHECKING:
    from collections.abc import Callable

    from scraper.connectors.base import ParsedTender, RawNotice

log = get_logger(__name__)


def id_evls_esperados() -> frozenset[str]:
    """``idEvl`` de los avisos TED que siguen sin pareja."""
    from db.repositories import dedupe as dedupe_repo
    from services.dedupe import id_evl_de_url

    return frozenset(
        evl
        for fila in dedupe_repo.ted_sin_pareja_con_id_evl()
        if (evl := id_evl_de_url(fila.get("url"))) is not None
    )


def _ya_existe(id_externo: str) -> bool:
    from db.repositories import dedupe as dedupe_repo

    return bool(dedupe_repo.filas_por_id([id_externo]))


class BulkEsperadasPorTed(PlacspBulkConnector):
    """El ZIP de un mes, reducido a las entries que espera un aviso TED sin pareja."""

    def __init__(
        self,
        year: int,
        month: int,
        objetivo: frozenset[str],
        *,
        ya_existe: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__(year, month)
        self._objetivo = objetivo
        self._ya_existe = ya_existe or _ya_existe
        self.candidatas = 0
        self.ya_existian = 0
        self.escribibles = 0

    def parse(self, raw: RawNotice) -> ParsedTender | None:
        from scraper.codice_parser import NS
        from services.dedupe import id_evl_de_url

        entry, _ = raw.payload
        enlaces = entry.xpath("./atom:link/@href", namespaces=NS)
        if id_evl_de_url(str(enlaces[0]) if enlaces else None) not in self._objetivo:
            return None
        self.candidatas += 1
        parsed = super().parse(raw)
        if parsed is None:
            return None
        if self._ya_existe(parsed.licitacion.id_externo):
            self.ya_existian += 1
            return None
        self.escribibles += 1
        return parsed

    def contadores_de_descarte(self) -> dict[str, int]:
        return {
            "reproceso_ted_candidatas": self.candidatas,
            "reproceso_ted_ya_existian": self.ya_existian,
            **super().contadores_de_descarte(),
        }


@dataclass
class ResumenReprocesoTed:
    objetivo: int = 0
    meses: int = 0
    candidatas: int = 0
    ya_existian: int = 0
    escribibles: int = 0
    nuevas: int = 0
    emparejadas: int = 0


def reprocesar(desde: str, hasta: str, *, aplicar: bool) -> ResumenReprocesoTed:
    """Recorre el rango, del mes más nuevo al más viejo; con ``aplicar`` escribe."""
    from scraper.connectors.base import run_connector

    objetivo = id_evls_esperados()
    resumen = ResumenReprocesoTed(objetivo=len(objetivo))
    log.info("reproceso_ted_inicio", desde=desde, hasta=hasta, objetivo=len(objetivo))
    if not objetivo:
        return resumen

    for year, month in reversed(meses_entre(desde, hasta)):
        conector = BulkEsperadasPorTed(year, month, objetivo)
        if aplicar:
            resultado = run_connector(conector)
            resumen.nuevas += resultado.nuevas
        else:
            for raw in conector.fetch(None):
                conector.parse(raw)
        resumen.meses += 1
        resumen.candidatas += conector.candidatas
        resumen.ya_existian += conector.ya_existian
        resumen.escribibles += conector.escribibles
        log.info(
            "reproceso_ted_mes",
            year=year,
            month=month,
            candidatas=conector.candidatas,
            ya_existian=conector.ya_existian,
            escribibles=conector.escribibles,
            aplicar=aplicar,
        )

    if aplicar and resumen.escribibles:
        from services.dedupe import reemparejar_ted_por_id_evl

        resumen.emparejadas = reemparejar_ted_por_id_evl().confirmados
    return resumen


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    p.add_argument("--desde", required=True, help="Primer mes, YYYY-MM")
    p.add_argument("--hasta", required=True, help="Último mes, YYYY-MM (incluido)")
    p.add_argument("--aplicar", action="store_true", help="Escribir en la BD (sin él solo cuenta)")
    args = p.parse_args(argv)
    configure_logging()
    resumen = reprocesar(args.desde, args.hasta, aplicar=args.aplicar)
    log.info("reproceso_ted_fin", aplicar=args.aplicar, **vars(resumen))
    return 0


if __name__ == "__main__":
    sys.exit(main())
