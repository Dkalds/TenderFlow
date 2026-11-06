"""Construcción del ``WHERE`` de las agregaciones y la conexión de lectura compartida."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from db.database import connect_read
from db.repositories.base import csv_values
from db.sql_fragments import (
    FOLD_TABLE,
    codigo_normalizado_sql,
    columna_nucleo_sql,
    escape_like,
    exclude_duplicados_presentacion_sql,
    fold_expr,
    normaliza_codigo,
    tecnologia_en_csv_sql,
)
from shared.estados import abierta_sql


@contextmanager
def _lectura(conn: Any | None) -> Iterator[Any]:
    """Reutiliza la conexión dada, o abre una de lectura si no hay ninguna.

    Lo aprovecha el precálculo de KPIs, que ya corre dentro de una transacción
    con su propia conexión: sin esto abriría cinco más para preguntar lo mismo,
    reteniendo slots del pool mientras sostiene la de escritura. Y lo que
    permite es que el snapshot lo calculen **estas mismas funciones** en vez de
    una copia del SQL en el scheduler que hubiera que mantener sincronizada a
    mano — que es exactamente como el resumen y el Radar acabaron contando
    cosas distintas.

    ``conn`` va tipado como ``Any`` porque es el objeto de conexión de psycopg,
    igual que en el resto de helpers de ``db/repositories``.
    """
    if conn is not None:
        yield conn
    else:
        with connect_read() as abierta:
            yield abierta


def _in_clause(column: str, values: list[str]) -> str:
    """``col = %s`` para un valor, ``col IN (%s, …)`` para varios.

    Se conserva la igualdad en el caso de uno solo para no cambiar el plan de
    las consultas que ya existían (el índice btree de la columna).
    """
    if len(values) == 1:
        return f"{column} = %s"
    # Se interpolan placeholders, nunca valores: éstos van siempre por params.
    placeholders = ",".join("%s" for _ in values)
    return f"{column} IN ({placeholders})"


@dataclass(frozen=True)
class LicitacionesFilters:
    """Filtros comunes sobre ``licitaciones`` para las agregaciones de analytics.

    Valores planos (no el DTO Pydantic del servicio) — mantiene ``db/`` sin
    depender de ``services/analytics/*``.
    """

    ccaa: str | None = None
    tecnologia: str | None = None
    estado: str | None = None
    fecha_desde: str | None = None
    fecha_hasta: str | None = None
    importe_min: float | None = None
    q: str | None = None
    cpv: str | None = None
    # Un órgano concreto, por igualdad exacta sobre ``organo_contratacion`` —
    # la misma comparación que ya usan los drill-downs
    # (``licitaciones_por_organo`` y los agregados por órgano de
    # ``AdjudicacionRepository``),
    # que reciben el nombre como argumento aparte. Aquí viaja dentro de los
    # filtros para que una agregación acotada a un órgano no necesite un
    # parámetro extra en cada firma. No es lo mismo que ``q``: aquélla es
    # búsqueda difusa sobre cuatro columnas, ésta es "este órgano y no otro".
    organo: str | None = None
    # "Sólo las que siguen abiertas": descarta los estados terminales en vez de
    # enumerar los abiertos (ver shared/estados.py). No es redundante con
    # ``estado``: ése fija uno concreto, éste excluye el cierre y deja pasar
    # cualquier código que la fuente publique mañana.
    solo_abiertas: bool = False
    # ── F1.1: los filtros del listado que faltaban aquí ──────────────────
    # Misma semántica que ``LicitacionRepository._base_filters``: sin ellos,
    # el listado acotaba por provincia o procedimiento y los KPIs y el export
    # de la misma pantalla seguían contando el corpus entero.
    #: Importe de licitación máximo (inclusive). NULL queda fuera, igual que
    #: con ``importe_min``.
    importe_max: float | None = None
    #: Provincias, CSV.
    provincia: str | None = None
    #: Códigos CODICE de procedimiento, CSV; se comparan normalizados.
    procedimiento: str | None = None
    # ── F6.1: ámbito de mercado de la organización ───────────────────────
    #: CPVs por **prefijo**, CSV. No es ``cpv`` (igualdad exacta, lo que usan
    #: los drill-downs): el ámbito se declara por familias (``72`` = TI).
    cpv_prefijos: str | None = None
    #: Procedimientos que **no** se quieren ver, CSV (códigos normalizados).
    #: Un expediente sin procedimiento publicado no se excluye.
    procedimientos_excluidos: str | None = None
    #: Tipos de órgano (``organos.tipo`` del maestro, C1.2), CSV. Solo excluye
    #: los expedientes cuyo órgano tiene un tipo **conocido y distinto**: el
    #: maestro todavía no rellena ``tipo``, y exigirlo vaciaría el Radar.
    tipos_organo: str | None = None

    def is_empty(self) -> bool:
        """True si ningún filtro está activo, es decir, si el ámbito es la tabla entera.

        Es la condición que habilita los caminos precalculados del overview: un
        agregado global solo se puede servir desde un snapshot si la pregunta
        es efectivamente global.

        Deliberadamente estricta. ``_build_where`` ignora un ``q`` en blanco o
        un ``ccaa`` vacío, así que hay filtros que no añaden cláusula y aun así
        se cuentan aquí como activos: equivocarse por este lado significa
        calcular en vivo algo que se podría haber leído del snapshot, y por el
        otro significaría servir un número que no corresponde al filtro pedido.
        """
        return self == LicitacionesFilters()


def build_licitaciones_where(
    filters: LicitacionesFilters,
    *,
    alias: str | None = None,
    nucleo: bool = False,
    presentacion: bool = False,
) -> tuple[str, list[object]]:
    """Construye el ``WHERE`` (dialecto qmark) desde :class:`LicitacionesFilters`.

    ``alias`` califica las columnas (``l.estado``) para las consultas que cruzan
    ``licitaciones`` con otra tabla — el drill-down de un órgano acota así sus
    adjudicaciones con el mismo ámbito que sus licitaciones, en vez de dejar
    que "top adjudicatario" y "lead time" midan el histórico completo mientras
    los KPIs de al lado miden el filtro. Sin ``alias`` las columnas van
    desnudas, como en las agregaciones que leen sólo de ``licitaciones``.

    **Semántica compartida con ``LicitacionRepository._base_filters``.** Los dos
    construyen el mismo filtro para la misma pantalla —éste los KPIs, aquél el
    listado— con implementaciones distintas (texto contra SQLAlchemy Core), y
    hasta 2026-09 también con *semánticas* distintas: ``q`` buscaba aquí en
    título + órgano + id y allí en título + descripción, sin plegar acentos. El
    mismo texto en la misma caja daba dos recuentos, y ninguno de los dos era
    explicable. Unificado en:

    - ``q``: título + descripción + órgano + id externo, **con plegado de
      acentos** en los dos lados de la comparación. La columna se pliega con
      :func:`db.sql_fragments.fold_expr`, cuyas tablas de ``translate`` son
      literales y no parámetros: es la condición para que un índice trigram
      sobre esa misma expresión pueda usarse algún día.
    - ``tecnologia``: pertenencia al CSV de la fila, nunca igualdad, como
      solapamiento de arrays sobre la expresión normalizada
      (:func:`db.sql_fragments.tecnologia_en_csv_sql`).

    Las dos implementaciones siguen siendo dos —unificarlas exigiría reescribir
    el listado o el agregado entero—, pero ``tests/test_s1_paridad_filtros.py``
    compara la semántica emitida (columnas tocadas y forma del predicado) para
    los mismos filtros, y además que la expresión de cada columna sea **la
    misma cadena** en los dos lados: un índice de expresión solo casa con una.
    Si una se mueve sin la otra, falla ahí y no en un recuento que nadie cuadra.

    ``nucleo=True`` (T2) hace que los filtros de fecha de publicación e
    importe lean la columna que decide
    :func:`db.sql_fragments.columna_nucleo_sql` —la sombra tipada de ``v133``
    con ``NUCLEO_TIPADO_LECTURA`` encendido—. Es **opt-in por consulta** y no
    global a propósito: el runbook (``docs/runbooks/nucleo-tipado-ventana.md``,
    paso 6) pasa las lecturas consulta a consulta, y este constructor lo usan
    decenas de agregados que no son de las cinco calientes. Con el flag
    apagado el texto emitido es el mismo con y sin ``nucleo``.

    ``presentacion=True`` (ADR-026 D23, 2026-10-17) añade la exclusión de
    republicaciones de presentación —``pending`` y ``confirmed``, la misma que
    ``_base_filters`` aplica siempre al listado— para que lo que encabeza o
    abre una lista cuente lo que la lista enseña: el overview y sus tarjetas,
    el Resumen, el calendario de vencimientos y el Radar. Es **opt-in** y no la
    base del constructor por dos razones. La primera es semántica: D23 dice
    «presentación esconde; métrica cuenta», y las agregaciones de Mercado
    (tendencias, geografía, órganos, tecnologías, CPV, forecast, tipos) y sus
    drill-downs son métricas que siguen contando sobre el ámbito entero. La
    segunda es física: esas agregaciones leen de ``idx_lic_analitica`` (v144)
    por Index Only Scan, y el anti-join sobre ``id_externo`` —columna que el
    índice no incluye— las devolvería al heap (``tests/test_v144_indices_analitica.py``).
    """

    def col(name: str) -> str:
        return f"{alias}.{name}" if alias else name

    def col_nucleo(name: str) -> str:
        return columna_nucleo_sql(name, alias) if nucleo else col(name)

    clauses: list[str] = ["1 = 1"]
    params: list[object] = []
    if presentacion:
        # Va justo detrás de la base y antes de cualquier filtro: así el
        # ``WHERE`` de una superficie de presentación sin filtros es
        # ``1 = 1 AND <anti-join>`` y el de una métrica sigue siendo ``1 = 1``.
        clauses.append(exclude_duplicados_presentacion_sql(col("id_externo")))

    if filters.fecha_desde:
        clauses.append(f"{col_nucleo('fecha_publicacion')} >= %s")
        params.append(filters.fecha_desde)
    if filters.fecha_hasta:
        clauses.append(f"{col_nucleo('fecha_publicacion')} <= %s")
        params.append(filters.fecha_hasta)
    ccaas = csv_values(filters.ccaa)
    if ccaas:
        clauses.append(_in_clause(col("ccaa"), ccaas))
        params.extend(ccaas)
    tecnologias = csv_values(filters.tecnologia)
    if tecnologias:
        clauses.append(tecnologia_en_csv_sql(col("tecnologia"), n=len(tecnologias)))
        params.extend(tecnologias)
    estados = csv_values(filters.estado)
    if estados:
        clauses.append(_in_clause(col("estado"), estados))
        params.extend(estados)
    if filters.solo_abiertas:
        clauses.append(abierta_sql(col("estado")))
    if filters.importe_min is not None:
        clauses.append(f"{col_nucleo('importe')} >= %s")
        params.append(filters.importe_min)
    if filters.q and filters.q.strip():
        needle = f"%{escape_like(filters.q.strip().translate(FOLD_TABLE).lower())}%"
        # ``descripcion`` entró el 2026-09-03 para casar con el listado, que
        # siempre la había buscado. Un NULL en cualquiera de las cuatro da NULL
        # en su ``LIKE`` y el ``OR`` lo absorbe, así que no hace falta coalesce.
        columnas = ("titulo", "descripcion", "organo_contratacion", "id_externo")
        disyuntos = " OR ".join(f"{fold_expr(col(c))} LIKE %s ESCAPE '\\'" for c in columnas)
        clauses.append(f"({disyuntos})")
        params.extend([needle] * len(columnas))
    if filters.cpv:
        clauses.append(f"{col('cpv')} = %s")
        params.append(filters.cpv)
    if filters.organo and filters.organo.strip():
        clauses.append(f"{col('organo_contratacion')} = %s")
        params.append(filters.organo.strip())

    # ── F1.1 ──────────────────────────────────────────────────────────────
    if filters.importe_max is not None:
        clauses.append(f"{col('importe')} <= %s")
        params.append(filters.importe_max)
    provincias = csv_values(filters.provincia)
    if provincias:
        clauses.append(_in_clause(col("provincia"), provincias))
        params.extend(provincias)
    procedimientos = sorted({normaliza_codigo(c) for c in csv_values(filters.procedimiento)})
    if procedimientos:
        marcadores = ",".join("%s" for _ in procedimientos)
        clauses.append(f"{codigo_normalizado_sql(col('procedimiento'))} IN ({marcadores})")
        params.extend(procedimientos)

    # ── F6.1 ──────────────────────────────────────────────────────────────
    prefijos = csv_values(filters.cpv_prefijos)
    if prefijos:
        disyuntos = " OR ".join(f"{col('cpv')} LIKE %s ESCAPE '\\'" for _ in prefijos)
        clauses.append(f"({disyuntos})")
        params.extend(f"{escape_like(p)}%" for p in prefijos)
    excluidos = sorted({normaliza_codigo(c) for c in csv_values(filters.procedimientos_excluidos)})
    if excluidos:
        marcadores = ",".join("%s" for _ in excluidos)
        clauses.append(
            f"({col('procedimiento')} IS NULL OR "
            f"{codigo_normalizado_sql(col('procedimiento'))} NOT IN ({marcadores}))"
        )
        params.extend(excluidos)
    tipos = csv_values(filters.tipos_organo)
    if tipos:
        # La tabla exterior se califica siempre: sin alias, `organo_id` a
        # secas dentro de la subconsulta resolvería a `o.organo_id` y la
        # condición compararía la columna consigo misma.
        exterior = alias or "licitaciones"
        marcadores = ",".join("%s" for _ in tipos)
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM organos o "
            f"WHERE o.organo_id = {exterior}.organo_id "
            f"AND o.tipo IS NOT NULL AND o.tipo NOT IN ({marcadores}))"
        )
        params.extend(tipos)

    return " AND ".join(clauses), params


# Nombre interno histórico: los call sites de este paquete agregan sobre
# ``licitaciones`` a secas y nunca pasan ``alias``.
_build_where = build_licitaciones_where


class _AgregadosBase:
    """Lo que comparten varias familias de :class:`AggregateRepository`.

    Hoy, la guarda de tecnología: la usan Tecnologías y Proyectos.
    """

    # Todas las consultas que explotan el CSV de ``tecnologia`` llevan
    # ``_CON_TECNOLOGIA``. No cambia el resultado —una fila sin tecnología no
    # produce ningún ``code``—, pero es lo que deja a Postgres ir por un índice
    # de tecnología (el parcial ``idx_lic_tecnologia_cubriente``, ``WHERE
    # tecnologia IS NOT NULL``, o ``idx_lic_tecnologia``) en vez de recorrer la
    # tabla entera, que es ~99 % filas sin etiqueta (casi todo PSCP): ~10k filas
    # en lugar de ~713k. Misma guarda, y mismo motivo, que la de
    # :func:`db.sql_fragments.tecnologia_en_csv_sql`.

    _CON_TECNOLOGIA = "tecnologia IS NOT NULL"
