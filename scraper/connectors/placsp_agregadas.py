"""Plataformas autonómicas agregadas en PLACSP (sindicación 1044) — apagado.

Las plataformas autonómicas que no publican su perfil del contratante en PLACSP
vierten sus licitaciones en ella por agregación, y PLACSP las sindica aparte
del feed principal, sin contratos menores. Es la vía para ver las convocatorias
TI de los portales que D16 declaró «no integrados» sin escribir un conector por
portal. Escrito y apagado hasta que el dueño revise D16
(``PLACSP_AGREGADAS_ATOM_URL`` vacía por defecto; ver
``scraper.connectors.sindicacion_placsp``).

**A diferencia de los contratos menores, esto sí son oportunidades**: se
parsean con el mismo núcleo que el feed principal (``_PlacspParseCore``: CODICE,
puerta tecnológica, rescate por CPV y clasificador) y entran en el universo
``technology_observed``, con su estado y su plazo. Es el mismo dato que PLACSP
publica, filtrado con la misma regla; lo único distinto es la plataforma de
origen, y eso lo dice ``fuente = placsp_agregadas``, por la que cualquier
métrica puede separarlas.

**Deduplicadas frente a lo que ya entra.** Una plataforma agregada puede ser
también fuente propia (la PSCP catalana lo es), y el mismo contrato puede estar
ya en el feed principal. Tres capas, ninguna nueva:

- ``id_externo = placsp_agregadas:<ID_OC_PLAT>:<ContractFolderID>`` (ADR-009,
  ADR-038): nunca pisa la fila de otra fuente ni la de otro órgano, y su
  expediente natural (lo que va tras el segundo ``:``,
  ``shared.identidad_placsp.expediente_natural``) es el mismo que el de esa
  fila.
- ``detect_duplicates(fuente="placsp_agregadas")``, que ``run_connector`` lanza
  tras cada lote, casa por expediente natural + órgano + CPV4 y marca la
  duplicada (``confirmed`` con CPV4 igual). La canónica es la de PLACSP si la
  hay; si no, la publicada antes (``services.dedupe._pick_canonical``).
- La clave canónica de la superficie pública (órgano + CPV4 + año-mes + título,
  ``db.sql_fragments.fila_canonica_sql``) colapsa lo que el expediente no casa.

El Radar y los listados esconden ``pending`` y ``confirmed`` (ADR-026, D23); la
cuota de mercado, solo ``confirmed``.

**Documentos.** Solo se guardan las referencias de hosts que el descargador
acepta (``DOCUMENT_ALLOWED_HOSTS``, la misma regla que ``shared.ssrf``): una
referencia a otro host fallaría en cada pasada del job de pliegos. La hipótesis
inicial —que las plataformas agregadas enlazan sus pliegos en PLACSP— era falsa:
en 20 páginas del feed real (9.349 entradas, 728 admitidas por el filtro) las
1.057 referencias de documento apuntan a tres hosts autonómicos y ninguna a
``contrataciondelestado.es``: ``contractaciopublica.cat`` (544, ya en la
allowlist por PSCP), ``www.contratacion.euskadi.eus`` (346) y
``contratos-publicos.comunidad.madrid`` (167). Con el filtro «solo PLACSP» se
habrían descartado todas. Los dos últimos hosts siguen fuera de la allowlist y
se cuentan (``placsp_agregadas_documentos_de_otro_host``): ampliarla es una
decisión de seguridad del propietario (ver el backlog).

Las de la Junta de Andalucía no traen ninguna referencia (383 de 383 el
2026-11-09). Sus pliegos los lee el paso de documentos del conector
(:meth:`PlacspAgregadasConnector.completar_documentos`) de la ficha pública que
enlaza su ``url``, solo mientras la convocatoria está vigente
(``scraper.documentos_plataforma.completar_documentos_andalucia``).

**Identidad.** El ``ContractFolderID`` solo es único dentro del órgano: en el
muestreo 57 los comparten órganos distintos (74 filas que se habrían pisado de
7.956, el 0,9 %). Por eso la clave lo acota con el órgano, como el feed
principal (RFC ``2026-10-24-rfc-identidad-placsp-organo-expediente``): aquí el
órgano viene en ``ID_OC_PLAT`` (100 % de las entradas) y, sin él, en DIR3
(``scraper.codice_parser.ESQUEMAS_ORGANO_AGREGADAS``); sin ninguno la entrada se
descarta y se cuenta (``placsp_agregadas_sin_identificador_de_organo``). El
conector nunca se encendió en producción (0 filas), así que
``v164_identidad_placsp_rekey`` no tuvo nada suyo que mover.

Uso::

    python -m scraper.connectors.placsp_agregadas --check --dump muestra.atom
    python -m scraper.connectors.placsp_agregadas        # pasada incremental
    python -m scraper.connectors.placsp_agregadas --desde 2026-09 --hasta 2026-10  # histórico

El histórico lee los ZIP mensuales de la sindicación (:class:`PlacspAgregadasHistorico`):
el feed solo trae lo publicado desde su primera pasada (2026-11-04).
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from config import settings
from observability import get_logger
from scraper.connectors.base import ParsedTender, RawNotice
from scraper.connectors.sindicacion_placsp import (
    URL_BASE_SINDICACION,
    FeedSindicacionPlacsp,
    ejecutar_sindicacion,
    main_sindicacion,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from db.upsert import DocumentoReferencia
    from scraper.connectors.base import ConnectorRunResult

log = get_logger(__name__)

SOURCE_ID = "placsp_agregadas"
#: URL del feed (página de datos abiertos del Ministerio de Hacienda). Verificada
#: el 2026-10-24: 200 ``application/atom+xml`` a un GET, 283 entradas en la
#: primera página, ``rel="next"`` hacia ``..._AAAAMMDD_HHMMSS[_N].atom`` y
#: contenido CODICE. El órgano va en ``ID_OC_PLAT``, no en ``ID_PLATAFORMA``.
URL_SINDICACION_1044 = f"{URL_BASE_SINDICACION}sindicacion_1044/PlataformasAgregadasSinMenores.atom"
VARIABLE = "PLACSP_AGREGADAS_ATOM_URL"


def _host_permitido(documento: DocumentoReferencia) -> bool:
    """¿Acepta el descargador el host de esta referencia? (regla de ``shared.ssrf``)."""
    host = (urlparse(documento.uri).hostname or "").lower()
    reglas = [r.strip().lower() for r in settings.DOCUMENT_ALLOWED_HOSTS.split(",") if r.strip()]
    return bool(host) and any(
        host == regla.lstrip("*.") or (regla.startswith("*.") and host.endswith(regla[1:]))
        for regla in reglas
    )


class PlacspAgregadasConnector(FeedSindicacionPlacsp):
    """Licitaciones TI de las plataformas autonómicas agregadas en PLACSP."""

    source_id = SOURCE_ID

    def __init__(self, url: str) -> None:
        from scraper.codice_parser import ESQUEMAS_ORGANO_AGREGADAS
        from scraper.connectors.placsp import EsperadasPorTed, _PlacspParseCore

        super().__init__(url)
        # El núcleo pone la clave `placsp_agregadas:<ID_OC_PLAT>:<expediente>`
        # antes de copiar el id a adjudicaciones y lotes.
        self._core = _PlacspParseCore(prefijo=SOURCE_ID, esquemas=ESQUEMAS_ORGANO_AGREGADAS)
        # Los avisos TED enlazan por `idEvl` el feed principal, no este: aquí
        # se apaga con un mapa vacío, que además evita su consulta a la BD.
        self._core.esperadas = EsperadasPorTed(cargar=list)
        self._fuera_de_universo = 0
        self._documentos_de_otro_host = 0

    def parse(self, raw: RawNotice) -> ParsedTender | None:
        entry, updated = raw.payload
        sin_organo_antes = self._core.contadores["sin_organo"]
        parsed = self._core.parse_entry_elem(entry, fuente=SOURCE_ID, updated_str=updated or None)
        if parsed is None:
            # La que se descarta por no traer órgano ya la cuenta el núcleo.
            if self._core.contadores["sin_organo"] == sin_organo_antes:
                self._fuera_de_universo += 1
            return None

        documentos = [d for d in parsed.documentos if _host_permitido(d)]
        self._documentos_de_otro_host += len(parsed.documentos) - len(documentos)
        return replace(parsed, documentos=documentos)

    def contadores_de_descarte(self) -> dict[str, int]:
        return {
            "placsp_agregadas_fuera_de_universo": self._fuera_de_universo,
            "placsp_agregadas_documentos_de_otro_host": self._documentos_de_otro_host,
            **self._core.contadores_de_descarte(),
        }

    #: El paso de documentos lee de la BD las convocatorias andaluzas vigentes, no
    #: el lote ni las marcas del dedupe: va antes del cierre, como el de PSCP.
    completar_documentos_primero = True

    def completar_documentos(self) -> None:
        """Pliegos de las convocatorias vigentes de Andalucía, que su CODICE no referencia."""
        from scraper.documentos_plataforma import completar_documentos_andalucia

        resumen = completar_documentos_andalucia()
        log.info("placsp_agregadas_documentos_andalucia", **resumen.as_dict())


#: ZIP mensual de la misma sindicación, con el nombre del feed y ``_AAAAMM``,
#: como ``licitacionesPerfilesContratanteCompleto3_AAAAMM.zip`` en la 643.
URL_ZIP_1044 = f"{URL_BASE_SINDICACION}sindicacion_1044/PlataformasAgregadasSinMenores_{{year}}{{month:02d}}.zip"


def _ya_existe(id_externo: str) -> bool:
    from db.repositories import dedupe as dedupe_repo

    return bool(dedupe_repo.filas_por_id([id_externo]))


class PlacspAgregadasHistorico(PlacspAgregadasConnector):
    """Un mes del ZIP de la sindicación 1044: lo que el feed ya no trae.

    El conector incremental empezó el 2026-11-04 y solo lee hacia atrás hasta
    su cursor, así que lo publicado antes no entró nunca. Mismo parseo, misma
    puerta y mismo filtro de hosts que el feed.

    **Nunca pisa una fila que ya existe**: el ZIP no trae ``<updated>`` y su
    versión puede ser más vieja que la que trajo el feed. Por eso
    :func:`ejecutar_historico` recorre los meses del más nuevo al más viejo.
    ``new_cursor`` es ``None``: el cursor del feed no se toca.
    """

    def __init__(
        self, year: int, month: int, *, ya_existe: Callable[[str], bool] | None = None
    ) -> None:
        super().__init__(URL_SINDICACION_1044)
        self.year = year
        self.month = month
        self._ya_existe = ya_existe or _ya_existe
        self.ya_existian = 0

    def fetch(self, cursor: object) -> Iterator[RawNotice]:
        from scraper.bulk_downloader import download_month, iter_xml_files
        from scraper.connectors.placsp import _iter_atom_entries

        zip_path = download_month(
            self.year, self.month, url_template=URL_ZIP_1044, prefijo=SOURCE_ID
        )
        if zip_path is None:
            log.info("placsp_agregadas_mes_no_publicado", year=self.year, month=self.month)
            return
        for nombre, contenido in iter_xml_files(zip_path):
            for entry, _ in _iter_atom_entries(contenido):
                yield RawNotice(natural_id=nombre, payload=(entry, None))

    def parse(self, raw: RawNotice) -> ParsedTender | None:
        parsed = super().parse(raw)
        if parsed is not None and self._ya_existe(parsed.licitacion.id_externo):
            self.ya_existian += 1
            return None
        return parsed

    def new_cursor(self) -> None:
        return None

    def contadores_de_descarte(self) -> dict[str, int]:
        return {
            "placsp_agregadas_ya_existian": self.ya_existian,
            **super().contadores_de_descarte(),
        }


def ejecutar_historico(desde: str, hasta: str) -> list[ConnectorRunResult]:
    """Ingiere los meses ``desde``..``hasta`` (``YYYY-MM``), del más nuevo al más viejo."""
    from scraper.connectors.base import run_connector
    from scraper.reproceso_lotes import meses_entre

    return [
        run_connector(PlacspAgregadasHistorico(year, month))
        for year, month in reversed(meses_entre(desde, hasta))
    ]


def ejecutar(*, url: str | None = None) -> ConnectorRunResult | None:
    """Una pasada incremental; ``None`` si la fuente está apagada (sin URL).

    La usan ``main`` y el carril diario del worker
    (``scheduler/jobs/daily_atom.py``). No abre ni cierra la BD.
    """
    return ejecutar_sindicacion(
        source_id=SOURCE_ID,
        url=url if url is not None else settings.PLACSP_AGREGADAS_ATOM_URL,
        variable=VARIABLE,
        crear=PlacspAgregadasConnector,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    historico = argparse.ArgumentParser(add_help=False)
    historico.add_argument("--desde", help="Histórico desde los ZIP mensuales: primer mes, YYYY-MM")
    historico.add_argument("--hasta", help="Último mes, YYYY-MM (por defecto, --desde)")
    args, resto = historico.parse_known_args(argv)
    if args.desde:
        from db.database import close_pool, init_db

        init_db()
        try:
            resultados = ejecutar_historico(args.desde, args.hasta or args.desde)
        finally:
            close_pool()
        return 0 if all(r.errores == 0 for r in resultados) else 1
    return main_sindicacion(
        resto,
        descripcion="Ingesta de las plataformas autonómicas agregadas en PLACSP (sindicación 1044)",
        source_id=SOURCE_ID,
        variable=VARIABLE,
        url_documentada=URL_SINDICACION_1044,
        crear=PlacspAgregadasConnector,
    )


if __name__ == "__main__":
    raise SystemExit(main())
