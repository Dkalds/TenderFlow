"""El aislamiento entre tests se conserva con las dos estrategias (C3.4).

`tests/conftest.py` creaba un schema Postgres nuevo por test: aplicar el DDL
completo —unas 50 tablas más sus índices— cientos de veces es el techo de
velocidad de la suite de integración que el backlog señala como P2.

La alternativa es un schema por sesión y `TRUNCATE … RESTART IDENTITY CASCADE`
entre tests. Es mucho más rápida y tiene un riesgo propio y concreto: si el
aislamiento se rompe, no falla — **contamina**, y el síntoma aparece en otro
test, a veces solo según el orden. Por eso el aislamiento se comprueba aquí y
no se da por supuesto.

Estos tests corren con **cualquiera** de las dos estrategias
(`TF_TEST_SCHEMA_STRATEGY`), que es justo lo que los hace útiles: son el gate
que hay que ver en verde con `truncate` antes de cambiar el default.
"""

from __future__ import annotations

import pytest

from tests.conftest import ESTRATEGIA_SCHEMA

pytestmark = pytest.mark.usefixtures("tmp_db")


#: Filas que el primer test escribe y el segundo no puede ver.
_ID_FUGA = "FUGA-C3.4-no-debe-sobrevivir"


def _contar(db_mod, id_externo: str) -> int:
    with db_mod.connect() as c:
        fila = c.execute(
            "SELECT COUNT(*) FROM licitaciones WHERE id_externo = %s", (id_externo,)
        ).fetchone()
    return int(fila[0])


def _insertar(db_mod, id_externo: str) -> None:
    with db_mod.connect() as c:
        # `fecha_extraccion` es NOT NULL y no tiene default: sin ella el INSERT
        # falla con `NotNullViolation` y el test no llega a probar el
        # aislamiento, que es lo suyo. Se descubrió al correr esta suite contra
        # Postgres por primera vez — la sesión que escribió el test no tenía
        # base delante, y sin ella un INSERT incompleto no se distingue de uno
        # bueno. Mismo valor fijo que usan los demás tests de integración.
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (id_externo) DO NOTHING",
            (id_externo, "Fuga entre tests", "test", "2026-01-01"),
        )


def test_a_escribe_una_fila(tmp_db) -> None:
    """Primer test del par: deja una fila con un id reconocible."""
    db_mod, _ = tmp_db
    _insertar(db_mod, _ID_FUGA)
    assert _contar(db_mod, _ID_FUGA) == 1


def test_b_no_ve_la_fila_del_test_anterior(tmp_db) -> None:
    """Segundo test del par: la fila no puede estar.

    Si esto falla con `TF_TEST_SCHEMA_STRATEGY=truncate`, el truncado no está
    limpiando lo que debería y el default **no** se puede cambiar. Con
    `schema` no puede fallar por construcción: son bases distintas.
    """
    db_mod, _ = tmp_db
    assert _contar(db_mod, _ID_FUGA) == 0, (
        f"fuga entre tests con estrategia {ESTRATEGIA_SCHEMA!r}: la fila del "
        "test anterior sobrevivió al aislamiento"
    )


def test_las_secuencias_vuelven_a_empezar(tmp_db) -> None:
    """`RESTART IDENTITY`: un test que asuma `id == 1` no puede depender del orden.

    Sin reiniciar las secuencias, el truncado deja la BD vacía pero con los
    contadores donde los dejó el test anterior — y un test que compruebe el id
    asignado pasaría o fallaría según en qué posición de la suite corriera.
    """
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        # `fecha_extraccion` es NOT NULL sin default: ver `_insertar`.
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s)",
            ("SECUENCIA-C3.4", "Reinicio de secuencia", "test", "2026-01-01"),
        )
        fila = c.execute(
            "SELECT id FROM licitaciones WHERE id_externo = %s", ("SECUENCIA-C3.4",)
        ).fetchone()
    assert int(fila[0]) == 1, (
        f"la secuencia de `licitaciones` no reinició (id={fila[0]}) con estrategia "
        f"{ESTRATEGIA_SCHEMA!r}"
    )


def test_las_semillas_de_migracion_sobreviven(tmp_db) -> None:
    """`TRUNCATE` se lleva por delante lo que sembró una migración.

    `api_key_tiers` (v28) es el caso conocido: sin restaurarlo, cada test vería
    la tabla vacía y las aserciones sobre tiers pasarían vacunadas — que es peor
    que fallar. El snapshot de semillas se toma por catálogo, no por una lista
    escrita a mano, para que una migración nueva no obligue a volver al
    conftest.
    """
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        existe = c.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'api_key_tiers'"
        ).fetchone()
        if not existe or int(existe[0]) == 0:
            pytest.skip("api_key_tiers no está en este schema")
        filas = c.execute("SELECT COUNT(*) FROM api_key_tiers").fetchone()
    assert int(filas[0]) > 0, (
        f"las semillas de migración no sobrevivieron al aislamiento "
        f"{ESTRATEGIA_SCHEMA!r}: api_key_tiers está vacía"
    )
