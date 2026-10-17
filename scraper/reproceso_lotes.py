"""Reproceso dirigido: el lote de las adjudicaciones ya guardadas, desde los ZIP.

Uso::

  python -m scraper.reproceso_lotes --desde 2025-01 --hasta 2026-10            # cuenta
  python -m scraper.reproceso_lotes --desde 2025-01 --hasta 2026-10 --aplicar  # escribe

Lee los ZIP mensuales de PLACSP del rango y, de cada entry, solo mira las de
los expedientes multilote que tienen adjudicaciones sin ``lote_id``
(``db.repositories.reproceso_lotes.multilote_sin_lote``). De esas saca el lote
de cada adjudicación y lo asigna **en sitio** a la fila que ya existe. No toca
la licitación, ni los documentos, ni los lotes: el bulk completo tarda más de
dos horas por mes porque escribe todo eso, y aquí solo falta una columna.

Cada mes se aplica al terminar de leerlo, así que un rango largo puede partirse
en varias ejecuciones y una que se corte conserva lo hecho. El emparejamiento
solo rellena ``lote_id`` vacío: repetir un mes no cambia nada.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from db.repositories.reproceso_lotes import AsignacionLote, asignar_lotes, multilote_sin_lote
from observability import configure_logging, get_logger

log = get_logger(__name__)

_MES_RE = re.compile(r"^(\d{4})-(\d{2})$")


def meses_entre(desde: str, hasta: str) -> list[tuple[int, int]]:
    """Los meses ``YYYY-MM`` de ``desde`` a ``hasta``, ambos incluidos."""
    inicio, fin = _mes(desde), _mes(hasta)
    if inicio > fin:
        raise ValueError(f"--desde ({desde}) es posterior a --hasta ({hasta})")
    meses: list[tuple[int, int]] = []
    year, month = inicio
    while (year, month) <= fin:
        meses.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return meses


def _mes(texto: str) -> tuple[int, int]:
    m = _MES_RE.match(texto)
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ValueError(f"mes inválido: {texto!r} (se espera YYYY-MM)")
    return int(m.group(1)), int(m.group(2))


def asignaciones_de_entry(entry: Any, objetivo: set[str]) -> list[AsignacionLote]:
    """Las adjudicaciones con lote de una entry, si es de un expediente objetivo.

    El id sale de ``ContractFolderID``, que es lo que ``parse_entry`` usa como
    ``id_externo`` en PLACSP; mirarlo antes de parsear nada más es lo que hace
    barato recorrer un ZIP entero buscando unos cientos de expedientes.
    """
    from scraper.codice_parser import NS, parse_adjudicaciones

    ids = entry.xpath("./cacext:ContractFolderStatus/cbc:ContractFolderID/text()", namespaces=NS)
    licitacion_id = str(ids[0]).strip() if ids else ""
    if licitacion_id not in objetivo:
        return []
    return [
        AsignacionLote(
            licitacion_id=licitacion_id,
            nombre=adj.nombre,
            nif=adj.nif,
            importe_adjudicado=adj.importe_adjudicado,
            lote_numero=adj.lote_numero_raw,
        )
        for adj in parse_adjudicaciones(entry, licitacion_id)
        if adj.lote_numero_raw is not None
    ]


def _entries_del_mes(year: int, month: int) -> Iterator[Any]:
    from scraper.bulk_downloader import download_month, iter_xml_files
    from scraper.connectors.placsp import _iter_atom_entries

    zip_path = download_month(year, month)
    if zip_path is None:
        log.info("reproceso_lotes_mes_no_publicado", year=year, month=month)
        return
    try:
        for _nombre, contenido in iter_xml_files(zip_path):
            for entry, _ in _iter_atom_entries(contenido):
                yield entry
    finally:
        # Un rango de dos años son decenas de ZIP: no se guardan en el runner.
        zip_path.unlink(missing_ok=True)


@dataclass
class ResumenReproceso:
    objetivo: int = 0
    meses: int = 0
    entries_objetivo: int = 0
    asignaciones: int = 0
    filas_actualizadas: int = 0
    expedientes_vistos: set[str] = field(default_factory=set)


def reprocesar(desde: str, hasta: str, *, aplicar: bool) -> ResumenReproceso:
    """Recorre el rango y, con ``aplicar``, asigna los lotes mes a mes."""
    meses = meses_entre(desde, hasta)
    objetivo = multilote_sin_lote()
    resumen = ResumenReproceso(objetivo=len(objetivo))
    log.info("reproceso_lotes_inicio", desde=desde, hasta=hasta, objetivo=len(objetivo))
    if not objetivo:
        return resumen

    for year, month in meses:
        del_mes: list[AsignacionLote] = []
        for entry in _entries_del_mes(year, month):
            asignaciones = asignaciones_de_entry(entry, objetivo)
            if asignaciones:
                resumen.entries_objetivo += 1
                resumen.expedientes_vistos.add(asignaciones[0].licitacion_id)
                del_mes.extend(asignaciones)
        resumen.meses += 1
        resumen.asignaciones += len(del_mes)
        actualizadas = asignar_lotes(del_mes) if aplicar and del_mes else 0
        resumen.filas_actualizadas += actualizadas
        log.info(
            "reproceso_lotes_mes",
            year=year,
            month=month,
            asignaciones=len(del_mes),
            filas_actualizadas=actualizadas,
            aplicar=aplicar,
        )
    return resumen


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    p.add_argument("--desde", required=True, help="Primer mes, YYYY-MM")
    p.add_argument("--hasta", required=True, help="Último mes, YYYY-MM (incluido)")
    p.add_argument("--aplicar", action="store_true", help="Escribir en la BD (sin él solo cuenta)")
    args = p.parse_args(argv)
    configure_logging()
    resumen = reprocesar(args.desde, args.hasta, aplicar=args.aplicar)
    log.info(
        "reproceso_lotes_fin",
        aplicar=args.aplicar,
        objetivo=resumen.objetivo,
        meses=resumen.meses,
        expedientes_vistos=len(resumen.expedientes_vistos),
        entries_objetivo=resumen.entries_objetivo,
        asignaciones=resumen.asignaciones,
        filas_actualizadas=resumen.filas_actualizadas,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
