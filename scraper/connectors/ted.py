"""Conector TED — Search API v3 (contratos UE sobre umbrales armonizados).

API pública sin autenticación: ``POST https://api.ted.europa.eu/v3/notices/search``
con sintaxis de expert query. Filtra por país de ejecución España y familias
CPV configurables (por defecto 48 software y 72 servicios TI).

Mapeo eForms → modelo canónico:
- ``id_externo`` = ``ted:{publication-number}`` (namespacing ADR-009).
- Campos multilingües (notice-title, buyer-name…): preferencia spa → eng →
  primer idioma disponible.
- ``notice-type``: cn-* (convocatoria) → estado PUB; can-* (adjudicación/
  resultado) → RES, con Adjudicacion si trae winner-name; pin-* → PRE.
- ``place-of-performance``: primer código NUTS provincial → ccaa vía
  shared.geo.

Uso directo (backfill o cron):
    python -m scraper.connectors.ted                 # incremental desde cursor
    python -m scraper.connectors.ted --desde 20250101 --cpv 48,72
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import requests

from db.upsert import Adjudicacion, Licitacion
from observability import get_logger
from scraper.connectors.base import ParsedTender, RawNotice
from scraper.filters import matches_technology
from shared.geo import nuts_to_ccaa

if TYPE_CHECKING:
    from collections.abc import Iterator

log = get_logger(__name__)

SOURCE_ID = "ted"
_API_URL = "https://api.ted.europa.eu/v3/notices/search"
_PAGE_SIZE = 100
_TIMEOUT = 60
_PAGE_PAUSE_S = 0.5  # cortesía con la API pública

_FIELDS = [
    "publication-number",
    "notice-title",
    "description-proc",
    "buyer-name",
    "classification-cpv",
    "publication-date",
    "deadline-receipt-tender-date-lot",
    "notice-type",
    "links",
    "estimated-value-proc",
    "result-value-notice",
    "winner-name",
    "place-of-performance",
    "contract-nature",
]

# notice-type eForms → estado canónico (códigos PLACSP)
_ESTADO_MAP = {
    "pin": "PRE",  # prior information notice
    "cn": "PUB",  # contract notice
    "can": "RES",  # contract award notice (incl. can-modif)
}


def _first_lang(value: Any) -> str | None:
    """Extrae el texto de un campo multilingüe eForms (spa → eng → primero)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return str(value[0]) if value else None
    if isinstance(value, dict):
        for lang in ("spa", "eng"):
            if lang in value:
                return _first_lang(value[lang])
        for v in value.values():
            return _first_lang(v)
    return None


def _first_date(value: Any) -> str | None:
    """Normaliza fechas eForms ('2026-06-01+02:00' o lista) a YYYY-MM-DD."""
    if isinstance(value, list):
        value = value[0] if value else None
    if not value or not isinstance(value, str):
        return None
    return str(value)[:10]


def _to_float(value: Any) -> float | None:
    if isinstance(value, list):
        value = value[0] if value else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _nuts_provincial(value: Any) -> str | None:
    """Primer código NUTS por debajo de país (p. ej. ES703); ignora 'ESP'."""
    if not isinstance(value, list):
        value = [value] if value else []
    for code in value:
        if isinstance(code, str) and len(code) > 3 and code.upper().startswith("ES"):
            return code.upper()
    return None


class TedConnector:
    """Implementación del contrato Connector para la Search API v3 de TED."""

    source_id = SOURCE_ID

    def __init__(
        self,
        *,
        cpv_families: tuple[str, ...] = ("48", "72"),
        country: str = "ESP",
        default_lookback_days: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        self.cpv_families = cpv_families
        self.country = country
        self.default_lookback_days = default_lookback_days
        self._session = session or requests.Session()
        self._max_pub_date: str | None = None

    # ── fetch ────────────────────────────────────────────────────────────

    def _build_query(self, since_yyyymmdd: str) -> str:
        cpv_clause = " OR ".join(f"classification-cpv IN ({fam}*)" for fam in self.cpv_families)
        return (
            f"place-of-performance IN ({self.country}) "
            f"AND publication-date >= {since_yyyymmdd} "
            f"AND ({cpv_clause})"
        )

    def _since(self, cursor: dict[str, Any] | None) -> str:
        last = (cursor or {}).get("last_seen_updated")
        if last:
            # Re-consultar desde el último día visto (solapamiento de 1 día);
            # el upsert idempotente absorbe los duplicados.
            return str(last)[:10].replace("-", "")
        from datetime import UTC, datetime, timedelta

        start = datetime.now(UTC) - timedelta(days=self.default_lookback_days)
        return start.strftime("%Y%m%d")

    def fetch(self, cursor: dict[str, Any] | None) -> Iterator[RawNotice]:
        query = self._build_query(self._since(cursor))
        page = 1
        total: int | None = None
        seen = 0
        while True:
            resp = self._session.post(
                _API_URL,
                json={
                    "query": query,
                    "fields": _FIELDS,
                    "page": page,
                    "limit": _PAGE_SIZE,
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            notices = data.get("notices") or []
            if total is None:
                total = int(data.get("totalNoticeCount") or 0)
                log.info("ted_fetch_start", query=query, total=total)
            log.info("ted_fetch_page", page=page, records=len(notices), seen=seen)
            for notice in notices:
                pub_number = notice.get("publication-number")
                if not pub_number:
                    continue
                pub_date = _first_date(notice.get("publication-date"))
                if pub_date and (self._max_pub_date is None or pub_date > self._max_pub_date):
                    self._max_pub_date = pub_date
                seen += 1
                yield RawNotice(natural_id=str(pub_number), payload=notice)
            if not notices or seen >= total:
                break
            page += 1
            time.sleep(_PAGE_PAUSE_S)

    # ── parse ────────────────────────────────────────────────────────────

    def parse(self, raw: RawNotice) -> ParsedTender | None:
        n = raw.payload
        notice_type = str(n.get("notice-type") or "")
        estado = _ESTADO_MAP.get(notice_type.split("-")[0])
        if estado is None:
            return None  # tipos no relevantes (sanciones, perfiles, etc.)

        titulo = _first_lang(n.get("notice-title")) or f"TED {raw.natural_id}"
        descripcion = _first_lang(n.get("description-proc"))
        organo = _first_lang(n.get("buyer-name"))
        cpvs = n.get("classification-cpv") or []
        cpv = str(cpvs[0]) if isinstance(cpvs, list) and cpvs else None
        nuts = _nuts_provincial(n.get("place-of-performance"))
        links = n.get("links") or {}
        url = (links.get("pdf") or {}).get("SPA") or (links.get("xml") or {}).get("MUL")
        importe = _to_float(n.get("estimated-value-proc")) or _to_float(
            n.get("result-value-notice")
        )
        naturalezas = n.get("contract-nature") or []
        tipo = str(naturalezas[0]) if isinstance(naturalezas, list) and naturalezas else None

        _, tech_matches = matches_technology(titulo, descripcion)
        tecnologias = sorted(tech_matches)
        keywords = sorted({kw for kws in tech_matches.values() for kw in kws})

        lic = Licitacion(
            id_externo=f"{SOURCE_ID}:{raw.natural_id}",
            titulo=titulo[:500],
            descripcion=descripcion,
            organo_contratacion=organo,
            importe=importe,
            cpv=cpv,
            tipo_contrato=tipo,
            estado=estado,
            fecha_publicacion=_first_date(n.get("publication-date")),
            fecha_limite=_first_date(n.get("deadline-receipt-tender-date-lot")),
            url=url,
            raw_keywords=",".join(keywords) or None,
            tecnologia=",".join(tecnologias) or None,
            nuts_code=nuts,
            ccaa=nuts_to_ccaa(nuts) if nuts else None,
            inclusion_reason="source_cpv_query",
            analysis_universe="technology_observed",
            fuente=SOURCE_ID,
        )

        adjudicaciones: list[Adjudicacion] = []
        winner = _first_lang(n.get("winner-name"))
        if winner and estado == "RES":
            adjudicaciones.append(
                Adjudicacion(
                    licitacion_id=lic.id_externo,
                    nombre=winner,
                    importe_adjudicado=_to_float(n.get("result-value-notice")),
                    fecha_adjudicacion=lic.fecha_publicacion,
                    nuts_code=nuts,
                    ccaa=lic.ccaa,
                )
            )
        return ParsedTender(licitacion=lic, adjudicaciones=adjudicaciones)

    # ── cursor ───────────────────────────────────────────────────────────

    def new_cursor(self) -> dict[str, Any] | None:
        if self._max_pub_date is None:
            return None
        return {"last_seen_updated": self._max_pub_date}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Ingesta TED (Search API v3)")
    parser.add_argument("--desde", help="Fecha inicial YYYYMMDD (ignora el cursor)")
    parser.add_argument("--cpv", default="48,72", help="Familias CPV separadas por coma")
    args = parser.parse_args(argv)

    from db.database import init_db
    from scraper.connectors.base import run_connector

    init_db()
    connector = TedConnector(cpv_families=tuple(args.cpv.split(",")))
    if args.desde:
        connector._since = lambda cursor: args.desde  # type: ignore[method-assign]
    result = run_connector(connector)
    print(
        f"TED: {result.fetched} avisos · {result.nuevas} nuevas · "
        f"{result.actualizadas} actualizadas · {result.adjudicaciones} adjudicaciones · "
        f"{result.descartadas} descartadas · {result.errores} errores"
    )
    return 0 if result.errores == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
