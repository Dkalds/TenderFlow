"""Consultas preliminares de mercado de PLACSP (sindicación 1403) — apagado.

Una consulta preliminar (art. 115 LCSP) es el órgano preguntando al mercado
antes de redactar los pliegos: todavía no hay licitación, pero ya se sabe qué
se va a comprar y quién. Es la otra mitad de la bandeja «Próximas» junto al
anuncio previo, y el feed principal no la trae: el spike de T5
(``docs/plans/2026-09-spike-planes-anuales-placsp.md``) contó ``DOC_CON`` cero
veces en 1.403 entradas, y en la base no hay ninguna fila ``CPM`` fechada en
2026. PLACSP la sindica aparte, en ``sindicacion_1403``. Escrito y apagado
(``PLACSP_CONSULTAS_ATOM_URL`` vacía por defecto; ver
``scraper.connectors.sindicacion_placsp``).

**Medido contra el feed real (2026-10-31).** La primera página trae 459
entradas del 13 de enero al 30 de octubre de 2026, que son 400 consultas
distintas (una consulta reaparece con cada cambio, y el upsert se queda con la
última); 455 entradas en ``PUB`` y 4 en ``REA``. La mitad no trae CPV, y ahí la
única señal es el texto. Esta puerta admite 59 consultas: unas seis al mes.

**No es CODICE de expediente.** Cada entrada es un
``cacext:PreliminaryMarketConsultationStatus``, no un ``ContractFolderStatus``:
sin importe, sin lugar de ejecución, sin plazo de ofertas y casi siempre sin
CPV. Por eso no pasa por ``_PlacspParseCore``; lo que sí reutiliza es la
lectura del órgano (``codice_parser.identificador_organo`` con su ``cfs``) y la
puerta tecnológica.

**Cómo se modela para que no se lea como licitación en plazo.**

1. **Estado ``CPM``** (``services.classification.ESTADOS_PRE_LICITACION``), que
   es lo que lee «Próximas». ``REA`` (realizada) sigue siendo ``CPM``: la
   consulta terminó pero la licitación aún no ha salido. Solo ``ANU``
   (anulada) pasa a ``ANUL``, cerrado.
2. **Sin ``fecha_limite``.** El ``LimitDate`` de la consulta es el plazo para
   *responder*, no para presentar oferta, y el universo puntuable del Radar
   (``scoring_candidates``) es «estado abierto y ``fecha_limite`` viva»: con
   ese plazo en la columna, la consulta entraría a puntuarse como una
   licitación. Viaja en ``descripcion``, junto al texto completo de la
   consulta.
3. **Sin ``fecha_inicio``.** «Próximas» la lee como fecha prevista de la
   compra; ``PlannedDate`` es cuándo se abre la consulta, no eso.

**Filtro TI igual que PLACSP**: la misma puerta
(``scraper.puerta_tecnologica.senal_tecnologica``) sobre el título y todos sus
CPV; entra por keyword (con etiquetas en ``tecnologia``) o por CPV 48/72/32 (sin
ellas), en ``technology_observed``. El título es el objeto
(``ProcurementProject/Name``, «Servicios de ciberseguridad») y, sin él, el
nombre de la consulta. El nombre suele ser un párrafo, y pasarlo también por la
puerta admitía 65 consultas en vez de 59 en la página medida; de las seis de
más, cuatro eran falsos positivos (un microscopio electrónico como
``CLOUD_INFRA``, la edición de un boletín oficial como ``CIBERSEGURIDAD``). Sin
el rescate por clasificador ML: puntúa oportunidades y esto aún no lo es.

**Identidad.** ``id_externo = placsp_consultas:<ID_PLATAFORMA>:<ConsultationID>``.
El identificador lo teclea cada órgano («1/2026», «CPM 01-0526») y se repite
entre órganos, así que va acotado como el feed principal (ADR-038), con NIF y
DIR3 de respaldo; sin ninguno, la entrada se descarta y se cuenta.

Uso::

    python -m scraper.connectors.placsp_consultas --check --dump muestra.atom
    python -m scraper.connectors.placsp_consultas        # pasada incremental
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

if TYPE_CHECKING:
    from scraper.connectors.base import ConnectorRunResult

log = get_logger(__name__)

SOURCE_ID = "placsp_consultas"
#: URL del feed. Verificada el 2026-10-31: 200 ``application/atom+xml`` a un
#: GET, 459 entradas en la primera página y ``rel="next"`` hacia
#: ``CPM_SectorPublico_AAAAMMDD_HHMMSS.atom``.
URL_SINDICACION_1403 = f"{URL_BASE_SINDICACION}sindicacion_1403/CPM_SectorPublico.atom"
VARIABLE = "PLACSP_CONSULTAS_ATOM_URL"

_CPM = "./cacext:PreliminaryMarketConsultationStatus"
#: ``PreliminaryMarketConsultationStatusCode-2.09.gc``: CRE, PUB, REA y ANU.
_ESTADO_ANULADA = "ANU"


class PlacspConsultasConnector(FeedSindicacionPlacsp):
    """Consultas preliminares de mercado TI de la sindicación 1403."""

    source_id = SOURCE_ID

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self._sin_senal = 0
        self._ambigua_sin_cpv_ti = 0
        self._sin_organo = 0
        self._sin_bloque = 0

    def parse(self, raw: RawNotice) -> ParsedTender | None:
        from db.upsert import Licitacion
        from scraper.codice_parser import (
            NS,
            _dir3_del_organo,
            _text,
            _tipos_anuncio,
            identificador_organo,
        )
        from scraper.lineage import current_filter_version
        from scraper.puerta_tecnologica import (
            MOTIVO_AMBIGUA_SIN_CPV_TI,
            MOTIVO_SIN_SENAL,
            senal_tecnologica,
        )
        from shared.dates import to_iso_date

        entry, updated = raw.payload
        consulta_id = _text(entry, f"{_CPM}/cbc:PreliminaryMarketConsultationID")
        if consulta_id is None:
            self._sin_bloque += 1
            return None

        nombre = _text(entry, f"{_CPM}/cbc:ConsultationName") or _text(entry, "./atom:title")
        objeto = _text(entry, f"{_CPM}/cac:ProcurementProject/cbc:Name")
        cpvs = [
            str(c) for c in entry.xpath(f"{_CPM}//cbc:ItemClassificationCode/text()", namespaces=NS)
        ]
        titulo = objeto or nombre or "(sin título)"
        senal = senal_tecnologica(titulo, " ".join(cpvs))
        if not senal.admitida:
            if senal.motivo == MOTIVO_AMBIGUA_SIN_CPV_TI:
                self._ambigua_sin_cpv_ti += 1
            elif senal.motivo == MOTIVO_SIN_SENAL:
                self._sin_senal += 1
            return None

        organo = identificador_organo(entry, _CPM)
        if organo is None:
            self._sin_organo += 1
            return None

        estado = _text(entry, f"{_CPM}/cbcext:PreliminaryMarketConsultationStatusCode")
        limite = to_iso_date(_text(entry, f"{_CPM}/cbc:LimitDate"))
        descripcion = "\n\n".join(
            filter(None, (nombre, limite and f"Plazo para responder a la consulta: {limite}."))
        )
        enlaces = entry.xpath("./atom:link/@href", namespaces=NS)
        publicada = _text(
            entry,
            f"{_CPM}/cacext:ValidNoticeInfo/cacext:AdditionalPublicationStatus"
            "/cacext:AdditionalPublicationDocumentReference/cbc:IssueDate",
        ) or _text(entry, f"{_CPM}/cbc:PlannedDate")

        lic = Licitacion(
            id_externo=f"{SOURCE_ID}:{organo}:{consulta_id}",
            titulo=titulo,
            descripcion=descripcion or None,
            organo_contratacion=_text(
                entry, f"{_CPM}/cacext:LocatedContractingParty/cac:Party/cac:PartyName/cbc:Name"
            ),
            organo_dir3=_dir3_del_organo(entry, _CPM),
            organo_ref_fuente=organo,
            cpv=cpvs[0] if cpvs else None,
            tipo_contrato=_text(entry, f"{_CPM}/cac:ProcurementProject/cbc:TypeCode"),
            estado="ANUL" if estado == _ESTADO_ANULADA else "CPM",
            fecha_publicacion=to_iso_date(publicada) or to_iso_date(updated),
            url=str(enlaces[0]) if enlaces else None,
            raw_keywords=",".join(senal.keywords) or None,
            tecnologia=",".join(senal.tecnologias) or None,
            filter_version=current_filter_version(),
            inclusion_reason=senal.motivo,
            analysis_universe="technology_observed",
            fecha_actualizacion_fuente=updated or None,
            tipos_anuncio=_tipos_anuncio(entry, _CPM),
            fuente=SOURCE_ID,
        )
        # shortcut: los `GeneralDocument` de la consulta (memoria, anexos) no se
        # guardan; subirlo cuando «preparo» necesite leerlos como un pliego.
        return ParsedTender(licitacion=lic)

    def contadores_de_descarte(self) -> dict[str, int]:
        return {
            "placsp_consultas_sin_senal_tecnologica": self._sin_senal,
            "placsp_consultas_keyword_ambigua_sin_cpv_ti": self._ambigua_sin_cpv_ti,
            "placsp_consultas_sin_identificador_de_organo": self._sin_organo,
            "placsp_consultas_sin_bloque_de_consulta": self._sin_bloque,
        }


def ejecutar(*, url: str | None = None) -> ConnectorRunResult | None:
    """Una pasada incremental; ``None`` si la fuente está apagada (sin URL).

    La usan ``main`` y el carril diario del worker
    (``scheduler/jobs/daily_atom.py``). No abre ni cierra la BD.
    """
    return ejecutar_sindicacion(
        source_id=SOURCE_ID,
        url=url if url is not None else settings.PLACSP_CONSULTAS_ATOM_URL,
        variable=VARIABLE,
        crear=PlacspConsultasConnector,
    )


def main(argv: list[str] | None = None) -> int:
    return main_sindicacion(
        argv,
        descripcion="Ingesta de consultas preliminares de mercado de PLACSP (sindicación 1403)",
        source_id=SOURCE_ID,
        variable=VARIABLE,
        url_documentada=URL_SINDICACION_1403,
        crear=PlacspConsultasConnector,
    )


if __name__ == "__main__":
    raise SystemExit(main())
