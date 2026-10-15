"""Contratos menores de PLACSP (sindicación 1143) — inteligencia competitiva, apagado.

Un contrato menor se adjudica sin concurrencia y se publica después del hecho:
no hay convocatoria a la que presentarse, así que **no es una oportunidad**. Lo
que aporta es quién gana qué y a quién: adjudicaciones y empresas. Por eso D16
lo dejó fuera del alcance (``FUERA_DE_ALCANCE``), y por eso este conector está
escrito pero apagado hasta que el dueño revise esa decisión
(``PLACSP_MENORES_ATOM_URL`` vacía por defecto; ver
``scraper.connectors.sindicacion_placsp``).

**Cómo se modela para que nunca se lea como licitación abierta.** Se guarda en
``licitaciones`` —las adjudicaciones cuelgan de ella por clave foránea y la
resolución de empresas recorre por fuente—, pero con cuatro decisiones que la
mantienen fuera de toda superficie de oportunidad sin tocar ningún predicado ni
la vista ``licitaciones_canonicas`` (ADR-026), y por tanto sin migración:

1. **Estado cerrado siempre.** El del feed si ya es terminal
   (``shared.estados.ESTADOS_CERRADOS``); si no trae ninguno, o trae uno
   abierto, ``RES``. No es un dato inventado sino la definición legal: un
   contrato menor está adjudicado cuando se publica. Se cuenta
   (``placsp_menores_estado_cerrado_por_defecto``) para que se vea si pasa.
2. **Sin plazo** (``fecha_limite = NULL``). El Radar (``scoring_candidates``)
   exige estado abierto **y** plazo vivo; con las dos cosas negadas no hay
   camino de entrada aunque el feed trajera un plazo.
3. **Universo propio** (``analysis_universe = placsp_contratos_menores_observed``),
   que no está en ``UNIVERSOS_TECNOLOGICOS``: fuera de la cuota de mercado y de
   la población del clasificador (no son convocatorias, y entrenar con ellas
   enseñaría al modelo otra cosa).
4. **Sin etiqueta ``tecnologia``**. Es la columna que decide pertenencia al
   listado (``only_classified``), a la superficie pública y a los KPIs
   (``universo_tecnologico_sql`` admite cualquier fila con ``tecnologia``). La
   evidencia del filtro no se pierde: las keywords que casaron van a
   ``raw_keywords`` y el motivo a ``inclusion_reason``.

Lo que sí alimenta: ``adjudicaciones`` (con su NIF) y, vía la resolución de
empresas que ``run_connector`` lanza acotada a la fuente, el maestro de
empresas. Las consultas de competidores que no filtran por universo
(``AdjudicacionRepository.load_for_competitors`` y las de UTE) las verán al
encenderlo; las que filtran por ``tecnologia``, no.

**Filtro TI igual que PLACSP**: la misma puerta
(``scraper.puerta_tecnologica.senal_tecnologica``) sobre el título y todos los
CPV del proyecto; entra por keyword o por CPV 48/72. Sin el rescate por
clasificador ML que PLACSP aplica a las entries CPV TI: puntúa oportunidades, y
esto no lo es.

``id_externo`` es ``placsp_menores:<ContractFolderID>`` (ADR-009), como hacen
``placsp_watched_company_awards`` y el resto de fuentes derivadas de PLACSP.

Uso::

    python -m scraper.connectors.placsp_menores --check --dump muestra.atom
    python -m scraper.connectors.placsp_menores        # pasada incremental
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from config import settings
from observability import get_logger
from scraper.connectors.base import ParsedTender, RawNotice
from scraper.connectors.sindicacion_placsp import (
    URL_BASE_SINDICACION,
    FeedSindicacionPlacsp,
    ejecutar_sindicacion,
    main_sindicacion,
)
from shared.estados import ESTADOS_CERRADOS

if TYPE_CHECKING:
    from scraper.connectors.base import ConnectorRunResult

log = get_logger(__name__)

SOURCE_ID = "placsp_menores"
#: Ver el punto 3 del docstring.
ANALYSIS_UNIVERSE = "placsp_contratos_menores_observed"
#: Estado con el que se guarda un contrato menor cuyo feed no trae uno terminal.
ESTADO_POR_DEFECTO = "RES"
#: URL documentada del feed (página de datos abiertos del Ministerio de
#: Hacienda). No se pudo descargar desde la sesión que escribió el conector:
#: `--check` antes de fijarla en `PLACSP_MENORES_ATOM_URL`.
URL_SINDICACION_1143 = (
    f"{URL_BASE_SINDICACION}sindicacion_1143/contratosMenoresPerfilesContratantes.atom"
)
VARIABLE = "PLACSP_MENORES_ATOM_URL"

_CPVS_XPATH = (
    "./cacext:ContractFolderStatus/cac:ProcurementProject"
    "/cac:RequiredCommodityClassification/cbc:ItemClassificationCode/text()"
)


class PlacspContratosMenoresConnector(FeedSindicacionPlacsp):
    """Contratos menores TI de la sindicación 1143, como adjudicaciones cerradas."""

    source_id = SOURCE_ID

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self._sin_senal = 0
        self._ambigua_sin_cpv_ti = 0
        self._estado_por_defecto = 0

    def parse(self, raw: RawNotice) -> ParsedTender | None:
        from scraper.codice_parser import NS, parse_adjudicaciones, parse_entry_unfiltered
        from scraper.lineage import current_filter_version
        from scraper.puerta_tecnologica import (
            MOTIVO_AMBIGUA_SIN_CPV_TI,
            MOTIVO_SIN_SENAL,
            senal_tecnologica,
        )

        entry, updated = raw.payload
        lic = parse_entry_unfiltered(entry)
        if lic is None:
            return None
        cpvs = " ".join(str(c) for c in entry.xpath(_CPVS_XPATH, namespaces=NS))
        senal = senal_tecnologica(lic.titulo, cpvs or lic.cpv)
        if not senal.admitida:
            if senal.motivo == MOTIVO_AMBIGUA_SIN_CPV_TI:
                self._ambigua_sin_cpv_ti += 1
            elif senal.motivo == MOTIVO_SIN_SENAL:
                self._sin_senal += 1
            return None

        id_externo = f"{SOURCE_ID}:{lic.id_externo}"
        lic.id_externo = id_externo
        lic.fuente = SOURCE_ID
        lic.analysis_universe = ANALYSIS_UNIVERSE
        lic.inclusion_reason = f"contrato_menor_{senal.motivo}"
        lic.filter_version = current_filter_version()
        # Punto 4 del docstring: la evidencia, no la etiqueta.
        lic.raw_keywords = ",".join(senal.keywords) or None
        lic.tecnologia = None
        # Puntos 1 y 2: cerrado y sin plazo, diga lo que diga el feed.
        lic.fecha_limite = None
        if lic.estado not in ESTADOS_CERRADOS:
            self._estado_por_defecto += 1
            lic.estado = ESTADO_POR_DEFECTO
        if updated:
            lic.fecha_actualizacion_fuente = updated

        return ParsedTender(licitacion=lic, adjudicaciones=parse_adjudicaciones(entry, id_externo))

    def contadores_de_descarte(self) -> dict[str, int]:
        """Descartes y correcciones de este run, por motivo (como PSCP, C4.1)."""
        return {
            "placsp_menores_sin_senal_tecnologica": self._sin_senal,
            "placsp_menores_keyword_ambigua_sin_cpv_ti": self._ambigua_sin_cpv_ti,
            "placsp_menores_estado_cerrado_por_defecto": self._estado_por_defecto,
        }


def ejecutar(*, url: str | None = None) -> ConnectorRunResult | None:
    """Una pasada incremental; ``None`` si la fuente está apagada (sin URL).

    La usan ``main`` y el carril diario del worker
    (``scheduler/jobs/daily_atom.py``). No abre ni cierra la BD.
    """
    return ejecutar_sindicacion(
        source_id=SOURCE_ID,
        url=url if url is not None else settings.PLACSP_MENORES_ATOM_URL,
        variable=VARIABLE,
        crear=PlacspContratosMenoresConnector,
    )


def main(argv: list[str] | None = None) -> int:
    return main_sindicacion(
        argv,
        descripcion="Ingesta de contratos menores de PLACSP (sindicación 1143)",
        source_id=SOURCE_ID,
        variable=VARIABLE,
        url_documentada=URL_SINDICACION_1143,
        crear=PlacspContratosMenoresConnector,
    )


if __name__ == "__main__":
    raise SystemExit(main())
