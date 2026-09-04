"""Framework de conectores multi-fuente (ADR-009).

Cada fuente implementa el contrato ``Connector`` (fetch + parse); el runner
genérico aporta cursores incrementales, upsert idempotente con historial,
DLQ, resolución de empresas e invalidación de caché.

``REGISTERED_SOURCES`` es además el **inventario de frescura** que consume
``scheduler/healthcheck.py`` (S2.3): sin él, una fuente muerta durante semanas
no se distingue de una fuente que simplemente no tenía nada que ingerir, porque
seis de los conectores corren en ``scrape-daily.yml`` con
``continue-on-error: true`` y el job sale verde igual.
"""

from __future__ import annotations

from dataclasses import dataclass

from scraper.connectors.base import Connector, ParsedTender, RawNotice, run_connector
from scraper.connectors.euskadi import EuskadiRssConnector
from scraper.connectors.galicia import GaliciaRssConnector
from scraper.connectors.watched_company_awards import PlacspWatchedCompanyAwardsConnector


@dataclass(frozen=True)
class RegisteredSource:
    """Una fuente de ingesta y el SLA de frescura que se le exige.

    Attributes:
        source_id: Nombre canónico, **tal como se escribe en
            ``source_ingestion_health.source``** (o sea, el ``source_id`` del
            conector). Es la clave de unión con el repositorio de salud: si no
            coincide, el chequeo mide otra cosa, o no mide nada.
        modulo: Módulo importable del conector. Documental —el healthcheck no
            importa nada— pero permite ir del nombre de una alerta al código.
        max_lag_hours: Horas sin un run exitoso a partir de las cuales la
            fuente se considera atrasada.
        motivo: Por qué ese umbral y no otro. Un umbral sin motivo escrito se
            «ajusta» a la primera alerta molesta hasta que deja de alertar.
        opcional: La fuente puede estar legítimamente apagada (le falta su
            variable de entorno, o no tiene nada que vigilar). Para estas, «no
            hay ningún registro de salud» NO alerta — pero un registro viejo
            sí: eso significa que corría y dejó de correr.
    """

    source_id: str
    modulo: str
    max_lag_hours: int
    motivo: str
    opcional: bool = False


#: Umbral de referencia del carril diario: la pipeline corre cada 4 h, así que
#: 36 h son nueve ciclos. Es el mismo número que usa ``--freshness-hours`` del
#: healthcheck para el último ``extraction_run``, y a propósito: la fuente que
#: sostiene el corpus y la pasada que lo ingiere no pueden tener SLAs distintos.
_LAG_CARRIL_DIARIO = 36
#: Dos días de margen para fuentes que corren a diario pero cuyo fallo no pierde
#: datos de forma irreversible (la fuente conserva el histórico y el siguiente
#: run lo recupera).
_LAG_DIARIO_TOLERANTE = 72
#: Una semana. Para las fuentes declaradas explícitamente como *cobertura de
#: descubrimiento*, no como censo (ver el docstring de ``regional_rss``).
_LAG_SEMANAL = 168

#: Inventario de fuentes vivas. Las fuentes ``bulk_YYYYMM`` NO están aquí: son
#: efímeras por diseño (una por mes reprocesado) y no tienen frescura que vigilar.
REGISTERED_SOURCES: tuple[RegisteredSource, ...] = (
    RegisteredSource(
        source_id="placsp",
        modulo="scraper.connectors.placsp",
        max_lag_hours=_LAG_CARRIL_DIARIO,
        motivo=(
            "Feed ATOM nacional: es el corpus, no un complemento. Corre en cada "
            "pasada de 4 h; 36 h sin un run exitoso son nueve ciclos perdidos."
        ),
    ),
    RegisteredSource(
        source_id="ted",
        modulo="scraper.connectors.ted",
        max_lag_hours=_LAG_SEMANAL,
        motivo=(
            "Cobertura europea complementaria. Corre a diario, pero un run sin "
            "avisos TI se registra igual como 'success', así que el lag solo "
            "crece cuando el conector de verdad no completa."
        ),
    ),
    RegisteredSource(
        source_id="galicia_rss",
        modulo="scraper.connectors.galicia",
        max_lag_hours=_LAG_SEMANAL,
        motivo=(
            "RSS autonómico declarado como cobertura de descubrimiento, no como "
            "censo de mercado (ver `regional_rss`). Su SLA es más flojo por "
            "diseño, y una indisponibilidad regional no debe generar ruido diario."
        ),
    ),
    RegisteredSource(
        source_id="euskadi_rss",
        modulo="scraper.connectors.euskadi",
        max_lag_hours=_LAG_SEMANAL,
        motivo="Mismo criterio que galicia_rss.",
    ),
    RegisteredSource(
        source_id="pscp",
        modulo="scraper.connectors.pscp",
        max_lag_hours=_LAG_DIARIO_TOLERANTE,
        motivo=(
            "Dataset Socrata de ~1,86 M filas con paginación por cursor: un run "
            "puede agotar su presupuesto de 10 min sin terminar y aun así haber "
            "progresado. Dos días seguidos sin completar sí es señal."
        ),
        opcional=True,
    ),
    RegisteredSource(
        source_id="tacrc",
        modulo="scraper.connectors.tacrc",
        max_lag_hours=_LAG_SEMANAL,
        motivo=(
            "Índice de resoluciones: el contenido nuevo llega en tandas "
            "semanales, así que exigirle cadencia diaria solo produciría ruido."
        ),
        opcional=True,
    ),
    RegisteredSource(
        source_id="placsp_watched_company_awards",
        modulo="scraper.connectors.watched_company_awards",
        max_lag_hours=_LAG_DIARIO_TOLERANTE,
        motivo=(
            "Carril de radar por NIF vigilado. Corre a diario, pero sin NIFs "
            "canónicos vigilados el CLI termina antes de tocar la fuente y no "
            "deja registro de salud — de ahí `opcional`."
        ),
        opcional=True,
    ),
)

#: Índice por nombre canónico, que es como llegan las filas de
#: ``source_ingestion_health``.
REGISTERED_SOURCES_BY_ID: dict[str, RegisteredSource] = {s.source_id: s for s in REGISTERED_SOURCES}

__all__ = [
    "REGISTERED_SOURCES",
    "REGISTERED_SOURCES_BY_ID",
    "Connector",
    "EuskadiRssConnector",
    "GaliciaRssConnector",
    "ParsedTender",
    "PlacspWatchedCompanyAwardsConnector",
    "RawNotice",
    "RegisteredSource",
    "run_connector",
]
