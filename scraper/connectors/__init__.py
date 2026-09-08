"""Framework de conectores multi-fuente (ADR-009).

Cada fuente implementa el contrato ``Connector`` (fetch + parse); el runner
genérico aporta cursores incrementales, upsert idempotente con historial,
DLQ, resolución de empresas e invalidación de caché.

``REGISTERED_SOURCES`` es además el **inventario de frescura** que consume
``scheduler/healthcheck.py`` (S2.3): sin él, una fuente muerta durante semanas
no se distingue de una fuente que simplemente no tenía nada que ingerir, porque
seis de los conectores corren en ``scrape-daily.yml`` con
``continue-on-error: true`` y el job sale verde igual.

Desde T7/D16 (2026-09-06) es también la **cobertura declarada**: cada fuente
lleva su nombre público, su ``alcance`` honesto y su ``estado``, y el módulo
declara además qué queda ``FUERA_DE_ALCANCE`` y por qué. Lo publica
``GET /api/v1/publico/cobertura`` y lo pinta ``/cobertura``. Vive aquí, y no en
una prosa aparte, porque una página de cobertura escrita a mano envejece contra
el código sin que falle nada: hasta hoy la página nombraba PLACSP, TED, Galicia
y Euskadi en un párrafo, y no había forma de notar que faltaban tres.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scraper.connectors.base import Connector, ParsedTender, RawNotice, run_connector
from scraper.connectors.euskadi import EuskadiApiConnector
from scraper.connectors.galicia import GaliciaRssConnector
from scraper.connectors.watched_company_awards import PlacspWatchedCompanyAwardsConnector

#: Los tres estados en los que una fuente puede estar declarada (D16).
#:
#: - ``activa``: corre y se le exige frescura. Su ausencia alerta.
#: - ``opcional``: puede estar legítimamente apagada —le falta su variable de
#:   entorno, o no tiene nada que vigilar—. «Sin registro de salud» no alerta;
#:   un registro viejo sí, porque eso significa que corría y dejó de correr.
#: - ``fuera_de_alcance``: declarada fuera del alcance del producto. Ni se
#:   ingiere ni se vigila, y el healthcheck la salta entera. Es el estado que
#:   permite retirar una fuente **diciéndolo** en `/cobertura`, en vez de
#:   borrarla del inventario y dejar de contarla.
EstadoCobertura = Literal["activa", "opcional", "fuera_de_alcance"]


@dataclass(frozen=True)
class RegisteredSource:
    """Una fuente de ingesta: su SLA de frescura y su cobertura declarada.

    Attributes:
        source_id: Nombre canónico, **tal como se escribe en
            ``source_ingestion_health.source``** (o sea, el ``source_id`` del
            conector). Es la clave de unión con el repositorio de salud: si no
            coincide, el chequeo mide otra cosa, o no mide nada.
        nombre: Cómo se llama la fuente para un lector que no conoce el
            ``source_id``. Se publica en `/cobertura`; el ``source_id`` viaja
            igualmente, porque es el que aparece en una alerta o en un ticket.
        modulo: Módulo importable del conector. Documental —el healthcheck no
            importa nada— pero permite ir del nombre de una alerta al código.
        max_lag_hours: Horas sin un run exitoso a partir de las cuales la
            fuente se considera atrasada.
        motivo: Por qué ese umbral y no otro. Un umbral sin motivo escrito se
            «ajusta» a la primera alerta molesta hasta que deja de alertar.
            Es razonamiento operativo interno y NO se publica.
        alcance: Qué universo cubre la fuente y qué no. Esto sí se publica: es
            la frase que impide leer un feed de descubrimiento como un censo
            de mercado (ver ``docs/regional-source-coverage.md``).
        estado: Ver ``EstadoCobertura``.
    """

    source_id: str
    nombre: str
    modulo: str
    max_lag_hours: int
    motivo: str
    alcance: str
    estado: EstadoCobertura = "activa"

    @property
    def opcional(self) -> bool:
        """¿«Sin registro de salud» es un estado legítimo para esta fuente?

        Se conserva como propiedad derivada —y no como campo— porque
        ``scheduler/healthcheck.py`` y sus tests preguntan exactamente esto y
        la respuesta no cambió al abrir el tercer estado: lo que cambió es que
        ahora hay dos motivos distintos para que no alerte. Un booleano no
        podía distinguir «apagada porque le falta su variable» de «retirada del
        alcance del producto», y esa diferencia es justo la que `/cobertura`
        tiene que contarle a quien lee la página.
        """
        return self.estado != "activa"


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
        nombre="PLACSP — Plataforma de Contratación del Sector Público",
        modulo="scraper.connectors.placsp",
        max_lag_hours=_LAG_CARRIL_DIARIO,
        motivo=(
            "Feed ATOM nacional: es el corpus, no un complemento. Corre en cada "
            "pasada de 4 h; 36 h sin un run exitoso son nueve ciclos perdidos."
        ),
        alcance=(
            "Feed ATOM oficial. Es el corpus: los anuncios de los órganos que "
            "publican allí su perfil del contratante, acotados a la señal de "
            "tecnología enterprise. Se consulta cada cuatro horas con cursor "
            "incremental e historial de cambios por expediente."
        ),
    ),
    RegisteredSource(
        source_id="ted",
        nombre="TED — Diario Oficial de la Unión Europea",
        modulo="scraper.connectors.ted",
        max_lag_hours=_LAG_SEMANAL,
        motivo=(
            "Cobertura europea complementaria. Corre a diario, pero un run sin "
            "avisos TI se registra igual como 'success', así que el lag solo "
            "crece cuando el conector de verdad no completa."
        ),
        alcance=(
            "Cobertura europea complementaria. Ni sustituye a PLACSP ni "
            "completa su histórico: aporta los anuncios que llegan al diario "
            "europeo, no una segunda copia del mercado español."
        ),
    ),
    RegisteredSource(
        source_id="galicia_rss",
        nombre="Galicia — RSS oficial de contratación",
        modulo="scraper.connectors.galicia",
        max_lag_hours=_LAG_SEMANAL,
        motivo=(
            "RSS autonómico declarado como cobertura de descubrimiento, no como "
            "censo de mercado (ver `regional_rss`). Su SLA es más flojo por "
            "diseño, y una indisponibilidad regional no debe generar ruido diario."
        ),
        alcance=(
            "Publicaciones recientes del RSS oficial, filtradas por señal "
            "tecnológica. Descubrimiento, no censo: el feed no es histórico ni "
            "comunica todos los cambios de un expediente."
        ),
    ),
    RegisteredSource(
        source_id="euskadi",
        nombre="Euskadi — API oficial de contratación",
        modulo="scraper.connectors.euskadi",
        max_lag_hours=_LAG_DIARIO_TOLERANTE,
        motivo=(
            "Buscador oficial paginado, no un feed de descubrimiento: recorre el "
            "histórico por cursor de fecha, así que un run perdido se recupera "
            "solo en el siguiente. SLA más estricto que el de galicia_rss porque "
            "aquí sí hay un censo detrás (~698.000 resultados) y dejar de mirarlo "
            "dos días sí es señal."
        ),
        alcance=(
            "Censo, no descubrimiento (C4.3): la API REST oficial se recorre "
            "paginada por cursor de fecha, así que el histórico es alcanzable y "
            "no sólo la ventana del feed. El RSS se mantiene como descubrimiento."
        ),
    ),
    RegisteredSource(
        source_id="pscp",
        nombre="Catalunya — PSCP (dataset Socrata)",
        modulo="scraper.connectors.pscp",
        max_lag_hours=_LAG_DIARIO_TOLERANTE,
        motivo=(
            "Dataset Socrata de ~1,86 M filas con paginación por cursor: un run "
            "puede agotar su presupuesto de 10 min sin terminar y aun así haber "
            "progresado. Dos días seguidos sin completar sí es señal."
        ),
        alcance=(
            "Dataset Socrata incremental de la Plataforma de Serveis de "
            "Contractació Pública. Lo que entra depende del dataset "
            "configurado y de los campos que ese dataset publica."
        ),
        estado="opcional",
    ),
    RegisteredSource(
        source_id="tacrc",
        nombre="TACRC — resoluciones de recurso",
        modulo="scraper.connectors.tacrc",
        max_lag_hours=_LAG_SEMANAL,
        motivo=(
            "Índice de resoluciones: el contenido nuevo llega en tandas "
            "semanales, así que exigirle cadencia diaria solo produciría ruido."
        ),
        alcance=(
            "Índice de resoluciones del Tribunal Administrativo Central de "
            "Recursos Contractuales. No aporta anuncios de licitación: aporta "
            "cómo terminaron los recursos presentados."
        ),
        estado="opcional",
    ),
    RegisteredSource(
        source_id="placsp_watched_company_awards",
        nombre="PLACSP — adjudicaciones de empresas vigiladas",
        modulo="scraper.connectors.watched_company_awards",
        max_lag_hours=_LAG_DIARIO_TOLERANTE,
        motivo=(
            "Carril de radar por NIF vigilado. Corre a diario, pero sin NIFs "
            "canónicos vigilados el CLI termina antes de tocar la fuente y no "
            "deja registro de salud — de ahí que sea opcional."
        ),
        alcance=(
            "Carril específico sobre la misma fuente PLACSP: conserva las "
            "adjudicaciones de las empresas que una organización vigila desde "
            "el momento del alta. Sin empresas vigiladas no ingiere nada."
        ),
        estado="opcional",
    ),
)

#: Índice por nombre canónico, que es como llegan las filas de
#: ``source_ingestion_health``.
REGISTERED_SOURCES_BY_ID: dict[str, RegisteredSource] = {s.source_id: s for s in REGISTERED_SOURCES}


@dataclass(frozen=True)
class AmbitoExcluido:
    """Un trozo de contratación pública que el producto NO cubre, con fecha.

    No es un ``RegisteredSource`` sin conector: es lo contrario de una fuente.
    No tiene módulo, ni SLA de frescura, ni fila en ``source_ingestion_health``,
    y meterlo en ``REGISTERED_SOURCES`` haría que el healthcheck lo reclamara
    cada seis horas como una fuente muerta.

    Lo que sí comparte con una fuente es el sitio donde vive. La alternativa
    —escribir la lista en la página— es la que crea el fallo de siempre: la
    prosa y el código dicen cosas distintas y nada falla.

    Attributes:
        ambito: Qué queda fuera, en los términos en los que lo preguntaría un
            cliente («contratos menores», no «tabla X»).
        motivo: Por qué. Una exclusión sin motivo se lee como un olvido.
        decision: Identificador de la decisión que lo dejó fuera, para poder
            ir del párrafo publicado al acta que lo decidió.
        desde: Fecha (ISO) de esa decisión. Sin fecha, «fuera de alcance» no se
            distingue de «todavía no llegamos», y la segunda caduca sola.
    """

    ambito: str
    motivo: str
    decision: str
    desde: str


#: Cómo entra algo que hoy está fuera. No por descubrimiento nuestro: por
#: petición escrita, que es lo que D16 fijó el 2026-09-06.
VIA_DE_ENTRADA_FUERA_DE_ALCANCE = (
    "Se abre un conector cuando una organización cliente lo pide por escrito. "
    "No hay una fecha comprometida para ninguno de estos ámbitos."
)

#: Fecha de la decisión D16. Se escribe una vez y viaja con cada exclusión.
_FECHA_D16 = "2026-09-06"

#: Lo que queda fuera del alcance declarado (D16, 2026-09-06).
FUERA_DE_ALCANCE: tuple[AmbitoExcluido, ...] = (
    AmbitoExcluido(
        ambito="Contratos menores",
        motivo=(
            "Se adjudican sin concurrencia previa y se publican agregados "
            "después del hecho. No hay ventana de licitación que anticipar, "
            "que es exactamente lo que el producto sirve."
        ),
        decision="D16",
        desde=_FECHA_D16,
    ),
    AmbitoExcluido(
        ambito="BOE",
        motivo=(
            "Sus anuncios de contratación remiten al perfil del contratante. "
            "No se ha medido qué expedientes aportaría que PLACSP no traiga ya, "
            "y sin esa medición no se integra."
        ),
        decision="D16",
        desde=_FECHA_D16,
    ),
    AmbitoExcluido(
        ambito="Portales autonómicos no integrados (Madrid, Andalucía, Comunidad Valenciana)",
        motivo=(
            "Cada portal es una integración propia, con su formato y su "
            "mantenimiento. Hoy hay conector para Catalunya, Galicia y "
            "Euskadi; lo que publiquen los demás por su cuenta no se descubre "
            "y tampoco se cuenta."
        ),
        decision="D16",
        desde=_FECHA_D16,
    ),
)

__all__ = [
    "FUERA_DE_ALCANCE",
    "REGISTERED_SOURCES",
    "REGISTERED_SOURCES_BY_ID",
    "VIA_DE_ENTRADA_FUERA_DE_ALCANCE",
    "AmbitoExcluido",
    "Connector",
    "EstadoCobertura",
    "EuskadiApiConnector",
    "GaliciaRssConnector",
    "ParsedTender",
    "PlacspWatchedCompanyAwardsConnector",
    "RawNotice",
    "RegisteredSource",
    "run_connector",
]
