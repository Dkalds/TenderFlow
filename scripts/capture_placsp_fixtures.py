"""Extrae expedientes reales de los ZIP mensuales cacheados al corpus golden.

Los fixtures de ``tests/fixtures/placsp/`` nacieron sintéticos: estructuralmente
fieles al CODICE que publica PLACSP, pero escritos a mano. Este script los
sustituye por expedientes **reales**, que es lo que da valor al corpus -- la
clase de bug que motivó el corpus (fecha_limite ausente, multi-lote, UTE) venía
justamente de formas del feed que nadie había imaginado al escribir un fixture.

Requiere ZIP ya descargados en ``settings.DOWNLOADS_DIR`` (``data/downloads/``,
gitignoreado). Los baja el propio scraper::

    python -m scheduler.run_update --backfill 2026 5

No hay descarga aquí a propósito: este script solo lee lo que ya está en disco,
así puede correr sin red y sin tocar la fuente.

Uso (``ENV=dev`` porque carga ``config.settings`` para resolver ``DOWNLOADS_DIR``)::

    ENV=dev python scripts/capture_placsp_fixtures.py --listar   # qué hay disponible
    ENV=dev python scripts/capture_placsp_fixtures.py --caso multilote --caso ute

Cada expediente capturado se escribe como ``<NN>_<caso>.xml``. Tras capturar,
regenerá el golden y revisá el diff::

    ENV=dev python -m tests.test_codice_parser_golden --update
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_FIXTURES = _ROOT / "tests" / "fixtures" / "placsp"


def _ns() -> dict[str, str]:
    from scraper.codice_parser import NS

    return dict(NS)


# ── Selectores por caso ──────────────────────────────────────────────────────
# Cada uno recibe un elemento <entry> y responde si es un ejemplar del caso.
# El nombre es el que se pasa por --caso y el que da nombre al fichero.


def _cfs(entry: Any) -> list[Any]:
    return entry.xpath("./cacext:ContractFolderStatus", namespaces=_ns())


def _es_multilote(entry: Any) -> bool:
    return len(entry.xpath(".//cac:ProcurementProjectLot", namespaces=_ns())) >= 2


def _es_ute(entry: Any) -> bool:
    return any(
        len(tr.xpath("./cac:WinningParty", namespaces=_ns())) >= 2
        for tr in entry.xpath(".//cac:TenderResult", namespaces=_ns())
    )


def _sin_fecha_limite(entry: Any) -> bool:
    tiene_plazo = entry.xpath(
        ".//cac:TenderingProcess/cac:TenderSubmissionDeadlinePeriod/cbc:EndDate",
        namespaces=_ns(),
    )
    return bool(_cfs(entry)) and not tiene_plazo


def _plazo_participacion(entry: Any) -> bool:
    return bool(
        entry.xpath(
            ".//cac:TenderingProcess/cac:ParticipationRequestReceptionPeriod/cbc:EndDate",
            namespaces=_ns(),
        )
    )


def _importe_total_amount(entry: Any) -> bool:
    ns = _ns()
    return bool(
        entry.xpath(".//cac:BudgetAmount/cbc:TotalAmount", namespaces=ns)
    ) and not entry.xpath(".//cac:BudgetAmount/cbc:TaxExclusiveAmount", namespaces=ns)


def _con_documentos(entry: Any) -> bool:
    ns = _ns()
    return bool(
        entry.xpath(".//cac:LegalDocumentReference", namespaces=ns)
        and entry.xpath(".//cac:TechnicalDocumentReference", namespaces=ns)
    )


def _adjudicacion_pyme(entry: Any) -> bool:
    return bool(entry.xpath(".//cbc:SMEAwardedIndicator", namespaces=_ns()))


_CASOS: dict[str, Callable[[Any], bool]] = {
    "multilote": _es_multilote,
    "ute": _es_ute,
    "sin_fecha_limite": _sin_fecha_limite,
    "plazo_participacion": _plazo_participacion,
    "importe_total_amount": _importe_total_amount,
    "documentos": _con_documentos,
    "pyme": _adjudicacion_pyme,
}


def _iter_entries(max_zips: int) -> Iterator[Any]:
    """Produce elementos ``<entry>`` de los ZIP más recientes en caché."""
    from lxml import etree

    from config import settings
    from scraper.bulk_downloader import iter_xml_files

    downloads = getattr(settings, "DOWNLOADS_DIR", None)
    if not downloads or not Path(downloads).exists():
        print(f"[capture] Sin ZIP cacheados en {downloads} — nada que extraer.", file=sys.stderr)
        return

    zips = sorted(Path(downloads).glob("placsp_*.zip"), reverse=True)[:max_zips]
    if not zips:
        print(f"[capture] No hay placsp_*.zip en {downloads}.", file=sys.stderr)
        return

    ns = _ns()
    for zip_path in zips:
        print(f"[capture] Leyendo {zip_path.name}")
        for _name, blob in iter_xml_files(zip_path):
            try:
                root = etree.fromstring(blob)
            except etree.XMLSyntaxError:
                continue
            yield from root.iter(f"{{{ns['atom']}}}entry")


def _siguiente_indice() -> int:
    existentes = [p.name for p in _FIXTURES.glob("*.xml")]
    indices = [int(n[:2]) for n in existentes if n[:2].isdigit()]
    return max(indices, default=0) + 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--caso",
        action="append",
        choices=sorted(_CASOS),
        help="Caso a capturar (repetible). Por defecto: todos.",
    )
    parser.add_argument("--max-zips", type=int, default=2, help="ZIP más recientes a recorrer")
    parser.add_argument(
        "--listar",
        action="store_true",
        help="Solo cuenta cuántos ejemplares hay de cada caso, sin escribir nada",
    )
    args = parser.parse_args()

    from lxml import etree

    casos = args.caso or sorted(_CASOS)
    pendientes = {c: _CASOS[c] for c in casos}
    encontrados: dict[str, Any] = {}
    conteo = dict.fromkeys(casos, 0)

    for entry in _iter_entries(args.max_zips):
        for nombre, predicado in list(pendientes.items()):
            try:
                if not predicado(entry):
                    continue
            except Exception as exc:  # pragma: no cover -- entry malformada
                print(f"[capture] {nombre}: entry descartada ({exc})", file=sys.stderr)
                continue
            conteo[nombre] += 1
            if nombre not in encontrados:
                encontrados[nombre] = entry
                if not args.listar:
                    del pendientes[nombre]
        if not args.listar and not pendientes:
            break

    if args.listar:
        print("\nEjemplares encontrados por caso:")
        for nombre in casos:
            print(f"  {nombre:24} {conteo[nombre]}")
        return 0

    if not encontrados:
        print("[capture] Ningún ejemplar encontrado. ¿Hay ZIP cacheados?", file=sys.stderr)
        return 1

    indice = _siguiente_indice()
    for nombre, entry in sorted(encontrados.items()):
        destino = _FIXTURES / f"{indice:02d}_{nombre}_real.xml"
        destino.write_bytes(etree.tostring(entry, pretty_print=True, xml_declaration=False))
        print(f"[capture] {destino.relative_to(_ROOT)}")
        indice += 1

    print(
        "\nRevisá los XML capturados (pueden traer datos que no querés commitear) y "
        "regenerá el golden:\n  ENV=dev python -m tests.test_codice_parser_golden --update"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
