"""Cliente para el feed ATOM en vivo paginado de PLACE.

Consume el feed de sindicación oficial con paginación ``rel="next"`` y
soporte para ``ETag`` / ``If-Modified-Since`` (caché condicional).
Reutiliza el circuit breaker y retry de ``scraper.resilience``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, cast

import requests
from lxml import etree

from config import (
    PLACE_LIVE_ATOM_URL,
    USER_AGENT,
    settings,
)
from observability.logging import get_logger
from observability.ops_events import record_event
from scraper.resilience import http_retry, placsp_breaker

log = get_logger(__name__)

ATOM_NS = "http://www.w3.org/2005/Atom"


@dataclass
class FetchResult:
    """Resultado de una petición a una página del feed ATOM."""

    content: bytes | None  # None si 304 Not Modified
    status_code: int
    etag: str | None = None
    last_modified: str | None = None


@placsp_breaker
@http_retry
def fetch_atom_page(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
) -> FetchResult:
    """Descarga una página del feed ATOM con caché condicional."""
    headers: dict[str, str] = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    resp = requests.get(url, headers=headers, timeout=settings.REQUEST_TIMEOUT)
    resp.raise_for_status()

    if resp.status_code == 304:
        log.info("atom_page_not_modified", url=url)
        return FetchResult(
            content=None,
            status_code=304,
            etag=etag,
            last_modified=last_modified,
        )

    content = resp.content
    if len(content) > settings.MAX_XML_SIZE_BYTES:
        raise ValueError(
            f"Página ATOM demasiado grande: {len(content):,} bytes "
            f"(límite: {settings.MAX_XML_SIZE_BYTES:,})."
        )

    return FetchResult(
        content=content,
        status_code=resp.status_code,
        etag=resp.headers.get("ETag"),
        last_modified=resp.headers.get("Last-Modified"),
    )


def _parse_feed_links(root: etree._Element) -> str | None:
    """Extrae la URL ``rel="next"`` de un documento ATOM.

    Solo acepta URLs bajo el dominio oficial de PLACE para prevenir SSRF.
    """
    for link in root.findall(f"{{{ATOM_NS}}}link"):
        if link.get("rel") == "next":
            href = link.get("href")
            if href and _is_allowed_url(href):
                return cast(str, href)
            log.warning("atom_next_link_rejected", href=href)
            return None
    return None


# PLACE sirve el feed ATOM bajo el dominio .gob.es pero los links de
# paginación rel="next" pueden apuntar al dominio histórico
# contrataciondelestado.es (mismo usado como PLACE_BASE_URL en
# config/constants.py) — ambos son dominios oficiales de la plataforma.
_ALLOWED_HOSTS = ("contrataciondelsectorpublico.gob.es", "contrataciondelestado.es")


def _is_allowed_url(url: str) -> bool:
    """Valida que la URL pertenezca a un dominio oficial de PLACE."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("https", "http"):
        return False
    host = (parsed.hostname or "").lower()
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in _ALLOWED_HOSTS)


def _entry_updated(entry: etree._Element) -> str | None:
    """Extrae el valor ``<updated>`` de una entry ATOM."""
    el = entry.find(f"{{{ATOM_NS}}}updated")
    if el is not None and el.text:
        return cast(str, el.text.strip())
    return None


def iter_live_entries(
    *,
    last_seen_updated: str | None = None,
    max_pages: int | None = None,
    start_url: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
) -> tuple[list[tuple[etree._Element, str]], dict[str, Any]]:
    """Pagina el feed ATOM en vivo y devuelve entries más recientes que el cursor.

    Args:
        last_seen_updated: ISO timestamp del cursor. Solo se devuelven entries
            con ``<updated>`` estrictamente posterior. ``None`` = primera ejecución
            (solo primera página como bootstrap conservador).
        max_pages: Límite de páginas a recorrer (default: ``DAILY_MAX_PAGES``).
        start_url: URL de la primera página (default: ``PLACE_LIVE_ATOM_URL``).
        etag, last_modified: los del cursor anterior. Solo viajan con la primera
            página: un 304 dice que la cabecera del feed no cambió y la pasada
            termina sin leer nada (``stopped_reason="not_modified"``).

    Returns:
        Tupla ``(entries, meta)`` donde:
        - ``entries`` es lista de ``(entry_element, updated_str)`` ordenada
          de más nueva a más vieja.
        - ``meta`` es dict con ``newest_updated``, ``pages_fetched``,
          ``entries_seen``, ``etag``, ``last_modified``.
    """
    url: str | None = start_url or PLACE_LIVE_ATOM_URL
    limit = max_pages or settings.DAILY_MAX_PAGES
    is_bootstrap = last_seen_updated is None

    collected: list[tuple[etree._Element, str]] = []
    meta: dict[str, Any] = {
        "newest_updated": None,
        "pages_fetched": 0,
        "entries_seen": 0,
        "etag": None,
        "last_modified": None,
        "stopped_reason": "exhausted",
    }

    first_page = True
    stop = False

    for _ in range(limit):
        if url is None or stop:
            break

        if first_page:
            result = fetch_atom_page(url, etag=etag, last_modified=last_modified)
        else:
            result = fetch_atom_page(url)
        meta["pages_fetched"] += 1

        if first_page:
            meta["etag"] = result.etag
            meta["last_modified"] = result.last_modified
            first_page = False

        if result.content is None:
            # 304 Not Modified — nada nuevo
            meta["stopped_reason"] = "not_modified"
            break

        parser = etree.XMLParser(
            huge_tree=False, recover=True, resolve_entities=False, no_network=True
        )
        root = etree.fromstring(result.content, parser=parser)

        for entry in root.findall(f"{{{ATOM_NS}}}entry"):
            updated = _entry_updated(entry)
            meta["entries_seen"] += 1

            if updated is None:
                # Sin <updated> — incluir pero no usar como cursor
                collected.append((entry, ""))
                continue

            # Actualizar el timestamp más nuevo visto
            if meta["newest_updated"] is None or updated > meta["newest_updated"]:
                meta["newest_updated"] = updated

            # Comprobar si la entry es anterior al cursor
            if last_seen_updated and updated <= last_seen_updated:
                stop = True
                meta["stopped_reason"] = "cursor_reached"
                break

            collected.append((entry, updated))

        if stop:
            break

        # En modo bootstrap (sin cursor), solo procesar la primera página
        if is_bootstrap:
            meta["stopped_reason"] = "bootstrap"
            break

        url = _parse_feed_links(root)
        if url is None:
            meta["stopped_reason"] = "no_next_link"

        # Delay entre páginas para no saturar PLACE
        if url:
            time.sleep(settings.REQUEST_DELAY_SECONDS)

    if meta["stopped_reason"] == "exhausted" and last_seen_updated:
        # Tope de páginas sin llegar al cursor: entre la última página leída y
        # el cursor queda un hueco que esta pasada no ha visto. Ver
        # :func:`cursor_siguiente`, que por eso no avanza el cursor.
        mas_viejo = next((u for _, u in reversed(collected) if u), None)
        log.warning(
            "atom_live_tope_sin_cursor",
            pages=meta["pages_fetched"],
            cursor=last_seen_updated,
            mas_viejo_leido=mas_viejo,
            start_url=start_url or PLACE_LIVE_ATOM_URL,
        )
        record_event(
            EVENTO_TOPE_SIN_CURSOR,
            value=meta["pages_fetched"],
            detail=f"cursor={last_seen_updated};mas_viejo_leido={mas_viejo}",
        )

    log.info(
        "atom_live_iteration_done",
        pages=meta["pages_fetched"],
        entries_seen=meta["entries_seen"],
        entries_collected=len(collected),
        newest=meta["newest_updated"],
        stopped=meta["stopped_reason"],
    )

    return collected, meta


#: Evento de ``ops_events`` de una pasada que agotó el tope sin llegar al cursor.
EVENTO_TOPE_SIN_CURSOR = "atom_live_tope_sin_cursor"


def cursor_siguiente(meta: dict[str, Any], last_seen_updated: str | None) -> dict[str, Any] | None:
    """El cursor que deja una pasada de :func:`iter_live_entries`.

    El feed va de más nuevo a más viejo. Si la pasada agota ``DAILY_MAX_PAGES``
    sin llegar al cursor (``stopped_reason="exhausted"``), avanzar al
    ``newest_updated`` daba por leído el hueco entre la última página y el
    cursor viejo, y nadie volvía a pedirlo. Se conserva entonces el cursor
    anterior —sin ``etag``, para que la próxima pasada no se quede en un 304—:
    lo leído ya está escrito (el upsert es idempotente) y, en el feed de
    ``placsp``, un cursor que no avanza es justo lo que dispara el respaldo al
    ZIP mensual (``scheduler/respaldo_zip_placsp.py``).
    """
    if meta.get("stopped_reason") == "exhausted" and last_seen_updated:
        return {"last_seen_updated": last_seen_updated, "etag": None, "last_modified": None}
    newest = meta.get("newest_updated") or last_seen_updated
    if newest is None and not meta.get("etag"):
        return None
    return {
        "last_seen_updated": newest,
        "etag": meta.get("etag"),
        "last_modified": meta.get("last_modified"),
    }
