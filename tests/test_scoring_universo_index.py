"""Regresiones de ``v84_lic_universo_cpv_index`` y del predicado que lo activa.

El índice de v84 es **parcial**: Postgres solo lo usa cuando puede demostrar que
el ``WHERE`` de la consulta implica el predicado del índice, y no normaliza
variantes del ``COALESCE``. Es decir, el índice y la consulta están acoplados
por el **texto** —o más exactamente por el árbol que ese texto produce— y ese
acoplamiento no lo protege ningún tipo, ningún contrato y ninguna excepción: si
alguien reescribe el predicado en la consulta, el resultado sigue siendo
correcto y lo único que pasa es que el plan vuelve en silencio al Parallel Seq
Scan de 9,5 s que motivó la migración. Exactamente la clase de regresión que
nadie nota.

Estos tests fijan ese acoplamiento sin Postgres (no hay ninguno en el entorno
local, y el criterio de aceptación del ítem —"primera carga del Radar bajo 5 s"—
solo se puede medir contra datos de producción):

1. la revisión encadena donde debe y crea el índice como debe;
2. el predicado del índice es el mismo que el del fragmento compartido;
3. la consulta de competencia lo interpola en vez de escribirlo a mano;
4. ningún módulo del repo escribe una variante distinta del mismo predicado.

Sin fixtures de BD, así que ``tests/conftest.py`` los marca ``unit``.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

import pytest

from db.sql_fragments import TECHNOLOGY_OBSERVED_SQL

_REPO_ROOT = Path(__file__).resolve().parents[1]
# Dónde se consulta el universo del radar. `tests/` queda fuera a propósito:
# un test puede querer escribir el predicado a mano para comprobar otra cosa.
_PAQUETES_CON_SQL = ("db", "services", "scheduler", "api", "scraper")


def _normaliza(sql: str) -> str:
    """Colapsa espacios y quita el alias de tabla.

    Lo que Postgres compara es el árbol de la expresión, no el texto: los
    espacios y el alias (``l.``, que un ``CREATE INDEX`` ni siquiera puede
    llevar porque no tiene ``FROM``) son ruido, y exigir igualdad byte a byte
    haría fallar el test por un salto de línea sin que nada se hubiera roto.
    """
    return re.sub(r"\s+", " ", sql).replace("l.analysis_universe", "analysis_universe").strip()


def _load_migration() -> Any:
    return importlib.import_module("db.alembic.versions.v84_lic_universo_cpv_index")


class _RecordingOp:
    """``op`` de mentira que anota el SQL y finge el ``autocommit_block``."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.autocommit_blocks = 0

    def execute(self, statement: Any) -> None:
        self.statements.append(str(statement))

    def get_context(self) -> _RecordingOp:
        return self

    def autocommit_block(self) -> Any:
        self.autocommit_blocks += 1
        return _Block()


class _Block:
    """El ``autocommit_block`` real confirma la transacción; aquí basta pasar."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: Any) -> bool:
        return False


def _statements(monkeypatch: pytest.MonkeyPatch, accion: str) -> tuple[Any, _RecordingOp]:
    migration = _load_migration()
    monkeypatch.setattr(migration, "_is_postgres", lambda: True)
    fake_op = _RecordingOp()
    monkeypatch.setattr(migration, "op", fake_op)
    getattr(migration, accion)()
    return migration, fake_op


# ---------------------------------------------------------------------------
# La revisión
# ---------------------------------------------------------------------------


def test_v84_encadena_con_v83() -> None:
    """Una migración fuera de la cadena no se aplica nunca."""
    migration = _load_migration()

    assert migration.revision == "v84_lic_universo_cpv_index"
    assert migration.down_revision == "v83_pursuit_next_action"


def test_v84_es_noop_fuera_de_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    """El guard de dialecto: v48 hacía ``return`` en Postgres, el error inverso."""
    migration = _load_migration()
    monkeypatch.setattr(migration, "_is_postgres", lambda: False)

    class _FailingOp:
        def __getattr__(self, name: str) -> Any:
            def _boom(*args: Any, **kwargs: Any) -> None:
                raise AssertionError(f"no debería llamarse: op.{name}")

            return _boom

    monkeypatch.setattr(migration, "op", _FailingOp())

    migration.upgrade()
    migration.downgrade()


def test_v84_crea_el_indice_sin_bloquear_al_scraper(monkeypatch: pytest.MonkeyPatch) -> None:
    """``CONCURRENTLY`` dentro de ``autocommit_block``, o la tabla se bloquea.

    Un ``CREATE INDEX`` normal sobre ``licitaciones`` retiene un lock que
    bloquea las escrituras del scraper durante toda la construcción, y sobre
    1,6 M filas eso son minutos. ``CONCURRENTLY`` no puede correr dentro de una
    transacción, así que sin el ``autocommit_block`` la sentencia ni siquiera
    llega a ejecutarse.
    """
    _migration, fake_op = _statements(monkeypatch, "upgrade")

    assert fake_op.autocommit_blocks == 1
    create = next(s for s in fake_op.statements if "CREATE INDEX" in s)
    assert "CONCURRENTLY" in create
    # Idempotente: la migración puede reintentarse tras un fallo de lock.
    assert "IF NOT EXISTS" in create


def test_v84_indexa_las_dos_columnas_que_pide_la_consulta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``(id_externo, cpv)`` y no ``(cpv)``: si no, el join vuelve al heap.

    De ``licitaciones`` la señal de competencia necesita justo dos columnas —la
    clave del join contra ``adjudicaciones`` y el segmento CPV— y el sentido de
    este índice es entregar las dos sin leer la fila. Con ``cpv`` solo, el
    planificador tendría que bajar al heap de 972 MB a por ``id_externo``, que
    es el coste que la migración quita. ``id_externo`` va primero por ser la
    clave del join.
    """
    _migration, fake_op = _statements(monkeypatch, "upgrade")

    create = next(s for s in fake_op.statements if "CREATE INDEX" in s)
    columnas = re.search(r"ON licitaciones \(([^)]*)\)", create)
    assert columnas is not None
    assert [c.strip() for c in columnas.group(1).split(",")] == ["id_externo", "cpv"]


def test_v84_relaja_el_statement_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin esto la construcción muere a los 2 min y deja un índice ``INVALID``.

    Mismo motivo que en v79: el ``PGOPTIONS`` de ``migrate.yml`` no llega a
    través de este pooler, así que el techo que regiría es el default de sesión
    — menos de lo que tarda un CONCURRENTLY sobre 972 MB.
    """
    _migration, fake_op = _statements(monkeypatch, "upgrade")

    assert "SET statement_timeout = 0" in fake_op.statements


def test_v84_downgrade_borra_el_indice_sin_bloquear(monkeypatch: pytest.MonkeyPatch) -> None:
    """El ``downgrade`` es además la limpieza de un CONCURRENTLY fallido."""
    _migration, fake_op = _statements(monkeypatch, "downgrade")

    drop = next(s for s in fake_op.statements if "DROP INDEX" in s)
    assert "CONCURRENTLY" in drop
    assert "IF EXISTS" in drop
    assert "idx_lic_universo_cpv" in drop


# ---------------------------------------------------------------------------
# El acoplamiento índice ↔ consulta
# ---------------------------------------------------------------------------


def test_el_predicado_del_indice_es_el_del_fragmento_compartido() -> None:
    """Si divergen, el índice parcial deja de aplicar y nadie se entera.

    Postgres solo usa un índice parcial cuando demuestra que el ``WHERE`` de la
    consulta implica su predicado, y no reescribe ``COALESCE`` para intentarlo:
    un ``'technology_observed'`` cambiado por una variable, un ``IS NOT
    DISTINCT FROM`` en vez del ``=``, u otro valor por defecto, y el plan vuelve
    al seq scan con el resultado intacto.
    """
    migration = _load_migration()

    assert _normaliza(migration.INDEX_PREDICATE) == _normaliza(TECHNOLOGY_OBSERVED_SQL)


def test_la_consulta_de_competencia_interpola_el_fragmento(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El SQL real que se manda a Postgres lleva el predicado indexado.

    No basta con que el fragmento exista: lo que el planificador ve es el texto
    ya compuesto. Este test lo captura sustituyendo la conexión, así que
    detecta también una copia del ``COALESCE`` pegada a mano en la consulta.
    """
    from db.repositories import aggregates as mod

    ejecutadas: list[str] = []

    class _Cursor:
        description = (("cpv4",), ("media_ofertas",))

        def fetchall(self) -> list[tuple[Any, ...]]:
            return []

        def fetchone(self) -> None:
            return None

    class _Conn:
        def execute(self, sql: str, params: Any = None) -> _Cursor:
            ejecutadas.append(sql)
            return _Cursor()

        def __enter__(self) -> _Conn:
            return self

        def __exit__(self, *exc: Any) -> bool:
            return False

    monkeypatch.setattr(mod, "connect_read", _Conn)

    rows, media_global = mod.AggregateRepository().competencia_ofertas_por_cpv4(
        cutoff_iso="2024-08-17T00:00:00+00:00"
    )

    assert rows == []
    assert media_global is None
    assert len(ejecutadas) == 2
    for sql in ejecutadas:
        assert TECHNOLOGY_OBSERVED_SQL in sql
    # Y de `licitaciones` no se pide nada más que lo que el índice cubre: las
    # dos columnas de su clave, más la del predicado (que el índice no guarda
    # pero tampoco necesita leer, porque el filtro lo implica el propio índice
    # parcial). Una cuarta columna aquí obliga a bajar al heap y deshace la
    # migración sin cambiar ni un resultado.
    por_cpv4 = ejecutadas[0]
    assert set(re.findall(r"\bl\.(\w+)", por_cpv4)) == {"id_externo", "cpv", "analysis_universe"}


def test_ningun_modulo_escribe_una_variante_del_predicado() -> None:
    """Todas las copias del ``COALESCE`` deben pedir lo mismo.

    El predicado está replicado a mano en varios módulos (``kpi_precompute``,
    ``ml_dataset``, ``pricing``, ``domain_truth_audit``…) porque ``db/`` no
    puede importar de ``services/`` y viceversa según el caso. Da igual el
    espaciado —Postgres compara árboles, no bytes— pero no da igual el valor por
    defecto ni el valor comparado: una variante con otra constante no la sirve
    el índice parcial de v84.
    """
    # El disparador busca solo el arranque de la expresión, para no confundir
    # con prosa que mencione ``COALESCE`` y la columna en la misma frase (los
    # docstrings de este repo argumentan largo y lo hacen a menudo).
    arranque = re.compile(r"COALESCE\(\s*(?:\w+\.)?analysis_universe\b")
    completo = re.compile(
        r"COALESCE\(\s*(?:\w+\.)?analysis_universe\s*,\s*'([^']*)'\s*\)\s*=\s*'([^']*)'"
    )
    vistos = 0
    for paquete in _PAQUETES_CON_SQL:
        for fichero in sorted((_REPO_ROOT / paquete).rglob("*.py")):
            texto = fichero.read_text(encoding="utf-8")
            for candidato in arranque.finditer(texto):
                donde = (
                    f"{fichero.relative_to(_REPO_ROOT)}:"
                    f"{texto.count(chr(10), 0, candidato.start()) + 1}"
                )
                match = completo.match(texto, candidato.start())
                assert match is not None, (
                    f"{donde}: variante no reconocida del predicado de universo; "
                    "no la servirá el índice parcial de v84"
                )
                assert match.groups() == ("technology_observed", "technology_observed"), (
                    f"{donde}: {match.group(0)}"
                )
                vistos += 1
    # Red de seguridad del propio test: si un refactor deja de escribir el
    # predicado a mano en ningún sitio, el bucle pasaría en vacío.
    assert vistos > 0
