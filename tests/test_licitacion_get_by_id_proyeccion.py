"""`get_by_id` nombra sus columnas y no se deja fuera nada que lean sus consumidores.

Hasta el 2026-11-19 era un `SELECT *`: una columna nueva viajaba en cada lectura
y el orden de las columnas era contrato implícito. La fila entera solo la quiere
la herramienta MCP `ficha_licitacion`, por `get_fila_completa`.
"""

from __future__ import annotations

from api.routes.licitaciones.modelos import LicitacionDetail
from db.repositories.licitaciones import _COLS_DETALLE, LicitacionRepository
from services.rag.context import _PRIMARY_DOC_FIELDS

#: Lo que leen de `get_by_id` el dossier, el detalle de tecnologías, pursuits y
#: el simulador, aparte de la ficha y el RAG.
_OTROS_CONSUMIDORES = {
    "importe",
    "importe_base_sin_iva",
    "titulo",
    "organo_contratacion",
    "id_externo",
    "estado",
    "fecha_limite",
    "cpv",
    "tecnologia",
    "peso_precio_pct",
}


def _columnas(db_mod) -> set[str]:
    with db_mod.connect() as c:
        filas = c.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'licitaciones'"
        ).fetchall()
    return {str(f[0]) for f in filas}


def _sembrar(db_mod) -> None:
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion, "
            "peso_precio_pct, ml_proba) VALUES ('PROY-1', 'Proyección', 'test', "
            "'2026-01-01', 60, 0.9)"
        )


def test_la_proyeccion_cubre_las_columnas_de_la_ficha_y_del_resto(tmp_db) -> None:
    db_mod, _ = tmp_db
    columnas = _columnas(db_mod)
    pedidas = (
        (set(LicitacionDetail.model_fields) & columnas)
        | set(_PRIMARY_DOC_FIELDS)
        | {"descripcion"}
        | _OTROS_CONSUMIDORES
    )

    assert pedidas <= set(_COLS_DETALLE)
    assert set(_COLS_DETALLE) <= columnas


def test_get_by_id_trae_la_proyeccion_y_no_las_columnas_internas(tmp_db) -> None:
    db_mod, _ = tmp_db
    _sembrar(db_mod)

    fila = LicitacionRepository().get_by_id("PROY-1")

    assert fila is not None
    assert list(fila) == list(_COLS_DETALLE)
    assert fila["peso_precio_pct"] == 60
    assert "ml_proba" not in fila


def test_get_fila_completa_trae_todas_las_columnas(tmp_db) -> None:
    db_mod, _ = tmp_db
    _sembrar(db_mod)

    fila = LicitacionRepository().get_fila_completa("PROY-1")

    assert fila is not None
    assert set(fila) == _columnas(db_mod)
    assert LicitacionRepository().get_fila_completa("NO-EXISTE") is None
