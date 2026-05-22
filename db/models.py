"""Definiciones de tablas SQLAlchemy Core para el proyecto.

Usado exclusivamente para **construcción de queries** (compiler-only): las
expresiones SA se compilan a SQL paramétrico y se ejecutan sobre la conexión
``libsql`` existente. No se usa SA Engine ni Session.

Patrón de uso::

    from db.models import licitaciones, licitacion_tecnologia_score
    from sqlalchemy import select, and_

    stmt = (
        select(licitaciones.c.id_externo, licitaciones.c.titulo)
        .where(and_(
            licitaciones.c.tecnologia.isnot(None),
            licitaciones.c.ccaa == "Madrid",
        ))
        .order_by(licitaciones.c.fecha_publicacion.desc())
        .limit(50)
    )

    # Compilar a SQLite dialect
    from db.models import compile_query
    sql, params = compile_query(stmt)
    rows = conn.execute(sql, params).fetchall()
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects import sqlite as _sqlite_dialect

metadata = MetaData()

# ---------------------------------------------------------------------------
# Tabla principal
# ---------------------------------------------------------------------------

licitaciones = Table(
    "licitaciones",
    metadata,
    Column("id_externo", String, primary_key=True),
    Column("titulo", Text, nullable=False),
    Column("descripcion", Text),
    Column("organo_contratacion", Text),
    Column("importe", Float),
    Column("moneda", String, default="EUR"),
    Column("cpv", String),
    Column("tipo_contrato", String),
    Column("estado", String),
    Column("fecha_publicacion", String),
    Column("fecha_limite", String),
    Column("url", Text),
    Column("raw_keywords", Text),
    Column("provincia", String),
    Column("ccaa", String),
    Column("nuts_code", String),
    Column("duracion_valor", Float),
    Column("duracion_unidad", String),
    Column("fecha_inicio", String),
    Column("fecha_fin", String),
    Column("prorroga_descripcion", Text),
    Column("ml_proba", Float),
    Column("tecnologia", String),
    Column("ml_tecnologias", Text),
    Column("ml_proba_max", Float),
    Column("ml_tech_principal", String),
    Column("fecha_actualizacion_fuente", String),
    Column("fecha_extraccion", String, nullable=False),
)

# ---------------------------------------------------------------------------
# Scores de tecnología por licitación
# ---------------------------------------------------------------------------

licitacion_tecnologia_score = Table(
    "licitacion_tecnologia_score",
    metadata,
    Column("licitacion_id", String, nullable=False),
    Column("tecnologia", String, nullable=False),
    Column("probabilidad", Float, nullable=False),
    Column("threshold_aplicado", Float, nullable=False),
    Column("computed_at", String, nullable=False),
)

# ---------------------------------------------------------------------------
# Adjudicaciones
# ---------------------------------------------------------------------------

adjudicaciones = Table(
    "adjudicaciones",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("licitacion_id", String, nullable=False),
    Column("nif", String),
    Column("nombre", Text, nullable=False),
    Column("provincia", String),
    Column("ccaa", String),
    Column("nuts_code", String),
    Column("importe_adjudicado", Float),
    Column("importe_pagable", Float),
    Column("fecha_adjudicacion", String),
    Column("es_pyme", Integer),
    Column("n_ofertas_recibidas", Integer),
    Column("oferta_minima", Float),
    Column("oferta_maxima", Float),
    Column("result_code", String),
    Column("result_description", Text),
    Column("fecha_extraccion", String, nullable=False),
)

# ---------------------------------------------------------------------------
# Compiler helper
# ---------------------------------------------------------------------------

_DIALECT = _sqlite_dialect.dialect()


def compile_query(stmt) -> tuple[str, list]:
    """Compila una expresión SQLAlchemy a (sql_string, params_list) para libsql.

    Usa el dialecto SQLite con parámetros posicionales (``?``) compatibles con
    la API ``libsql`` / ``sqlite3``.

    Args:
        stmt: Expresión SQLAlchemy Core (``Select``, ``Insert``, ``Update``, …).

    Returns:
        Tupla ``(sql, params)`` lista para pasar a ``conn.execute(sql, params)``.
    """
    compiled = stmt.compile(
        dialect=_DIALECT,
        compile_kwargs={"literal_binds": False},
    )
    sql: str = str(compiled)
    raw_params: dict = compiled.params

    # SA SQLite dialect ya emite ? posicionales; el orden está en positiontup.
    position_tup = getattr(compiled, "positiontup", None)
    if position_tup is not None:
        params = [raw_params[k] for k in position_tup]
    else:
        # Fallback: sin parámetros o literal_binds
        params = list(raw_params.values())

    return sql, params
