"""Escrituras de los sembradores: negativos del clasificador y datos de desarrollo.

El SQL de ``scraper/seed_negatives.py`` y ``scripts/seed_dev.py`` (ADR-022);
la descarga, el filtrado y los datos de ejemplo se quedan en sus módulos.
"""

from __future__ import annotations

from collections.abc import Sequence

from db.connection import now_utc_iso
from db.database import connect, get_table_columns
from db.fechas_ts import LIC_COLUMNAS_UPSERT, sombra, sombras_presentes, valores_lic
from db.nucleo_tipado import COLUMNAS_SOMBRA, sombras_disponibles, valores_sombra
from observability.logging import get_logger

log = get_logger(__name__)

#: Orden de cada fila de ``scraper.seed_negatives._collect_negatives_from_month``.
_CAMPOS_NEGATIVO = (
    "id_externo",
    "titulo",
    "descripcion",
    "organo_contratacion",
    "importe",
    "moneda",
    "cpv",
    "tipo_contrato",
    "estado",
    "fecha_publicacion",
    "fecha_actualizacion_fuente",
    "url",
    "provincia",
    "nuts_code",
    "ccaa",
    "duracion_valor",
    "duracion_unidad",
    "fecha_inicio",
    "fecha_fin",
    "prorroga_descripcion",
    "organo_ref_fuente",
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

    Cada fila tiene la forma de :data:`_CAMPOS_NEGATIVO`. ``fecha_extraccion`` y
    ``primera_extraccion`` son ``now_utc_iso()`` y, como en ``db/upsert.py``,
    se escriben las sombras de ``v133`` y ``v159`` si existen: en
    ``licitaciones`` no las mantiene un trigger, y sin ellas la fila salta en el
    healthcheck (``licitaciones_sin_sombra_fecha``). ``raw_keywords`` y
    ``tecnologia`` van a ``NULL``: un negativo no tiene tecnología. Una conexión
    por fila: un fallo no deshace las anteriores.
    """
    if not filas:
        return 0, 0
    columnas = _columnas_de_licitaciones()
    with connect() as c:
        con_sombras = sombras_disponibles(c)
        con_fechas_ts = sombras_presentes(c, "licitaciones", LIC_COLUMNAS_UPSERT)
    ahora = now_utc_iso()
    insertados = existentes = 0
    for fila in filas:
        data: dict[str, object] = dict(zip(_CAMPOS_NEGATIVO, fila, strict=True))
        data.update(fecha_extraccion=ahora, primera_extraccion=ahora, raw_keywords=None)
        if "tecnologia" in columnas:
            data["tecnologia"] = None
        valores = {k: v for k, v in data.items() if k in columnas}
        if con_sombras:
            valores.update(zip((s for s, _ in COLUMNAS_SOMBRA), valores_sombra(data), strict=True))
        if con_fechas_ts:
            fechas = {k: v if isinstance(v, str) else None for k, v in data.items()}
            valores.update(zip(map(sombra, LIC_COLUMNAS_UPSERT), valores_lic(fechas), strict=True))
        # Nombres de columna de este módulo o del catálogo; los valores van como parámetros.
        sql = (
            f"INSERT INTO licitaciones ({', '.join(valores)}) "
            f"VALUES ({', '.join(['%s'] * len(valores))}) ON CONFLICT(id_externo) DO NOTHING"
        )
        with connect() as c:
            if c.execute(sql, list(valores.values())).rowcount:
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
