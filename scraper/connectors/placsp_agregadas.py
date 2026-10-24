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

**Identidad.** ``placsp_agregadas:<ContractFolderID>`` se mantiene porque el
dedupe casa por expediente natural, pero tiene el mismo defecto que tenía
menores: en el muestreo 57 ``ContractFolderID`` los comparten órganos distintos
(74 filas pisadas de 7.956, el 0,9 %). Ver el backlog: el feed principal
(``placsp``, sin prefijo) tiene el problema con más peso (67 de 3.646, el 2,5 %)
y arreglarlo exige migrar filas escritas.

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
        documentos = [d for d in parsed.documentos if _host_permitido(d)]
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
