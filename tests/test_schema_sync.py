"""Test de sincronización entre db/schema.py (DDL) y db/models.py (SQLAlchemy Core).

Verifica que las definiciones de tablas en models.py se mantienen alineadas con
la DDL canónica en schema.py. Esto detecta automáticamente cuando se añade una
columna al DDL pero se olvida actualizarla en models.py (o viceversa).

Solo valida las 3 tablas cubiertas por models.py (licitaciones,
licitacion_tecnologia_score, adjudicaciones). Las ~22 tablas restantes que solo
existen en schema.py no se verifican aquí.
"""

from __future__ import annotations

import sqlite3
from typing import Any, ClassVar

import pytest


def _create_tables_from_ddl(conn: sqlite3.Connection) -> None:
    """Ejecuta el DDL de schema.py en una BD in-memory."""
    from db.schema import SCHEMA

    for stmt in SCHEMA.split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # Puede haber IF NOT EXISTS repetidos, ok


def _get_columns_from_db(conn: sqlite3.Connection, table: str) -> set[str]:
    """Obtiene los nombres de columna de una tabla via PRAGMA."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _get_columns_from_sa_table(table: Any) -> set[str]:
    """Obtiene nombres de columna de un objeto Table de SQLAlchemy."""
    return {col.key for col in table.columns}


class TestSchemaModelsSync:
    """Verifica que schema.py y models.py están sincronizados para tablas compartidas."""

    TABLES: ClassVar[list[tuple[str, str]]] = [
        ("licitaciones", "licitaciones"),
        ("licitacion_tecnologia_score", "licitacion_tecnologia_score"),
        ("adjudicaciones", "adjudicaciones"),
    ]

    @pytest.fixture(scope="class")
    def ddl_columns(self) -> dict[str, set[str]]:
        """Crea la BD desde DDL y extrae columnas por tabla."""
        conn = sqlite3.connect(":memory:")
        _create_tables_from_ddl(conn)
        result = {}
        for table_name, _ in self.TABLES:
            result[table_name] = _get_columns_from_db(conn, table_name)
        conn.close()
        return result

    @pytest.fixture(scope="class")
    def sa_columns(self) -> dict[str, set[str]]:
        """Extrae columnas de las definiciones SQLAlchemy."""
        from db.models import adjudicaciones, licitacion_tecnologia_score, licitaciones

        sa_tables = {
            "licitaciones": licitaciones,
            "licitacion_tecnologia_score": licitacion_tecnologia_score,
            "adjudicaciones": adjudicaciones,
        }
        return {name: _get_columns_from_sa_table(t) for name, t in sa_tables.items()}

    @pytest.mark.parametrize(
        "table_name", ["licitaciones", "licitacion_tecnologia_score", "adjudicaciones"]
    )
    def test_ddl_columns_subset_of_sa(self, ddl_columns, sa_columns, table_name):
        """Todas las columnas del DDL deben existir en la definición SA."""
        ddl = ddl_columns[table_name]
        sa = sa_columns[table_name]
        missing_in_sa = ddl - sa
        assert not missing_in_sa, (
            f"Columnas en schema.py DDL pero ausentes en models.py para {table_name}: "
            f"{missing_in_sa}. Añádelas a db/models.py."
        )

    @pytest.mark.parametrize(
        "table_name", ["licitaciones", "licitacion_tecnologia_score", "adjudicaciones"]
    )
    def test_sa_columns_subset_of_ddl(self, ddl_columns, sa_columns, table_name):
        """Todas las columnas de SA deben existir en el DDL."""
        ddl = ddl_columns[table_name]
        sa = sa_columns[table_name]
        missing_in_ddl = sa - ddl
        assert not missing_in_ddl, (
            f"Columnas en models.py pero ausentes en schema.py DDL para {table_name}: "
            f"{missing_in_ddl}. Añádelas a db/schema.py."
        )
