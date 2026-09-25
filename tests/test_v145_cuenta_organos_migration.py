"""La forma de v145: lo que la migración emite, sin base.

Lo que v145 hace con datos —el backfill de una cuenta por órgano— lo ejerce
toda la suite de integración, que construye su esquema con ``alembic upgrade
head``. Aquí se fija lo que un test contra una base vacía no ve:

- que ``cuenta_organos`` nace protegida por RLS (FORCE y las dos políticas),
  porque ``tests/test_rls_tenant_scope_integration.py`` sólo comprueba que la
  tabla está *declarada* en ``TABLAS_CORPORATIVAS``;
- que el backfill corre **después** de crear la tabla y de relajar las columnas
  legadas, y que la unicidad nueva del nombre se crea sobre datos ya
  rellenados;
- que la clave del nombre en SQL pliega con las mismas tablas que
  ``clave_de_nombre`` en Python: si no, el backfill y el alta calcularían dos
  claves distintas para la misma cuenta.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

from db.repositories.cuentas import clave_de_nombre
from db.sql_fragments import FOLD_DST, FOLD_SRC

_RUTA = (
    Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions" / "v145_cuenta_organos.py"
)


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v145_cuenta_organos", _RUTA)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _sql_emitido(
    funcion: str, *, dialecto: str = "postgresql", tablas: frozenset[str] | None = None
) -> list[str]:
    modulo = _cargar()
    presentes = tablas if tablas is not None else frozenset({"cuentas_objetivo", "cuenta_organos"})
    emitido: list[str] = []
    with (
        patch.object(modulo, "op") as op_falso,
        patch.object(modulo, "_tablas", return_value=set(presentes)),
    ):
        op_falso.get_bind.return_value.dialect.name = dialecto
        op_falso.execute.side_effect = emitido.append
        getattr(modulo, funcion)()
    return emitido


def _indice(emitido: list[str], fragmento: str) -> int:
    return next(i for i, sql in enumerate(emitido) if fragmento in sql)


def test_cuenta_organos_nace_con_la_proteccion_rls() -> None:
    emitido = _sql_emitido("upgrade")

    assert "ALTER TABLE cuenta_organos ENABLE ROW LEVEL SECURITY" in emitido
    assert "ALTER TABLE cuenta_organos FORCE ROW LEVEL SECURITY" in emitido
    politicas = [s for s in emitido if s.startswith("CREATE POLICY")]
    assert len(politicas) == 2
    assert any("tenant_scope_cuenta_organos" in p and "PERMISSIVE" in p for p in politicas)
    assert any("tenant_guard_cuenta_organos" in p and "RESTRICTIVE" in p for p in politicas)
    assert _cargar().TABLAS_CORPORATIVAS == ("cuenta_organos",)


def test_un_organo_es_de_una_sola_cuenta_por_organizacion() -> None:
    crear = next(s for s in _sql_emitido("upgrade") if "CREATE TABLE" in s)

    assert "UNIQUE (organization_id, organo_norm)" in crear
    assert "REFERENCES cuentas_objetivo(id) ON DELETE CASCADE" in crear


def test_el_backfill_va_despues_de_preparar_las_tablas() -> None:
    """Relajar las legadas y crear la tabla antes de copiar; la unicidad del
    nombre después de rellenarlo, o fallaría con los ``NULL`` de antes."""
    emitido = _sql_emitido("upgrade")

    relajar = _indice(emitido, "ALTER COLUMN organo_norm DROP NOT NULL")
    rellenar_nombre = _indice(emitido, "SET nombre_norm")
    unicidad = _indice(emitido, "uq_cuentas_objetivo_org_nombre")
    crear = _indice(emitido, "CREATE TABLE IF NOT EXISTS cuenta_organos")
    copiar = _indice(emitido, "INSERT INTO cuenta_organos")

    assert relajar < rellenar_nombre < unicidad
    assert crear < copiar
    # La copia no puede fallar por un órgano repetido: se queda el primero.
    assert "ON CONFLICT (organization_id, organo_norm) DO NOTHING" in emitido[copiar]


def test_la_clave_del_nombre_pliega_como_clave_de_nombre() -> None:
    """Mismas tablas de plegado que ``fold_expr``, y espacios colapsados."""
    clave_sql = _cargar()._CLAVE_NOMBRE_SQL

    assert f"'{FOLD_SRC}'" in clave_sql
    assert f"'{FOLD_DST}'" in clave_sql
    assert "regexp_replace" in clave_sql
    assert clave_de_nombre("  AYUNTAMIENTO   de Alcalá ") == "ayuntamiento de alcala"


def test_downgrade_devuelve_cada_cuenta_a_su_primer_organo_antes_de_tirar_la_tabla() -> None:
    emitido = _sql_emitido("downgrade")

    recuperar = _indice(emitido, "DISTINCT ON (cuenta_id)")
    tirar = _indice(emitido, "DROP TABLE IF EXISTS cuenta_organos")
    obligar = _indice(emitido, "ALTER COLUMN organo_norm SET NOT NULL")
    assert recuperar < tirar < obligar


def test_fuera_de_postgres_o_sin_la_tabla_de_v105_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []
    assert _sql_emitido("upgrade", tablas=frozenset()) == []
