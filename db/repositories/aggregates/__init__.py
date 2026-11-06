"""Repository para agregaciones OLAP (``GROUP BY``/``COUNT``/``SUM`` en Postgres).

Contrapartida SQL de los servicios ``services/analytics/{overview,tecnologias,
competitors}.py``, que hasta ahora cargaban la tabla completa a pandas y
agregaban en el proceso web (ver AGENTS.md / postmortem OOM en
``services/_data_cache.py``). Este paquete es el único lugar donde vive el SQL
de esas agregaciones (ADR-022, invariante §3.10) — incluida la construcción del
``WHERE`` a partir de los filtros: los servicios de ``services/analytics/*``
pasan valores (fechas, strings, floats), nunca fragmentos de SQL.

Coste: ya no son milisegundos. Cuando se escribió esto la tabla tenía ~47k
filas; con la carga completa de PSCP pasó de 700k (~870 MB de heap) y un
``GROUP BY`` que la recorre entera tarda ~15 s en producción (medido el
2026-09-25), frente al ``statement_timeout`` de 30 s de la API. Antes de añadir
una agregación, mirá por qué índice va a ir. Sin filtros, por el cubriente
``idx_lic_analitica`` (``v144``), que solo sirve mientras la consulta no lea
columnas fuera de su ``INCLUDE``: ``tests/test_v144_indices_analitica.py`` lo
vigila para las de Mercado. Con filtro de tecnología, por
``idx_lic_tecnologia_cubriente`` (ver
:func:`db.sql_fragments.tecnologia_en_csv_sql` y ``_CON_TECNOLOGIA``). Y agrupá
por hash antes de ordenar: con ``work_mem`` de 3,5 MB, ordenar la tabla es
ordenarla en disco (ver la sección de órganos, en ``organos.py``).

Convenciones de fecha (importante, ver ``db/alembic/versions/
v59_pg_date_format_checks.py``): las columnas de fecha (``fecha_publicacion``,
``fecha_limite``, ``fecha_adjudicacion``) son ``TEXT`` ISO-8601, no
``TIMESTAMP`` — hay filas históricas con formato inválido (el CHECK que las
valida es ``NOT VALID``, no cubre datos previos a la migración). Por eso:

- Los filtros simples (``>=``/``<=`` con la fecha que llega del usuario) se
  comparan como string, igual que el resto de repositories del proyecto — sin
  CAST, sin riesgo de reventar la query por una fila legado malformada.
- El bucketing mensual usa ``substr(fecha, 1, 7)`` (prefijo ``YYYY-MM``) en
  vez de ``date_trunc``: evita casts a ``timestamp`` (y con ellos, cualquier
  ambigüedad de timezone de sesión) y es exacto para cualquier fecha ISO bien
  formada.
- Las ventanas relativas a "ahora" (últimos N días/horas) reciben el cutoff ya
  calculado en Python (``datetime.now(UTC).isoformat()`` — mismo formato que
  ``db.connection.now_utc_iso()``) como parámetro, comparado con ``>=``/``<``
  de forma lexicográfica, igual que los filtros. Se guardan con un rango
  lexicográfico sargable (``>= '1900' AND < '3000'``, ver ``iso_guard``) para
  excluir filas claramente malformadas del cálculo, replicando el
  ``errors="coerce"`` + ``dropna`` que hacía pandas fila a fila sin renunciar
  al índice btree de la columna.

Un submódulo por familia de métodos (2026-11-06; hasta entonces era un único
``aggregates.py`` de ~2.780 líneas y el conflicto de merge más probable de
``db/``). Cada familia es una clase mixin, con sus formas de fila al lado, y
:class:`AggregateRepository` hereda de todas:

- ``filtros``: ``LicitacionesFilters``, ``build_licitaciones_where`` (alias
  interno ``_build_where``), ``_lectura`` y la guarda de tecnología que
  comparten Tecnologías y Proyectos.
- ``overview``: KPIs, embudo, mapa y la tarjeta «Para hoy» (``ParaHoy``).
- ``resumen``: timeline, novedades, sankey y top licitaciones.
- ``tecnologias``: ranking, cruces, evolución y detalle de una tecnología.
- ``geografia_tendencias``: geografía, tendencias (también por CPV) y
  calendario de vencimientos.
- ``organos``: totales, ranking y treemap de órganos.
- ``proyectos``: familias y módulos, tipos de contrato, CPV y listas CODICE.
- ``calidad_forecast``: completitud, forecast, retendering y clustering.
- ``scoring``: proyecciones acotadas y contexto del Radar y del pipeline.

Se importa siempre del paquete (``from db.repositories.aggregates import X``).
Un test que sustituya ``connect_read`` lo parchea en el submódulo que ejecuta
la consulta (``db.repositories.aggregates.<familia>.connect_read``, o
``...filtros.connect_read`` para los métodos que pasan por ``_lectura``): el
paquete no lo reexporta, así que un parche al nombre antiguo falla en vez de
no surtir efecto.
"""

from __future__ import annotations

from db.repositories.aggregates.calidad_forecast import (
    AdjudicacionForecastFila,
    CalidadForecastMixin,
    ClusteringFila,
    CompletitudGlobal,
    CompletitudMesFila,
    PublicacionesMesFila,
    RetenderingFila,
    SerieMensualFila,
)
from db.repositories.aggregates.filtros import (
    LicitacionesFilters,
    build_licitaciones_where,
)
from db.repositories.aggregates.geografia_tendencias import (
    CcaaImporteFila,
    CpvImporteTotalFila,
    CpvMesFila,
    DiaImporteFila,
    GeografiaTendenciasMixin,
    MesEstadoFila,
    ProvinciaImporteFila,
)
from db.repositories.aggregates.organos import (
    OrganoRankingFila,
    OrganosMixin,
    TreemapFila,
)
from db.repositories.aggregates.overview import (
    CcaaConteoFila,
    EstadoConteoFila,
    KpisOverview,
    MesImporteFila,
    OrganoTopFila,
    OverviewMixin,
    ParaHoy,
)
from db.repositories.aggregates.proyectos import (
    CpvConteoFila,
    ProyectosMixin,
    TipoContratoFila,
    TipoEstadoConteoFila,
)
from db.repositories.aggregates.resumen import (
    NovedadFila,
    ResumenMixin,
    TimelineItemFila,
    TipoEstadoValorFila,
    TopLicitacionFila,
)
from db.repositories.aggregates.scoring import (
    CompetenciaCpv4Fila,
    OrganoLicitacionFila,
    ScoringMixin,
)
from db.repositories.aggregates.tecnologias import (
    TecnologiaCcaaFila,
    TecnologiaEntradaFila,
    TecnologiaItemFila,
    TecnologiaMesFila,
    TecnologiaOrganoFila,
    TecnologiasMixin,
)


class AggregateRepository(
    OverviewMixin,
    ResumenMixin,
    TecnologiasMixin,
    GeografiaTendenciasMixin,
    OrganosMixin,
    ProyectosMixin,
    CalidadForecastMixin,
    ScoringMixin,
):
    """Acceso a las vistas materializadas de aggregates y a agregaciones en vivo."""


__all__ = [
    "AdjudicacionForecastFila",
    "AggregateRepository",
    "CcaaConteoFila",
    "CcaaImporteFila",
    "ClusteringFila",
    "CompetenciaCpv4Fila",
    "CompletitudGlobal",
    "CompletitudMesFila",
    "CpvConteoFila",
    "CpvImporteTotalFila",
    "CpvMesFila",
    "DiaImporteFila",
    "EstadoConteoFila",
    "KpisOverview",
    "LicitacionesFilters",
    "MesEstadoFila",
    "MesImporteFila",
    "NovedadFila",
    "OrganoLicitacionFila",
    "OrganoRankingFila",
    "OrganoTopFila",
    "ParaHoy",
    "ProvinciaImporteFila",
    "PublicacionesMesFila",
    "RetenderingFila",
    "SerieMensualFila",
    "TecnologiaCcaaFila",
    "TecnologiaEntradaFila",
    "TecnologiaItemFila",
    "TecnologiaMesFila",
    "TecnologiaOrganoFila",
    "TimelineItemFila",
    "TipoContratoFila",
    "TipoEstadoConteoFila",
    "TipoEstadoValorFila",
    "TopLicitacionFila",
    "TreemapFila",
    "build_licitaciones_where",
]
