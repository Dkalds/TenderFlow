"""Base conservadora para feeds RSS autonómicos de contratación.

Los RSS se tratan como cobertura de descubrimiento, no como un censo de
mercado: solo se persisten avisos con señal tecnológica y se conserva el
origen/fecha publicada para que el SLA pueda declarar esa limitación.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET  # nosec B405 -- nosemgrep: use-defused-xml -- ver mitigación junto a ET.fromstring más abajo
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import requests

from db.upsert import Licitacion
from scraper.connectors.base import ParsedTender, RawNotice
from scraper.filters import matches_technology

if TYPE_CHECKING:
    from collections.abc import Iterator

_TIMEOUT = 45
_MAX_FEED_BYTES = 5 * 1024 * 1024
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_DATE_RE = re.compile(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?:\s+(\d{1,2}):(\d{2}))?")
_ID_RE = re.compile(r"(?:\bID\s*:\s*|[?&]N=)([A-Za-z0-9._/-]+)", re.IGNORECASE)


def _plain(value: str | None) -> str:
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", value or ""))).strip()


def _date(value: str | None) -> str | None:
    """Fecha ISO sin pretender interpretar el locale del ``pubDate`` RSS."""
    match = _DATE_RE.search(value or "")
    if not match:
        return None
    day, month, year, hour, minute = match.groups()
    suffix = f"T{int(hour):02d}:{int(minute):02d}:00+00:00" if hour else ""
    return f"{year}-{int(month):02d}-{int(day):02d}{suffix}"


def _amount(value: str) -> float | None:
    match = re.search(r"([\d.]+(?:,\d{1,2})?)\s*(?:€|&euro;|\beur\b)", value, re.IGNORECASE)
    if not match:
        return None
    raw = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _label(text: str, labels: tuple[str, ...]) -> str | None:
    # Cada valor viene tras ``<b>Etiqueta:</b> valor </p>``.  El corte por
    # etiquetas conocidas evita inventar una estructura DOM que los feeds no
    # prometen mantener.
    for label in labels:
        match = re.search(
            rf"{re.escape(label)}\s*:\s*(.+?)(?=(?:Estado|Órgano|Organo|Tipo|Importe|Data|Fecha|Sistema|Lugar)\s*:|$)",
            text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip().strip("-;").strip() or None
    return None


class RegionalRssConnector:
    """Implementación común para un RSS oficial con id namespaceado."""

    source_id: str
    feed_url: str
    ccaa: str
    analysis_universe: str

    def __init__(
        self, *, feed_url: str | None = None, session: requests.Session | None = None
    ) -> None:
        self._feed_url = feed_url or self.feed_url
        self._session = session or requests.Session()
        self._max_seen: str | None = None

    def fetch(self, cursor: dict[str, Any] | None) -> Iterator[RawNotice]:
        response = self._session.get(self._feed_url, timeout=_TIMEOUT)
        response.raise_for_status()
        content = response.content
        if len(content) > _MAX_FEED_BYTES:
            raise ValueError("El feed regional supera el límite seguro de 5 MiB.")
        lowered = content.lower()
        if b"<!doctype" in lowered or b"<!entity" in lowered:
            raise ValueError("El feed regional contiene declaraciones XML no permitidas.")
        # ElementTree es suficiente tras limitar tamaño y rechazar DTD/entidades.
        root = ET.fromstring(content)  # noqa: S314  # nosec B314
        previous = str((cursor or {}).get("last_seen_updated") or "")
        for item in root.findall("./channel/item"):
            title = _plain(item.findtext("title"))
            link = _plain(item.findtext("link"))
            description = "".join(item.itertext()) if item.find("description") is not None else ""
            published = _date(_plain(item.findtext("pubDate"))) or _date(description)
            natural_id = self._natural_id(title, link, _plain(item.findtext("guid")))
            if not natural_id:
                continue
            if published and previous and published < previous:
                continue
            if published and (self._max_seen is None or published > self._max_seen):
                self._max_seen = published
            yield RawNotice(
                natural_id=natural_id,
                payload={
                    "title": title,
                    "link": link,
                    "description": description,
                    "published": published,
                },
            )

    @staticmethod
    def _natural_id(title: str, link: str, guid: str) -> str | None:
        for value in (link, guid, title):
            query = parse_qs(urlparse(value).query)
            if query.get("N"):
                return query["N"][0]
            match = _ID_RE.search(value)
            if match:
                return match.group(1)
        return None

    def parse(self, raw: RawNotice) -> ParsedTender | None:
        payload = raw.payload
        title = str(payload["title"])
        description = _plain(str(payload.get("description") or ""))
        # Algunos feeds añaden " - ID: nnn" al título: no es parte del objeto.
        tender_title = re.sub(r"\s*-\s*ID\s*:\s*\S+\s*$", "", title, flags=re.IGNORECASE).strip()
        if not tender_title:
            return None
        _, matches = matches_technology(f"{tender_title} {description}", None)
        if not matches:
            return None
        technologies = sorted(matches)
        keywords = sorted({keyword for values in matches.values() for keyword in values})
        published = payload.get("published")
        lic = Licitacion(
            id_externo=f"{self.source_id}:{raw.natural_id}",
            titulo=tender_title[:500],
            organo_contratacion=_label(
                description, ("Órgano de contratación", "Organo de contratacion", "Órgano")
            ),
            importe=_amount(description),
            tipo_contrato=_label(description, ("Tipo de contrato",)),
            estado=_label(description, ("Estado",)),
            fecha_publicacion=published[:10] if isinstance(published, str) else None,
            fecha_limite=_date(
                _label(
                    description,
                    (
                        "Data e hora límite de presentación de ofertas",
                        "Fecha y hora límite de presentación de ofertas",
                        "Fecha límite",
                    ),
                )
            ),
            url=str(payload.get("link") or "") or None,
            raw_keywords=",".join(keywords) or None,
            tecnologia=",".join(technologies) or None,
            ccaa=self.ccaa,
            inclusion_reason="regional_rss_technology_match",
            analysis_universe=self.analysis_universe,
            fecha_actualizacion_fuente=published if isinstance(published, str) else None,
            fuente=self.source_id,
        )
        return ParsedTender(licitacion=lic)

    def new_cursor(self) -> dict[str, Any] | None:
        return {"last_seen_updated": self._max_seen} if self._max_seen else None
