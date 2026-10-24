"""Agenda de Mi Pipeline: la cronología fusionada de compromisos."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.dto.pursuits import PursuitDecision, PursuitStatus

# ── Agenda de Mi Pipeline ───────────────────────────────────────────────────
#
# La agenda fusiona los compromisos de la organización en una sola cronología
# por usuario/organización. La fusión, el orden y la banda de urgencia se
# calculan en backend (ADR-014: el frontend no fabrica orden ni agregados).
#
# Cada ``kind`` lleva **una** fecha y dice de qué clase es (``due_kind``): el
# plazo externo de presentación de un pursuit y la acción interna que alguien
# tiene que hacer son compromisos distintos, con dueños distintos, y mezclarlos
# en un mismo ``due_date`` dejaba al usuario sin saber cuál de los dos vencía.

AgendaItemKind = Literal["pursuit", "tarea", "contrato", "senal", "renovacion"]
#: Qué clase de fecha es ``due_date``: ``plazo`` (presentación de la licitación,
#: en pursuits y señales), ``accion`` (vencimiento de una tarea), ``fin_contrato``
#: (fin efectivo de un contrato, propio o del mercado) o ``relicitacion``
#: (inicio de la ventana en la que se espera la relicitación de un contrato
#: propio sin renovación preparada).
AgendaDueKind = Literal["plazo", "accion", "fin_contrato", "relicitacion"]
AgendaUrgencia = Literal["vencida", "hoy", "semana", "mes", "despues", "sin_fecha"]
#: En qué tramo de la agenda va la fila. Es ``urgencia`` salvo en los dos casos
#: en que el plazo de presentación ya no es algo que se pueda cumplir:
#: ``plazo_pasado`` (ya no se puede presentar y no hubo oferta: lo pendiente es
#: cerrarla) y ``en_resolucion`` (la oferta está entregada: lo pendiente es el
#: resultado). «Ya no se puede presentar» es que el plazo pasó **o** que el
#: expediente está cerrado (``expediente_cerrado``), tenga o no fecha límite.
#: El orden de este ``Literal`` es el de los tramos en pantalla.
AgendaBanda = Literal[
    "vencida",
    "hoy",
    "semana",
    "plazo_pasado",
    "mes",
    "despues",
    "en_resolucion",
    "sin_fecha",
]
#: Los contadores de la franja, que además filtran la lista. Cada fila declara
#: en cuáles cuenta (``PipelineAgendaItem.cuenta_en``) y el contador es ese
#: recuento (``PipelineAgendaContadores``): número y filas salen de una regla.
AgendaContador = Literal["plazo_semana", "accion_vencida", "go_no_go", "sin_paso", "plazo_pasado"]


class PipelineAgendaItem(BaseModel):
    """Una fila de la agenda, ya clasificada por urgencia.

    Los campos específicos de cada ``kind`` son NULL en los demás:

    - ``pursuit``: ``pursuit_id``/``status``/``decision``/``responsible_*``/
      ``next_action``/``version``. ``due_date`` es **solo** el plazo de
      presentación; ``next_action``/``next_action_due`` viajan como dato
      informativo, no como la fecha del compromiso. Lleva además lo que la
      ingesta sabe del expediente: ``expediente_estado``,
      ``expediente_cerrado`` y, si ya hay adjudicación publicada, sus
      adjudicatarios en ``adjudicatario``.
    - ``tarea``: los mismos campos del pursuit al que pertenece, más
      ``tarea_id``/``tarea_texto``. ``tarea_id`` es NULL cuando la fila es la
      ``next_action`` manual de un pursuit sin tareas abiertas (se edita con
      ``PATCH /pursuits/{id}``, no con las rutas de tareas).
    - ``contrato``: ``cartera_id``, ``fecha_fin_efectiva``, ``fecha_fin_origen``,
      ``relicitacion_desde``/``relicitacion_hasta``, ``renovacion_pursuit_id``
      y ``prorrogas_aplicadas``; ``pursuit_id`` es la oportunidad ganada de
      origen.
    - ``senal``: ``rule_id``/``rule_nombre``.
    - ``renovacion`` (mercado, solo con ``incluir_mercado``): ``adjudicatario``,
      ``riesgo_cambio`` y ``fecha_fin_origen``.

    ``importe_eur`` es presupuesto de licitación (pursuit/tarea/señal) o importe
    adjudicado del contrato (contrato/renovación).
    """

    model_config = ConfigDict(extra="forbid")

    kind: AgendaItemKind
    urgencia: AgendaUrgencia
    due_date: date | None
    dias_restantes: int | None
    licitacion_id: str
    titulo: str | None
    organo: str | None
    importe_eur: float | None
    ccaa: str | None
    tecnologia: str | None
    url: str | None
    pursuit_id: int | None
    status: PursuitStatus | None
    decision: PursuitDecision | None
    responsible_user_id: int | None
    responsible_name: str | None
    next_action: str | None
    next_action_due: date | None
    version: int | None
    rule_id: int | None
    rule_nombre: str | None
    adjudicatario: str | None
    riesgo_cambio: float | None
    #: En renovaciones de mercado: ``real`` si la fuente publicó la fecha de
    #: fin, ``estimada_*`` si se calculó con la duración. En contratos propios:
    #: ``publicada`` | ``duracion`` | ``prorroga`` | ``manual`` (el vocabulario
    #: de la cartera). Opcional para no romper a los clientes que construyen
    #: items sin este dato.
    fecha_fin_origen: str | None = None
    #: Qué clase de fecha es ``due_date``. Va puesto aunque ``due_date`` sea
    #: NULL: describe el hueco del compromiso, no solo la fecha que lo llena.
    due_kind: AgendaDueKind | None = None
    #: Solo en ``tarea``. ``tarea_id`` NULL = la ``next_action`` manual del
    #: pursuit (no hay fila en ``pursuit_tasks`` que editar).
    tarea_id: int | None = None
    tarea_texto: str | None = None
    #: Solo en ``contrato`` (la fila de ``contratos_cartera`` que lo origina).
    cartera_id: int | None = None
    fecha_fin_efectiva: date | None = None
    relicitacion_desde: date | None = None
    relicitacion_hasta: date | None = None
    renovacion_pursuit_id: int | None = None
    prorrogas_aplicadas: int | None = None
    #: Hora peninsular (``HH:MM``) del plazo de presentación, cuando la fuente
    #: la publicó. Solo en ``pursuit`` y ``senal``: «hoy» no distingue las 09:00
    #: de la medianoche. NULL si el plazo es una fecha sola.
    due_hora: str | None = None
    #: Tramo en el que va la fila. Opcional por los clientes que construyen
    #: items sin él; el servicio lo pone siempre, y quien no lo tenga cae en
    #: ``urgencia``.
    banda: AgendaBanda | None = None
    #: Contadores de la franja en los que cuenta esta fila.
    cuenta_en: list[AgendaContador] = Field(default_factory=list)
    #: Solo en ``pursuit``: cuántas filas ``tarea`` suyas hay en la agenda.
    tareas_abiertas: int | None = None
    #: Solo en ``pursuit``: el estado del expediente tal y como lo guarda la
    #: ingesta (``PUB``, ``EV``, ``RES``, ``ADJ``, ``ANUL``…), o NULL.
    expediente_estado: str | None = None
    #: Solo en ``pursuit``: el expediente ya no admite ofertas —su estado es de
    #: cierre (``shared.estados.ESTADOS_CERRADOS``) o tiene adjudicación
    #: publicada—. Lo decide el servicio; la consola no lo deduce del estado.
    expediente_cerrado: bool = False


class PipelineAgendaKpis(BaseModel):
    """Franja de compromisos de la agenda, calculada sobre el scope completo.

    ``vence_semana`` mide **plazos de presentación** (pursuits, vencidos
    incluidos); ``acciones_hoy`` mide tareas; ``relicitaciones_abiertas``,
    contratos propios cuya ventana de relicitación ya empezó sin renovación
    preparada. Tres relojes distintos, tres contadores: sumarlos daría un
    número que no dice a quién le toca hacer qué.

    La consola dejó de leer ``vence_semana``, ``go_no_go_pendientes`` y
    ``sin_proxima_accion`` (lee ``PipelineAgendaContadores``): contaban como
    trabajo pendiente los plazos que ya habían pasado. Se conservan con el
    significado de siempre porque son contrato publicado.
    """

    vence_semana: int = Field(ge=0)
    vence_semana_importe_eur: float = Field(ge=0)
    go_no_go_pendientes: int = Field(ge=0)
    #: Pursuits sin ``next_action`` **y** sin tarea abierta.
    sin_proxima_accion: int = Field(ge=0)
    senales_nuevas: int = Field(ge=0)
    #: Tareas que vencen hoy o ya vencieron.
    acciones_hoy: int = Field(default=0, ge=0)
    #: Contratos con ``due_kind="relicitacion"`` cuya ventana ya está abierta.
    relicitaciones_abiertas: int = Field(default=0, ge=0)


class PipelineAgendaContadores(BaseModel):
    """Los contadores que la franja de la agenda enseña y con los que filtra.

    Cada uno es el número de filas que lo llevan en ``cuenta_en``, y los cuatro
    de oportunidades miran solo las que **siguen vivas**: un plazo que pasó sin
    oferta cuenta en ``plazo_pasado`` y en ninguno más, y una oferta presentada
    no cuenta en ninguno. Así el número de un contador y las filas que deja al
    pulsarlo son siempre los mismos.
    """

    #: Oportunidades sin presentar con el plazo entre hoy y siete días.
    plazo_semana: int = Field(default=0, ge=0)
    #: Presupuesto de esas oportunidades: lo que todavía se puede presentar.
    plazo_semana_importe_eur: float = Field(default=0, ge=0)
    #: Tareas que vencen hoy o ya vencieron.
    accion_vencida: int = Field(default=0, ge=0)
    #: Oportunidades vivas sin decisión go/no-go.
    go_no_go: int = Field(default=0, ge=0)
    #: Oportunidades vivas sin ``next_action`` ni tarea abierta.
    sin_paso: int = Field(default=0, ge=0)
    #: Oportunidades sin presentar a las que ya no se puede presentar oferta:
    #: el plazo pasó o el expediente está cerrado.
    plazo_pasado: int = Field(default=0, ge=0)


class PipelineAgendaResponse(BaseModel):
    """Respuesta de ``GET /api/v1/pursuits/agenda``."""

    organization_id: int = Field(ge=1)
    solo_mios: bool
    items: list[PipelineAgendaItem] = Field(default_factory=list)
    kpis: PipelineAgendaKpis
    #: Nº de pursuits abiertos considerados; si se alcanzó el tope interno la
    #: agenda lo declara en vez de presentar KPIs silenciosamente bajos.
    pursuits_total: int = Field(ge=0)
    pursuits_truncados: bool
    senales_truncadas: bool
    renovaciones_horizonte_meses: int = Field(ge=1, le=60)
    #: Las tareas abiertas también tienen tope; si se alcanzó, se declara.
    tareas_truncadas: bool = False
    contadores: PipelineAgendaContadores = Field(default_factory=PipelineAgendaContadores)
    #: Reglas de watchlist activas del usuario. Con cero no puede llegar
    #: ninguna señal: la consola lo dice en vez de enseñar una bandeja vacía.
    reglas_activas: int = Field(default=0, ge=0)
