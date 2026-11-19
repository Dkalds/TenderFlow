"""Materializar el DDL no depende de lo que haya en otros schemas de la base.

v171 decide si añadir `fk_access_grants_revoked_by` buscando su nombre en
`pg_constraint`, sin filtrar por schema. Cuando `tests/conftest.py` migraba
sobre la propia base de tests, el schema de un test de otra sesión viva (o
huérfano de una pasada interrumpida) con esa FK hacía que la migración se la
saltara y fallara en el `VALIDATE CONSTRAINT`: toda la sesión acababa en error.
"""

from __future__ import annotations

import os

import psycopg

from tests.conftest import _materialize_schema_ddl, _pg_test_url


def test_ddl_se_materializa_con_la_fk_de_v171_en_otro_schema(tmp_db) -> None:
    url = _pg_test_url()
    huerfano = f"tf_huerfano_{os.getpid()}"
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{huerfano}" CASCADE')
        conn.execute(f'CREATE SCHEMA "{huerfano}"')
        conn.execute(f'CREATE TABLE "{huerfano}".users (id INTEGER PRIMARY KEY)')
        conn.execute(
            f'CREATE TABLE "{huerfano}".access_grants (revoked_by INTEGER, '
            "CONSTRAINT fk_access_grants_revoked_by FOREIGN KEY (revoked_by) "
            f'REFERENCES "{huerfano}".users (id))'
        )
    try:
        ddl = _materialize_schema_ddl(url)
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{huerfano}" CASCADE')

    assert "fk_access_grants_revoked_by" in ddl
