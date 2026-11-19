"""Escrituras de los sembradores: negativos del clasificador y datos de desarrollo.

El SQL de ``scraper/seed_negatives.py`` y ``scripts/seed_dev.py`` (ADR-022);
la descarga, el filtrado y los datos de ejemplo se quedan en sus módulos.
"""

from __future__ import annotations

from collections.abc import Sequence

from db.database import connect, get_table_columns
from observability.logging import get_logger

log = get_logger(__name__)

_COLUMNAS_NEGATIVO = (
    "id_externo, titulo, descripcion, organo_contratacion, "
    "importe, moneda, cpv, tipo_contrato, estado, "
    "fecha_publicacion, fecha_extraccion, url, raw_keywords, "
    "provincia, nuts_code, ccaa, "
    "duracion_valor, duracion_unidad, fecha_inicio, "
    "fecha_fin, prorroga_descripcion, organo_ref_fuente"
)


def _columnas_de_licitaciones() -> set[str]:
    try:
        with connect() as conn:
            return set(get_table_columns(conn, "licitaciones"))
    except Exception:
        log.warning("semillas_columnas_por_cursor", exc_info=True)
        with connect() as c:
            cur = c.execute("SELECT * FROM licitaciones LIMIT 0")
            return {d[0] for d in (cur.description or [])}


def insertar_negativos(filas: Sequence[Sequence[object]]) -> tuple[int, int]:
    """Inserta los negativos que aún no están; devuelve ``(insertados, ya_existían)``.

    Cada fila tiene la forma que arma ``scraper.seed_negatives._collect_negatives_from_month``
    (21 valores; el 10 es ``fecha_actualizacion_fuente``). ``fecha_extraccion`` es
    ``NOW()`` y ``raw_keywords`` y ``tecnologia`` van a ``NULL``: un negativo no
    tiene tecnología. Una conexión por fila: un fallo no deshace las anteriores.
    """
    if not filas:
        return 0, 0
    columnas = _columnas_de_licitaciones()
    con_fecha_act = "fecha_actualizacion_fuente" in columnas
    extra_cols = ", fecha_actualizacion_fuente" if con_fecha_act else ""
    extra_vals = ", %s" if con_fecha_act else ""
    if "tecnologia" in columnas:
        extra_cols += ", tecnologia"
        extra_vals += ", NULL"
    # Columnas y marcadores fijos del módulo; los valores van como parámetros.
    sql = (
        f"INSERT INTO licitaciones ({_COLUMNAS_NEGATIVO}{extra_cols}) "
        f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s{extra_vals}) "
        "ON CONFLICT(id_externo) DO NOTHING"
    )
    insertados = existentes = 0
    for fila in filas:
        params = [*fila[:10], *fila[11:21]]
        if con_fecha_act:
            params.append(fila[10])
        with connect() as c:
            if c.execute(sql, params).rowcount:
                insertados += 1
            else:
                existentes += 1
    return insertados, existentes


def borrar_semilla_dev() -> None:
    """Borra lo que siembra ``scripts/seed_dev.py``: predicciones antes por la FK."""
    with connect() as c:
        c.execute(
            "DELETE FROM predicciones_baja WHERE licitacion_id IN "
            "(SELECT id_externo FROM licitaciones WHERE fuente='seed')"
        )
        c.execute("DELETE FROM adjudicaciones WHERE licitacion_id LIKE 'SEED-%'")
        c.execute("DELETE FROM licitaciones WHERE fuente='seed'")


def upsert_predicciones_demo(filas: Sequence[tuple[str, float, float, float, int, str]]) -> None:
    """``(licitacion_id, p10, p50, p90, model_version, computed_at)`` agregadas, sin lote."""
    with connect() as c:
        c.executemany(
            "INSERT INTO predicciones_baja "
            "(licitacion_id, p10, p50, p90, model_version, computed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            # Árbitro del único parcial agregado (v140): la PK ya no existe.
            "ON CONFLICT (licitacion_id) WHERE lote_numero IS NULL DO UPDATE SET "
            "p10 = EXCLUDED.p10, p50 = EXCLUDED.p50, p90 = EXCLUDED.p90, "
            "model_version = EXCLUDED.model_version, computed_at = EXCLUDED.computed_at",
            filas,
        )
