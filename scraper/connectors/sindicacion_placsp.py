"""Lo común a las sindicaciones secundarias de PLACSP (1143 y 1044).

PLACSP publica, además del feed principal (``sindicacion_643``, el corpus), dos
sindicaciones con el mismo ATOM paginado —500 entradas por fichero y el resto
por ``rel="next"`` (página de datos abiertos del Ministerio de Hacienda)—:

- ``sindicacion_1143/contratosMenoresPerfilesContratantes.atom``: contratos
  menores de los perfiles del contratante alojados en la Plataforma
  (``scraper.connectors.placsp_menores``).
- ``sindicacion_1044/PlataformasAgregadasSinMenores.atom``: licitaciones que las
  plataformas autonómicas vierten en PLACSP por agregación, sin contratos
  menores (``scraper.connectors.placsp_agregadas``).

Los dos conectores están **apagados por defecto** (decisión del dueño al
revisar D16): su variable de URL —``PLACSP_MENORES_ATOM_URL`` y
``PLACSP_AGREGADAS_ATOM_URL``— va vacía, y sin ella declaran ``disabled`` y no
descargan nada, igual que PSCP sin ``PSCP_DATASET_ID``. La URL documentada de
cada uno está en su módulo (``URL_SINDICACION_*``) y se valida con ``--check``
antes de fijarla. Ninguna de las dos se pudo descargar desde la sesión que las
escribió (2026-10-12; el proxy denegaba el host): el nombre de cada fichero sale
de la página de datos abiertos del Ministerio de Hacienda y el contenido de cada
entrada se asume CODICE, como el del feed principal. ``--check --dump`` es lo
primero que hay que correr al activar una.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from observability import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from scraper.connectors.base import ConnectorRunResult, ParsedTender, RawNotice

log = get_logger(__name__)

#: Base de las sindicaciones de PLACSP; el feed principal cuelga de la misma.
URL_BASE_SINDICACION = "https://contrataciondelsectorpublico.gob.es/sindicacion/"


class FeedSindicacionPlacsp:
    """``fetch`` y ``new_cursor`` de un ATOM de PLACSP servido desde otra URL.

    Es el mismo recorrido que el feed principal (``scraper.atom_live``): de más
    nuevo a más viejo hasta el cursor, así que **no** declara
    ``cursor_advances_incrementally`` (ver el docstring de
    ``scraper.connectors.base``). El cursor es propio de cada fuente.
    """

    source_id: str = ""

    def __init__(self, url: str) -> None:
        from scraper.atom_live import _is_allowed_url

        partes = urlparse(url)
        # Solo HTTPS y solo los dominios de la Plataforma: la URL llega de una
        # variable de entorno, y `iter_live_entries` ya restringe así los
        # enlaces `rel="next"`; la primera página merece la misma guarda.
        if partes.scheme != "https" or not _is_allowed_url(url):
            raise ValueError(f"URL de sindicación fuera de PLACSP: {url!r}")
        self.url = url
        self._meta: dict[str, Any] = {}
        self._last_seen_updated: str | None = None

    def fetch(self, cursor: dict[str, Any] | None) -> Iterator[RawNotice]:
        from scraper.atom_live import iter_live_entries
        from scraper.connectors.base import RawNotice

        last_seen_updated = str((cursor or {}).get("last_seen_updated") or "") or None
        self._last_seen_updated = last_seen_updated
        entries, self._meta = iter_live_entries(
            last_seen_updated=last_seen_updated, start_url=self.url
        )
        for entry_elem, updated_str in entries:
            yield RawNotice(natural_id=updated_str or "unknown", payload=(entry_elem, updated_str))

    def new_cursor(self) -> dict[str, Any] | None:
        newest = self._meta.get("newest_updated") or self._last_seen_updated
        if newest is None and not self._meta.get("etag"):
            return None
        return {
            "last_seen_updated": newest,
            "etag": self._meta.get("etag"),
            "last_modified": self._meta.get("last_modified"),
        }

    def parse(self, raw: RawNotice) -> ParsedTender | None:  # pragma: no cover — abstracto
        raise NotImplementedError


def ejecutar_sindicacion(
    *,
    source_id: str,
    url: str,
    variable: str,
    crear: Callable[[str], FeedSindicacionPlacsp],
) -> ConnectorRunResult | None:
    """Una pasada incremental; ``None`` si la fuente está apagada.

    Sin URL configurada la fuente está APAGADA, no rota: lo declara en
    ``source_ingestion_health`` (``disabled``), que es lo que lee el chequeo de
    frescura del healthcheck para no confundirla con una fuente muerta. No abre
    ni cierra la BD: el worker comparte el pool con la cola.
    """
    from scraper.connectors import base

    if not url:
        base.record_source_disabled(
            source_id,
            motivo=(
                f"{variable} vacía: fuente apagada por defecto (revisión de D16). "
                f"Validá la URL con `python -m scraper.connectors.{source_id} --check` "
                "y fijala por entorno para encenderla"
            ),
        )
        return None
    return base.run_connector(crear(url))


def comprobar(conector: FeedSindicacionPlacsp, *, dump: str | None = None) -> int:
    """``--check``: pide la primera página, la parsea entera y no escribe nada.

    Devuelve 0 si la página trae entradas. Con *dump* guarda los bytes tal como
    llegaron: es como se sustituye la fixture sintética por un recorte real.
    """
    from lxml import etree

    from scraper.atom_live import ATOM_NS, fetch_atom_page

    pagina = fetch_atom_page(conector.url)
    contenido = pagina.content or b""
    if dump:
        from pathlib import Path

        Path(dump).write_bytes(contenido)
        print(f"Primera página guardada en {dump} ({len(contenido)} bytes)")
    parser = etree.XMLParser(huge_tree=False, recover=True, resolve_entities=False, no_network=True)
    raiz = etree.fromstring(contenido, parser=parser) if contenido else None
    entradas = raiz.findall(f"{{{ATOM_NS}}}entry") if raiz is not None else []
    from scraper.connectors.base import RawNotice

    admitidas = 0
    for entry in entradas:
        updated = entry.findtext(f"{{{ATOM_NS}}}updated") or ""
        if conector.parse(RawNotice(natural_id=updated, payload=(entry, updated))) is not None:
            admitidas += 1
    print(
        f"{conector.source_id} --check: {len(entradas)} entradas en la primera página, "
        f"{admitidas} admitidas por el filtro de tecnología"
    )
    contadores = getattr(conector, "contadores_de_descarte", None)
    if callable(contadores):
        for motivo, n in contadores().items():
            print(f"  {motivo}: {n}")
    return 0 if entradas else 1


def main_sindicacion(
    argv: list[str] | None,
    *,
    descripcion: str,
    source_id: str,
    variable: str,
    url_documentada: str,
    crear: Callable[[str], FeedSindicacionPlacsp],
) -> int:
    """CLI común: ``--check [--url] [--dump]`` valida; sin flags, una pasada."""
    import argparse

    from config import settings

    parser = argparse.ArgumentParser(description=descripcion)
    parser.add_argument("--url", help=f"Override de {variable}")
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Solo valida la primera página (descarga + parseo, sin escribir en BD). "
            "Sin --url ni variable usa la URL documentada"
        ),
    )
    parser.add_argument("--dump", metavar="ARCHIVO", help="Con --check: guarda la página recibida")
    args = parser.parse_args(argv)
    configurada = str(getattr(settings, variable) or "")

    if args.check:
        return comprobar(crear(args.url or configurada or url_documentada), dump=args.dump)

    from db.database import close_pool, init_db

    init_db()
    try:
        resultado = ejecutar_sindicacion(
            source_id=source_id, url=args.url or configurada, variable=variable, crear=crear
        )
    finally:
        close_pool()
    if resultado is None:
        print(f"{source_id}: sin {variable} configurada — fuente declarada 'disabled'.")
        return 0
    print(
        f"{source_id}: {resultado.fetched} avisos · {resultado.nuevas} nuevas · "
        f"{resultado.actualizadas} actualizadas · {resultado.adjudicaciones} adjudicaciones · "
        f"{resultado.descartadas} descartadas · {resultado.errores} errores"
    )
    return 0 if resultado.errores == 0 else 1
