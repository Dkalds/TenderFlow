"""Extrae expedientes reales de PLACSP al corpus golden del parser CODICE.

Los fixtures de ``tests/fixtures/placsp/`` nacieron sintéticos: estructuralmente
fieles al CODICE que publica PLACSP, pero escritos a mano. Este script los
complementa (o sustituye, con ``--sustituir``) con expedientes **reales**, que
es lo que da valor al corpus -- la clase de bug que motivó el corpus
(fecha_limite ausente, multi-lote, UTE, el lote del resultado) venía justamente
de formas del feed que nadie había imaginado al escribir un fixture.

Lee lo que ya está en disco, nunca la red: los ZIP mensuales cacheados por el
scraper en ``settings.DOWNLOADS_DIR`` (``data/downloads/``, gitignoreado; los
baja ``python -m scheduler.run_update --backfill 2026 5``), o las páginas ATOM
y ZIP que se le pasen con ``--atom`` (las que guarda
``scripts/medir_terminos_codice.py --vivo --guardar``, o un ZIP mensual bajado
a mano). Así la misma muestra con la que se mide da los fixtures.

Uso (``ENV=dev`` porque carga ``config.settings``)::

    ENV=dev python scripts/capture_placsp_fixtures.py --listar
    ENV=dev python scripts/capture_placsp_fixtures.py --atom muestra/*.atom --caso condiciones
    # un expediente concreto (el que cita el README del corpus)
    ENV=dev python scripts/capture_placsp_fixtures.py --atom muestra/*.atom \\
        --caso solvencia_umbral --id 20767321

Solo se captura lo que el conector **ingiere** (el universo tecnológico, con
el rescate ML anulado como en el golden): una entry descartada da un golden
``null`` que no congela nada. La excepción es ``fuera_universo``, que existe
para congelar justo eso.

Cada expediente se escribe como ``<NN>_<caso>_real.xml`` con la declaración
XML delante (los tests lo cortan por ``?>``), salto de línea final y los
espacios finales de línea escritos como referencia de carácter: el hook
``trailing-whitespace`` los borraría y cambiaría el texto del expediente.
``--sustituir`` escribe en cambio sobre el fixture sintético del caso, si lo
tiene. Tras capturar, revisá el XML (puede traer datos personales en
``cac:Contact`` o en el adjudicatario) y regenerá el golden revisando el diff::

    ENV=dev python -m tests.test_codice_parser_golden --update
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_FIXTURES = _ROOT / "tests" / "fixtures" / "placsp"
_CFS = "./cacext:ContractFolderStatus"


def _ns() -> dict[str, str]:
    from scraper.codice_parser import NS

    return dict(NS)


def _x(entry: Any, xpath: str) -> list[Any]:
    return list(entry.xpath(xpath, namespaces=_ns()))


def parseado(entry: Any) -> Any | None:
    """El parseo del camino de producción, como lo hace el golden, o ``None``."""
    from unittest.mock import patch

    import scraper.pipeline  # noqa: F401  -- registra el submódulo para el patch
    from scraper.connectors.placsp import _PlacspParseCore

    with patch("scraper.pipeline._ml_classify_entry", return_value=None):
        return _PlacspParseCore().parse_entry_elem(entry, fuente="placsp")


# ── Selectores por caso ──────────────────────────────────────────────────────
# Cada uno recibe un elemento <entry> y su parseo (nunca ``None`` salvo en
# ``fuera_universo``) y responde si es un ejemplar del caso. El nombre es el
# que se pasa por --caso y el que da nombre al fichero.


def _es_multilote(entry: Any, p: Any) -> bool:
    return len(_x(entry, f"{_CFS}/cac:ProcurementProjectLot")) >= 2


def _multilote_adjudicado(entry: Any, p: Any) -> bool:
    """Varios lotes y todas las adjudicaciones resuelven el suyo."""
    adjudicaciones = p.adjudicaciones
    return (
        _es_multilote(entry, p)
        and len(adjudicaciones) >= 2
        and all(a.lote_numero_raw for a in adjudicaciones)
    )


def _es_ute(entry: Any, p: Any) -> bool:
    return any(
        len(_x(tr, "./cac:WinningParty")) >= 2 for tr in _x(entry, f"{_CFS}/cac:TenderResult")
    )


def _lotes_repiten_presupuesto(entry: Any, p: Any) -> bool:
    """Cada lote publica como presupuesto propio el del expediente entero."""
    total = p.licitacion.importe
    return (
        len(p.lotes) >= 2 and total is not None and all(lote.importe == total for lote in p.lotes)
    )


def _sin_fecha_limite(entry: Any, p: Any) -> bool:
    return p.licitacion.fecha_limite is None


def _plazo_participacion(entry: Any, p: Any) -> bool:
    tp = f"{_CFS}/cac:TenderingProcess"
    return bool(_x(entry, f"{tp}/cac:ParticipationRequestReceptionPeriod/cbc:EndDate")) and not _x(
        entry, f"{tp}/cac:TenderSubmissionDeadlinePeriod/cbc:EndDate"
    )


def _ambos_periodos(entry: Any, p: Any) -> bool:
    tp = f"{_CFS}/cac:TenderingProcess"
    return bool(
        _x(entry, f"{tp}/cac:ParticipationRequestReceptionPeriod/cbc:EndDate")
        and _x(entry, f"{tp}/cac:TenderSubmissionDeadlinePeriod/cbc:EndDate")
    )


def _hora_local(entry: Any, p: Any) -> bool:
    """Plazo con ``EndTime``: la hora peninsular que el parser pasa a UTC."""
    plazo = f"{_CFS}/cac:TenderingProcess/cac:TenderSubmissionDeadlinePeriod"
    return bool(_x(entry, f"{plazo}/cbc:EndDate") and _x(entry, f"{plazo}/cbc:EndTime"))


def _importe_total_amount(entry: Any, p: Any) -> bool:
    presupuesto = f"{_CFS}/cac:ProcurementProject/cac:BudgetAmount"
    return bool(_x(entry, f"{presupuesto}/cbc:TotalAmount")) and not _x(
        entry, f"{presupuesto}/cbc:TaxExclusiveAmount"
    )


def _con_documentos(entry: Any, p: Any) -> bool:
    return len({d.tipo for d in p.documentos}) >= 3


def _adjudicacion_pyme(entry: Any, p: Any) -> bool:
    return bool(_x(entry, ".//cbc:SMEAwardedIndicator"))


def _lotes_heredan(entry: Any, p: Any) -> bool:
    """Unos lotes con plazo propio y otros sin él."""
    lotes = _x(entry, f"{_CFS}/cac:ProcurementProjectLot")
    propios = [
        bool(_x(lote, "./cac:TenderingProcess/cac:TenderSubmissionDeadlinePeriod/cbc:EndDate"))
        for lote in lotes
    ]
    return len(lotes) >= 2 and any(propios) and not all(propios)


def _criterios_raiz(p: Any) -> list[Any]:
    condiciones = p.licitacion.condiciones
    if condiciones is None:
        return []
    return [c for c in condiciones.criterios if c.padre_orden is None and c.lote_numero is None]


def _criterios_sin_escala(entry: Any, p: Any) -> bool:
    raiz = _criterios_raiz(p)
    return bool(raiz) and all(c.peso_pct is None for c in raiz)


def _criterios_fraccion(entry: Any, p: Any) -> bool:
    raiz = _criterios_raiz(p)
    return (
        bool(raiz)
        and all(c.peso_pct is not None for c in raiz)
        and all(c.peso is not None and c.peso <= 1 for c in raiz)
    )


def _anuncio_previo(entry: Any, p: Any) -> bool:
    return "PIN" in (p.licitacion.tipos_anuncio or "")


def _fuera_universo(entry: Any, p: Any) -> bool:
    return p is None and bool(_x(entry, _CFS))


def _condiciones(entry: Any, p: Any) -> bool:
    """v148: el expediente trae criterios **y** garantía o solvencia propios."""
    condiciones = p.licitacion.condiciones
    if condiciones is None:
        return False
    expediente = [c for c in condiciones.criterios if c.lote_numero is None]
    otros = [x for x in (*condiciones.garantias, *condiciones.solvencia) if x.lote_numero is None]
    return bool(expediente and otros)


def _condiciones_por_lote(entry: Any, p: Any) -> bool:
    """v148: algún lote publica su propio ``TenderingTerms`` con criterios."""
    condiciones = p.licitacion.condiciones
    return condiciones is not None and any(c.lote_numero is not None for c in condiciones.criterios)


def _solvencia_umbral(entry: Any, p: Any) -> bool:
    """Solvencia económica con umbral en ``ThresholdQuantity`` (la forma real)."""
    return bool(
        _x(
            entry,
            f"{_CFS}/cac:TenderingTerms/cac:TendererQualificationRequest"
            "/cac:FinancialEvaluationCriteria/cbc:ThresholdQuantity",
        )
    )


Selector = Callable[[Any, Any], bool]

_CASOS: dict[str, Selector] = {
    "ambos_periodos": _ambos_periodos,
    "anuncio_previo": _anuncio_previo,
    "condiciones": _condiciones,
    "condiciones_por_lote": _condiciones_por_lote,
    "criterios_fraccion": _criterios_fraccion,
    "criterios_sin_escala": _criterios_sin_escala,
    "documentos": _con_documentos,
    "fuera_universo": _fuera_universo,
    "hora_local": _hora_local,
    "importe_total_amount": _importe_total_amount,
    "lotes_heredan": _lotes_heredan,
    "lotes_repiten_presupuesto": _lotes_repiten_presupuesto,
    "multilote": _es_multilote,
    "multilote_adjudicado": _multilote_adjudicado,
    "plazo_participacion": _plazo_participacion,
    "pyme": _adjudicacion_pyme,
    "sin_fecha_limite": _sin_fecha_limite,
    "solvencia_umbral": _solvencia_umbral,
    "ute": _es_ute,
}

#: Fixture sintético que ``--sustituir`` reescribe con el ejemplar real.
#:
#: Solo están los casos cuyo sintético congela **una** forma que un expediente
#: real del caso también trae. Los que además fijan una construcción que el
#: feed no publica no se sustituyen, porque el real dejaría sin golden ese
#: camino del parser: 01 (lote en ``ProcurementProjectLotReference``), 06
#: (adjunto sin URI que se descarta), 10 (lote 1 con ``TotalAmount``), 11 (los
#: dos plazos con fechas distintas: en el feed coinciden), 12 (subcriterios
#: anidados), 14 (dos PCAP con hash distinto) y 07/18 (otros tests los leen por
#: su id). Para esos, el real entra como caso nuevo.
SINTETICO_POR_CASO: dict[str, str] = {
    "ute": "02_ute_dos_ganadores_un_resultado.xml",
    "sin_fecha_limite": "03_sin_fecha_limite.xml",
    "plazo_participacion": "04_deadline_participation_request.xml",
    "importe_total_amount": "05_importe_solo_total_amount.xml",
    "fuera_universo": "08_fuera_universo_tecnologico.xml",
    "hora_local": "09_deadline_hora_local.xml",
    "criterios_sin_escala": "13_criterios_sin_escala_deducible.xml",
    "anuncio_previo": "15_anuncio_previo_notice_type_code.xml",
    "condiciones": "16_condiciones_expediente.xml",
    "condiciones_por_lote": "17_condiciones_por_lote.xml",
}


def _entry_id(entry: Any) -> str:
    """El número final del ``<id>`` ATOM (``.../licitacionesPerfilContratante/<n>``)."""
    ns = _ns()
    texto = entry.findtext(f"{{{ns['atom']}}}id") or ""
    return texto.rstrip("/").rsplit("/", 1)[-1]


def _entries_de_bytes(contenido: bytes) -> Iterator[Any]:
    from lxml import etree

    parser = etree.XMLParser(huge_tree=False, resolve_entities=False, no_network=True)
    try:
        raiz = etree.fromstring(contenido, parser)
    except etree.XMLSyntaxError:
        return
    yield from raiz.iter(f"{{{_ns()['atom']}}}entry")


def _entries_de_zip(zip_path: Path) -> Iterator[Any]:
    from scraper.bulk_downloader import iter_xml_files

    print(f"[capture] Leyendo {zip_path.name}")
    for _name, blob in iter_xml_files(zip_path):
        yield from _entries_de_bytes(blob)


def _iter_entries(max_zips: int) -> Iterator[Any]:
    """Produce elementos ``<entry>`` de los ZIP más recientes en caché."""
    from config import settings

    downloads = getattr(settings, "DOWNLOADS_DIR", None)
    if not downloads or not Path(downloads).exists():
        print(f"[capture] Sin ZIP cacheados en {downloads} — nada que extraer.", file=sys.stderr)
        return

    zips = sorted(Path(downloads).glob("placsp_*.zip"), reverse=True)[:max_zips]
    if not zips:
        print(f"[capture] No hay placsp_*.zip en {downloads}.", file=sys.stderr)
        return
    for zip_path in zips:
        yield from _entries_de_zip(zip_path)


def _iter_entries_atom(rutas: list[Path]) -> Iterator[Any]:
    """Produce elementos ``<entry>`` de páginas ATOM o ZIP ya descargados."""
    for ruta in rutas:
        if ruta.suffix.lower() == ".zip":
            yield from _entries_de_zip(ruta)
            continue
        print(f"[capture] Leyendo {ruta.name}")
        yield from _entries_de_bytes(ruta.read_bytes())


_ESPACIO_FINAL = re.compile(rb"[ \t]+(?=\r?\n)")


def serializar(entry: Any) -> bytes:
    """El XML del fixture: declaración, sin espacios finales y con salto final.

    Los espacios y tabuladores al final de una línea pasan a referencias de
    carácter (``&#32;``/``&#9;``): el XML que se lee es el mismo, y los hooks
    ``trailing-whitespace`` y ``end-of-file-fixer`` no tienen nada que tocar.
    Un ``\\r`` dentro del texto ya sale como ``&#13;`` desde lxml.
    """
    from lxml import etree

    cuerpo = etree.tostring(entry, encoding="UTF-8", xml_declaration=False, with_tail=False)

    def a_referencias(m: re.Match[bytes]) -> bytes:
        return b"".join(b"&#32;" if c == 0x20 else b"&#9;" for c in m.group(0))

    cuerpo = _ESPACIO_FINAL.sub(a_referencias, cuerpo)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + cuerpo.rstrip() + b"\n"


def _siguiente_indice() -> int:
    existentes = [p.name for p in _FIXTURES.glob("*.xml")]
    indices = [int(n[:2]) for n in existentes if n[:2].isdigit()]
    return max(indices, default=0) + 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--caso",
        action="append",
        choices=sorted(_CASOS),
        help="Caso a capturar (repetible). Por defecto: todos.",
    )
    parser.add_argument("--max-zips", type=int, default=2, help="ZIP más recientes a recorrer")
    parser.add_argument(
        "--atom",
        nargs="+",
        type=Path,
        help="páginas ATOM o ZIP mensuales ya descargados, en vez de los ZIP cacheados",
    )
    parser.add_argument(
        "--id",
        action="append",
        dest="ids",
        help="solo entries con este número de <id> ATOM (repetible)",
    )
    parser.add_argument(
        "--sustituir",
        action="store_true",
        help="escribe sobre el fixture sintético del caso en vez de añadir uno nuevo",
    )
    parser.add_argument(
        "--listar",
        action="store_true",
        help="Solo cuenta cuántos ejemplares hay de cada caso, sin escribir nada",
    )
    args = parser.parse_args(argv)

    casos = args.caso or sorted(_CASOS)
    pendientes = {c: _CASOS[c] for c in casos}
    encontrados: dict[str, Any] = {}
    conteo = dict.fromkeys(casos, 0)
    ids = set(args.ids or ())

    entradas = _iter_entries_atom(args.atom) if args.atom else _iter_entries(args.max_zips)
    for entry in entradas:
        if ids and _entry_id(entry) not in ids:
            continue
        try:
            parseo = parseado(entry)
        except Exception as exc:  # pragma: no cover -- entry malformada
            print(f"[capture] entry descartada ({exc})", file=sys.stderr)
            continue
        for nombre, predicado in list(pendientes.items()):
            if (parseo is None) != (nombre == "fuera_universo"):
                continue
            try:
                if not predicado(entry, parseo):
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
        print("[capture] Ningún ejemplar encontrado.", file=sys.stderr)
        return 1

    indice = _siguiente_indice()
    for nombre, entry in sorted(encontrados.items()):
        if args.sustituir and nombre in SINTETICO_POR_CASO:
            destino = _FIXTURES / SINTETICO_POR_CASO[nombre]
        else:
            destino = _FIXTURES / f"{indice:02d}_{nombre}_real.xml"
            indice += 1
        destino.write_bytes(serializar(entry))
        print(f"[capture] {destino.relative_to(_ROOT)} (entry {_entry_id(entry)})")

    print(
        "\nRevisá los XML capturados (pueden traer datos que no querés commitear) y "
        "regenerá el golden:\n  ENV=dev python -m tests.test_codice_parser_golden --update"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
