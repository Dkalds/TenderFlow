"""Analytics overview service for aggregated tender KPIs and breakdowns.

Las agregaciones (KPIs, breakdowns por estado/mes/organo, indicadores de
mercado) se calculan en Postgres vía ``db.repositories.aggregates`` — antes se
cargaba la tabla ``licitaciones`` completa (~47k filas) a pandas y se
agregaba en el proceso web (capado a 4 hilos, ver ``api/app.py`` y el
postmortem de ``services/_data_cache.py``). Postgres resuelve estos
``GROUP BY`` en milisegundos.

``hhi``/``pct_oferta_unica``/``lead_time_medio`` se agregan también en
Postgres (``overview_adjudicaciones_indicadores``) — antes venían del
DataFrame full-table de ``load_adjudicaciones()`` (27 s y ~170k filas por
llamada medidos en prod), que en Render además estaba bloqueado por
``render_api_full_table_loads_blocked`` y dejaba los tres KPIs a cero/None.
Siguen ignorando los filtros del endpoint, como siempre hicieron — y por eso
se leen del snapshot **también con filtros** (ver ``get_overview``).

Las consultas que dependen del filtro son una docena, independientes entre
sí, y hasta 2026-09 corrían una detrás de otra en el hilo de la petición: una
búsqueda o un filtro del dashboard pagaban la suma de doce agregaciones sobre
1,64 M filas. Ahora corren con paralelismo acotado (``_en_paralelo``), con un
tope de conexiones extra por proceso para no vaciar el pool de lectura.

``pct_oferta_unica`` y ``pct_pyme`` viajan además con su cobertura
(``CoberturaMetricaDTO``). El motivo: en producción la tira de salud
competitiva del Resumen publicaba «oferta única 93,1 %» y «PYME adjudicataria
0,7 %», dos cifras que nadie del dominio se cree. No son el mercado español,
son el reparto de qué filas traen ``n_ofertas_recibidas`` y ``es_pyme`` — la
republicación masiva de PSCP no los trae. Sin denominador, un porcentaje así
describe la fuente, no el fenómeno. La cobertura de ``pct_oferta_unica`` ya sale
medida —el agregado de ``db/`` cuenta su base y su universo—; la de ``pct_pyme``
sigue **desconocida** a propósito hasta que el denominador de esa métrica y el
de su cobertura sean el mismo (ver ``_K_ADJ_*``), y desconocida basta para que
el consumidor se abstenga.
"""

from __future__ import annotations

import contextvars
import queue
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Final, Generic, Protocol, TypeVar

from pydantic import BaseModel, Field

from config import settings
from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from db.repositories.kpi_snapshots import (
    OverviewSnapshot,
    read_adj_indicadores_snapshot,
    read_overview_snapshot_for,
)
from observability.logging import get_logger
from shared.dto import DESCRIPCION_GRANDES_EN_PLAZO, CoberturaMetricaDTO

log = get_logger(__name__)

_repo = AggregateRepository()

_T = TypeVar("_T")

# ---------------------------------------------------------------------------
# Paralelismo acotado de las consultas del overview
# ---------------------------------------------------------------------------
#
# Cómo llega aquí la petición: `/analytics/overview` es un handler síncrono con
# `cache_response(user_scoped=False)` y **sin** `cpu_bound`, así que corre en el
# threadpool general de anyio (`API_THREADPOOL_TOKENS`), dentro del lock
# anti-estampida de su clave de caché. Ese hilo ya lleva copiado el contexto de
# la petición (anyio lo copia): la organización de `shared.tenant_context`, que
# `connect_read` convierte en `SET LOCAL`, y el contexto de structlog. Un hilo
# nuevo **no** lo hereda, y por eso cada ayudante corre dentro de su propia
# `contextvars.copy_context()` tomada en el hilo de la petición.
#
# Cada consulta sostiene una conexión del pool de lectura (12 en producción,
# `render.yaml`) durante lo que tarde —con filtros, escaneos de 1,64 M filas—.
# Un paralelismo por petición sin tope global multiplicaría eso por cada
# overview concurrente con filtros distintos (el lock solo agrupa los
# idénticos) y dejaría sin conexión al resto de la API, que esperaría
# `DB_POOL_TIMEOUT` y fallaría. De ahí las dos cotas:
#
# - por petición, como mucho `_AYUDANTES_POR_PETICION` hilos además del de la
#   propia petición: tres consultas a la vez;
# - por proceso, un semáforo con como mucho `_AYUDANTES_MAX` ayudantes vivos,
#   y nunca más de una cuarta parte del pool de lectura.
#
# El hilo de la petición **no espera** a que haya ayudantes: consume la cola
# él mismo y los ayudantes solo se suman si hay cupo libre en ese momento. Con
# el proceso saturado, una petición cae a la ejecución en serie de siempre, sin
# hacer cola detrás de otra, y el peor caso del pool es el de antes más
# `_AYUDANTES_MAX` conexiones. Conservador a propósito: con filtros, cada
# consulta es un escaneo secuencial, y el límite real lo pone la CPU y el disco
# de la base; tres a la vez aprovechan los escaneos sincronizados de Postgres
# sin convertir cada filtro del dashboard en una ráfaga contra el pool.
_AYUDANTES_POR_PETICION: Final = 2
_AYUDANTES_MAX: Final = 2

_semaforo: threading.BoundedSemaphore | None = None
_semaforo_lock = threading.Lock()


def _cupo_ayudantes() -> int:
    """Ayudantes permitidos en todo el proceso, según el pool de lectura vigente.

    Mismo cálculo que ``db/connection.py`` para el tamaño del pool de lectura
    (``DB_READ_POOL_SIZE``, o ``DB_POOL_SIZE`` si vale 0). Con el pool por
    defecto de desarrollo (5) sale un ayudante; con el de producción (12), dos.
    """
    pool = int(settings.DB_READ_POOL_SIZE or settings.DB_POOL_SIZE)
    return max(0, min(_AYUDANTES_MAX, pool // 4))


def _semaforo_ayudantes() -> threading.BoundedSemaphore:
    """Semáforo global de ayudantes, creado en el primer uso.

    Perezoso para que el cupo se lea con la configuración ya cargada y no al
    importar el módulo.
    """
    global _semaforo
    if _semaforo is None:
        with _semaforo_lock:
            if _semaforo is None:
                _semaforo = threading.BoundedSemaphore(_cupo_ayudantes())
    return _semaforo


class _Ejecutable(Protocol):
    """Lo que ``_en_paralelo`` necesita de una tarea, sea cual sea su resultado."""

    @property
    def pendiente(self) -> bool: ...

    def ejecutar(self) -> BaseException | None: ...


class _Tarea(Generic[_T]):
    """Una consulta del overview y el hueco tipado donde deja su resultado.

    El ``Future`` hace de buzón entre hilos: quien ejecuta la consulta deja el
    valor —o la excepción— y el hilo de la petición lo recoge después con su
    tipo intacto. Una tarea ``resuelta`` nace con el valor puesto (la pieza vino
    del snapshot) y ``_en_paralelo`` la salta.
    """

    def __init__(self, fn: Callable[[], _T]) -> None:
        self._fn = fn
        self._futuro: Future[_T] = Future()

    @classmethod
    def resuelta(cls, valor: _T) -> _Tarea[_T]:
        tarea = cls(lambda: valor)
        tarea._futuro.set_result(valor)
        return tarea

    @property
    def pendiente(self) -> bool:
        return not self._futuro.done()

    def ejecutar(self) -> BaseException | None:
        """Corre la consulta; devuelve la excepción si falló, ``None`` si no.

        Captura ``BaseException`` y no solo ``Exception``: una tarea que muriese
        sin dejar nada en su ``Future`` dejaría bloqueado para siempre a quien
        la espera. La primera excepción la relanza ``_en_paralelo``; el log es
        para las demás. Con varias consultas en marcha pueden fallar dos a la
        vez —un ``statement_timeout`` suele arrastrar a sus vecinas—, y solo
        una llega al llamante: sin esta línea, la otra desaparecería sin rastro
        y el diagnóstico diría «falló una» cuando fallaron dos.
        """
        try:
            self._futuro.set_result(self._fn())
        except BaseException as exc:
            log.warning(
                "overview_consulta_fallida", consulta=_nombre_consulta(self._fn), exc_info=True
            )
            self._futuro.set_exception(exc)
            return exc
        return None

    def resultado(self) -> _T:
        return self._futuro.result()


def _nombre_consulta(fn: Callable[[], object]) -> str:
    """Nombre legible de la consulta de una tarea, para el log: desenvuelve el ``partial``."""
    base = getattr(fn, "func", fn)
    return str(getattr(base, "__name__", repr(base)))


def _correr_ayudante(
    semaforo: threading.BoundedSemaphore,
    contexto: contextvars.Context,
    trabajo: Callable[[], None],
) -> None:
    try:
        contexto.run(trabajo)
    finally:
        semaforo.release()


def _lanzar_ayudantes(trabajo: Callable[[], None], cuantos: int) -> list[threading.Thread]:
    """Arranca hasta ``cuantos`` ayudantes, solo los que quepan en el cupo global."""
    semaforo = _semaforo_ayudantes()
    hilos: list[threading.Thread] = []
    for _ in range(cuantos):
        if not semaforo.acquire(blocking=False):
            break
        hilo = threading.Thread(
            target=_correr_ayudante,
            # Una copia por hilo: un mismo `Context` no puede estar entrado en
            # dos hilos a la vez.
            args=(semaforo, contextvars.copy_context(), trabajo),
            name="overview-ayudante",
            daemon=True,
        )
        try:
            hilo.start()
        except RuntimeError:
            semaforo.release()
            log.warning("overview_ayudante_no_arranca", exc_info=True)
            break
        hilos.append(hilo)
    return hilos


def _en_paralelo(tareas: Sequence[_Ejecutable]) -> None:
    """Ejecuta las tareas pendientes con paralelismo acotado; relanza el primer fallo.

    El orden de ``tareas`` es el orden en que se empiezan: conviene poner
    primero las más caras, para que la última en acabar no sea una lenta que
    arrancó tarde.

    Si una falla, nadie empieza tareas nuevas —el resultado ya va a ser un
    error, no hay por qué seguir ocupando la base—, se espera a las que ya
    estaban en marcha y se relanza la primera excepción. Es lo mismo que veía
    el llamante cuando las consultas iban en serie: la primera que fallaba
    cortaba el overview.
    """
    pendientes = [t for t in tareas if t.pendiente]
    if not pendientes:
        return
    cola: queue.SimpleQueue[_Ejecutable] = queue.SimpleQueue()
    for tarea in pendientes:
        cola.put(tarea)
    errores: list[BaseException] = []

    def drenar() -> None:
        while not errores:
            try:
                tarea = cola.get_nowait()
            except queue.Empty:
                return
            error = tarea.ejecutar()
            if error is not None:
                errores.append(error)

    ayudantes = _lanzar_ayudantes(drenar, min(_AYUDANTES_POR_PETICION, len(pendientes) - 1))
    drenar()
    for hilo in ayudantes:
        hilo.join()
    if errores:
        raise errores[0]


#: Umbral de cobertura por debajo del cual un porcentaje agregado deja de ser un
#: hecho del mercado y pasa a ser un hecho sobre qué filas traen el campo.
#:
#: 50 % es el punto en que la muestra deja de ser mayoría del corpus: por debajo,
#: el sesgo de selección de la fuente puede mover el resultado más que el
#: fenómeno medido. No es un umbral estadístico —no hay uno que valga para
#: cualquier campo—, es el mínimo defendible ante alguien del dominio: «lo
#: calculo sobre menos de la mitad de las adjudicaciones» ya obliga a explicarse.
UMBRAL_COBERTURA_PCT: Final = 50.0

#: Claves de cobertura de ``overview_adjudicaciones_indicadores``.
#:
#: Las dos primeras **ya llegan**: el agregado de ``db/repositories`` cuenta las
#: adjudicaciones totales y las que declaran ``n_ofertas_recibidas``, así que la
#: cobertura de ``pct_oferta_unica`` es un número medido y la celda deja de
#: abstenerse por falta de dato.
#:
#: La tercera **sigue sin llegar, y a propósito**: ``pct_pyme`` divide entre
#: ``COUNT(*)`` —el NULL cuenta como «no PYME»— mientras que su cobertura
#: mediría las filas que sí declaran ``es_pyme``. Valor y cobertura hablarían de
#: bases distintas, y destaparla sin corregir antes el denominador en ``db/``
#: sería pasar de ocultar un número dudoso a publicarlo. Hasta entonces la
#: métrica se abstiene, que es el default correcto.
#:
#: Se leen todas con ``.get`` por lo mismo de siempre: una clave que falte tiene
#: que dar cobertura desconocida, nunca un cero que parezca medido.
_K_ADJ_TOTAL: Final = "adj_total"
_K_ADJ_CON_N_OFERTAS: Final = "adj_con_n_ofertas"
_K_ADJ_CON_ES_PYME: Final = "adj_con_es_pyme"


def _cobertura_desconocida() -> CoberturaMetricaDTO:
    """Cobertura sin medir: ``suficiente=False``, que es el default seguro."""
    return CoberturaMetricaDTO(umbral_pct=UMBRAL_COBERTURA_PCT)


def _cobertura(base: float | None, universo: float | None) -> CoberturaMetricaDTO:
    """Cobertura de un porcentaje a partir de su base y su universo.

    ``cobertura_pct`` no se redondea: un 3,4 % tiene que salir como 3,4 % para
    que el consumidor pueda decir cuánto de poco es. Redondearlo a algo cómodo
    —a cero, al umbral, a «bajo»— sería repetir el problema que este campo viene
    a resolver. El único ajuste es el tope en 100, que solo puede saltar si base
    y universo llegan de consultas incoherentes; el DTO lo exige (``le=100``) y
    reventar aquí por eso sería tumbar el overview entero por un decimal.

    Un universo a cero **no** es cobertura 100 %: es que no hay corpus que medir,
    y se devuelve como desconocida.
    """
    if base is None or universo is None or universo <= 0:
        return _cobertura_desconocida()
    pct = min(base / universo * 100, 100.0)
    return CoberturaMetricaDTO(
        base=int(base),
        universo=int(universo),
        cobertura_pct=pct,
        umbral_pct=UMBRAL_COBERTURA_PCT,
        suficiente=pct >= UMBRAL_COBERTURA_PCT,
    )


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class OverviewFilters(BaseModel):
    """Query filters for the overview endpoint."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    estado: str | None = None
    q: str | None = None
    importe_min: float | None = None
    # F1.1: los tres del listado que el overview no aceptaba. Sin ellos, la
    # barra de ámbito acotaba el listado por provincia o procedimiento y los
    # KPIs de la misma pantalla seguían midiendo el corpus entero.
    importe_max: float | None = None
    provincia: str | None = None
    procedimiento: str | None = None


class EstadoCount(BaseModel):
    """Count per estado."""

    estado: str
    n: int


class MesAggregate(BaseModel):
    """Monthly aggregate."""

    mes: str
    n_licitaciones: int
    importe: float


class OrganoAggregate(BaseModel):
    """Top organo aggregate."""

    organo_contratacion: str
    n: int
    importe: float


#: Los cinco escalones del embudo de tramitación, en su orden. Son el
#: denominador de `FunnelStep.pct` para los tramos que están dentro del embudo.
ESCALONES_EMBUDO: tuple[str, ...] = ("PUB", "EV", "RES", "ADJ", "ANUL")

#: Códigos que se cuentan aparte, **fuera** del embudo: `PRE` todavía no ha
#: salido a licitación, y `AGR`/`EJEC`/`CPM` (PSCP catalana, v91) son avisos de
#: contratos ya celebrados o consultas, no un escalón de nada. `AGR` sola es el
#: ~93 % del corpus.
FUERA_DEL_EMBUDO: tuple[str, ...] = ("PRE", "AGR", "EJEC", "CPM")


class FunnelStep(BaseModel):
    """Tramo del embudo por estado, con su conteo y su porcentaje.

    **Cambio de semántica de `pct` (2026-09-18, AGENTS §3.5).** Hasta esa fecha
    todos los tramos se dividían entre el total del ámbito, y como `AGR` es el
    ~93 % del corpus los cinco escalones sumaban ~6,7 %: el embudo se leía como
    si el 93 % de los expedientes se hubiera perdido entre publicación y
    adjudicación. Desde entonces el denominador depende del tramo y el tramo lo
    declara en `en_embudo`.
    """

    estado: str
    n: int
    pct: float = Field(
        description=(
            "Porcentaje del tramo. Si `en_embudo` es true, sobre "
            "`OverviewResult.funnel_denominador` (los cinco escalones PUB, EV, RES, "
            "ADJ y ANUL suman 100). Si es false, sobre el total del ámbito "
            "(`funnel_denominador + fuera_del_embudo`)."
        )
    )
    en_embudo: bool = Field(
        default=True,
        description=(
            "True para los cinco escalones de tramitación; false para lo que se "
            "cuenta aparte (PRE, AGR, EJEC, CPM y OTROS)."
        ),
    )


class OverviewResult(BaseModel):
    """Combined overview response."""

    total_licitaciones: int = 0
    importe_total: float = 0.0
    importe_medio: float = 0.0
    organos_unicos: int = 0
    yoy_delta: float = 0.0
    licitaciones_30d: int = 0
    importe_30d: float = 0.0
    por_estado: list[EstadoCount] = Field(default_factory=list)
    por_mes: list[MesAggregate] = Field(default_factory=list)
    top_organos: list[OrganoAggregate] = Field(default_factory=list)
    funnel_estados: list[FunnelStep] = Field(default_factory=list)
    funnel_denominador: int = Field(
        default=0,
        description=(
            "Expedientes en alguno de los cinco escalones del embudo: el "
            "denominador de `pct` en los tramos con `en_embudo`."
        ),
    )
    fuera_del_embudo: int = Field(
        default=0,
        description=(
            "Expedientes del ámbito que no están en ningún escalón (PRE, AGR, EJEC, "
            "CPM y sin código conocido). Con `funnel_denominador` suma el total del "
            "ámbito."
        ),
    )
    hhi: float = 0.0
    pct_oferta_unica: float = 0.0
    # Market indicators
    pct_pyme: float = 0.0
    # Cada uno de los dos porcentajes de arriba viaja con las filas que lo
    # sostienen. Campos nuevos con default: el contrato existente no se rompe y
    # un cliente que los ignore ve exactamente lo que veía antes — por eso el
    # gate vive en el consumidor y no en el valor, que se sigue sirviendo.
    cobertura_oferta_unica: CoberturaMetricaDTO = Field(default_factory=_cobertura_desconocida)
    cobertura_pyme: CoberturaMetricaDTO = Field(default_factory=_cobertura_desconocida)
    concentracion_top10: float = 0.0
    lead_time_medio: float | None = None
    tasa_anulacion: float = 0.0
    concentracion_geo_top3: float = 0.0
    ccaa_cubiertas: int = 0
    # "Para hoy" counts
    calientes_hoy: int = Field(default=0, description=DESCRIPCION_GRANDES_EN_PLAZO)
    vencen_48h: int = 0
    nuevas_24h: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_repo_filters(filters: OverviewFilters) -> LicitacionesFilters:
    return LicitacionesFilters(
        ccaa=filters.ccaa,
        tecnologia=filters.tecnologia,
        estado=filters.estado,
        fecha_desde=filters.fecha_desde.isoformat() if filters.fecha_desde else None,
        fecha_hasta=filters.fecha_hasta.isoformat() if filters.fecha_hasta else None,
        importe_min=filters.importe_min,
        q=filters.q,
        importe_max=filters.importe_max,
        provincia=filters.provincia,
        procedimiento=filters.procedimiento,
    )


def _adj_indicadores() -> dict[str, float | None]:
    """HHI, % oferta única, lead time medio y % PYME — en Postgres, sin filtros."""
    try:
        return _repo.overview_adjudicaciones_indicadores()
    except Exception:
        log.warning("overview_adj_indicadores_failed", exc_info=True)
        return {
            "hhi": 0.0,
            "pct_oferta_unica": 0.0,
            "lead_time_medio": None,
            "pct_pyme": 0.0,
        }


def construir_embudo(conteos: dict[str, int]) -> tuple[list[FunnelStep], int, int]:
    """Tramos del embudo, su denominador y lo que queda fuera.

    ``conteos`` es la salida de ``AggregateRepository.overview_funnel``: un
    conteo por código más ``total`` (todas las filas del ámbito).

    Los cinco escalones se dividen entre su propia suma, así que suman 100 y el
    embudo se lee como embudo. Lo que no es escalón (``FUERA_DEL_EMBUDO`` y lo
    que no cae en ningún código conocido) sigue en la lista —quitarlo lo haría
    invisible, que era la otra mitad del problema— pero con ``en_embudo=False``
    y su porcentaje sobre el total del ámbito.
    """
    total = int(conteos.get("total", 0))
    denominador = sum(int(conteos.get(est, 0)) for est in ESCALONES_EMBUDO)

    def _pct(n: int, base: int) -> float:
        return float(n / base * 100) if base else 0.0

    pasos: list[FunnelStep] = []
    for est in ESCALONES_EMBUDO:
        n = int(conteos.get(est, 0))
        pasos.append(FunnelStep(estado=est, n=n, pct=_pct(n, denominador), en_embudo=True))
    for est in FUERA_DEL_EMBUDO:
        n = int(conteos.get(est, 0))
        pasos.append(FunnelStep(estado=est, n=n, pct=_pct(n, total), en_embudo=False))

    # Lo que no cae en ningún código —filas sin estado, o con el texto crudo que
    # el conector escribió antes del arreglo y que la reparación aún no ha
    # limpiado— se declara en vez de desaparecer. Solo aparece si hay algo
    # dentro, así que sobre un corpus limpio nada cambia. Que los tramos sumen
    # el total es lo que deja saber si lo que falta es cero o un millón de filas.
    conocidos = denominador + sum(int(conteos.get(est, 0)) for est in FUERA_DEL_EMBUDO)
    resto = total - conocidos
    if resto > 0:
        pasos.append(FunnelStep(estado="OTROS", n=resto, pct=_pct(resto, total), en_embudo=False))

    return pasos, denominador, max(total - denominador, 0)


def _adj_precalculado(snap: OverviewSnapshot | None) -> dict[str, float | None] | None:
    """Los indicadores de adjudicaciones del snapshot, se haya filtrado o no.

    Si hay snapshot aplicable al filtro, su pieza es la de la fila global (en
    una variante por tecnología también). Si no lo hay —filtro sin variante, o
    snapshot global incompleto—, la fila se lee sola: esos indicadores ignoran
    los filtros desde siempre, así que la fila global responde exactamente lo
    mismo que el cálculo en vivo que antes se repetía en cada búsqueda.
    ``None`` —fila ausente o caducada— cae al cálculo en vivo.
    """
    if snap is not None:
        return snap.adj_indicadores
    return read_adj_indicadores_snapshot()


def get_overview(filters: OverviewFilters) -> OverviewResult:
    """Compute the full overview payload — agregaciones vía SQL en Postgres."""
    log.info("analytics_overview_start", filters=filters.model_dump(exclude_none=True))
    repo_filters = _to_repo_filters(filters)

    # Sin filtros, los agregados sobre la tabla completa vienen del snapshot que
    # deja el pipeline de ingesta: entre scrapes no cambian, y calcularlos aquí
    # costaba 22 s (KPIs), 25 s (tasa de anulación) y 42 s (adjudicaciones) por
    # cada fallo de caché. Con un filtro de una sola tecnología frecuente
    # también hay snapshot (variante), y los indicadores de adjudicaciones, que
    # no dependen del filtro, salen del snapshot con cualquier filtro. Cada
    # pieza cae por su cuenta al cálculo en vivo si falta, así que un snapshot
    # incompleto degrada en vez de romper.
    snap = read_overview_snapshot_for(repo_filters)
    snap_kpis = snap.kpis if snap is not None else None
    snap_tasa = snap.tasa_anulacion if snap is not None else None
    snap_adj = _adj_precalculado(snap)

    hoy = datetime.now(UTC)
    hace_30d_iso = (hoy - timedelta(days=30)).isoformat()
    hace_60d_iso = (hoy - timedelta(days=60)).isoformat()
    hace_365d_iso = (hoy - timedelta(days=365)).isoformat()
    hace_24h_iso = (hoy - timedelta(hours=24)).isoformat()
    hoy_iso = hoy.isoformat()
    limite_48h_iso = (hoy + timedelta(hours=48)).isoformat()

    # Todas las consultas de abajo son independientes entre sí; lo único que
    # comparten es el filtro. Van ordenadas de más a menos cara según lo
    # medido en producción sin filtros (adjudicaciones 42 s, CCAA 31 s, tasa
    # 25 s, KPIs 22 s, "para hoy" 20-26 s): con paralelismo acotado, empezar
    # por las lentas es lo que evita que la última en terminar sea una lenta
    # que arrancó tarde. Las que llegan del snapshot nacen resueltas y no
    # cuestan nada.
    t_adj = _Tarea.resuelta(snap_adj) if snap_adj is not None else _Tarea(_adj_indicadores)
    t_ccaa = _Tarea(partial(_repo.overview_ccaa_cubiertas, repo_filters))
    t_tasa = (
        _Tarea.resuelta(snap_tasa)
        if snap_tasa is not None
        else _Tarea(
            partial(_repo.overview_tasa_anulacion, repo_filters, hace_365d_iso=hace_365d_iso)
        )
    )
    t_kpis = (
        _Tarea.resuelta(snap_kpis)
        if snap_kpis is not None
        else _Tarea(partial(_repo.overview_kpis, repo_filters))
    )
    t_para_hoy = _Tarea(
        partial(
            _repo.overview_para_hoy,
            repo_filters,
            hoy_iso=hoy_iso,
            limite_48h_iso=limite_48h_iso,
            hace_24h_iso=hace_24h_iso,
            p75=snap.importe_p75 if snap is not None else None,
            total_activas=snap.total_activas if snap is not None else None,
        )
    )
    t_yoy = _Tarea(
        partial(
            _repo.overview_yoy_and_recent,
            repo_filters,
            hace_30d_iso=hace_30d_iso,
            hace_60d_iso=hace_60d_iso,
        )
    )
    t_conc_organos = _Tarea(partial(_repo.overview_concentracion_organos, repo_filters, top_n=10))
    t_conc_ccaa = _Tarea(partial(_repo.overview_concentracion_ccaa, repo_filters, top_n=3))
    t_top_organos = _Tarea(partial(_repo.overview_top_organos, repo_filters))
    t_por_mes = _Tarea(partial(_repo.overview_por_mes, repo_filters))
    t_por_estado = _Tarea(partial(_repo.overview_por_estado, repo_filters))
    t_funnel = _Tarea(partial(_repo.overview_funnel, repo_filters))

    _en_paralelo(
        [
            t_adj,
            t_ccaa,
            t_tasa,
            t_kpis,
            t_para_hoy,
            t_yoy,
            t_conc_organos,
            t_conc_ccaa,
            t_top_organos,
            t_por_mes,
            t_por_estado,
            t_funnel,
        ]
    )

    adj_ind = t_adj.resultado()
    k = t_kpis.resultado()

    yoy_data = t_yoy.resultado()
    v_act = yoy_data["lics_30d"]
    v_prev = yoy_data["lics_prev30d"]
    yoy = ((v_act - v_prev) / v_prev * 100) if v_prev else 0.0

    # --- Market indicators ---
    top10_imp, total_imp = t_conc_organos.resultado()
    total_imp = total_imp or 1.0
    concentracion_top10 = top10_imp / total_imp * 100

    anul_count, total_12m = t_tasa.resultado()
    tasa_anulacion = (anul_count / total_12m * 100) if total_12m > 0 else 0.0

    top3_imp, total_imp_geo = t_conc_ccaa.resultado()
    total_imp_geo = total_imp_geo or 1.0
    concentracion_geo_top3 = top3_imp / total_imp_geo * 100

    ccaa_cubiertas = t_ccaa.resultado()
    para_hoy = t_para_hoy.resultado()

    por_estado = [
        EstadoCount(estado=row["estado"], n=int(row["n"])) for row in t_por_estado.resultado()
    ]
    por_mes = [
        MesAggregate(
            mes=row["mes"], n_licitaciones=int(row["n_licitaciones"]), importe=float(row["importe"])
        )
        for row in t_por_mes.resultado()
    ]
    top_organos = [
        OrganoAggregate(
            organo_contratacion=row["organo_contratacion"],
            n=int(row["n"]),
            importe=float(row["importe"]),
        )
        for row in t_top_organos.resultado()
    ]

    funnel_estados, funnel_denominador, fuera_del_embudo = construir_embudo(t_funnel.resultado())

    result = OverviewResult(
        total_licitaciones=k["total"],
        importe_total=k["importe_total"],
        importe_medio=k["importe_medio"],
        organos_unicos=k["organos"],
        yoy_delta=yoy,
        licitaciones_30d=int(v_act),
        importe_30d=yoy_data["importe_30d"],
        por_estado=por_estado,
        por_mes=por_mes,
        top_organos=top_organos,
        funnel_estados=funnel_estados,
        funnel_denominador=funnel_denominador,
        fuera_del_embudo=fuera_del_embudo,
        hhi=adj_ind["hhi"] or 0.0,
        pct_oferta_unica=adj_ind["pct_oferta_unica"] or 0.0,
        pct_pyme=adj_ind["pct_pyme"] or 0.0,
        cobertura_oferta_unica=_cobertura(
            adj_ind.get(_K_ADJ_CON_N_OFERTAS), adj_ind.get(_K_ADJ_TOTAL)
        ),
        # OJO al destapar este: `pct_pyme` se calcula hoy con denominador
        # `COUNT(*)` —el NULL cuenta como «no PYME», ver el comentario de
        # `overview_adjudicaciones_indicadores`—, así que su valor y esta
        # cobertura hablan de bases distintas. Mientras la cobertura siga por
        # debajo del umbral el consumidor se abstiene y da igual; el día que
        # `adj_con_es_pyme` supere el 50 %, el denominador de `pct_pyme` tiene
        # que corregirse en `db/` **en el mismo cambio** o pasaremos de ocultar
        # un número dudoso a publicarlo.
        cobertura_pyme=_cobertura(adj_ind.get(_K_ADJ_CON_ES_PYME), adj_ind.get(_K_ADJ_TOTAL)),
        concentracion_top10=concentracion_top10,
        lead_time_medio=adj_ind["lead_time_medio"],
        tasa_anulacion=tasa_anulacion,
        concentracion_geo_top3=concentracion_geo_top3,
        ccaa_cubiertas=ccaa_cubiertas,
        calientes_hoy=para_hoy["calientes_hoy"],
        vencen_48h=para_hoy["vencen_48h"],
        nuevas_24h=para_hoy["nuevas_24h"],
    )
    log.info("analytics_overview_done", total=result.total_licitaciones)
    return result
