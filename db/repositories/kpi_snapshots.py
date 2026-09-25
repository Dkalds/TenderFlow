"""Snapshot de los agregados globales del overview, sobre ``kpi_snapshots``.

``GET /analytics/overview`` sin filtros ejecutaba media docena de agregaciones
sobre la tabla completa en cada fallo de caché. Medido en producción el
2026-08-12: 22,3 s los KPIs, 30,9 s las CCAA cubiertas, 24,8 s la tasa de
anulación y 42,3 s los indicadores de adjudicaciones — cada una reteniendo una
conexión de las doce del pool mientras tanto.

Ninguno de esos números cambia entre ingestas, y la ingesta corre cada 4 h
(``scrape-daily.yml``), así que se calculan una vez por ciclo en el paso
``kpi_precompute`` del pipeline y el endpoint los lee de una tabla de unas
pocas filas. El desfase máximo es el que ya tenían los datos.

Sobre la tabla que se reutiliza: ``kpi_snapshots`` (v51) ya existía con este
propósito exacto y con reemplazo atómico —``DELETE`` e ``INSERT`` en la misma
transacción, la de ``db.kpi_precompute.compute_and_persist_snapshots``—, así
que esto no añade esquema. Las métricas ``ov_*`` conviven con las que calcula
``db.kpi_precompute.compute_all_kpis``, pero **no son las mismas y no deben
mezclarse**: las de allí (``total_licitaciones``, ``importe_total``…) filtran
por el universo tecnológico en su forma ancha
(``db.sql_fragments.universo_tecnologico_sql``) y el overview sin filtros
agrega sin filtro de universo. Por eso se recalculan aquí llamando a
``AggregateRepository``, que es literalmente el mismo código que sirve el
camino en vivo — la paridad no depende de mantener dos SQL parecidos
sincronizados a mano.

Dos lecturas más, las dos sin tocar el esquema (2026-09):

- **Los indicadores de adjudicaciones valen para cualquier filtro.**
  ``overview_adjudicaciones_indicadores`` ignora los filtros a propósito, así
  que su fila ``global`` sirve también a una petición filtrada
  (:func:`read_adj_indicadores_snapshot`). Antes solo se leía sin filtros, y
  cada búsqueda o filtro del dashboard recalculaba en vivo la pieza más cara
  del overview —42 s medidos— para obtener el mismo número.
- **Variantes por tecnología.** ``dimension`` es texto libre y la tabla no
  tiene unicidad por métrica, así que una fila con
  ``dimension = 'tecnologia:SAP'`` es una variante del mismo agregado sin
  ninguna migración. Se precalculan ``ov_kpis`` y ``ov_tasa_anulacion`` —las
  dos piezas filtradas que el overview sabe tomar del snapshot— para las
  :data:`N_TECNOLOGIAS_VARIANTES` tecnologías más frecuentes, y
  :func:`read_overview_snapshot_for` las sirve cuando el filtro es
  **exactamente** una de ellas. Se calculan dentro del mismo
  ``compute_all_kpis`` y no en un paso aparte: ``persist_snapshots`` borra la
  tabla entera en cada pasada, así que cualquier fila escrita por otro paso
  desaparecería en la siguiente, y además llevaría otro ``computed_at``, que es
  lo que ``get_all_latest`` y el healthcheck (``last_pipeline_run``) toman por
  «el snapshot vigente».
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from db.database import connect_read
from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from db.repositories.base import csv_values, loose_distinct_strings
from observability.logging import get_logger

log = get_logger(__name__)

OV_KPIS: Final = "ov_kpis"
OV_ADJ_INDICADORES: Final = "ov_adj_indicadores"
OV_TASA_ANULACION: Final = "ov_tasa_anulacion"
OV_IMPORTE_P75: Final = "ov_importe_p75"
OV_TOTAL_ACTIVAS: Final = "ov_total_activas"
META_CPV_VALUES: Final = "meta_cpv_values"

_DIMENSION: Final = "global"

#: Prefijo de ``dimension`` de las variantes por tecnología (``tecnologia:SAP``).
_PREFIJO_TECNOLOGIA: Final = "tecnologia:"

#: Cuántas tecnologías llevan variante precalculada. Cada una cuesta dos
#: agregaciones más por pasada (``overview_kpis`` y ``overview_tasa_anulacion``
#: con su filtro), secuenciales sobre ``licitaciones`` mientras no exista el GIN
#: sobre ``tecnologia_tokens_sql`` (propuesto en
#: ``docs/plans/2026-09-indices-busqueda-propuestos.md``); con él pasan a leer
#: solo las filas de esa tecnología. Cinco es un tope conservador, no una
#: medida: cuánto del tráfico filtrado cubre depende de qué tecnologías filtra
#: la gente, que hoy no se registra. Subirlo alarga un paso que ya es el más
#: lento de la pasada; conviene hacerlo con ``v142`` aplicada.
N_TECNOLOGIAS_VARIANTES: Final = 5

#: Métricas que lleva cada variante. Son las dos piezas **dependientes del
#: filtro** que el overview sabe servir desde el snapshot; el resto (P75,
#: activas) solo tiene sentido sin filtros y los indicadores de adjudicaciones
#: son globales: se leen de la fila ``global``.
_METRICAS_VARIANTE: Final = (OV_KPIS, OV_TASA_ANULACION)

# Tres ciclos de pipeline perdidos. Pasado eso el snapshot se ignora y se
# vuelve al cálculo en vivo: es lento, pero servir cifras de ayer como si
# fueran de hoy es peor que tardar.
_DEFAULT_MAX_AGE_S: Final = 12 * 3600

_OVERVIEW_METRICAS: Final = (
    OV_KPIS,
    OV_ADJ_INDICADORES,
    OV_TASA_ANULACION,
    OV_IMPORTE_P75,
    OV_TOTAL_ACTIVAS,
)

# Claves que cada JSON debe traer para considerarse utilizable. Se validan aquí
# y no en el servicio: un snapshot a medias tiene que degradar a cálculo en
# vivo, no reventar el endpoint con un KeyError.
_KPIS_KEYS: Final = ("total", "importe_total", "importe_medio", "organos")
_ADJ_KEYS: Final = ("hhi", "pct_oferta_unica", "lead_time_medio", "pct_pyme")


@dataclass(frozen=True)
class OverviewSnapshot:
    """Agregados precalculados, ya validados.

    Cada campo puede venir a ``None`` por separado: el consumidor recalcula en
    vivo solo esa pieza en vez de tirar el snapshot entero.

    ``dimension`` dice a qué pregunta responde: ``global`` (la tabla entera) o
    una variante ``tecnologia:<código>``. En una variante ``importe_p75`` y
    ``total_activas`` van siempre a ``None`` —solo describen la tabla entera y
    el camino filtrado calcula su propio P75—, y ``adj_indicadores`` es el
    global, porque esa pieza nunca dependió del filtro.
    """

    computed_at: str
    # Misma forma que ``AggregateRepository.overview_kpis``: total (int),
    # importe_total/importe_medio (float), organos (int).
    kpis: dict[str, Any] | None
    adj_indicadores: dict[str, float | None] | None
    tasa_anulacion: tuple[int, int] | None
    importe_p75: float | None
    total_activas: int | None
    dimension: str = _DIMENSION


def dimension_tecnologia(codigo: str) -> str:
    """``dimension`` de la variante de ``codigo`` en ``kpi_snapshots``."""
    return f"{_PREFIJO_TECNOLOGIA}{codigo}"


def tecnologia_de_variante(filters: LicitacionesFilters) -> str | None:
    """El código si ``filters`` es exactamente «una tecnología y nada más».

    Es la única forma de filtro con variante precalculada. Se compara después
    de ``csv_values``, igual que hace ``build_licitaciones_where``: ``" SAP "``
    y ``"SAP,"`` emiten el mismo SQL que ``"SAP"`` y pueden servirse de la
    misma fila. Dos códigos, o cualquier otro filtro al lado, ya no son esa
    pregunta y devuelven ``None``.
    """
    codigos = csv_values(filters.tecnologia)
    if len(codigos) != 1 or not replace(filters, tecnologia=None).is_empty():
        return None
    return codigos[0]


def _fila(
    metrica: str,
    *,
    valor: float | None = None,
    valor_text: str | None = None,
    dimension: str = _DIMENSION,
) -> dict[str, Any]:
    """Fila de ``kpi_snapshots`` sin ``computed_at``.

    ``db.kpi_precompute.compute_all_kpis`` se lo añade antes de que
    ``db.kpi_precompute.persist_snapshots`` la escriba.
    """
    return {
        "metrica": metrica,
        "dimension": dimension,
        "valor": valor,
        "valor_text": valor_text,
    }


@contextmanager
def _aislado(conn: Any, nombre: str) -> Iterator[None]:
    """Punto de guardado: un fallo dentro no aborta la transacción del precálculo.

    Las variantes son un extra del snapshot global y se calculan en la misma
    transacción que él. Sin esto, un ``statement_timeout`` en una sola variante
    dejaría la transacción abortada y el ``persist_snapshots`` posterior
    fallaría entero: la pasada se quedaría sin snapshot global por culpa de
    una optimización. ``nombre`` es siempre una constante de este módulo.
    """
    conn.execute(f"SAVEPOINT {nombre}")
    try:
        yield
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {nombre}")
        conn.execute(f"RELEASE SAVEPOINT {nombre}")
        raise
    conn.execute(f"RELEASE SAVEPOINT {nombre}")


def _filas_variantes_tecnologia(
    conn: Any, repo: AggregateRepository, *, hace_365d_iso: str
) -> list[dict[str, Any]]:
    """Filas de las variantes por tecnología, o las que se hayan podido calcular.

    Cada variante se calcula con **las mismas llamadas** que el camino en vivo
    hace para ese filtro —``overview_kpis`` y ``overview_tasa_anulacion`` con
    ``LicitacionesFilters(tecnologia=código)``—, por lo mismo que las globales:
    la paridad sale de compartir código, no de copiarlo.

    Best-effort por variante: la que falla se registra y se omite (su filtro se
    seguirá calculando en vivo), y las demás se escriben.
    """
    try:
        with _aislado(conn, "ov_top_tecnologias"):
            codigos = repo.tecnologias_mas_frecuentes(N_TECNOLOGIAS_VARIANTES, conn=conn)
    except Exception:
        log.warning("kpi_snapshot_top_tecnologias_fallido", exc_info=True)
        return []

    filas: list[dict[str, Any]] = []
    for codigo in codigos:
        filtros = LicitacionesFilters(tecnologia=codigo)
        try:
            with _aislado(conn, "ov_variante"):
                kpis = repo.overview_kpis(filtros, conn=conn)
                anul, total_12m = repo.overview_tasa_anulacion(
                    filtros, hace_365d_iso=hace_365d_iso, conn=conn
                )
        except Exception:
            log.warning("kpi_snapshot_variante_fallida", tecnologia=codigo, exc_info=True)
            continue
        dimension = dimension_tecnologia(codigo)
        filas.append(
            _fila(OV_KPIS, valor_text=json.dumps(kpis, ensure_ascii=False), dimension=dimension)
        )
        filas.append(
            _fila(
                OV_TASA_ANULACION,
                valor_text=json.dumps({"anul": anul, "total": total_12m}),
                dimension=dimension,
            )
        )
    return filas


def compute_overview_snapshot_rows(conn: Any) -> list[dict[str, Any]]:
    """Calcula las métricas ``ov_*`` y la lista de CPV, listas para persistir.

    Se llama desde ``db/kpi_precompute.py`` (``compute_all_kpis``), que las
    añade a las suyas y les pone a todas el mismo ``computed_at``. El SQL de
    estas métricas vive en ``AggregateRepository`` y en
    ``db.repositories.base.loose_distinct_strings`` — nunca en ``scheduler/``
    (ADR-022).

    Todo va por la ``conn`` que ya tiene abierta el precálculo: son seis
    consultas de lectura y abrirles conexiones propias mientras se sostiene la
    de escritura solo gasta slots del pool.

    La ventana de la tasa de anulación se ancla al momento del precálculo y no
    al de la petición. Son 365 días: que el borde se mueva unas horas no cambia
    el porcentaje de forma observable.

    Las variantes por tecnología van **después** de las globales y aisladas en
    puntos de guardado (:func:`_filas_variantes_tecnologia`): las globales
    siguen fallando como siempre —si una no sale, el snapshot entero no se
    escribe—, y una variante que falla solo se pierde a sí misma.
    """
    repo = AggregateRepository()
    sin_filtros = LicitacionesFilters()
    hace_365d_iso = (datetime.now(UTC) - timedelta(days=365)).isoformat()

    kpis = repo.overview_kpis(sin_filtros, conn=conn)
    adj = repo.overview_adjudicaciones_indicadores(conn=conn)
    anul, total_12m = repo.overview_tasa_anulacion(
        sin_filtros, hace_365d_iso=hace_365d_iso, conn=conn
    )
    p75 = repo.importe_p75(conn=conn)
    activas = repo.count_total_activas(conn=conn)
    cpv = loose_distinct_strings(conn, "licitaciones", "cpv")

    return [
        _fila(OV_KPIS, valor_text=json.dumps(kpis, ensure_ascii=False)),
        _fila(OV_ADJ_INDICADORES, valor_text=json.dumps(adj, ensure_ascii=False)),
        _fila(OV_TASA_ANULACION, valor_text=json.dumps({"anul": anul, "total": total_12m})),
        _fila(OV_IMPORTE_P75, valor=p75),
        _fila(OV_TOTAL_ACTIVAS, valor=float(activas)),
        _fila(META_CPV_VALUES, valor_text=json.dumps(cpv, ensure_ascii=False)),
        *_filas_variantes_tecnologia(conn, repo, hace_365d_iso=hace_365d_iso),
    ]


def _read_metricas(
    metricas: tuple[str, ...], *, max_age_seconds: int, dimension: str = _DIMENSION
) -> tuple[str, dict[str, tuple[float | None, str | None]]] | None:
    """Lee las métricas pedidas y su ``computed_at``, o ``None`` si no sirven.

    ``DISTINCT ON`` porque la tabla no tiene unicidad por métrica: si un
    precálculo dejase filas de dos tandas, gana la más reciente.
    """
    sql = (
        "SELECT DISTINCT ON (metrica) metrica, valor, valor_text, computed_at "
        "FROM kpi_snapshots "
        "WHERE dimension = %s AND metrica = ANY(%s) "
        "ORDER BY metrica, computed_at DESC"
    )
    try:
        with connect_read() as c:
            rows = c.execute(sql, (dimension, list(metricas))).fetchall()
    except Exception:
        log.warning("kpi_snapshot_read_failed", exc_info=True)
        return None

    if not rows and dimension != _DIMENSION:
        # Una tecnología sin variante es el caso normal —solo las más
        # frecuentes la llevan—, no una anomalía del snapshot.
        log.debug("kpi_snapshot_sin_variante", dimension=dimension)
        return None
    if len(rows) != len(metricas):
        log.info(
            "kpi_snapshot_incompleto",
            dimension=dimension,
            encontradas=len(rows),
            esperadas=len(metricas),
        )
        return None

    valores: dict[str, tuple[float | None, str | None]] = {}
    computed_at = ""
    for metrica, valor, valor_text, fila_computed_at in rows:
        valores[str(metrica)] = (
            float(valor) if valor is not None else None,
            str(valor_text) if valor_text is not None else None,
        )
        computed_at = max(computed_at, str(fila_computed_at))

    try:
        edad = (datetime.now(UTC) - datetime.fromisoformat(computed_at)).total_seconds()
    except ValueError:
        log.warning("kpi_snapshot_computed_at_ilegible", computed_at=computed_at)
        return None
    if edad > max_age_seconds:
        log.info("kpi_snapshot_caducado", edad_s=int(edad), max_age_s=max_age_seconds)
        return None
    return computed_at, valores


def _json_dict(raw: str | None, *, requiere: tuple[str, ...] = ()) -> dict[str, Any] | None:
    """Parsea un ``valor_text`` que debería ser un objeto JSON con ciertas claves."""
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        log.warning("kpi_snapshot_json_invalido")
        return None
    if not isinstance(parsed, dict):
        return None
    faltan = [k for k in requiere if k not in parsed]
    if faltan:
        log.warning("kpi_snapshot_claves_ausentes", faltan=faltan)
        return None
    return parsed


def _tasa_par(raw: str | None) -> tuple[int, int] | None:
    """``(anuladas, total)`` de la tasa de anulación, o ``None`` si no se lee."""
    tasa = _json_dict(raw, requiere=("anul", "total"))
    return (int(tasa["anul"]), int(tasa["total"])) if tasa is not None else None


def _adj_tipado(raw: str | None) -> dict[str, float | None] | None:
    """Los indicadores de adjudicaciones con sus valores como ``float``.

    Lo comparten el snapshot completo y la lectura suelta de
    :func:`read_adj_indicadores_snapshot`: validar dos veces lo mismo con dos
    códigos distintos acabaría aceptando en una lo que la otra rechaza.
    """
    adj = _json_dict(raw, requiere=_ADJ_KEYS)
    if adj is None:
        return None
    return {k: (float(v) if v is not None else None) for k, v in adj.items()}


def read_overview_snapshot(*, max_age_seconds: int = _DEFAULT_MAX_AGE_S) -> OverviewSnapshot | None:
    """Devuelve el snapshot del overview, o ``None`` si no hay uno utilizable.

    ``None`` significa "calculalo en vivo", nunca un error: falta de datos,
    JSON corrupto o snapshot viejo son todos casos esperables —el pipeline
    todavía no ha corrido, o falló— y ninguno justifica un 500 en un endpoint
    que sabe calcular lo mismo por sí solo.
    """
    leido = _read_metricas(_OVERVIEW_METRICAS, max_age_seconds=max_age_seconds)
    if leido is None:
        return None
    computed_at, valores = leido

    activas_raw = valores[OV_TOTAL_ACTIVAS][0]
    return OverviewSnapshot(
        computed_at=computed_at,
        kpis=_json_dict(valores[OV_KPIS][1], requiere=_KPIS_KEYS),
        adj_indicadores=_adj_tipado(valores[OV_ADJ_INDICADORES][1]),
        tasa_anulacion=_tasa_par(valores[OV_TASA_ANULACION][1]),
        # `valor` NULL es legítimo aquí: corpus sin ningún importe. Se propaga
        # como None para que el llamante no aplique umbral, no como 0.0.
        importe_p75=valores[OV_IMPORTE_P75][0],
        total_activas=int(activas_raw) if activas_raw is not None else None,
    )


def read_adj_indicadores_snapshot(
    *, max_age_seconds: int = _DEFAULT_MAX_AGE_S
) -> dict[str, float | None] | None:
    """Los indicadores de adjudicaciones precalculados, **con o sin filtros**.

    Es la pieza que no depende del filtro: ``overview_adjudicaciones_indicadores``
    agrega ``adjudicaciones`` entera a propósito, así que la fila ``global``
    responde igual a una petición filtrada que a una sin filtrar, con la misma
    regla de frescura (``max_age_seconds``) que el resto del snapshot. Se lee
    sola porque con filtros el resto del snapshot global no aplica, y porque
    así sobrevive a un snapshot incompleto en otra métrica.

    ``None`` —fila ausente, caducada, ilegible o cualquier error— significa lo
    de siempre: calcularlo en vivo. Nunca lanza.
    """
    try:
        leido = _read_metricas((OV_ADJ_INDICADORES,), max_age_seconds=max_age_seconds)
        if leido is None:
            return None
        return _adj_tipado(leido[1][OV_ADJ_INDICADORES][1])
    except Exception:
        log.warning("kpi_snapshot_adj_no_disponible", exc_info=True)
        return None


def _read_overview_variante(codigo: str, *, max_age_seconds: int) -> OverviewSnapshot | None:
    """La variante precalculada de una tecnología, o ``None`` si no la hay.

    Las dos métricas filtradas salen de la fila de su ``dimension``; los
    indicadores de adjudicaciones, de la global. ``importe_p75`` y
    ``total_activas`` van a ``None`` a propósito: solo describen la tabla
    entera, y con un filtro ``overview_para_hoy`` calcula su propio P75.
    """
    dimension = dimension_tecnologia(codigo)
    leido = _read_metricas(_METRICAS_VARIANTE, max_age_seconds=max_age_seconds, dimension=dimension)
    if leido is None:
        return None
    computed_at, valores = leido
    return OverviewSnapshot(
        computed_at=computed_at,
        kpis=_json_dict(valores[OV_KPIS][1], requiere=_KPIS_KEYS),
        adj_indicadores=read_adj_indicadores_snapshot(max_age_seconds=max_age_seconds),
        tasa_anulacion=_tasa_par(valores[OV_TASA_ANULACION][1]),
        importe_p75=None,
        total_activas=None,
        dimension=dimension,
    )


def read_overview_snapshot_for(
    filters: LicitacionesFilters, *, max_age_seconds: int = _DEFAULT_MAX_AGE_S
) -> OverviewSnapshot | None:
    """El snapshot, si hay uno aplicable a ``filters``.

    Dos preguntas tienen snapshot: la tabla entera (``dimension = 'global'``) y
    **exactamente una tecnología** de las que llevan variante precalculada
    (:func:`tecnologia_de_variante`). Cualquier otro filtro devuelve ``None``:
    lo precalculado responde a esas preguntas y no a otras, y aplicarlo a una
    pregunta distinta daría números que no corresponden al filtro.

    Quien distinga entre las dos lo hace por ``dimension``; en una variante
    ``importe_p75`` y ``total_activas`` son ``None``, así que un consumidor que
    solo use esos dos campos (``/analytics/resumen/hoy``) ve lo mismo que
    antes de que existieran las variantes.

    Cualquier fallo devuelve ``None`` — leer el snapshot es una optimización, y
    ninguna optimización debe poder tumbar un endpoint que sabe calcular lo
    mismo por sí solo.
    """
    try:
        if filters.is_empty():
            return read_overview_snapshot(max_age_seconds=max_age_seconds)
        codigo = tecnologia_de_variante(filters)
        if codigo is None:
            return None
        return _read_overview_variante(codigo, max_age_seconds=max_age_seconds)
    except Exception:
        log.warning("kpi_snapshot_overview_no_disponible", exc_info=True)
        return None


def read_meta_cpv(*, max_age_seconds: int = _DEFAULT_MAX_AGE_S) -> list[str] | None:
    """Lista de CPV distintos precalculada, o ``None`` para recalcular en vivo.

    Es la única de las cuatro listas de ``/meta/filters`` que sigue siendo cara
    tras el loose index scan: 18.203 valores distintos son 18.203 descensiones
    por el btree, unos 9,5 s. Las otras tres bajaron a decenas de milisegundos
    y se siguen resolviendo en vivo.
    """
    leido = _read_metricas((META_CPV_VALUES,), max_age_seconds=max_age_seconds)
    if leido is None:
        return None
    raw = leido[1][META_CPV_VALUES][1]
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        log.warning("kpi_snapshot_cpv_json_invalido")
        return None
    if not isinstance(parsed, list):
        return None
    return [str(v) for v in parsed]
