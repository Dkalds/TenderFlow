"""El índice de v146 y la expresión con la que las cuentas casan órganos son la misma.

Un índice funcional sólo sirve si su expresión coincide con la del ``WHERE``.
Si divergen no falla nada visible: el planificador ignora el índice y el
resumen de /cuentas, la ficha de cada cuenta y los avisos vuelven al escaneo
completo de ~710k filas con un ``translate`` por fila. Es el mismo modo de
fallo silencioso que ``test_clave_canonica_index.py`` vigila para v101, y por
la misma razón: la revisión congela su copia en vez de importarla.

Si este test falla, la corrección **no** es tocar la constante de v146
—describe el índice que existe en producción—. Es escribir una revisión nueva
que reconstruya el índice con la expresión nueva y apuntar ``_RUTA_INDICE`` a
ella.
"""

from __future__ import annotations

import contextlib
import importlib.util
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from db.sql_fragments import fold_expr, organo_normalizado_sql

_RUTA_INDICE = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v146_lic_organo_norm_index.py"
)


def _cargar_revision() -> Any:
    """Por ruta: ``db/alembic/versions/`` no es un paquete."""
    spec = importlib.util.spec_from_file_location("v146_lic_organo_norm_index", _RUTA_INDICE)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _sql_emitido(funcion: str, *, dialecto: str = "postgresql") -> list[str]:
    modulo = _cargar_revision()
    emitido: list[str] = []
    with patch.object(modulo, "op") as op_falso:
        op_falso.get_bind.return_value.dialect.name = dialecto
        op_falso.execute.side_effect = emitido.append
        getattr(modulo, funcion)()
    return emitido


def test_el_indice_indexa_la_expresion_con_la_que_casan_las_cuentas() -> None:
    """El alias de la migración es el nombre de la tabla; en las consultas es
    ``l``. Es la única diferencia admisible."""
    congelada = _cargar_revision()._ORGANO_NORMALIZADO_SQL
    assert organo_normalizado_sql("licitaciones") == congelada


def test_upgrade_construye_sin_bloquear_ni_morir_por_timeout() -> None:
    """``CONCURRENTLY``: el scraper sigue escribiendo mientras se construye.
    ``statement_timeout = 0``: sobre ~710k filas pasa de los 30 s del rol.
    ``ANALYZE`` al final, para que el planificador sepa que el índice existe."""
    emitido = _sql_emitido("upgrade")

    assert "SET statement_timeout = 0" in emitido
    crear = next(s for s in emitido if s.startswith("CREATE INDEX"))
    assert "CONCURRENTLY" in crear
    assert "IF NOT EXISTS idx_lic_organo_norm " in crear
    assert organo_normalizado_sql("licitaciones") in crear
    assert emitido[-1] == "ANALYZE licitaciones"


def test_downgrade_retira_el_indice_tambien_sin_bloquear() -> None:
    assert _sql_emitido("downgrade") == ["DROP INDEX CONCURRENTLY IF EXISTS idx_lic_organo_norm"]


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []


def test_el_buscador_de_organos_lleva_la_expresion_del_trigram_de_v143(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El buscador del alta filtra también por ``fold_expr`` del órgano entero.

    Es la expresión de ``idx_lic_organo_plegado_trgm`` (v143;
    ``tests/test_indices_busqueda.py`` fija que es la misma), y sin ese
    predicado cada tecla del buscador recorre la tabla: la clave de las cuentas
    lleva ``btrim``/``nullif`` y no casa con el trigram. Los dos ``LIKE`` van con
    el mismo patrón, así que el segundo decide lo que sale.
    """
    from db.repositories import cuentas

    llamadas: list[tuple[str, tuple[Any, ...]]] = []

    def _ejecutar(sql: str, params: tuple[Any, ...]) -> SimpleNamespace:
        llamadas.append((sql, params))
        return SimpleNamespace(description=[], fetchall=list)

    @contextlib.contextmanager
    def _conexion() -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(execute=_ejecutar)

    monkeypatch.setattr(cuentas, "connect_read", _conexion)

    assert cuentas.CuentasRepository().buscar_organos(7, "  Madrid ", 20) == []

    ((sql, params),) = llamadas
    assert f"WHERE {fold_expr('l.organo_contratacion')} LIKE %s " in sql
    assert f"AND {organo_normalizado_sql('l')} LIKE %s " in sql
    assert params == ("%madrid%", "%madrid%", 20, 7)
