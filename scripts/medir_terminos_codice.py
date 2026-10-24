"""Mide qué traen las entradas del ATOM de PLACSP en ``cac:TenderingTerms`` (v148).

Por qué existe
--------------
v148 empieza a guardar criterios de adjudicación, garantías y solvencia desde
CODICE, a nivel de expediente y de lote. La pregunta previa —qué porcentaje de
entradas trae cada bloque, y dónde— no se pudo contestar en la sesión que lo
escribió: su política de red bloqueaba ``contrataciondelsectorpublico.gob.es``
(2026-10-12). Este script es esa medición, para hacerla con un comando y que
el número quede escrito con su muestra y su fecha.

Mide **lo que el parser extrae** (``scraper.codice_parser.parse_condiciones``)
y, aparte, la mera presencia del elemento ``cac:TenderingTerms``: si un nivel
trae el bloque y el parser no saca nada de él, la diferencia entre las dos
columnas es justo lo que hay que mirar a mano.

Uso::

    # páginas ya descargadas, o ZIP mensuales enteros
    ENV=dev python scripts/medir_terminos_codice.py muestra/*.atom
    ENV=dev python scripts/medir_terminos_codice.py licitacionesPerfilesContratanteCompleto3_202609.zip
    # el feed en vivo, siguiendo rel="next", guardando lo leído
    ENV=dev python scripts/medir_terminos_codice.py --vivo --paginas 2 --guardar muestra/
    # para archivar
    ENV=dev python scripts/medir_terminos_codice.py muestra/*.atom --json

Con las páginas guardadas, ``scripts/capture_placsp_fixtures.py --atom
muestra/*.atom --caso condiciones`` recorta entradas reales para el corpus.

Cómo leer el resultado
----------------------
- El denominador es **toda entrada** del ATOM, no solo las del universo
  tecnológico: el parser lee ``TenderingTerms`` antes del filtro, y lo que se
  quiere saber es qué publica la fuente.
- ``en lote`` cuenta entradas con al menos un lote que trae el bloque; el
  porcentaje se da también sobre las entradas que tienen lotes.
- Los **códigos observados** y el rango de ``AmountRate`` sirven para
  verificar dos supuestos del parser: que los códigos son de listas que no se
  traducen y que ``AmountRate`` viene en porcentaje (5 = 5 %), no en fracción.
- La tabla **por estado** (``ContractFolderStatusCode``: PUB, EV, ADJ, RES…)
  dice si una fase deja de publicar el bloque, que es lo que decide si el
  histórico se puede rellenar desde los ZIP mensuales.

Primera medición (2026-10-24), en cualquier nivel: ocho páginas del ATOM vivo
(3.903 entradas) dan criterios 94,2 %, garantías 53,4 %, solvencia técnica
67,2 %, económica 66,5 % y clasificación 6,0 %; el ZIP de 2026-09 (95.910
entradas) 88,4 / 54,0 / 64,5 / 64,1 / 6,5 %. ``AmountRate`` viene en
porcentaje (mediana 5; 14 de 59.114 valores por debajo de 1). Las fases
ADJ y RES siguen publicando el bloque (criterios en el 79 % y el 83 % del ZIP).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

ATOM = "{http://www.w3.org/2005/Atom}"

#: Bloques que se miden, en el orden en que se imprimen.
BLOQUES: tuple[str, ...] = (
    "criterios",
    "garantias",
    "solvencia_tecnica",
    "solvencia_economica",
    "clasificacion",
)

_HOSTS_OFICIALES = ("contrataciondelsectorpublico.gob.es", "contrataciondelestado.es")


@dataclass
class Medicion:
    """Conteos de una muestra. Todo entero: los porcentajes se calculan al imprimir."""

    entradas: int = 0
    con_lotes: int = 0
    terms_expediente: int = 0
    terms_lote: int = 0
    #: ``{bloque: {"expediente": n, "lote": n, "cualquiera": n}}``
    por_bloque: dict[str, dict[str, int]] = field(
        default_factory=lambda: {b: {"expediente": 0, "lote": 0, "cualquiera": 0} for b in BLOQUES}
    )
    criterios_filas: int = 0
    criterios_con_peso: int = 0
    criterios_con_pct: int = 0
    criterios_con_tipo: int = 0
    criterios_con_subtipo: int = 0
    criterios_con_nota: int = 0
    garantias_con_importe: int = 0
    porcentajes_garantia: list[float] = field(default_factory=list)
    codigos_criterio: Counter[str] = field(default_factory=Counter)
    codigos_garantia: Counter[str] = field(default_factory=Counter)
    codigos_solvencia: Counter[str] = field(default_factory=Counter)
    solvencia_economica_con_umbral: int = 0
    #: Entradas por ``ContractFolderStatusCode`` y, de ellas, cuántas traen
    #: cada bloque en cualquier nivel: ``{estado: {"entradas": n, bloque: n}}``.
    por_estado: dict[str, dict[str, int]] = field(default_factory=dict)
    updated_min: str | None = None
    updated_max: str | None = None


def _bloques_de(condiciones: Any) -> dict[str, set[str]]:
    """Para cada bloque, en qué niveles (``expediente``/``lote``) aparece."""
    niveles: dict[str, set[str]] = {b: set() for b in BLOQUES}

    def nivel(lote_numero: str | None) -> str:
        return "expediente" if lote_numero is None else "lote"

    for criterio in condiciones.criterios:
        niveles["criterios"].add(nivel(criterio.lote_numero))
    for garantia in condiciones.garantias:
        niveles["garantias"].add(nivel(garantia.lote_numero))
    for requisito in condiciones.solvencia:
        clave = {
            "tecnica": "solvencia_tecnica",
            "economica": "solvencia_economica",
            "clasificacion": "clasificacion",
        }[requisito.clase]
        niveles[clave].add(nivel(requisito.lote_numero))
    return niveles


def medir(entradas: Iterable[Any]) -> Medicion:
    """Mide una secuencia de elementos ``<entry>``. Pura: ni red ni BD."""
    from scraper.codice_parser import NS, parse_condiciones

    m = Medicion()
    for entry in entradas:
        m.entradas += 1
        updated = (entry.findtext(f"{ATOM}updated") or "").strip() or None
        if updated:
            m.updated_min = min(filter(None, (m.updated_min, updated)))
            m.updated_max = max(filter(None, (m.updated_max, updated)))
        cfs = "./cacext:ContractFolderStatus"
        if entry.xpath(f"{cfs}/cac:ProcurementProjectLot", namespaces=NS):
            m.con_lotes += 1
        if entry.xpath(f"{cfs}/cac:TenderingTerms", namespaces=NS):
            m.terms_expediente += 1
        if entry.xpath(f"{cfs}/cac:ProcurementProjectLot/cac:TenderingTerms", namespaces=NS):
            m.terms_lote += 1

        estado = (
            entry.findtext(f"{cfs}/cbcext:ContractFolderStatusCode", namespaces=NS) or "—"
        ).strip() or "—"
        conteo_estado = m.por_estado.setdefault(estado, {"entradas": 0})
        conteo_estado["entradas"] += 1

        condiciones = parse_condiciones(entry)
        for bloque, niveles in _bloques_de(condiciones).items():
            for nivel in niveles:
                m.por_bloque[bloque][nivel] += 1
            if niveles:
                m.por_bloque[bloque]["cualquiera"] += 1
                conteo_estado[bloque] = conteo_estado.get(bloque, 0) + 1

        for criterio in condiciones.criterios:
            m.criterios_filas += 1
            m.criterios_con_peso += criterio.peso is not None
            m.criterios_con_pct += criterio.peso_pct is not None
            m.criterios_con_tipo += criterio.tipo_codigo is not None
            m.criterios_con_subtipo += criterio.subtipo_codigo is not None
            m.criterios_con_nota += criterio.nota is not None
            if criterio.tipo_codigo:
                m.codigos_criterio[criterio.tipo_codigo] += 1
        for garantia in condiciones.garantias:
            m.garantias_con_importe += garantia.importe is not None
            if garantia.porcentaje is not None:
                m.porcentajes_garantia.append(garantia.porcentaje)
            if garantia.tipo_codigo:
                m.codigos_garantia[garantia.tipo_codigo] += 1
        for requisito in condiciones.solvencia:
            if requisito.clase == "economica" and requisito.umbral_importe is not None:
                m.solvencia_economica_con_umbral += 1
            if requisito.tipo_codigo:
                m.codigos_solvencia[f"{requisito.clase}:{requisito.tipo_codigo}"] += 1
    return m


def _pct(parte: int, total: int) -> str:
    return f"{100.0 * parte / total:.1f} %" if total else "—"


def informe_markdown(m: Medicion, *, muestra: str, fecha: str) -> str:
    """El resultado como Markdown, con la muestra y la fecha delante."""
    lineas = [
        f"Muestra: {muestra} — {m.entradas} entradas, `updated` de {m.updated_min} a "
        f"{m.updated_max}. Medido el {fecha}.",
        "",
        f"- Entradas con lotes: {m.con_lotes} ({_pct(m.con_lotes, m.entradas)})",
        f"- `TenderingTerms` en el expediente: {m.terms_expediente} "
        f"({_pct(m.terms_expediente, m.entradas)}); en algún lote: {m.terms_lote} "
        f"({_pct(m.terms_lote, m.entradas)})",
        "",
        "| Bloque | Expediente | En lote | En lote / con lotes | Cualquiera |",
        "|---|---:|---:|---:|---:|",
    ]
    for bloque in BLOQUES:
        conteo = m.por_bloque[bloque]
        lineas.append(
            f"| {bloque} | {_pct(conteo['expediente'], m.entradas)} "
            f"| {_pct(conteo['lote'], m.entradas)} "
            f"| {_pct(conteo['lote'], m.con_lotes)} "
            f"| {_pct(conteo['cualquiera'], m.entradas)} |"
        )
    lineas += [
        "",
        f"Criterios extraídos: {m.criterios_filas}; con peso {_pct(m.criterios_con_peso, m.criterios_filas)}, "
        f"con escala deducible {_pct(m.criterios_con_pct, m.criterios_filas)}, "
        f"con tipo {_pct(m.criterios_con_tipo, m.criterios_filas)}, "
        f"con subtipo {_pct(m.criterios_con_subtipo, m.criterios_filas)}, "
        f"con nota {_pct(m.criterios_con_nota, m.criterios_filas)}.",
    ]
    lineas.append(
        f"Requisitos de solvencia económica con umbral en importe: "
        f"{m.solvencia_economica_con_umbral}."
    )
    if m.por_estado:
        lineas += [
            "",
            "| Estado | Entradas | " + " | ".join(BLOQUES) + " |",
            "|---|---:|" + "---:|" * len(BLOQUES),
        ]
        for estado, conteo in sorted(m.por_estado.items(), key=lambda kv: -kv[1]["entradas"]):
            celdas = " | ".join(_pct(conteo.get(b, 0), conteo["entradas"]) for b in BLOQUES)
            lineas.append(f"| {estado} | {conteo['entradas']} | {celdas} |")
        lineas.append("")
    if m.porcentajes_garantia:
        lineas.append(
            f"`AmountRate` de garantía: min {min(m.porcentajes_garantia)}, mediana "
            f"{statistics.median(m.porcentajes_garantia)}, max {max(m.porcentajes_garantia)} "
            f"({len(m.porcentajes_garantia)} valores); con `LiabilityAmount`: "
            f"{m.garantias_con_importe}."
        )
    for titulo, codigos in (
        ("Códigos de tipo de criterio", m.codigos_criterio),
        ("Códigos de tipo de garantía", m.codigos_garantia),
        ("Códigos de solvencia (clase:código)", m.codigos_solvencia),
    ):
        if codigos:
            muestra_codigos = ", ".join(f"`{c}` ({n})" for c, n in codigos.most_common(15))
            lineas.append(f"{titulo}: {muestra_codigos}.")
    return "\n".join(lineas) + "\n"


def _entradas_de_ficheros(rutas: list[Path]) -> Iterator[Any]:
    """Entradas de páginas ATOM o de ZIP mensuales, según la extensión.

    Los ZIP se leen con ``iter_xml_files`` del descargador masivo, que ya
    trae las defensas contra ZIP bomb (ratio, número de entradas, tamaño
    leído en streaming): son datos de fuera, igual que cuando ingiere.
    """
    from lxml import etree

    from scraper.bulk_downloader import iter_xml_files

    parser = etree.XMLParser(huge_tree=False, resolve_entities=False, no_network=True)
    for ruta in rutas:
        if ruta.suffix.lower() == ".zip":
            for _nombre, contenido in iter_xml_files(ruta):
                yield from etree.fromstring(contenido, parser).iter(f"{ATOM}entry")
            continue
        raiz = etree.parse(str(ruta), parser).getroot()
        yield from raiz.iter(f"{ATOM}entry")


def _siguiente(raiz: Any) -> str | None:
    """``rel="next"`` del documento, solo si apunta a un dominio de la Plataforma."""
    for enlace in raiz.findall(f"{ATOM}link"):
        if enlace.get("rel") != "next":
            continue
        href = enlace.get("href") or ""
        host = (urlparse(href).hostname or "").lower()
        if urlparse(href).scheme == "https" and any(
            host == h or host.endswith(f".{h}") for h in _HOSTS_OFICIALES
        ):
            return href
        return None
    return None


def _entradas_en_vivo(paginas: int, guardar: Path | None) -> Iterator[Any]:
    from lxml import etree

    from config import PLACE_LIVE_ATOM_URL
    from scraper.atom_live import fetch_atom_page

    url: str | None = PLACE_LIVE_ATOM_URL
    parser = etree.XMLParser(huge_tree=False, resolve_entities=False, no_network=True)
    for indice in range(paginas):
        if url is None:
            return
        resultado = fetch_atom_page(url)
        if resultado.content is None:
            return
        if guardar is not None:
            guardar.mkdir(parents=True, exist_ok=True)
            (guardar / f"pagina_{indice + 1:02d}.atom").write_bytes(resultado.content)
        raiz = etree.fromstring(resultado.content, parser)
        yield from raiz.iter(f"{ATOM}entry")
        url = _siguiente(raiz)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "ficheros", nargs="*", type=Path, help="páginas ATOM ya descargadas o ZIP mensuales"
    )
    parser.add_argument("--vivo", action="store_true", help="lee el feed en vivo")
    parser.add_argument("--paginas", type=int, default=2, help="páginas a leer con --vivo")
    parser.add_argument("--guardar", type=Path, help="carpeta donde guardar lo leído con --vivo")
    parser.add_argument("--json", action="store_true", help="salida JSON en vez de Markdown")
    args = parser.parse_args(argv)

    if args.vivo == bool(args.ficheros):
        parser.error("pasa ficheros o --vivo, no las dos cosas ni ninguna")

    if args.vivo:
        muestra = f"feed en vivo, {args.paginas} página(s)"
        medicion = medir(_entradas_en_vivo(args.paginas, args.guardar))
    else:
        muestra = ", ".join(p.name for p in args.ficheros)
        medicion = medir(_entradas_de_ficheros(args.ficheros))

    fecha = datetime.now(UTC).date().isoformat()
    if args.json:
        datos = asdict(medicion)
        print(json.dumps({"muestra": muestra, "fecha": fecha, **datos}, ensure_ascii=False))
    else:
        print(informe_markdown(medicion, muestra=muestra, fecha=fecha), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
