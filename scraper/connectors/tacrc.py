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

**Índice completo (2026-10).** El valor por defecto de ``TACRC_INDEX_URL`` es el
índice del Pleno: unas 17 resoluciones doctrinales, no las ~1.900 al año que
dicta el tribunal. El buscador completo (``BuscadordeResoluciones.aspx``) lo
pinta JavaScript y con ``lxml`` no da nada. Lo que sí está a la vista es dónde
viven los PDFs: la biblioteca de SharePoint ``/tacrc/resoluciones/año AAAA/``
(comprobado el 2026-10-12 por las URL de PDFs publicados, p. ej.
``/tacrc/resoluciones/año 2025/recurso 1745-2025 (res 1758) 04-12-2025.pdf``).
Para leerla, este conector acepta además:

- **Un listado JSON** de la API REST de SharePoint (``{"d": {"results": [...]}}``
  o ``{"value": [...]}``, con ``Name`` y ``ServerRelativeUrl`` por fichero),
  que se parsea con los mismos patrones de nombre que el HTML.
- **Una URL con** ``{anio}``, que se recorre año a año, ascendente, desde el año
  del cursor (o ``TACRC_PRIMER_ANIO`` sin cursor) hasta el actual, avanzando el
  cursor tras cada año: un run cortado conserva los años ya escritos. Un año
  que responde 404 no tiene carpeta y no es un error.

La candidata es :data:`URL_BIBLIOTECA_RESOLUCIONES`. **No está verificada**: la
sesión que la escribió no tenía salida a ``hacienda.gob.es``, y que el servidor
sirva su API REST a un visitante anónimo es justo lo que hay que comprobar con
``--check`` antes de fijarla. El valor por defecto no cambia a propósito: en el
plano del worker, sin variable, manda el valor por defecto, y cambiarlo
encendería el índice completo sin decidirlo.

Uso directo:
    python -m scraper.connectors.tacrc            # ingesta incremental
    python -m scraper.connectors.tacrc --check    # valida la URL sin escribir
    python -m scraper.connectors.tacrc --url "<plantilla con {anio}>" --desde-anio 2010
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote, unquote, urlparse

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

#: Marcador de año en una URL de índice que se recorre año a año.
MARCADOR_ANIO = "{anio}"
#: Candidata al índice completo: los ficheros de la carpeta de un año de la
#: biblioteca de resoluciones, por la API REST de SharePoint. Sin verificar
#: (ver docstring del módulo): `--check --url` antes de fijarla.
URL_BIBLIOTECA_RESOLUCIONES = (
    "https://www.hacienda.gob.es/tacrc/_api/web/"
    "GetFolderByServerRelativeUrl('/tacrc/resoluciones/año {anio}')/Files"
    "?$select=Name,ServerRelativeUrl,TimeLastModified"
)
#: La API REST de SharePoint responde Atom XML salvo que se le pida JSON. La
#: forma ``verbose`` la entienden todas sus versiones; ``nometadata``, no.
_ACCEPT_JSON_SHAREPOINT = "application/json;odata=verbose"

_NUM_RESOLUCION_RE = re.compile(r"resoluci[oó]n\s*n?[ºo°.]*\s*(\d{1,5}/\d{4})", re.IGNORECASE)
_NUM_BARE_RE = re.compile(r"\b(\d{1,5}/\d{4})\b")
_NUM_RECURSO_RE = re.compile(r"recurso\s*n?[ºo°.]*\s*(\d{1,5}/\d{4})", re.IGNORECASE)
# Patrones de los PDFs reales del TACRC en hacienda.gob.es, p. ej.
# "Recurso 1443-2025 (Res 1782) 04-12-2025.pdf"
_RECURSO_GUION_RE = re.compile(r"recursos?\s*(\d{1,5})-(\d{4})", re.IGNORECASE)
_RES_PAREN_RE = re.compile(r"\(\s*res\.?\s*(\d{1,5})\s*\)", re.IGNORECASE)
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


def _extraer_numero_recurso(textos: tuple[str, ...]) -> str | None:
    """Número de recurso: prefijo 'Recurso nº NNN/AAAA' o el patrón de los
    PDFs reales del TACRC ('Recurso 1443-2025'), normalizado a NNN/AAAA."""
    for texto in textos:
        m = _NUM_RECURSO_RE.search(texto)
        if m:
            return str(m.group(1))
    for texto in textos:
        m = _RECURSO_GUION_RE.search(texto)
        if m:
            return f"{int(m.group(1))}/{m.group(2)}"
    return None


def _extraer_numero_resolucion(
    textos: tuple[str, ...], numero_recurso: str | None, fecha: str | None
) -> str | None:
    """Número de resolución, en orden de confianza: prefijo explícito
    ('Resolución nº NNN/AAAA'), el patrón de los PDFs reales '(Res NNNN)'
    (año inferido del recurso o de la fecha), y por último un número suelto
    que no sea el del recurso (ambos comparten el formato NNN/AAAA)."""
    for texto in textos:
        m = _NUM_RESOLUCION_RE.search(texto)
        if m:
            return str(m.group(1))
    year = None
    if numero_recurso and "/" in numero_recurso:
        year = numero_recurso.rsplit("/", 1)[-1]
    elif fecha:
        year = fecha[:4]
    if year:
        for texto in textos:
            m = _RES_PAREN_RE.search(texto)
            if m:
                return f"{int(m.group(1))}/{year}"
    for texto in textos:
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

    Si lo que llega es un listado JSON de la biblioteca de SharePoint, lo
    parsea :func:`parse_listado_json` (ver docstring del módulo).
    """
    if not page_html:
        return []
    texto = page_html.decode("utf-8", "replace") if isinstance(page_html, bytes) else page_html
    if texto.lstrip().startswith("{"):
        return parse_listado_json(texto, base_url=base_url)
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
        href_decodificado = unquote(href)
        textos = (texto_link, href_decodificado, texto)
        numero_recurso = _extraer_numero_recurso(textos)
        fecha = _fecha_iso(f"{texto} {href_decodificado}")
        numero = _extraer_numero_resolucion(textos, numero_recurso, fecha)
        es_pdf = href.lower().endswith(".pdf") or "pdf" in href.lower()
        if not numero or not (es_pdf or "resoluci" in href.lower()):
            continue
        expediente = _EXPEDIENTE_RE.search(texto)
        res = Resolucion(
            numero_resolucion=numero,
            numero_recurso=numero_recurso,
            fecha=fecha,
            expediente=expediente.group(1) if expediente else None,
            sentido=_sentido(texto),
            url_pdf=href if es_pdf else None,
            resumen=texto[:500] or None,
        )
        previa = vistas.get(numero)
        if previa is None or (res.url_pdf and not previa.url_pdf):
            vistas[numero] = res
    return list(vistas.values())


def parse_listado_json(texto: str, base_url: str = "") -> list[Resolucion]:
    """Resoluciones de un listado JSON de la biblioteca de SharePoint.

    Acepta las dos formas de la API REST (``odata=verbose`` →
    ``{"d": {"results": [...]}}``, ``odata=nometadata`` → ``{"value": [...]}``)
    y, por fichero, ``Name``/``ServerRelativeUrl`` (``Files``) o
    ``FileLeafRef``/``FileRef`` (elementos de lista). Del nombre salen recurso,
    resolución y fecha con los mismos patrones que del HTML; la URL del PDF es
    la ruta del fichero sobre el host de *base_url*. Lo que no es un PDF
    —carpetas, ``Forms``— se ignora, y un JSON que no es un listado (un error
    de la API) da una lista vacía, no una excepción: ``--check`` lo dice.
    """
    try:
        datos = json.loads(texto)
    except ValueError:
        return []
    filas: Any = []
    if isinstance(datos, dict):
        filas = datos.get("value")
        if filas is None and isinstance(datos.get("d"), dict):
            filas = datos["d"].get("results")
    if not isinstance(filas, list):
        return []
    partes = urlparse(base_url)
    origen = f"{partes.scheme}://{partes.netloc}" if partes.scheme and partes.netloc else ""

    vistas: dict[str, Resolucion] = {}
    for fila in filas:
        if not isinstance(fila, dict):
            continue
        nombre = str(fila.get("Name") or fila.get("FileLeafRef") or "")
        ruta = str(fila.get("ServerRelativeUrl") or fila.get("FileRef") or "")
        if not nombre.lower().endswith(".pdf"):
            continue
        textos = (nombre, unquote(ruta))
        numero_recurso = _extraer_numero_recurso(textos)
        fecha = _fecha_iso(nombre)
        numero = _extraer_numero_resolucion(textos, numero_recurso, fecha)
        if not numero:
            continue
        url_pdf = f"{origen}{quote(ruta, safe='/()')}" if origen and ruta.startswith("/") else None
        res = Resolucion(
            numero_resolucion=numero,
            numero_recurso=numero_recurso,
            fecha=fecha,
            url_pdf=url_pdf,
            resumen=nombre[:500],
        )
        previa = vistas.get(numero)
        if previa is None or (res.url_pdf and not previa.url_pdf):
            vistas[numero] = res
    return list(vistas.values())


def _hoy() -> date:
    return datetime.now(UTC).date()


def urls_del_indice(
    index_url: str, *, desde_anio: int | None = None, hoy: date | None = None
) -> list[tuple[int | None, str]]:
    """Las páginas que recorre una pasada, con su año (``None`` si no va por años).

    Sin :data:`MARCADOR_ANIO`, una sola página: el comportamiento de siempre.
    Con él, de *desde_anio* (o ``TACRC_PRIMER_ANIO``) al año de *hoy*, en orden
    ascendente: es el orden que deja avanzar el cursor año a año.
    """
    if MARCADOR_ANIO not in index_url:
        return [(None, index_url)]
    hasta = (hoy or _hoy()).year
    inicio = desde_anio if desde_anio is not None else settings.TACRC_PRIMER_ANIO
    return [
        (anio, index_url.replace(MARCADOR_ANIO, str(anio))) for anio in range(inicio, hasta + 1)
    ]


def fetch_index(index_url: str | None = None, *, session: requests.Session | None = None) -> str:
    url = index_url or settings.TACRC_INDEX_URL
    if not url:
        raise RuntimeError(
            "TACRC_INDEX_URL no configurada. Validá el índice vivo con "
            "`python -m scraper.connectors.tacrc --check --url <url>` y fijala "
            "por entorno (regla operativa del RFC 20260611-1)."
        )
    if "/_api/" in url:
        resp = (session or requests).get(
            url, timeout=_TIMEOUT, headers={"Accept": _ACCEPT_JSON_SHAREPOINT}
        )
    else:
        resp = (session or requests).get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    return str(resp.text)


def _es_404(exc: BaseException) -> bool:
    respuesta = getattr(exc, "response", None)
    return isinstance(exc, requests.HTTPError) and getattr(respuesta, "status_code", None) == 404


def run(
    index_url: str | None = None,
    *,
    session: requests.Session | None = None,
    desde_anio: int | None = None,
    hoy: date | None = None,
) -> dict[str, Any]:
    """Ciclo completo de ingesta TACRC: fetch → parse → upsert → vinculación.

    Cursor ``tacrc`` (last_seen_updated = fecha máxima vista): en ejecuciones
    incrementales solo se upsertan resoluciones con fecha >= cursor - el
    upsert idempotente absorbe el solape. Fallos de fetch van a la DLQ sin
    avanzar el cursor.

    Con un índice por años (:data:`MARCADOR_ANIO`) se recorre desde el año del
    cursor y el cursor avanza tras cada año; el primer año que falla corta la
    pasada —saltarlo y seguir movería el cursor por encima de él y no se
    volvería a pedir nunca—. *desde_anio* fuerza un backfill desde ese año e
    ignora el cursor. *hoy* existe para los tests.
    """
    from scraper.connectors.base import record_source_health, record_source_started

    url = index_url or settings.TACRC_INDEX_URL
    stats: dict[str, Any] = {"fetched": 0, "nuevas": 0, "actualizadas": 0, "errores": 0}
    cursor = get_cursor(SOURCE_ID)
    last_seen = "" if desde_anio is not None else str((cursor or {}).get("last_seen_updated") or "")
    anio_cursor = int(last_seen[:4]) if last_seen[:4].isdigit() else None
    # TACRC no pasa por ``run_connector`` (tiene runner ligero propio), así que
    # hasta 2026-09 era la única fuente que NO escribía
    # ``source_ingestion_health``: para cualquier chequeo de frescura era
    # indistinguible de una fuente muerta.
    record_source_started(SOURCE_ID)

    procesadas = parsed = 0
    cursor_escrito = last_seen
    for anio, url_pagina in urls_del_indice(url, desde_anio=desde_anio or anio_cursor, hoy=hoy):
        try:
            page = fetch_index(url_pagina, session=session)
            items = parse_index(page, base_url=url_pagina)
        except Exception as e:
            if anio is not None and _es_404(e):
                log.info("tacrc_anio_sin_indice", anio=anio)
                continue
            stats["errores"] += 1
            record_failure(None, SOURCE_ID, e, scope="fetch")
            log.error("tacrc_run_failed", error=str(e), anio=anio)
            break
        procesadas += 1
        stats["fetched"] += len(items)
        if last_seen:
            items = [r for r in items if not r.fecha or r.fecha >= last_seen]
        parsed += len(items)
        nuevas, actualizadas = upsert_resoluciones(items)
        stats["nuevas"] += nuevas
        stats["actualizadas"] += actualizadas
        fechas = [r.fecha for r in items if r.fecha]
        if fechas and max(fechas) > cursor_escrito:
            cursor_escrito = max(fechas)
            set_cursor(SOURCE_ID, last_seen_updated=cursor_escrito)

    if not procesadas and stats["errores"]:
        record_source_health(SOURCE_ID, status="failed", errors=int(stats["errores"]))
        return stats

    link_stats = link_unlinked()
    stats.update(link_stats)
    log.info("tacrc_run_done", **stats)
    record_source_health(
        SOURCE_ID,
        status="partial" if stats["errores"] else "success",
        fetched=int(stats["fetched"]),
        parsed=parsed,
        errors=int(stats["errores"]),
    )
    return stats


def ejecutar(
    *, index_url: str | None = None, desde_anio: int | None = None
) -> dict[str, Any] | None:
    """Una pasada de TACRC; ``None`` si la fuente está apagada.

    Sin índice configurado la fuente está APAGADA, no rota (S2.5): se declara
    ``disabled`` en ``ops_events`` en vez de lanzar desde ``fetch_index``.
    La usan ``main`` y el carril diario del worker
    (``scheduler/jobs/daily_atom.py``). No abre ni cierra la BD: el worker
    comparte el pool con la cola, y ``close_pool()`` se la llevaría por delante.
    """
    if not (index_url or settings.TACRC_INDEX_URL):
        from scraper.connectors.base import record_source_disabled

        record_source_disabled(
            SOURCE_ID,
            motivo=(
                "TACRC_INDEX_URL no configurada; validá el índice vivo con "
                "`python -m scraper.connectors.tacrc --check --url <url>`"
            ),
        )
        return None
    return run(index_url, desde_anio=desde_anio)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Ingesta de resoluciones TACRC")
    parser.add_argument("--url", help="Override de TACRC_INDEX_URL")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Solo valida la URL del índice (fetch + parse, sin escribir en BD)",
    )
    parser.add_argument(
        "--dump",
        metavar="ARCHIVO",
        help="Con --check: guarda el HTML recibido para diagnóstico del parser",
    )
    parser.add_argument(
        "--desde-anio",
        type=int,
        help=(
            f"Con una URL por años ({MARCADOR_ANIO}): backfill desde ese año, ignorando el cursor"
        ),
    )
    args = parser.parse_args(argv)

    if args.check:
        # Con un índice por años se mira solo el año en curso: basta para saber
        # si la URL responde y el parser la entiende, sin bajar todo el histórico.
        url_check = urls_del_indice(
            args.url or settings.TACRC_INDEX_URL, desde_anio=_hoy().year, hoy=_hoy()
        )[-1][1]
        page = fetch_index(url_check)
        if args.dump:
            from pathlib import Path

            Path(args.dump).write_text(page, encoding="utf-8")
            print(f"HTML recibido guardado en {args.dump} ({len(page)} bytes)")
        items = parse_index(page, base_url=url_check)
        print(f"TACRC --check: {len(items)} resoluciones detectadas en el índice")
        for res in items[:5]:
            print(f"  {res.numero_resolucion}  fecha={res.fecha}  sentido={res.sentido}")
        if not items:
            print(
                "Sin resultados: la página probablemente carga el listado por JS. "
                "Reintentá con --dump diagnostico.html para inspeccionar lo recibido, "
                "o localizá en las DevTools del navegador (pestaña Network) la URL "
                "de la petición que devuelve el listado y pasala con --url."
            )
        return 0 if items else 1

    from db.database import close_pool, init_db

    init_db()
    try:
        stats = ejecutar(index_url=args.url, desde_anio=args.desde_anio)
    finally:
        close_pool()
    if stats is None:
        print("TACRC: sin TACRC_INDEX_URL configurada — fuente declarada 'disabled'.")
        return 0
    print(
        f"TACRC: {stats['fetched']} resoluciones · {stats['nuevas']} nuevas · "
        f"{stats['actualizadas']} actualizadas · {stats.get('vinculadas', 0)} vinculadas · "
        f"{stats.get('eventos', 0)} eventos · {stats['errores']} errores"
    )
    return 0 if stats["errores"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
