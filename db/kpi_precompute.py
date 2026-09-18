"""SQL del precálculo de KPIs: métricas del radar, ``kpi_snapshots`` y Parquet.

Es el lado de persistencia de ``scheduler/kpi_precompute.py``. Las once
consultas de métricas, el reemplazo del snapshot, sus dos lecturas y las cinco
consultas materializadas del export Parquet vivían en el job, que abría su
propio ``connect()`` y era por eso una entrada del ratchet TID251. Bajaron aquí
sin cambiar el texto del SQL ni el tipo de conexión (ADR-022); el job se quedó
con lo que sí es orquestación: cronometrar, elegir entre DuckDB y pandas,
escribir los ficheros y loguear.

No vive en ``db/repositories/kpi_snapshots.py``, aunque ese módulo también
consulta ``kpi_snapshots``, para no juntar en un fichero las dos familias de
métricas que su docstring pide no mezclar: las ``ov_*`` de allí agregan sin
filtro de universo y las de aquí lo filtran.

Funciones de módulo y no clase: no hay estado que compartir (ADR-022 §2).

Qué universo miden estos KPIs (decisión del 2026-09-03)
--------------------------------------------------------
Hasta esta fecha las dieciséis consultas de este módulo que filtran universo
—las once de métricas y las cinco materializadas— escribían a mano la
forma **estrecha** del predicado de universo —el ``COALESCE`` de
:data:`db.sql_fragments.TECHNOLOGY_OBSERVED_SQL`— mientras la superficie
pública, el sitemap y los dos hubs usaban la **ancha**
(``db.sql_fragments.universo_tecnologico_sql``: además, los universos RSS
autonómicos y cualquier fila con señal técnica propia). Dos definiciones de "el
radar" en el mismo producto: el KPI de portada contaba una cosa y la portada
enseñaba otra.

Se unifica en la **ancha**, que es la que ve el usuario. Consecuencias que hay
que asumir a sabiendas:

- **Las cifras de ``kpi_snapshots`` cambian.** Todas las métricas de este
  módulo —``total_licitaciones``, ``importe_total``, ``n_organos``,
  ``licitaciones_30d`` y sus deltas, las series por CCAA/estado/mes y los cinco
  Parquet materializados— pasan a contar también las filas de los RSS
  autonómicos y las de PSCP con etiqueta técnica. El delta va en la dirección
  de crecer, pero **cuánto sólo se puede medir contra la BD real**, y la
  sesión que tomó la decisión no tenía Postgres: el número que salga en la
  primera pasada tras el despliegue no es comparable con el de la pasada
  anterior, y un salto en la serie histórica de ``kpi_snapshots`` en esa fecha
  es esperado, no una anomalía de ingesta.
- **Se pierde el índice parcial de ``v84``** para estas consultas: el predicado
  ancho es un ``OR`` que incluye filas fuera de ese índice, así que el
  planificador vuelve al seq scan. Es un job nocturno sin SLA de latencia, no
  una petición HTTP; se acepta a cambio de que el KPI y la portada cuenten lo
  mismo. Las consultas que sí necesitan el índice usan
  ``technology_observed_sql`` y siguen donde estaban.

Las métricas ``ov_*`` que añade ``db/repositories/kpi_snapshots.py`` no pasan
por aquí y **no** filtran universo: ver su propio módulo.

Imports diferidos
-----------------
``db.database.connect``, ``db.analytics``, ``pandas`` y el repository de las
``ov_*`` se importan dentro de cada función, como cuando este código vivía en
``scheduler/``. Dos motivos: importar ``scheduler.kpi_precompute`` —que carga
este módulo al arrancar— sigue sin arrastrar pandas ni el paquete
``db.repositories``, y los tests del job siguen sustituyendo
``db.database.connect`` y ``db.analytics.duckdb_query``, que un import de
módulo habría capturado antes del parche.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from db.sql_fragments import universo_tecnologico_sql

if TYPE_CHECKING:
    import pandas as pd

#: El universo del radar, en su forma ancha y escrita una sola vez. El alias
#: ``l`` obliga a que todas las consultas de abajo lo declaren; ver el
#: docstring del módulo para por qué la ancha y no la estrecha.
_UNIVERSO = universo_tecnologico_sql("l")

#: Una fila de ``kpi_snapshots`` antes de persistirse: ``metrica``,
#: ``dimension``, ``valor``, ``valor_text`` y ``computed_at``. Los valores son
#: ``Any`` porque ``valor`` es entero, float o ``None`` según la métrica. Es la
#: forma de ``db.repositories.kpi_snapshots._fila`` más ``computed_at``, que
#: añade :func:`compute_all_kpis` al final y sin el que
#: :func:`persist_snapshots` lanza ``KeyError``.
FilaSnapshot = dict[str, Any]


# ── Definición de KPIs a pre-calcular ────────────────────────────────────────


def compute_all_kpis(conn: Any) -> list[FilaSnapshot]:  # Any: `connect()` no tipa la conexión
    """Calcula todos los KPIs desde la BD directamente.

    Returns:
        Lista de {metrica, dimension, valor, valor_text, computed_at}, con las
        ``ov_*`` de ``db/repositories/kpi_snapshots.py`` al final.
    """
    snapshots: list[FilaSnapshot] = []
    now = datetime.now(UTC).isoformat()

    # ── Métricas globales ─────────────────────────────────────────────────

    # Total de licitaciones
    row = conn.execute(f"SELECT COUNT(*) FROM licitaciones l WHERE {_UNIVERSO}").fetchone()
    snapshots.append({"metrica": "total_licitaciones", "dimension": "global", "valor": row[0]})

    # Importe total y medio
    row = conn.execute(
        "SELECT SUM(l.importe), AVG(l.importe) FROM licitaciones l "
        f"WHERE l.importe IS NOT NULL AND {_UNIVERSO}"
    ).fetchone()
    snapshots.append({"metrica": "importe_total", "dimension": "global", "valor": row[0] or 0.0})
    snapshots.append({"metrica": "importe_medio", "dimension": "global", "valor": row[1] or 0.0})

    # Órganos distintos
    row = conn.execute(
        "SELECT COUNT(DISTINCT l.organo_contratacion) FROM licitaciones l "
        f"WHERE l.organo_contratacion IS NOT NULL AND {_UNIVERSO}"
    ).fetchone()
    snapshots.append({"metrica": "n_organos", "dimension": "global", "valor": row[0]})

    # CCAA distintas
    row = conn.execute(
        "SELECT COUNT(DISTINCT l.ccaa) FROM licitaciones l "
        f"WHERE l.ccaa IS NOT NULL AND {_UNIVERSO}"
    ).fetchone()
    snapshots.append({"metrica": "n_ccaa", "dimension": "global", "valor": row[0]})

    # Licitaciones últimos 30 días
    row = conn.execute(
        "SELECT COUNT(*) FROM licitaciones l WHERE l.fecha_publicacion >= "
        "to_char(CURRENT_DATE - INTERVAL '30 days', 'YYYY-MM-DD') "
        f"AND {_UNIVERSO}"
    ).fetchone()
    snapshots.append({"metrica": "licitaciones_30d", "dimension": "global", "valor": row[0]})

    # Licitaciones 30d anteriores (para delta)
    row = conn.execute(
        "SELECT COUNT(*) FROM licitaciones l "
        "WHERE l.fecha_publicacion >= to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD') "
        "  AND l.fecha_publicacion < to_char(CURRENT_DATE - INTERVAL '30 days', 'YYYY-MM-DD') "
        f"  AND {_UNIVERSO}"
    ).fetchone()
    snapshots.append({"metrica": "licitaciones_30d_prev", "dimension": "global", "valor": row[0]})

    # ── Por CCAA ──────────────────────────────────────────────────────────

    rows = conn.execute(
        "SELECT l.ccaa AS ccaa, COUNT(*) as n, SUM(l.importe) as total "
        "FROM licitaciones l WHERE l.ccaa IS NOT NULL "
        f"AND {_UNIVERSO} "
        "GROUP BY l.ccaa ORDER BY n DESC"
    ).fetchall()
    ccaa_data = [{"ccaa": r[0], "n": r[1], "importe": r[2]} for r in rows]
    snapshots.append(
        {
            "metrica": "licitaciones_por_ccaa",
            "dimension": "global",
            "valor": None,
            "valor_text": json.dumps(ccaa_data, ensure_ascii=False),
        }
    )

    # ── Por estado ────────────────────────────────────────────────────────

    rows = conn.execute(
        "SELECT l.estado, COUNT(*) FROM licitaciones l WHERE l.estado IS NOT NULL "
        f"AND {_UNIVERSO} "
        "GROUP BY l.estado ORDER BY 2 DESC"
    ).fetchall()
    estado_data = {r[0]: r[1] for r in rows}
    snapshots.append(
        {
            "metrica": "licitaciones_por_estado",
            "dimension": "global",
            "valor": None,
            "valor_text": json.dumps(estado_data, ensure_ascii=False),
        }
    )

    # ── Adjudicaciones ────────────────────────────────────────────────────

    row = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT a.licitacion_id) FROM adjudicaciones a "
        "JOIN licitaciones l ON l.id_externo = a.licitacion_id "
        f"WHERE {_UNIVERSO}"
    ).fetchone()
    snapshots.append({"metrica": "total_adjudicaciones", "dimension": "global", "valor": row[0]})
    snapshots.append({"metrica": "licitaciones_con_adj", "dimension": "global", "valor": row[1]})

    # Top 10 adjudicatarios por importe
    rows = conn.execute(
        "SELECT a.nombre, COUNT(*) as n, SUM(a.importe_adjudicado) as total "
        "FROM adjudicaciones a JOIN licitaciones l ON l.id_externo = a.licitacion_id "
        "WHERE a.nombre IS NOT NULL AND a.importe_adjudicado IS NOT NULL "
        f"AND {_UNIVERSO} "
        "GROUP BY a.nombre ORDER BY total DESC LIMIT 10"
    ).fetchall()
    top_adj = [{"nombre": r[0], "n": r[1], "importe": r[2]} for r in rows]
    snapshots.append(
        {
            "metrica": "top10_adjudicatarios",
            "dimension": "global",
            "valor": None,
            "valor_text": json.dumps(top_adj, ensure_ascii=False),
        }
    )

    # ── Serie mensual últimos 24 meses ────────────────────────────────────

    rows = conn.execute(
        "SELECT to_char(l.fecha_publicacion::date, 'YYYY-MM') as mes, "
        "       COUNT(*) as n, SUM(l.importe) as total "
        "FROM licitaciones l "
        "WHERE l.fecha_publicacion >= to_char(CURRENT_DATE - INTERVAL '24 months', 'YYYY-MM-DD') "
        f"AND {_UNIVERSO} "
        "GROUP BY mes ORDER BY mes"
    ).fetchall()
    serie = [{"mes": r[0], "n": r[1], "importe": r[2]} for r in rows]
    snapshots.append(
        {
            "metrica": "serie_mensual_24m",
            "dimension": "global",
            "valor": None,
            "valor_text": json.dumps(serie, ensure_ascii=False),
        }
    )

    # ── Agregados globales del overview (métricas ``ov_*``) ───────────────
    #
    # Las calcula `db/repositories/kpi_snapshots.py` con el mismo
    # `AggregateRepository` que sirve `/analytics/overview`, así que aquí no
    # se repite su SQL y la paridad con el camino en vivo no depende de
    # mantener dos consultas parecidas sincronizadas a mano. Ojo: **no** son
    # equivalentes a las métricas de arriba, que filtran por `_UNIVERSO`; estas
    # no aplican filtro de universo.
    from db.repositories.kpi_snapshots import compute_overview_snapshot_rows

    snapshots.extend(compute_overview_snapshot_rows(conn))

    # Añadir timestamp a todos
    for s in snapshots:
        s.setdefault("valor_text", None)
        s["computed_at"] = now

    return snapshots


def persist_snapshots(conn: Any, snapshots: list[FilaSnapshot]) -> int:  # Any: ídem
    """Inserta los snapshots en la BD. Devuelve el número de filas insertadas."""
    conn.execute(
        "DELETE FROM kpi_snapshots"  # Limpiar todos antes de insertar nuevo snapshot completo
    )
    if not snapshots:
        return 0
    rows = [
        (s["computed_at"], s["metrica"], s["dimension"], s.get("valor"), s.get("valor_text"))
        for s in snapshots
    ]
    # executemany: una sola sentencia en vez de N round-trips a la BD.
    conn.executemany(
        "INSERT INTO kpi_snapshots (computed_at, metrica, dimension, valor, valor_text) "
        "VALUES (%s, %s, %s, %s, %s)",
        rows,
    )
    return len(rows)


def compute_and_persist_snapshots() -> int:
    """Calcula el snapshot completo y reemplaza el anterior en una transacción.

    El ``DELETE`` y el ``INSERT`` de :func:`persist_snapshots` van en la misma
    transacción, cuyo commit llega al salir de ``connect()``: otra conexión no
    ve la tabla vacía entre las dos sentencias, y si el ``INSERT`` falla el
    rollback deja el snapshot anterior. Es el "reemplazo atómico" que da por
    supuesto ``db/repositories/kpi_snapshots.py``. Lo fijan los tres tests de
    ``tests/test_kpi_precompute_transaccion.py``: las dos sentencias con el
    mismo ``pg_current_xact_id()``, la vista desde otra conexión justo antes del
    ``INSERT`` y el snapshot anterior intacto tras un ``INSERT`` rechazado.

    El cálculo usa esa misma conexión porque así lo hacía el job antes de
    traer el SQL aquí, no porque añada una garantía: ``connect()`` no cambia el
    aislamiento por defecto de Postgres (``READ COMMITTED``), así que cada
    consulta del cálculo ve su propia foto y calcular en otra conexión antes
    del reemplazo dejaría la tabla igual.

    Returns:
        Número de filas insertadas.
    """
    from db.database import connect

    with connect() as c:
        snapshots = compute_all_kpis(c)
        return persist_snapshots(c, snapshots)


# ── Consultas materializadas del export Parquet (F2) ──────────────────────────

MAT_QUERIES: dict[str, str] = {
    # `substr` y no `strftime`: esta consulta la ejecuta DuckDB sólo si el
    # extra `[analytics]` está instalado; sin él —el caso de la imagen que se
    # despliega, `requirements.txt` no trae duckdb— cae al fallback de pandas
    # contra Postgres, que no tiene `strftime`. El `except` por tabla se comía
    # el error como un `.skip`, así que este Parquet no se escribía nunca y en
    # silencio. `fecha_publicacion` es texto ISO, de modo que cortar los 7
    # primeros caracteres da el mes en los dos motores sin castear.
    "mat_licitaciones_por_mes": (
        "SELECT substr(l.fecha_publicacion, 1, 7) AS mes, "
        "COUNT(*) AS n, SUM(l.importe) AS importe_total, AVG(l.importe) AS importe_medio "
        "FROM licitaciones l WHERE l.fecha_publicacion IS NOT NULL "
        f"AND {_UNIVERSO} "
        "GROUP BY mes ORDER BY mes"
    ),
    "mat_licitaciones_por_ccaa": (
        "SELECT l.ccaa AS ccaa, COUNT(*) AS n, SUM(l.importe) AS importe_total "
        "FROM licitaciones l WHERE l.ccaa IS NOT NULL "
        f"AND {_UNIVERSO} "
        "GROUP BY l.ccaa ORDER BY n DESC"
    ),
    "mat_licitaciones_por_estado": (
        "SELECT l.estado AS estado, COUNT(*) AS n FROM licitaciones l "
        "WHERE l.estado IS NOT NULL "
        f"AND {_UNIVERSO} "
        "GROUP BY l.estado ORDER BY n DESC"
    ),
    "mat_top_adjudicatarios": (
        "SELECT a.nombre, COUNT(*) AS n, SUM(a.importe_adjudicado) AS importe_total "
        "FROM adjudicaciones a JOIN licitaciones l ON l.id_externo = a.licitacion_id "
        "WHERE a.nombre IS NOT NULL AND a.importe_adjudicado IS NOT NULL "
        f"AND {_UNIVERSO} "
        "GROUP BY a.nombre ORDER BY importe_total DESC LIMIT 50"
    ),
    "mat_licitaciones_por_tipo": (
        "SELECT l.tipo_contrato AS tipo_contrato, COUNT(*) AS n, "
        "SUM(l.importe) AS importe_total "
        "FROM licitaciones l WHERE l.tipo_contrato IS NOT NULL "
        f"AND {_UNIVERSO} "
        "GROUP BY l.tipo_contrato ORDER BY n DESC"
    ),
}


def export_mat_query_duckdb(nombre: str, dest: str) -> None:
    """Materializa la consulta ``nombre`` de :data:`MAT_QUERIES` en ``dest`` vía DuckDB.

    Recibe el nombre y no el SQL para que el ``COPY`` solo pueda envolver
    consultas de este módulo. No captura nada: decidir si un fallo es un
    ``.skip`` de esa tabla es cosa del job, que es quien lo loguea.
    """
    from db.analytics import duckdb_query

    duckdb_query(f"COPY ({MAT_QUERIES[nombre]}) TO '{dest}' (FORMAT PARQUET)")


@contextmanager
def mat_query_reader() -> Iterator[Callable[[str], pd.DataFrame] | None]:
    """Conexión del fallback pandas, con un lector de :data:`MAT_QUERIES` por nombre.

    Se cede un lector y no la conexión para que el SQL no salga de ``db/``: el
    bucle por tabla, la escritura del Parquet y sus logs siguen en el job, con
    la misma conexión abierta durante todo el recorrido. Cede ``None`` si el
    adaptador no expone la conexión DBAPI cruda que exige ``pd.read_sql``; el
    job salta entonces todas las tablas sin error, como hacía antes.

    ``connect()`` y no ``connect_read()``: se conserva el pool que usaba el job.
    El de lectura tiene otra sesión (autocommit, read-only) y cambiarlo aquí
    mezclaría el traslado del SQL con una decisión de routing que nadie evaluó.
    """
    import pandas as pd

    from db.database import connect

    with connect() as conn:
        raw_conn = getattr(conn, "_conn", None) or getattr(conn, "connection", None)
        if raw_conn is None:
            yield None
            return

        def leer(nombre: str) -> pd.DataFrame:
            return pd.read_sql(MAT_QUERIES[nombre], raw_conn)

        yield leer


# ── Lecturas del último snapshot ──────────────────────────────────────────────


def get_latest_snapshot(
    metrica: str, dimension: str = "global"
) -> dict[str, Any] | None:  # Any: `valor_text` es JSON crudo
    """Lee el snapshot más reciente de una métrica desde la BD.

    Args:
        metrica: Nombre de la métrica (e.g. "total_licitaciones").
        dimension: Dimensión (default "global").

    Returns:
        Dict con {valor, valor_text, computed_at} o None si no hay datos.
    """
    from db.database import connect

    with connect() as c:
        row = c.execute(
            "SELECT valor, valor_text, computed_at FROM kpi_snapshots "
            "WHERE metrica = %s AND dimension = %s "
            "ORDER BY computed_at DESC LIMIT 1",
            [metrica, dimension],
        ).fetchone()
    if row is None:
        return None
    result: dict[str, Any] = {"valor": row[0], "computed_at": row[2]}
    if row[1]:
        try:
            result["valor_text"] = json.loads(row[1])
        except json.JSONDecodeError:
            result["valor_text"] = row[1]
    return result


def get_all_latest() -> dict[str, Any]:  # Any: cada métrica es un JSON distinto
    """Devuelve todos los snapshots más recientes como un dict plano.

    Útil para cargar todos los KPIs pre-calculados de una vez.
    """
    from db.database import connect

    with connect() as c:
        # Obtener la fecha del snapshot más reciente
        row = c.execute("SELECT MAX(computed_at) FROM kpi_snapshots").fetchone()
        if not row or not row[0]:
            return {}
        latest_ts = row[0]

        rows = c.execute(
            "SELECT metrica, dimension, valor, valor_text FROM kpi_snapshots WHERE computed_at = %s",
            [latest_ts],
        ).fetchall()

    result: dict[str, Any] = {"_computed_at": latest_ts}
    for metrica, dimension, valor, valor_text in rows:
        key = metrica if dimension == "global" else f"{metrica}__{dimension}"
        if valor_text:
            try:
                result[key] = json.loads(valor_text)
            except json.JSONDecodeError:
                result[key] = valor_text
        else:
            result[key] = valor
    return result
