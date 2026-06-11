"""Conector TACRC — índice público de resoluciones del Ministerio de Hacienda.

El TACRC no produce licitaciones, así que no se fuerza en ``ParsedTender`` ni
en ``run_connector``: tiene su camino de ingesta ligero propio que SÍ
reutiliza los cursores (``ingestion_cursors``, source ``tacrc``) y la DLQ
(RFC 20260611-1 §5.3).

v1 = solo metadatos + URL del PDF (la extracción de texto del PDF queda fuera
de alcance). El índice es HTML; el parser es deliberadamente tolerante: busca
filas/enlaces con número de resolución (``NNN/AAAA``) y extrae del texto
circundante recurso, fecha y sentido cuando aparecen.

La URL del índice no va hardcodeada (misma regla operativa que PSCP):
configurá ``TACRC_INDEX_URL`` tras validarla con ``--check``.

Uso directo:
    python -m scraper.connectors.tacrc            # ingesta incremental
    python -m scraper.connectors.tacrc --check    # valida la URL sin escribir
"""

from __future__ import annotations

import re
from typing import Any

import requests
from lxml import html as lxml_html

from config import settings
from db.database import get_cursor, set_cursor
from db.dlq import record_failure
from observability import get_logger
from services.resoluciones import Resolucion, link_unlinked, upsert_resoluciones

log = get_logger(__name__)

SOURCE_ID = "tacrc"
_TIMEOUT = 60

_NUM_RESOLUCION_RE = re.compile(r"resoluci[oó]n\s*n?[ºo°.]*\s*(\d{1,5}/\d{4})", re.IGNORECASE)
_NUM_BARE_RE = re.compile(r"\b(\d{1,5}/\d{4})\b")
_NUM_RECURSO_RE = re.compile(r"recurso\s*n?[ºo°.]*\s*(\d{1,5}/\d{4})", re.IGNORECASE)
_FECHA_RE = re.compile(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})")
_FECHA_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_EXPEDIENTE_RE = re.compile(r"expediente\s*[:\s]\s*([A-Za-z0-9][\w\./\-]{2,40})", re.IGNORECASE)

# Texto folded → sentido canónico. El orden importa: "desestima" contiene
# "estima", así que los negativos van primero.
_SENTIDOS = (
    ("desestim", "desestimado"),
    ("inadmi", "inadmitido"),
    ("desist", "desistimiento"),
    ("estim", "estimado"),
)


def _fecha_iso(text: str) -> str | None:
    m = _FECHA_ISO_RE.search(text)
    if m:
        return str(m.group(0))
    m = _FECHA_RE.search(text)
    if not m:
        return None
    dd, mm, yyyy = m.groups()
    return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"


def _sentido(text: str) -> str | None:
    from services.normalization import fold_text

    folded = fold_text(text)
    for needle, sentido in _SENTIDOS:
        if needle in folded:
            return sentido
    return None


def _extraer_numero_resolucion(
    texto_link: str, texto_fila: str, numero_recurso: str | None
) -> str | None:
    """Número de resolución: prefijo explícito primero; un número suelto solo
    si no es el del recurso (ambos comparten el formato NNN/AAAA)."""
    for texto in (texto_link, texto_fila):
        m = _NUM_RESOLUCION_RE.search(texto)
        if m:
            return m.group(1)
    for texto in (texto_link, texto_fila):
        candidatos = [str(n) for n in _NUM_BARE_RE.findall(texto) if n != numero_recurso]
        if candidatos:
            return candidatos[0]
    return None


def parse_index(page_html: str | bytes, base_url: str = "") -> list[Resolucion]:
    """Extrae resoluciones del índice HTML.

    Recorre los enlaces de la página; un enlace es una resolución si su texto
    o el de su fila contienen un número ``NNN/AAAA``. El contexto (la fila
    ``<tr>`` o ``<li>`` contenedora, o el propio texto del enlace) aporta el
    resto de metadatos. Deduplica por número de resolución.
    """
    if not page_html:
        return []
    tree = lxml_html.fromstring(page_html)
    if base_url:
        tree.make_links_absolute(base_url)

    vistas: dict[str, Resolucion] = {}
    for link in tree.iter("a"):
        href = link.get("href") or ""
        if not href or href.startswith(("#", "javascript:")):
            continue
        contexto = link
        for _ in range(4):  # subir hasta la fila/item contenedor
            parent = contexto.getparent()
            if parent is None or parent.tag in ("tr", "li", "article", "body"):
                contexto = parent if parent is not None else contexto
                break
            contexto = parent
        texto = " ".join((contexto if contexto is not None else link).itertext())
        texto = re.sub(r"\s+", " ", texto).strip()

        texto_link = " ".join(link.itertext())
        recurso = _NUM_RECURSO_RE.search(texto)
        numero = _extraer_numero_resolucion(
            texto_link, texto, recurso.group(1) if recurso else None
        )
        es_pdf = href.lower().endswith(".pdf") or "pdf" in href.lower()
        if not numero or not (es_pdf or "resoluci" in href.lower()):
            continue
        expediente = _EXPEDIENTE_RE.search(texto)
        res = Resolucion(
            numero_resolucion=numero,
            numero_recurso=recurso.group(1) if recurso else None,
            fecha=_fecha_iso(texto),
            expediente=expediente.group(1) if expediente else None,
            sentido=_sentido(texto),
            url_pdf=href if es_pdf else None,
            resumen=texto[:500] or None,
        )
        previa = vistas.get(numero)
        if previa is None or (res.url_pdf and not previa.url_pdf):
            vistas[numero] = res
    return list(vistas.values())


def fetch_index(index_url: str | None = None, *, session: requests.Session | None = None) -> str:
    url = index_url or settings.TACRC_INDEX_URL
    if not url:
        raise RuntimeError(
            "TACRC_INDEX_URL no configurada. Validá el índice vivo con "
            "`python -m scraper.connectors.tacrc --check --url <url>` y fijala "
            "por entorno (regla operativa del RFC 20260611-1)."
        )
    resp = (session or requests).get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def run(
    index_url: str | None = None, *, session: requests.Session | None = None
) -> dict[str, Any]:
    """Ciclo completo de ingesta TACRC: fetch → parse → upsert → vinculación.

    Cursor ``tacrc`` (last_seen_updated = fecha máxima vista): en ejecuciones
    incrementales solo se upsertan resoluciones con fecha >= cursor - el
    upsert idempotente absorbe el solape. Fallos de fetch van a la DLQ sin
    avanzar el cursor.
    """
    stats: dict[str, Any] = {"fetched": 0, "nuevas": 0, "actualizadas": 0, "errores": 0}
    cursor = get_cursor(SOURCE_ID)
    last_seen = str((cursor or {}).get("last_seen_updated") or "")
    try:
        page = fetch_index(index_url, session=session)
        items = parse_index(page, base_url=index_url or settings.TACRC_INDEX_URL)
    except Exception as e:
        stats["errores"] += 1
        record_failure(None, SOURCE_ID, e, scope="fetch")
        log.error("tacrc_run_failed", error=str(e))
        return stats

    stats["fetched"] = len(items)
    if last_seen:
        items = [r for r in items if not r.fecha or r.fecha >= last_seen]
    nuevas, actualizadas = upsert_resoluciones(items)
    stats["nuevas"], stats["actualizadas"] = nuevas, actualizadas

    link_stats = link_unlinked()
    stats.update(link_stats)

    fechas = [r.fecha for r in items if r.fecha]
    if fechas:
        set_cursor(SOURCE_ID, last_seen_updated=max(fechas))
    log.info("tacrc_run_done", **stats)
    return stats


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Ingesta de resoluciones TACRC")
    parser.add_argument("--url", help="Override de TACRC_INDEX_URL")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Solo valida la URL del índice (fetch + parse, sin escribir en BD)",
    )
    args = parser.parse_args(argv)

    if args.check:
        items = parse_index(fetch_index(args.url), base_url=args.url or settings.TACRC_INDEX_URL)
        print(f"TACRC --check: {len(items)} resoluciones detectadas en el índice")
        for res in items[:5]:
            print(f"  {res.numero_resolucion}  fecha={res.fecha}  sentido={res.sentido}")
        return 0 if items else 1

    from db.database import init_db

    init_db()
    stats = run(args.url)
    print(
        f"TACRC: {stats['fetched']} resoluciones · {stats['nuevas']} nuevas · "
        f"{stats['actualizadas']} actualizadas · {stats.get('vinculadas', 0)} vinculadas · "
        f"{stats.get('eventos', 0)} eventos · {stats['errores']} errores"
    )
    return 0 if stats["errores"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
