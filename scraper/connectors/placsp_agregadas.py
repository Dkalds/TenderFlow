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

- ``id_externo = placsp_agregadas:<ContractFolderID>`` (ADR-009): nunca pisa la
  fila de otra fuente, y su expediente natural (lo que va tras el ``:``) es el
  mismo que el de esa fila.
- ``detect_duplicates(fuente="placsp_agregadas")``, que ``run_connector`` lanza
  tras cada lote, casa por expediente natural + órgano + CPV4 y marca la
  duplicada (``confirmed`` con CPV4 igual). La canónica es la de PLACSP si la
  hay; si no, la publicada antes (``services.dedupe._pick_canonical``).
- La clave canónica de la superficie pública (órgano + CPV4 + año-mes + título,
  ``db.sql_fragments.fila_canonica_sql``) colapsa lo que el expediente no casa.

El Radar y los listados esconden ``pending`` y ``confirmed`` (ADR-026, D23); la
cuota de mercado, solo ``confirmed``.

**Documentos.** Solo se guardan las referencias alojadas en PLACSP: una
plataforma agregada puede enlazar sus pliegos en su propio host, que no está en
``DOCUMENT_ALLOWED_HOSTS``, y esas filas fallarían en cada pasada del job de
pliegos. Se cuentan (``placsp_agregadas_documentos_de_otro_host``) para poder
decidir con el número si merece la pena ampliar la allowlist.

Uso::

    python -m scraper.connectors.placsp_agregadas --check --dump muestra.atom
    python -m scraper.connectors.placsp_agregadas        # pasada incremental
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
    from db.upsert import DocumentoReferencia
    from scraper.connectors.base import ConnectorRunResult

log = get_logger(__name__)

SOURCE_ID = "placsp_agregadas"
#: URL documentada del feed (página de datos abiertos del Ministerio de
#: Hacienda). No se pudo descargar desde la sesión que escribió el conector:
#: `--check` antes de fijarla en `PLACSP_AGREGADAS_ATOM_URL`.
URL_SINDICACION_1044 = f"{URL_BASE_SINDICACION}sindicacion_1044/PlataformasAgregadasSinMenores.atom"
VARIABLE = "PLACSP_AGREGADAS_ATOM_URL"

#: Hosts de PLACSP desde los que se aceptan documentos. Son los
#: `dominios_documentos` de la fuente en `REGISTERED_SOURCES`, ya incluidos en
#: la allowlist por defecto del descargador.
_HOST_DOCUMENTOS = "contrataciondelestado.es"


def _alojado_en_placsp(documento: DocumentoReferencia) -> bool:
    host = (urlparse(documento.uri).hostname or "").lower()
    return host == _HOST_DOCUMENTOS or host.endswith(f".{_HOST_DOCUMENTOS}")


class PlacspAgregadasConnector(FeedSindicacionPlacsp):
    """Licitaciones TI de las plataformas autonómicas agregadas en PLACSP."""

    source_id = SOURCE_ID

    def __init__(self, url: str) -> None:
        from scraper.connectors.placsp import _PlacspParseCore
        from scraper.documentos_plataforma import RescatePliegosPlacsp

        super().__init__(url)
        self._core = _PlacspParseCore()
        # El rescate de pliegos para avisos TED es del feed principal: aquí se
        # apaga con un mapa vacío, que además evita su consulta a la BD.
        self._core.rescate = RescatePliegosPlacsp(cargar=list)
        self._fuera_de_universo = 0
        self._documentos_de_otro_host = 0

    def parse(self, raw: RawNotice) -> ParsedTender | None:
        entry, updated = raw.payload
        parsed = self._core.parse_entry_elem(entry, fuente=SOURCE_ID, updated_str=updated or None)
        if parsed is None:
            self._fuera_de_universo += 1
            return None

        id_externo = f"{SOURCE_ID}:{parsed.licitacion.id_externo}"
        parsed.licitacion.id_externo = id_externo
        documentos = [d for d in parsed.documentos if _alojado_en_placsp(d)]
        self._documentos_de_otro_host += len(parsed.documentos) - len(documentos)
        return ParsedTender(
            licitacion=parsed.licitacion,
            adjudicaciones=[replace(a, licitacion_id=id_externo) for a in parsed.adjudicaciones],
            documentos=documentos,
            lotes=[replace(lote, licitacion_id=id_externo) for lote in parsed.lotes],
        )

    def contadores_de_descarte(self) -> dict[str, int]:
        return {
            "placsp_agregadas_fuera_de_universo": self._fuera_de_universo,
            "placsp_agregadas_documentos_de_otro_host": self._documentos_de_otro_host,
        }


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
    return main_sindicacion(
        argv,
        descripcion="Ingesta de las plataformas autonómicas agregadas en PLACSP (sindicación 1044)",
        source_id=SOURCE_ID,
        variable=VARIABLE,
        url_documentada=URL_SINDICACION_1044,
        crear=PlacspAgregadasConnector,
    )


if __name__ == "__main__":
    raise SystemExit(main())
