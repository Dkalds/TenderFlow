"""Conector PSCP Catalunya — API Socrata del portal de transparencia (Fase 5).

La Plataforma de Serveis de Contractació Pública publica su histórico como
open data en ``analisi.transparenciacatalunya.cat``. Este conector consume el
dataset vía SoQL (paginación ``$limit``/``$offset`` ordenada por fecha de
publicación) con filtro incremental ``$where`` y 1 día de solape — el upsert
idempotente absorbe los duplicados, mismo patrón que ``_since`` en TED.

Regla operativa del RFC 20260611-1: el id de dataset y los nombres de campo
NO van hardcodeados como verdad absoluta. El dataset se configura por entorno
(``PSCP_DATASET_ID``) tras validarlo con ``scripts/probe_pscp.py``, y el mapeo
usa listas de candidatos por concepto (``_FIELD_CANDIDATES``) tolerantes a
variaciones de nombre entre versiones del dataset.

Los títulos/órganos en catalán se ingieren tal cual (el clasificador char_wb
tolera catalán; ver acceptance criteria del RFC).

Uso directo (backfill o cron):
    python -m scraper.connectors.pscp                     # incremental
    python -m scraper.connectors.pscp --desde 2024-01-01  # backfill
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import requests

from config import settings
from db.upsert import Adjudicacion, Licitacion
from observability import get_logger
from scraper.connectors.base import ParsedTender, RawNotice
from scraper.filters import matches_technology
from shared.geo import nuts_to_ccaa

if TYPE_CHECKING:
    from collections.abc import Iterator

log = get_logger(__name__)

SOURCE_ID = "pscp"
_PAGE_SIZE = 1000
_TIMEOUT = 60
_PAGE_PAUSE_S = 0.5  # cortesía con la API pública
# Toda la PSCP es contratación catalana: NUTS2 Cataluña (fallback si la
# fila no trae codi_nuts).
_NUTS_CATALUNYA = "ES51"
# Campo de sistema Socrata para el fetch incremental.
_CURSOR_FIELD = ":updated_at"

# Candidatos de nombre de campo por concepto, en orden de preferencia.
# Validados contra el dataset vivo ybgg-dgi6 el 2026-06-11 (salida real de
# scripts/probe_pscp.py); el parser usa el primero presente en cada registro.
_FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "expediente": ("codi_expedient", "numero_expedient", "expedient", "id"),
    "titulo": ("objecte_contracte", "denominacio", "descripcio", "titol"),
    "organo": ("nom_organ", "nom_unitat", "nom_departament_ens", "nom_ambit"),
    "fecha_publicacion": (
        "data_publicacio_anunci",
        "data_publicacio_adjudicacio",
        "data_publicacio_formalitzacio",
        "data_publicacio_contracte",
        "data_publicacio_avaluacio",
    ),
    "fecha_limite": ("termini_presentacio_ofertes", "data_limit_presentacio"),
    # Validado contra API viva ybgg-dgi6 (2026-06-11): los campos reales son
    # pressupost_licitacio_sense (sin IVA, convención del modelo canónico) y
    # pressupost_licitacio_amb (con IVA). Se mantienen candidatos históricos
    # como fallback por si el dataset cambia de nombre en futuras versiones.
    "importe": (
        "pressupost_licitacio_sense",
        "pressupost_licitacio_amb",
        "valor_estimat_contracte",
        "pressupost_licitacio",
        "import_licitacio",
    ),
    # import_adjudicacio_sense (sin IVA) es el campo real; import_adjudicacio_amb_iva
    # también existe pero incluye IVA (menos comparable con PLACSP).
    "importe_adjudicacion": (
        "import_adjudicacio_sense",
        "import_adjudicacio_amb_iva",
        "import_adjudicacio",
        "import_adjudicacio_sense_iva",
    ),
    "cpv": ("codi_cpv", "cpv"),
    "tipo_contrato": ("tipus_contracte", "tipus_de_contracte"),
    "fase": ("fase_publicacio", "fase", "tipus_publicacio"),
    "adjudicatario": ("denominacio_adjudicatari", "adjudicatari", "nom_adjudicatari"),
    "nif_adjudicatario": ("identificacio_adjudicatari", "nif_adjudicatari"),
    "fecha_adjudicacion": ("data_adjudicacio_contracte", "data_adjudicacio"),
    "url": ("enllac_publicacio", "url_publicacio", "enllac"),
    "nuts": ("codi_nuts",),
    "n_ofertas": ("ofertes_rebudes",),
}

# Fase de publicación PSCP (catalán, folded) → estado canónico PLACSP.
_FASE_ESTADO = (
    ("anunci previ", "PRE"),
    ("previ", "PRE"),
    ("formalitzaci", "RES"),
    ("formalizaci", "RES"),
    ("adjudicaci", "ADJ"),
    ("anul", "ANUL"),
    ("desist", "ANUL"),
    ("licitaci", "PUB"),
    ("anunci", "PUB"),
)


def _field(record: dict[str, Any], concept: str) -> Any:
    """Primer candidato de campo presente y no vacío para un concepto."""
    for name in _FIELD_CANDIDATES[concept]:
        value = record.get(name)
        if value not in (None, ""):
            return value
    return None


def _text(record: dict[str, Any], concept: str) -> str | None:
    value = _field(record, concept)
    if value is None:
        return None
    # Los campos URL de Socrata pueden llegar como {"url": "..."}.
    if isinstance(value, dict):
        value = value.get("url") or value.get("value")
    s = str(value).strip()
    return s or None


def _date(record: dict[str, Any], concept: str) -> str | None:
    """Normaliza timestamps Socrata ('2026-06-01T00:00:00.000') a YYYY-MM-DD."""
    value = _text(record, concept)
    return value[:10] if value else None


def _number(record: dict[str, Any], concept: str) -> float | None:
    value = _text(record, concept)
    if value is None:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _fase_to_estado(fase: str | None) -> str | None:
    if not fase:
        return None
    from services.normalization import fold_text

    folded = fold_text(fase)
    for needle, estado in _FASE_ESTADO:
        if needle in folded:
            return estado
    return fase.strip().upper()[:20] or None


class PscpConnector:
    """Implementación del contrato Connector para la API Socrata de la PSCP."""

    source_id = SOURCE_ID

    def __init__(
        self,
        *,
        dataset_id: str | None = None,
        domain: str | None = None,
        app_token: str | None = None,
        default_lookback_days: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        self.dataset_id = dataset_id or settings.PSCP_DATASET_ID
        self.domain = domain or settings.PSCP_DOMAIN
        self.app_token = (
            app_token if app_token is not None else settings.PSCP_APP_TOKEN.get_secret_value()
        )
        self.default_lookback_days = default_lookback_days
        self._session = session or requests.Session()
        self._max_pub_date: str | None = None

    # ── fetch ────────────────────────────────────────────────────────────

    @property
    def _resource_url(self) -> str:
        return f"https://{self.domain}/resource/{self.dataset_id}.json"

    def _since(self, cursor: dict[str, Any] | None) -> str:
        from datetime import UTC, datetime, timedelta

        last = (cursor or {}).get("last_seen_updated")
        if last:
            # Re-consultar desde el día anterior al último visto (solape de
            # 1 día); el upsert idempotente absorbe los duplicados.
            day = datetime.strptime(str(last)[:10], "%Y-%m-%d").replace(tzinfo=UTC)
            return (day - timedelta(days=1)).strftime("%Y-%m-%d")
        start = datetime.now(UTC) - timedelta(days=self.default_lookback_days)
        return start.strftime("%Y-%m-%d")

    def fetch(self, cursor: dict[str, Any] | None) -> Iterator[RawNotice]:
        if not self.dataset_id:
            raise RuntimeError(
                "PSCP_DATASET_ID no configurado. Validá el dataset contra la API "
                "viva con `python scripts/probe_pscp.py` y fijalo por entorno "
                "(regla operativa del RFC 20260611-1)."
            )
        since = self._since(cursor)
        headers = {"X-App-Token": self.app_token} if self.app_token else {}
        offset = 0
        log.info("pscp_fetch_start", dataset=self.dataset_id, since=since)
        while True:
            resp = self._session.get(
                self._resource_url,
                params={
                    # Incremental sobre el campo de sistema Socrata: cada fila
                    # del dataset es una publicación de fase con SU campo de
                    # fecha (anunci/adjudicació/formalització…); :updated_at
                    # es el único común a todas y nunca nulo.
                    "$select": f"{_CURSOR_FIELD}, *",
                    "$where": f"{_CURSOR_FIELD} >= '{since}'",
                    "$order": f"{_CURSOR_FIELD} ASC",
                    "$limit": str(_PAGE_SIZE),
                    "$offset": str(offset),
                },
                headers=headers,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            records = resp.json()
            if not isinstance(records, list) or not records:
                break
            for record in records:
                if not isinstance(record, dict):
                    continue
                natural_id = _text(record, "expediente")
                if not natural_id:
                    continue
                marca = str(record.get(_CURSOR_FIELD) or "")[:10] or _date(
                    record, "fecha_publicacion"
                )
                if marca and (self._max_pub_date is None or marca > self._max_pub_date):
                    self._max_pub_date = marca
                yield RawNotice(natural_id=natural_id, payload=record)
            if len(records) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
            time.sleep(_PAGE_PAUSE_S)

    # ── parse ────────────────────────────────────────────────────────────

    def parse(self, raw: RawNotice) -> ParsedTender | None:
        record = raw.payload
        titulo = _text(record, "titulo")
        if not titulo:
            return None  # sin objeto de contrato no hay nada que indexar

        organo = _text(record, "organo")
        estado = _fase_to_estado(_text(record, "fase"))
        cpv = _text(record, "cpv")
        if cpv:
            cpv = cpv.split(",")[0].split(";")[0].strip() or None
        importe = _number(record, "importe") or _number(record, "importe_adjudicacion")

        _, tech_matches = matches_technology(titulo, None)
        tecnologias = sorted(tech_matches)
        keywords = sorted({kw for kws in tech_matches.values() for kw in kws})

        nuts = (_text(record, "nuts") or _NUTS_CATALUNYA).upper()
        ccaa = nuts_to_ccaa(nuts) or nuts_to_ccaa(_NUTS_CATALUNYA)

        lic = Licitacion(
            id_externo=f"{SOURCE_ID}:{raw.natural_id}",
            titulo=titulo[:500],
            descripcion=None,
            organo_contratacion=organo,
            importe=importe,
            cpv=cpv,
            tipo_contrato=_text(record, "tipo_contrato"),
            estado=estado,
            fecha_publicacion=_date(record, "fecha_publicacion"),
            fecha_limite=_date(record, "fecha_limite"),
            url=_text(record, "url"),
            raw_keywords=",".join(keywords) or None,
            tecnologia=",".join(tecnologias) or None,
            nuts_code=nuts,
            ccaa=ccaa,
            fuente=SOURCE_ID,
        )

        adjudicaciones: list[Adjudicacion] = []
        adjudicatario = _text(record, "adjudicatario")
        if adjudicatario:
            n_ofertas = _number(record, "n_ofertas")
            adjudicaciones.append(
                Adjudicacion(
                    licitacion_id=lic.id_externo,
                    nombre=adjudicatario,
                    nif=_text(record, "nif_adjudicatario"),
                    importe_adjudicado=_number(record, "importe_adjudicacion"),
                    fecha_adjudicacion=_date(record, "fecha_adjudicacion")
                    or lic.fecha_publicacion,
                    n_ofertas_recibidas=int(n_ofertas) if n_ofertas is not None else None,
                    nuts_code=nuts,
                    ccaa=ccaa,
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

    parser = argparse.ArgumentParser(description="Ingesta PSCP Catalunya (Socrata)")
    parser.add_argument("--desde", help="Fecha inicial YYYY-MM-DD (ignora el cursor)")
    parser.add_argument("--dataset", help="Override de PSCP_DATASET_ID")
    args = parser.parse_args(argv)

    from db.database import init_db
    from scraper.connectors.base import run_connector

    init_db()
    connector = PscpConnector(dataset_id=args.dataset)
    if args.desde:
        connector._since = lambda cursor: args.desde  # type: ignore[method-assign]
    result = run_connector(connector)
    print(
        f"PSCP: {result.fetched} avisos · {result.nuevas} nuevas · "
        f"{result.actualizadas} actualizadas · {result.adjudicaciones} adjudicaciones · "
        f"{result.descartadas} descartadas · {result.errores} errores"
    )
    return 0 if result.errores == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
