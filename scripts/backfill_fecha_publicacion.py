"""One-shot backfill: corrige ``fecha_publicacion`` posterior a la adjudicación.

Detecta licitaciones cuyo ``fecha_publicacion`` quedó DESPUÉS de su primera
adjudicación —imposible, porque el hito de publicación es el primer anuncio del
expediente— y las **reprocesa desde la fuente**. Con el fix del upsert (que
conserva siempre la fecha de publicación más temprana, ver
``db/upsert.py::_earliest_iso_date``), el reproceso recomputa el anuncio
original y sana la fila sin poder empeorarla.

El bug se producía porque una fase posterior (adjudicación / formalización)
traía la fecha de publicación de SU anuncio y sobrescribía la del primer
anuncio. La fecha correcta original no está guardada en la BD (no está en los
snapshots de ``licitaciones_history``), por eso la única forma de recuperarla
es volver a leerla de la fuente.

Source-agnóstico:
- PLACSP (``fuente='placsp'``): re-ejecuta ``PlacspBulkConnector`` para los
  meses afectados (el ZIP mensual contiene la entry con todos los anuncios en
  ``ValidNoticeInfo``; ``_issue_date`` recomputa el ``IssueDate`` mínimo).
- TED (``fuente='ted'``): re-fetch por rango (``TedConnector`` con ``_since``
  forzado a la fecha más temprana afectada).
- PSCP (``fuente='pscp'``): re-fetch por rango (``PscpConnector`` idem).

Al terminar, vuelve a detectar las filas afectadas y reporta cuántas sanaron y
cuántas quedan (no recuperables porque la fuente ya no expone el anuncio
original).

Uso:
    python -m scripts.backfill_fecha_publicacion --dry-run   # solo detecta + plan
    python -m scripts.backfill_fecha_publicacion             # detecta y reprocesa
    python -m scripts.backfill_fecha_publicacion --sources placsp,ted
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from db.database import init_db
from db.repositories.adjudicaciones import AdjudicacionRepository
from observability.logging import get_logger

log = get_logger(__name__)

# Fuentes con handler de reproceso implementado.
_KNOWN_SOURCES = ("placsp", "ted", "pscp")


def find_affected(sources: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Licitaciones con ``fecha_publicacion`` posterior a su primera adjudicación.

    Devuelve una fila por licitación con ``id_externo``, ``fuente``,
    ``fecha_publicacion`` (los 10 primeros chars, ISO) y ``min_adj`` (la
    adjudicación más temprana, ISO). Source-agnóstico: cubre cualquier fuente
    con adjudicaciones fechadas.
    """
    rows = AdjudicacionRepository().find_publicacion_posterior_a_adjudicacion(fuentes=sources)
    return [
        {
            "id_externo": r["id_externo"],
            "fuente": (r["fuente"] or "").lower(),
            "pub": r["pub"],
            "min_adj": r["min_adj"],
        }
        for r in rows
    ]


def _ym(iso_date: str) -> tuple[int, int]:
    """(año, mes) a partir de una fecha ISO ``YYYY-MM-DD``."""
    return int(iso_date[:4]), int(iso_date[5:7])


def build_plan(affected: list[dict[str, Any]]) -> dict[str, Any]:
    """Deriva el plan de reproceso por fuente a partir de las filas afectadas.

    - PLACSP: conjunto de ``(año, mes)`` — tanto el mes del anuncio erróneo
      como el de la adjudicación (donde vive la entry con todos los anuncios).
    - TED / PSCP: fecha ``desde`` = la más temprana afectada de la fuente.
    """
    placsp_months: set[tuple[int, int]] = set()
    range_desde: dict[str, str] = {}

    for a in affected:
        fuente = a["fuente"]
        if fuente == "placsp":
            placsp_months.add(_ym(a["pub"]))
            placsp_months.add(_ym(a["min_adj"]))
        elif fuente in ("ted", "pscp"):
            earliest = min(a["pub"], a["min_adj"])  # la fecha conocida más temprana
            prev = range_desde.get(fuente)
            if prev is None or earliest < prev:
                range_desde[fuente] = earliest

    return {
        "placsp_months": sorted(placsp_months),
        "ted_desde": range_desde.get("ted"),
        "pscp_desde": range_desde.get("pscp"),
    }


def _print_plan(affected: list[dict[str, Any]], plan: dict[str, Any]) -> None:
    by_source: dict[str, int] = {}
    for a in affected:
        by_source[a["fuente"]] = by_source.get(a["fuente"], 0) + 1

    print(f"Licitaciones afectadas: {len(affected)}")
    for fuente, n in sorted(by_source.items()):
        print(f"  · {fuente}: {n}")
    print()
    if plan["placsp_months"]:
        meses = ", ".join(f"{y}-{m:02d}" for y, m in plan["placsp_months"])
        print(f"PLACSP → reprocesar meses: {meses}")
    if plan["ted_desde"]:
        print(f"TED    → re-fetch desde: {plan['ted_desde']}")
    if plan["pscp_desde"]:
        print(f"PSCP   → re-fetch desde: {plan['pscp_desde']}")


def _reprocess_placsp(months: list[tuple[int, int]]) -> None:
    """Re-ingiere los meses PLACSP indicados por el conector bulk.

    Antes llamaba a ``scraper.pipeline.process_month`` (retirado en S2.1,
    2026-09). Además del linaje/historial que aquel camino no escribía, aquí
    importa una cosa concreta: el remedio de este script es corregir
    ``fecha_publicacion``, y reprocesar por el camino legacy dejaba de paso sin
    documentos ni lotes a los expedientes que tocaba.
    """
    from scraper.connectors.base import run_connector
    from scraper.connectors.placsp import PlacspBulkConnector

    for year, month in months:
        log.info("backfill_reprocess_placsp", year=year, month=month)
        result = run_connector(PlacspBulkConnector(year, month))
        estado = "error_fetch" if result.fetch_failed else "ok"
        print(
            f"  PLACSP {year}-{month:02d}: {estado} "
            f"({result.nuevas} nuevas · {result.actualizadas} actualizadas · "
            f"{result.errores} errores)"
        )


def _reprocess_ted(desde_iso: str) -> None:
    from scraper.connectors.base import run_connector
    from scraper.connectors.ted import TedConnector

    desde = desde_iso.replace("-", "")  # TED usa YYYYMMDD
    connector = TedConnector()
    connector._since = lambda cursor: desde  # type: ignore[method-assign]
    log.info("backfill_reprocess_ted", desde=desde)
    result = run_connector(connector)
    print(f"  TED desde {desde}: {result.actualizadas} actualizadas, {result.errores} errores")


def _reprocess_pscp(desde_iso: str) -> None:
    from scraper.connectors.base import run_connector
    from scraper.connectors.pscp import PscpConnector

    connector = PscpConnector()
    connector._since = lambda cursor: desde_iso  # type: ignore[method-assign]  # PSCP usa YYYY-MM-DD
    log.info("backfill_reprocess_pscp", desde=desde_iso)
    result = run_connector(connector)
    print(f"  PSCP desde {desde_iso}: {result.actualizadas} actualizadas, {result.errores} errores")


def run(sources: tuple[str, ...], dry_run: bool) -> int:
    init_db()

    affected = find_affected(sources)
    if not affected:
        print("No hay licitaciones afectadas (fecha_publicacion > adjudicación). Nada que hacer.")
        return 0

    plan = build_plan(affected)
    _print_plan(affected, plan)

    if dry_run:
        print("\n[DRY RUN] No se reprocesó nada. Quitá --dry-run para aplicar.")
        return 0

    print("\nReprocesando desde la fuente…")
    if plan["placsp_months"]:
        _reprocess_placsp(plan["placsp_months"])
    if plan["ted_desde"]:
        _reprocess_ted(plan["ted_desde"])
    if plan["pscp_desde"]:
        _reprocess_pscp(plan["pscp_desde"])

    remaining = find_affected(sources)
    healed = len(affected) - len(remaining)
    print(f"\nResultado: {healed} sanadas, {len(remaining)} sin recuperar.")
    if remaining:
        print(
            "Las filas sin recuperar ya no tienen el anuncio original disponible "
            "en la fuente; su fecha_publicacion se queda como está (el fix del "
            "upsert impide que vuelva a empeorar)."
        )
        for a in remaining[:20]:
            print(f"  · {a['id_externo']} ({a['fuente']}): pub={a['pub']} > adj={a['min_adj']}")
        if len(remaining) > 20:
            print(f"  … y {len(remaining) - 20} más.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Corrige fecha_publicacion posterior a la adjudicación reprocesando la fuente."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo detecta las filas afectadas y muestra el plan, sin reprocesar.",
    )
    parser.add_argument(
        "--sources",
        default=",".join(_KNOWN_SOURCES),
        help=f"Fuentes a corregir, separadas por coma (por defecto: {','.join(_KNOWN_SOURCES)}).",
    )
    args = parser.parse_args(argv)

    sources = tuple(s.strip().lower() for s in args.sources.split(",") if s.strip())
    unknown = [s for s in sources if s not in _KNOWN_SOURCES]
    if unknown:
        parser.error(
            f"Fuentes sin handler de reproceso: {', '.join(unknown)}. "
            f"Soportadas: {', '.join(_KNOWN_SOURCES)}."
        )

    return run(sources, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
