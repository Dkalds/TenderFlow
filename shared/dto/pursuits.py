"""Oportunidades (pursuits): vocabularios, ficha, comentarios, métricas y calidad del Radar."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.dto.paginacion import MAX_PAGE_LIMIT
from shared.dto.primitivas import PgDateTime, SafeStr

# ── Vocabularios de oportunidades (Fase 1 TenderFlow) ──────────────────────

PursuitStatus = Literal[
    "identified",
    "qualifying",
    "go_no_go",
    "preparing",
    "submitted",
    "won",
    "lost",
    "withdrawn",
]
PursuitDecision = Literal["pending", "go", "no_go"]
PursuitOutcome = Literal["pending", "won", "lost", "cancelled"]

#: Filtro de plazo del tablero (`GET /pursuits?plazo=`): el de presentación del
#: expediente, sobre oportunidades abiertas y sin presentar. `vencido` es «el
#: día ya pasó»; `7d` y `30d`, «vence de hoy a dentro de N días», ambos
#: inclusive. Mismo criterio que `services/carga_equipo.py` en Dirección.
PursuitPlazo = Literal["vencido", "7d", "30d"]

#: Vocabulario de bandas del Radar, y **la declaración canónica de este
#: enumerado**. Lo fija ``_band()`` en ``services/analytics/scoring.py``; la
#: revisión ``v93`` lo guardó deliberadamente como TEXT para que la banda pueda
#: moverse sin migrar.
#:
#: Es la única: la copia ``Banda`` que vivía en ``services/watchlist_rules.py``
#: (y publicaba ``banda_min`` en el contrato) se sustituyó por este alias.
#: ``tests/test_radar_banda_canonica.py`` impide que vuelva otra.
#:
#: **Orden canónico: de mayor a menor interés comercial** (``Caliente`` →
#: ``Descarte``), el mismo en que ``_band()`` va comparando umbrales de arriba
#: abajo. Un ``Literal`` es un CONJUNTO —``typing.Literal`` compara y hashea
#: por conjunto—, así que este orden no significa nada para el tipo: significa
#: para el *contrato generado*, que es una lista y sí tiene orden. Quien
#: necesite comparar bandas entre sí usa una escala ordinal explícita, no este
#: orden (ver ``ORDEN_BANDAS`` en ``services/watchlist_rules.py``).
#:
#: **No vuelvas a escribir ``Literal["Caliente", …]`` en otro fichero: importa
#: este alias.** Precisamente porque son iguales por conjunto, dos
#: declaraciones de las mismas cuatro bandas en distinto orden son el MISMO
#: tipo (``==`` y ``hash()`` coinciden), y las cachés de ``typing`` van por
#: igualdad: en CPython 3.13 —el intérprete del CI— ``Banda | None`` pasa por
#: ``typing.Union``, que está memoizado, así que la segunda declaración
#: recupera la primera y el enumerado sale en el orden de quien se importase
#: antes. Eso dependía del orden de importación de los routers: el mismo código
#: generaba dos ``api/openapi.json`` distintos y el job «Codegen Drift Check»
#: fallaba al azar sobre una línea de ``web/src/generated/api.d.ts`` que nadie
#: había tocado. (En 3.14 ``|`` ya no pasa por esa caché y cada declaración
#: conserva su orden — que es peor, no mejor: el drift solo aparece en CI.) Un
#: gate que falla por azar deja de leerse, y este es el que impide que el
#: cliente TS y la API se separen. Una sola declaración cierra el problema en
#: cualquier versión; alinear copias a mano solo lo aplaza hasta la siguiente.
RadarBanda = Literal["Caliente", "Atractiva", "Tibia", "Descarte"]

#: Motivos de pérdida (D37). **Lista cerrada**, y ésa es la decisión: una lista
#: abierta no se puede agregar, y la pregunta que abre esta función —«¿por qué
#: perdemos en el CPV 72?»— sólo tiene respuesta si los motivos se pueden
#: contar. El matiz sigue viajando en `outcome_reason`, que es texto libre y no
#: se toca.
#:
#: `sin_codificar` **no** está aquí: no es un motivo que alguien elija, es la
#: ausencia de código de los cierres anteriores a v104. Se representa con la
#: columna a NULL para que no se confunda con un `otro` deliberado, que es una
#: respuesta distinta y mucho más informativa.
PursuitOutcomeReasonCode = Literal[
    "precio",
    "tecnica",
    "solvencia",
    "plazo",
    "desierto_o_anulado",
    "no_presentada",
    "otro",
]


class PursuitCreate(BaseModel):
    """Convierte una licitación existente en oportunidad colaborativa.

    ``score_al_abrir`` y ``banda_al_abrir`` son la puntuación que el usuario
    tenía en pantalla al comprometerse, y los manda el cliente porque el score
    no se persiste en ninguna parte: se calcula en vivo sobre el universo del día
    y los pesos del perfil, así que recalcularlo aquí daría un número distinto
    del que motivó la decisión. Sin ellos no hay forma de responder si el Radar
    prioriza bien —la promesa central del producto—, y el dato es irrecuperable
    a posteriori (revisión ``v93``).

    Opcionales: abrir la oportunidad es la acción y medir es el efecto
    secundario. Una llamada por API o un cliente antiguo siguen funcionando, y
    la fila queda con ``NULL``, que significa «no se supo».
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    licitacion_id: str = Field(min_length=1, max_length=500)
    organization_id: int | None = Field(default=None, ge=1)
    responsible_user_id: int | None = Field(default=None, ge=1)
    score_al_abrir: int | None = Field(default=None, ge=0, le=100)
    banda_al_abrir: RadarBanda | None = None
    #: Lote del expediente por el que se puja. ``None`` es «el expediente
    #: completo», que es lo único que existía hasta la revisión ``v110`` y
    #: sigue siendo el caso por defecto. Es el ``id`` de ``lotes`` que el
    #: cliente tiene en pantalla; el servicio comprueba que ese lote pertenezca
    #: a ``licitacion_id`` y persiste su número, que es la parte estable (los
    #: ids de ``lotes`` se renumeran en cada re-ingesta).
    lote_id: int | None = Field(default=None, ge=1)
    #: Valor de cada dimensión del score en el momento de abrir, tal como lo
    #: pintó el desglose del Radar. Mismo razonamiento que ``score_al_abrir``:
    #: no se puede recalcular después (depende del universo y de los pesos de
    #: aquel día), y sin él no hay forma de proponer un ajuste de pesos a
    #: partir de lo que la organización ganó y perdió. Acotado: el desglose
    #: tiene siete dimensiones y la columna es TEXT, no un almacén libre.
    desglose_al_abrir: dict[str, float] | None = Field(default=None, max_length=20)


class PursuitUpdate(BaseModel):
    """Patch parcial de una oportunidad con control optimista opcional."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: PursuitStatus | None = None
    decision: PursuitDecision | None = None
    decision_reason: str | None = Field(default=None, max_length=4000)
    responsible_user_id: int | None = Field(default=None, ge=1)
    offer_price_eur: float | None = Field(default=None, ge=0)
    outcome: PursuitOutcome | None = None
    awarded_amount_eur: float | None = Field(default=None, ge=0)
    outcome_reason: str | None = Field(default=None, max_length=4000)
    #: F3.1 — obligatorio al cerrar en `lost` (la ruta responde 422 sin él).
    #: Aquí es opcional porque este mismo patch sirve para editar otras cosas
    #: de una oportunidad ya cerrada sin tener que reenviar el motivo.
    outcome_reason_code: PursuitOutcomeReasonCode | None = None
    next_action: str | None = Field(default=None, max_length=300)
    next_action_due: date | None = None
    expected_version: int | None = Field(default=None, ge=1)


class PursuitEventOut(BaseModel):
    """Entrada inmutable del historial de una oportunidad."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    pursuit_id: int = Field(ge=1)
    event_type: str
    actor_user_id: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: PgDateTime


class ExpectedAward(BaseModel):
    """F4.4 — cuándo se espera la adjudicación, y de dónde sale esa fecha.

    Viaja con su dispersión y su ``n`` a propósito: una fecha sola se lee como
    un compromiso, y esto es una estimación. La regla que decide si se publica
    —y el mínimo de expedientes por debajo del cual **no** hay estimación—
    vive en :mod:`services.analytics.lead_time`.
    """

    model_config = ConfigDict(extra="forbid")

    #: La central, no la optimista.
    fecha: date
    #: Extremos del intervalo intercuartílico. Iguales a ``fecha`` cuando el
    #: método es ``hito``: una fecha publicada no tiene dispersión.
    p25: date
    p75: date
    #: Expedientes del órgano que sostienen la estimación. Con ``metodo="hito"``
    #: es 0: el dato no viene de una muestra.
    n: int = Field(default=0, ge=0)
    #: ``estimacion`` hoy; ``hito`` cuando F2.1 traiga la fecha publicada por
    #: el procedimiento y sustituya a la estimada.
    metodo: Literal["hito", "estimacion"] = "estimacion"


class PursuitSummary(BaseModel):
    """Oportunidad enriquecida con los datos básicos de su licitación."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    organization_id: int = Field(ge=1)
    licitacion_id: str
    #: Lote por el que se puja, o ``None`` para el expediente completo. Lo
    #: durable es ``lote_numero`` (la clave de negocio del lote dentro del
    #: expediente); ``lote_id`` y ``lote_titulo`` los resuelve el repositorio
    #: contra ``lotes`` en cada lectura y quedan en ``None`` si el pliego dejó
    #: de publicar ese lote — la oportunidad sigue diciendo para cuál se abrió.
    lote_numero: str | None = None
    lote_id: int | None = None
    lote_titulo: str | None = None
    tender_title: str | None = None
    tender_deadline: PgDateTime | None = None
    #: Campo ADITIVO (F4.4). El órgano de la licitación, que es de donde sale
    #: `expected_award`: sin él la consola no puede explicar por qué la fecha
    #: prevista es esa ni enlazar a la cuenta.
    tender_organo: str | None = None
    #: Campo ADITIVO (F4.4). `None` = sin estimación, y la UI lo dice; nunca se
    #: rellena con una fecha de menor calidad. Ver `services/analytics/
    #: lead_time.py` para por qué el mínimo de expedientes no es negociable.
    expected_award: ExpectedAward | None = None
    responsible_user_id: int | None = None
    responsible_name: str | None = None
    status: PursuitStatus
    decision: PursuitDecision
    decision_reason: str | None = None
    offer_price_eur: float | None = Field(default=None, ge=0)
    outcome: PursuitOutcome
    awarded_amount_eur: float | None = Field(default=None, ge=0)
    outcome_reason: str | None = None
    #: `None` = cierre anterior a F3.1, sin codificar. La UI lo ofrece para
    #: completar; la analítica lo cuenta aparte y no lo reparte entre motivos.
    outcome_reason_code: PursuitOutcomeReasonCode | None = None
    next_action: str | None = None
    next_action_due: date | None = None
    identified_at: PgDateTime
    decision_at: PgDateTime | None = None
    submitted_at: PgDateTime | None = None
    closed_at: PgDateTime | None = None
    created_at: PgDateTime
    updated_at: PgDateTime
    version: int = Field(ge=1)
    # Tamaño del hilo de comentarios. Lo calcula el repositorio en la misma
    # consulta (subconsulta correlacionada, v97): el tablero pinta el contador
    # en cada tarjeta sin una llamada por oportunidad.
    comments_count: int = Field(default=0, ge=0)


class PursuitAdjudicatario(BaseModel):
    """Un adjudicatario del expediente, tal como lo publicó la fuente."""

    model_config = ConfigDict(extra="forbid")

    nombre: str
    nif: str | None = None
    importe_adjudicado: float | None = Field(default=None, ge=0)
    fecha_adjudicacion: str | None = None
    n_ofertas_recibidas: int | None = Field(default=None, ge=0)
    lote_id: int | None = None


class PursuitAdjudicacionDetectada(BaseModel):
    """La adjudicación que el sistema ya conoce de una oportunidad abierta.

    Existe para cerrar el ciclo sin teclear: hasta 2026-09 ganada, perdida e
    importe adjudicado se escribían a mano aunque la ingesta ya traía
    adjudicatario, importe y número de ofertas del mismo expediente. La ficha
    la muestra como propuesta —«este expediente se adjudicó a X por Y €»— y la
    persona confirma el resultado. Desde S2 el sistema **sí** puede proponer
    cuál es (``resultado_sugerido``, calculado por NIF), pero sigue sin
    cerrarla: la propuesta llega preseleccionada y quien decide es la persona.
    """

    model_config = ConfigDict(extra="forbid")

    estado_licitacion: str | None = None
    adjudicatarios: list[PursuitAdjudicatario] = Field(default_factory=list)
    importe_total: float | None = Field(default=None, ge=0)
    n_ofertas: int | None = Field(default=None, ge=0)
    #: Resultado que el sistema propone preseleccionar, cruzando los NIFs de
    #: ``organization_nifs`` con los de los adjudicatarios publicados (S2.1).
    #: ``None`` es «no lo sé» y no «no ganó»: sale así cuando la organización
    #: no ha declarado ningún NIF o cuando la fuente no publicó el del
    #: adjudicatario. Se calcula en lectura y no se persiste — lo persistido
    #: es lo que confirma la persona, en ``pursuits.outcome``.
    resultado_sugerido: Literal["won", "lost"] | None = None
    #: ``True`` cuando el pursuit sigue abierto: es entonces cuando la ficha
    #: debe proponer el cierre. En un pursuit ya cerrado la adjudicación es
    #: contexto, no una acción pendiente.
    cierre_pendiente: bool


class PursuitDetail(PursuitSummary):
    """Detalle de una oportunidad con su ledger append-only."""

    events: list[PursuitEventOut] = Field(default_factory=list)
    #: Sólo viaja cuando la ingesta conoce una adjudicación del expediente.
    adjudicacion: PursuitAdjudicacionDetectada | None = None


class PursuitListResponse(BaseModel):
    """Listado paginado dentro de una única organización."""

    organization_id: int = Field(ge=1)
    items: list[PursuitSummary] = Field(default_factory=list)
    total: int = Field(ge=0)
    # El mismo tope que acepta la ruta (`api/pagination.py`). Con `le=200` aquí y
    # 500 allí, pedir `limit=300` pasaba la validación de entrada y reventaba al
    # construir la respuesta: un 400 por un parámetro que la API declara válido.
    limit: int = Field(ge=1, le=MAX_PAGE_LIMIT)
    offset: int = Field(ge=0)


# ── Comentarios de una oportunidad ──────────────────────────────────────────
#
# El hilo de conversación del equipo sobre un expediente. Tabla propia
# (``pursuit_comments``, v97) y no entradas del ledger ``pursuit_events``: el
# ledger es append-only por trigger (v61) y un comentario tiene que poder
# borrarse; además, mezclar conversación con auditoría convierte el historial
# de decisiones en ruido.

#: Longitud máxima de un comentario. La migración v97 lo fija también como
#: CHECK en la tabla, así que cambiarlo aquí exige una revisión nueva.
PURSUIT_COMMENT_MAX_CHARS = 4000


class PursuitCommentCreate(BaseModel):
    """Nuevo comentario en el hilo de una oportunidad."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    body: SafeStr = Field(min_length=1, max_length=PURSUIT_COMMENT_MAX_CHARS)


class PursuitCommentOut(BaseModel):
    """Comentario con el autor resuelto y el permiso de borrado de quien lo pide.

    ``can_delete`` se calcula en backend (autor, o owner/admin del espacio):
    así el frontend no duplica la regla de moderación ni necesita conocer el
    rol del solicitante. ``author_user_id`` queda ``NULL`` cuando la cuenta se
    anonimiza (RGPD); el texto sigue siendo parte del trabajo del equipo.
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    pursuit_id: int = Field(ge=1)
    organization_id: int = Field(ge=1)
    author_user_id: int | None = None
    author_name: str | None = None
    body: str
    created_at: PgDateTime
    can_delete: bool = False


class PursuitCommentListResponse(BaseModel):
    """Página del hilo, en orden cronológico y paginada desde el más reciente.

    ``offset=0`` son los últimos ``limit`` comentarios —lo que un chat abre—,
    devueltos del más antiguo al más nuevo. ``total`` declara el tamaño real
    del hilo para que el cliente diga cuánto no está mostrando (ADR-014).
    """

    pursuit_id: int = Field(ge=1)
    organization_id: int = Field(ge=1)
    items: list[PursuitCommentOut] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class PerdidaPorMotivo(BaseModel):
    """Cuántas veces se perdió por un motivo, y qué parte del total es."""

    model_config = ConfigDict(extra="forbid")

    #: Uno de `PursuitOutcomeReasonCode`, o `sin_codificar` para los cierres
    #: anteriores a F3.1.
    motivo: str
    n: int = Field(ge=0)
    #: Sobre el total de pérdidas del periodo, 0-1.
    pct: float = Field(ge=0, le=1)


class PursuitMetrics(BaseModel):
    """Métricas reproducibles de funnel y resultado por organización/periodo.

    **Cada cifra cuenta oportunidades, no expedientes.** Desde la revisión
    ``v110`` un mismo expediente puede tener varias oportunidades abiertas —una
    por lote—, así que «4 identificadas» pueden ser dos expedientes de dos lotes
    cada uno. ``unidad_de_conteo`` lo dice en el propio contrato para que
    ninguna pantalla tenga que suponerlo (ADR-014).
    """

    organization_id: int = Field(ge=1)
    period_from: PgDateTime | None = None
    period_to: PgDateTime | None = None
    #: Constante del contrato: qué cuenta una unidad de estas métricas. Es un
    #: ``Literal`` de un solo valor a propósito — el día que se cuente por
    #: expediente habrá que añadir el otro valor y el cliente dejará de
    #: compilar, en vez de seguir pintando un número que cambió de significado.
    unidad_de_conteo: Literal["oportunidad"] = "oportunidad"
    pursuits_identified: int = Field(ge=0)
    pursuits_submitted: int = Field(ge=0)
    pursuits_won: int = Field(ge=0)
    pursuits_lost: int = Field(ge=0)
    win_rate: float | None = Field(default=None, ge=0, le=1)
    awarded_amount_eur: float = Field(default=0, ge=0)
    median_decision_time_hours: float | None = Field(default=None, ge=0)
    #: Qué tal prioriza el Radar en esta organización. ``None`` cuando ninguna
    #: oportunidad del periodo lleva banda sellada (``v93``): el bucle no está
    #: cerrado y no hay nada que afirmar.
    radar_quality: RadarQuality | None = None
    #: Campo ADITIVO (F3.1). Vacío cuando no hay cierres suficientes: la UI
    #: sólo lo pinta con al menos cinco pérdidas en el corte, porque un
    #: «60 % por precio» sobre tres casos es ruido con aspecto de conclusión.
    perdidas_por_motivo: list[PerdidaPorMotivo] = Field(default_factory=list)
    #: Mínimo aplicado, declarado en vez de repetido en la UI.
    perdidas_n_minimo: int = Field(default=5, ge=1)
    #: Campo ADITIVO (F4.1). Suma de importes por la probabilidad de su etapa.
    #: Sólo cuenta oportunidades **abiertas**: una ganada ya está en
    #: `awarded_amount_eur` y sumarla aquí la contaría dos veces.
    pipeline_value_eur: float = Field(default=0, ge=0)
    #: Los supuestos con los que se calculó, declarados con el número (ADR-014).
    #: Sin esto, «1,2 M€ de pipeline» es una cifra que nadie puede reproducir.
    probabilidades_etapa_usadas: dict[str, int] = Field(default_factory=dict)
    #: Previsión por trimestre, `{"2026-Q4": 340000.0}`, repartiendo el valor
    #: ponderado por la fecha prevista de adjudicación o, si no la hay, por la
    #: fecha límite. Vacío cuando ninguna oportunidad abierta tiene fecha.
    prevision_trimestral: dict[str, float] = Field(default_factory=dict)
    #: Oportunidades abiertas sin importe publicado, que por tanto **no**
    #: entran en el valor ponderado. Se publica el hueco en vez de tratar el
    #: importe ausente como cero: un pipeline que ignora en silencio la mitad
    #: de su cartera es peor que uno que dice cuánta no pudo valorar.
    pipeline_sin_importe: int = Field(default=0, ge=0)


# ── ANCLA S3 — oportunidad por lote y calidad del Radar ────────────────────
#
# Los dos modelos de abajo cumplen el criterio de compartición del docstring:
# ``PursuitMetrics`` (aquí) los anida y ``services/product_metrics.py`` los
# reutiliza para ``make product-status``, que sirve la misma métrica sin pasar
# por HTTP. Los campos de lote son aditivos sobre ``PursuitCreate`` y
# ``PursuitSummary``, que ya vivían arriba.
#
# Lo que S3 NO aterriza aquí: los modelos de la propuesta de pesos
# (``PesosPropuestos`` y compañía). Los publica una sola ruta
# —``GET /pursuits/weights-proposal``— y viven junto a su función de dominio en
# ``services/pursuits.py``, como los de ``services/analytics/*``.

# ``RadarBanda`` (el vocabulario de bandas) NO se declara aquí: vive junto a
# los demás vocabularios de pursuits, arriba, porque ``PursuitCreate`` ya lo
# usaba y una segunda declaración es exactamente lo que hacía indeterminista el
# enumerado del contrato. Ver el comentario de ese alias.


class RadarBandaCalidad(BaseModel):
    """Qué le pasó a la organización con lo que el Radar puso en una banda.

    Cada porcentaje viaja con su denominador y solo se calcula cuando ese
    denominador aguanta (ADR-014): ``precision`` mide sobre ``resueltas``
    (ganadas + perdidas, las únicas que tienen veredicto) y ``tasa_cierre``
    sobre ``abiertas``. Por debajo del mínimo llegan en ``None``, que el
    cliente pinta como «sin datos suficientes» — nunca como cero.
    """

    model_config = ConfigDict(extra="forbid")

    banda: RadarBanda
    #: Oportunidades abiertas desde esa banda en la ventana.
    abiertas: int = Field(ge=0)
    #: De esas, las que llegaron a un estado terminal (won/lost/withdrawn).
    cerradas: int = Field(ge=0)
    ganadas: int = Field(ge=0)
    perdidas: int = Field(ge=0)
    #: ``ganadas + perdidas``. Denominador honesto de ``precision``: una
    #: oportunidad retirada no dice nada sobre si el Radar acertó.
    resueltas: int = Field(ge=0)
    #: ``ganadas / resueltas``. ``None`` si ``resueltas < minimo_por_banda``.
    precision: float | None = Field(default=None, ge=0, le=1)
    #: ``cerradas / abiertas``. ``None`` si ``abiertas < minimo_por_banda``.
    tasa_cierre: float | None = Field(default=None, ge=0, le=1)
    #: ``resueltas >= minimo_por_banda``. Lo decide el backend: el frontend
    #: presenta, no deriva analítica.
    suficiente: bool = False


class RadarQuality(BaseModel):
    """Precisión del Radar por banda de entrada, con su ventana y su cobertura.

    Cierra el bucle que la revisión ``v93`` dejó abierto: ``score_al_abrir`` y
    ``banda_al_abrir`` se escribían desde agosto de 2026 y ningún módulo de
    producción los leía, así que el producto no sabía responder a su propia
    promesa —«el Radar ordena bien»— ni siquiera con acceso a la base.

    Solo mide oportunidades con banda sellada. Las anteriores a ``v93`` tienen
    ``NULL`` y **no se rellenan**: por eso ``pursuits_con_banda`` viaja junto a
    ``pursuits_total``, para que la pantalla pueda decir sobre cuánto habla.
    """

    model_config = ConfigDict(extra="forbid")

    #: Denominador mínimo para publicar un porcentaje. Viaja con el dato para
    #: que el cliente no reinvente el umbral.
    minimo_por_banda: int = Field(ge=1)
    #: Ventana de ``identified_at`` que se midió. Con periodo pedido son sus
    #: extremos; sin él, la primera y la última oportunidad observadas.
    ventana_desde: PgDateTime | None = None
    ventana_hasta: PgDateTime | None = None
    ventana_origen: Literal["periodo_solicitado", "historico_observado"]
    #: Una entrada por banda con alguna oportunidad; las bandas sin nada no se
    #: inventan con ceros.
    bandas: list[RadarBandaCalidad] = Field(default_factory=list)
    #: Oportunidades de la ventana con banda sellada (el universo real de esta
    #: métrica) y oportunidades de la ventana en total.
    pursuits_con_banda: int = Field(ge=0)
    pursuits_total: int = Field(ge=0)
    #: ``pursuits_con_banda / pursuits_total * 100``. ``None`` cuando no hay
    #: ninguna oportunidad en la ventana: cobertura no medida, que no es cero.
    cobertura_pct: float | None = Field(default=None, ge=0, le=100)


# ``PursuitMetrics`` se declara arriba —donde vive el resto del recurso— y
# anota ``radar_quality: RadarQuality | None`` antes de que esta clase exista.
# Pydantic deja ese modelo incompleto hasta que la referencia se resuelve, y
# esta llamada es la que la resuelve contra el namespace del módulo.
PursuitMetrics.model_rebuild()
