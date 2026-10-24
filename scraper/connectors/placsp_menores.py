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

**Identidad (medida contra el feed real, 2026-10-24).** ``id_externo`` es
``placsp_menores:<ID_PLATAFORMA>:<ContractFolderID>`` (ADR-009), no
``placsp_menores:<ContractFolderID>``: el número de expediente de un contrato
menor es el contador interno de cada órgano («1/2026», «1000/2026») y lo repiten
órganos distintos. En 20 páginas del feed (9.977 entradas, ~4 días) 327 de los
9.563 ``ContractFolderID`` distintos los usaban 2 o más órganos, y con la clave
vieja habrían sido 390 filas pisadas por el ``ON CONFLICT(id_externo)`` del
upsert (el 3,9 %). ``ID_PLATAFORMA`` es el identificador del órgano de
contratación en la Plataforma: viene en el 100 % de las entradas, es 1:1 con el
órgano (ningún ``ID_PLATAFORMA`` con dos DIR3) y, con él, ``(órgano, expediente)``
es 1:1 con el ``<id>`` Atom de la entrada (9.953 pares, 9.953 ids; una
actualización repite el mismo par, así que el upsert sigue siendo idempotente).
No sirve el DIR3 (falta en el 17 % de las entradas) ni el NIF (una entidad con
varios órganos comparte NIF). Sin ``ID_PLATAFORMA`` se cae al NIF y, sin él, al
DIR3; sin ninguno de los tres la entrada se descarta y se cuenta.

El expediente natural (``services.dedupe.natural_expediente``: lo que va tras el
primer ``:``) pasa a ser ``<ID_PLATAFORMA>:<ContractFolderID>``, que no casa con
ninguna otra fuente. Es lo que se quiere: de las 9.951 claves ``(DIR3, expediente)``
del muestreo solo 5 aparecen también en el feed principal, así que menores y
principal son conjuntos casi disjuntos, y casar solo por el número de expediente
marcaría como duplicado un menor de un órgano contra la licitación de otro
contrato con el mismo número («12/2026») y el mismo CPV a 4 dígitos. Misma idea
que ``pscp:<uuid>:<codi_expedient>``. No hay filas escritas con la clave vieja:
el conector nunca se encendió (``PLACSP_MENORES_ATOM_URL`` vacía), así que no hay
nada que migrar.

**Adjudicatarios con NIF enmascarado.** PLACSP enmascara el NIF de los
adjudicatarios personas físicas (``***3418**``) y, a veces, el de una sociedad
(``****2061*``). Una clave así no identifica a nadie y la resolución de empresas
la trataría como una empresa más, fundiendo adjudicatarios sin relación: esas
adjudicaciones no se guardan (``placsp_menores_nif_enmascarado``). La
licitación sí. De las 241 admitidas por el filtro en el muestreo, 14 tienen el
primer adjudicatario con NIF enmascarado y 12 con NIF de persona física sin
enmascarar (esos sí se guardan, con nombre y apellidos: lo publica PLACSP, pero es
dato personal y lo decide el propietario, ver el backlog).

Uso::

    python -m scraper.connectors.placsp_menores --check --dump muestra.atom
    python -m scraper.connectors.placsp_menores        # pasada incremental
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
#: URL del feed (página de datos abiertos del Ministerio de Hacienda). Verificada
#: el 2026-10-24: responde 200 ``application/atom+xml`` a un GET (a un HEAD, la
#: conexión se cierra), 500 entradas por página, ``rel="next"`` hacia
#: ``..._AAAAMMDD_HHMMSS[_N].atom`` y contenido CODICE como el del feed principal.
URL_SINDICACION_1143 = (
    f"{URL_BASE_SINDICACION}sindicacion_1143/contratosMenoresPerfilesContratantes.atom"
)
VARIABLE = "PLACSP_MENORES_ATOM_URL"

_CPVS_XPATH = (
    "./cacext:ContractFolderStatus/cac:ProcurementProject"
    "/cac:RequiredCommodityClassification/cbc:ItemClassificationCode/text()"
)
_ORGANO_IDS_XPATH = (
    "./cacext:ContractFolderStatus/cacext:LocatedContractingParty"
    "/cac:Party/cac:PartyIdentification/cbc:ID"
)
#: Orden de preferencia del identificador del órgano en la clave (ver el
#: docstring del módulo): el de la Plataforma, el NIF y el DIR3.
_ESQUEMAS_ORGANO = ("ID_PLATAFORMA", "NIF", "DIR3")


def identificador_organo(entry: Any) -> str | None:  # Any: elemento lxml, sin stubs
    """Identificador del órgano de contratación que acota el expediente, o ``None``."""
    from scraper.codice_parser import NS

    por_esquema: dict[str, str] = {}
    for nodo in entry.xpath(_ORGANO_IDS_XPATH, namespaces=NS):
        valor = (nodo.text or "").strip()
        esquema = (nodo.get("schemeName") or "").strip().upper()
        if valor and esquema not in por_esquema:
            por_esquema[esquema] = valor
    for esquema in _ESQUEMAS_ORGANO:
        if esquema in por_esquema:
            return por_esquema[esquema]
    return None


def id_externo_menor(organo: str, expediente: str) -> str:
    """``placsp_menores:<órgano>:<expediente>``: el expediente solo es único por órgano."""
    return f"{SOURCE_ID}:{organo}:{expediente}"


def _nif_enmascarado(nif: str | None) -> bool:
    return bool(nif) and "*" in str(nif)


class PlacspContratosMenoresConnector(FeedSindicacionPlacsp):
    """Contratos menores TI de la sindicación 1143, como adjudicaciones cerradas."""

    source_id = SOURCE_ID

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self._sin_senal = 0
        self._ambigua_sin_cpv_ti = 0
        self._estado_por_defecto = 0
        self._sin_organo = 0
        self._adjudicaciones_enmascaradas = 0

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

        organo = identificador_organo(entry)
        if organo is None:
            # Sin órgano no hay clave que no pueda pisar a otro expediente.
            self._sin_organo += 1
            return None
        id_externo = id_externo_menor(organo, lic.id_externo)
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

        todas = parse_adjudicaciones(entry, id_externo)
        adjudicaciones = [a for a in todas if not _nif_enmascarado(a.nif)]
        self._adjudicaciones_enmascaradas += len(todas) - len(adjudicaciones)
        return ParsedTender(licitacion=lic, adjudicaciones=adjudicaciones)

    def contadores_de_descarte(self) -> dict[str, int]:
        """Descartes y correcciones de este run, por motivo (como PSCP, C4.1)."""
        return {
            "placsp_menores_sin_senal_tecnologica": self._sin_senal,
            "placsp_menores_keyword_ambigua_sin_cpv_ti": self._ambigua_sin_cpv_ti,
            "placsp_menores_estado_cerrado_por_defecto": self._estado_por_defecto,
            "placsp_menores_sin_identificador_de_organo": self._sin_organo,
            "placsp_menores_nif_enmascarado": self._adjudicaciones_enmascaradas,
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
