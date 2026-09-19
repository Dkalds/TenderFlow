"""Núcleo tipado (T2) contra Postgres: lo que sin motor real no prueba nada.

Criterios del plan (``docs/plans/2026-09-plan-arquitectura-v2.md`` §6 T2) que
viven aquí:

* «``values_equal`` deja de necesitarse para ``importe``: un test de round-trip
  exacto pasa **contra Postgres**» — con la columna vieja alineada con
  producción (``real``), no con el ``double precision`` que crea ``alembic
  upgrade head``.
* La clave canónica **byte a byte idéntica** durante la lectura dual: antes y
  después del backfill, y con el flag encendido.

Y la paridad de las gemelas: la función SQL de ``v133`` y
``db.nucleo_tipado.a_timestamptz`` tienen que dar lo mismo para los mismos
textos, o la verificación del backfill daría por divergente lo que la
escritura dual escribió bien.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

# `db_float4` cambia tipos y tira la vista canónica: schema de usar y tirar
# también con TF_TEST_SCHEMA_STRATEGY=truncate.
pytestmark = pytest.mark.schema_propio


@pytest.fixture()
def db(tmp_db: Any) -> Any:
    db_mod, _ = tmp_db
    return db_mod


@pytest.fixture()
def db_float4(db: Any) -> Any:
    """``importe`` y ``duracion_valor`` como en producción: ``real``.

    Mismo motivo y misma receta que ``db_importe_float4`` en
    ``tests/test_db_upsert.py``: la vista ``licitaciones_canonicas`` bloquea el
    ``ALTER`` y el schema es de usar y tirar.
    """
    from db.database import connect

    with connect() as c:
        c.execute("DROP MATERIALIZED VIEW IF EXISTS licitaciones_canonicas")
        c.execute("ALTER TABLE licitaciones ALTER COLUMN importe TYPE real")
        c.execute("ALTER TABLE licitaciones ALTER COLUMN duracion_valor TYPE real")
    return db


def _lic(**kwargs: Any) -> Any:
    from db.upsert import Licitacion

    base: dict[str, Any] = {
        "id_externo": "T2-001",
        "titulo": "Mantenimiento de la plataforma SAP del organismo",
        "organo_contratacion": "Ministerio de Hacienda",
        "cpv": "72200000",
        "importe": 500_000.0,
        "fecha_publicacion": "2026-01-15",
    }
    base.update(kwargs)
    return Licitacion(**base)


def _sombras(id_externo: str) -> tuple[Any, ...]:
    from db.database import connect

    with connect() as c:
        return tuple(
            c.execute(
                "SELECT fecha_publicacion_ts, fecha_limite_ts, importe_num, duracion_valor_num "
                "FROM licitaciones WHERE id_externo = %s",
                [id_externo],
            ).fetchone()
        )


def _rellenar_todo() -> int:
    from db.nucleo_tipado import rellenar_lote

    desde, total = "", 0
    while True:
        lote = rellenar_lote(desde, 2)
        if lote.hasta is None:
            return total
        total += lote.afectadas
        desde = lote.hasta


def _verificar_todo() -> dict[str, int]:
    from db.nucleo_tipado import DETALLE_VERIFICACION, verificar_lote

    desde = ""
    suma = dict.fromkeys(("divergentes", *DETALLE_VERIFICACION), 0)
    while True:
        lote = verificar_lote(desde, 2)
        if lote.hasta is None:
            return suma
        suma["divergentes"] += lote.afectadas
        for clave, valor in lote.detalle.items():
            suma[clave] += valor
        desde = lote.hasta


# ── Round-trip exacto ─────────────────────────────────────────────────────


def test_importe_num_hace_round_trip_exacto_con_la_columna_vieja_en_float4(db_float4: Any) -> None:
    """El criterio de aceptación del plan, contra Postgres y con ``real``.

    La columna vieja devuelve el importe degradado —es el bug de 2026-08-16—;
    la sombra devuelve exactamente el ``float`` que escribió el conector, sin
    ninguna tolerancia de por medio.
    """
    from db.database import connect
    from db.upsert import upsert_licitaciones_with_history

    importe = 12_345_678.91
    upsert_licitaciones_with_history([_lic(importe=importe)], source="ted")

    with connect() as c:
        viejo, sombra = c.execute(
            "SELECT importe, importe_num FROM licitaciones WHERE id_externo = 'T2-001'"
        ).fetchone()
    assert viejo != importe  # float4: lo que motivó todo esto
    assert sombra == Decimal("12345678.91")
    assert float(sombra) == importe  # igualdad exacta, sin values_equal


def test_el_backfill_no_machaca_la_sombra_exacta_con_el_valor_degradado(db_float4: Any) -> None:
    """La verificación compara la sombra con el ``real`` con tolerancia.

    Sin ella, el backfill vería divergente el ``importe_num`` exacto que dejó la
    escritura dual y lo sustituiría por lo que queda en el ``real``.
    """
    from db.upsert import upsert_licitaciones_with_history

    upsert_licitaciones_with_history([_lic(importe=12_345_678.91)], source="ted")
    assert _rellenar_todo() == 0
    assert _sombras("T2-001")[2] == Decimal("12345678.91")
    assert _verificar_todo()["divergentes"] == 0


# ── Escritura dual: regla de UPDATE ───────────────────────────────────────


def test_reingesta_sin_fecha_limite_conserva_fecha_y_sombra(db: Any) -> None:
    from db.upsert import upsert_licitaciones

    upsert_licitaciones([_lic(fecha_limite="2026-02-01T12:00:00+00:00")])
    upsert_licitaciones([_lic(fecha_limite=None)])
    assert _sombras("T2-001")[1] == datetime(2026, 2, 1, 12, tzinfo=UTC)


def test_reingesta_con_fecha_limite_no_iso_vacia_la_sombra(db: Any) -> None:
    """La vieja se actualiza al texto nuevo; la sombra no puede quedarse atrás.

    El texto empieza por un prefijo ISO porque el CHECK de ``v59`` rechaza lo
    demás; lo que sigue al prefijo es lo que ya no es una fecha.
    """
    from db.upsert import upsert_licitaciones

    upsert_licitaciones([_lic(fecha_limite="2026-02-01T12:00:00+00:00")])
    upsert_licitaciones([_lic(fecha_limite="2026-02-01 (estimada)")])
    assert _sombras("T2-001")[1] is None
    assert _verificar_todo()["divergentes"] == 0


# ── Paridad de las gemelas ────────────────────────────────────────────────

_TEXTOS = (
    "2026-09-18",
    "2026-09-18T09:30:00+00:00",
    "2026-09-18T09:30:00Z",
    "2026-09-18 09:30",
    "2026-09-18T09:30:00.123456",
    "2026-09-18T23:59:00+02:00",
    "2026-09-18T23:59:00+0200",
    "2026-09-18T23:59:00-03",
    "18/09/2026",
    "2026-02-30",
    "2026-13-01",
    "0000-01-01",
    "2026-09-18T24:00:00",
    "2026-09-18T09:30:00+99:00",
    "",
)


@pytest.mark.parametrize("texto", _TEXTOS)
def test_funcion_sql_y_gemela_python_dan_lo_mismo(db: Any, texto: str) -> None:
    from db.database import connect
    from db.nucleo_tipado import a_timestamptz

    with connect() as c:
        (sql,) = c.execute("SELECT nucleo_iso_a_timestamptz(%s)", [texto]).fetchone()
    assert sql == a_timestamptz(texto)


@pytest.mark.parametrize(
    "valor", [0.125, -0.125, 12_345_678.91, 999_999_999_999.99, 999_999_999_999.996, 1e13]
)
def test_importe_sql_y_gemela_python_dan_lo_mismo(db: Any, valor: float) -> None:
    from db.database import connect
    from db.nucleo_tipado import a_importe_num, importe_num_sql

    with connect() as c:
        # S608: el fragmento es constante; el valor va como parámetro.
        consulta = (
            f"SELECT {importe_num_sql('v')} FROM (SELECT CAST(%s AS double precision) AS v) s"  # noqa: S608
        )
        (sql,) = c.execute(consulta, [valor]).fetchone()
    assert sql == a_importe_num(valor)


# ── Clave canónica durante la lectura dual ────────────────────────────────


def test_la_clave_canonica_no_se_mueve_con_el_backfill_ni_con_el_flag(
    db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Trampa 1 del plan, medida sobre filas y no sobre el texto del SQL.

    Se escriben filas con las formas de fecha que existen, se vacían las
    sombras (el estado de una fila anterior a ``v133``), se calcula la clave, se
    rellena, se enciende el flag y se vuelve a calcular: tiene que salir la
    misma, fila a fila. Y el año-mes de la sombra leído en UTC coincide con el
    prefijo del texto en todas ellas, que es lo que la verificación cuenta como
    ``periodo_distinto``.
    """
    from config import settings
    from db.database import connect
    from db.sql_fragments import clave_canonica_agrupable_sql
    from db.upsert import upsert_licitaciones

    upsert_licitaciones(
        [
            _lic(id_externo="A", fecha_publicacion="2026-01-31"),
            _lic(id_externo="B", fecha_publicacion="2026-01-31T23:59:59+00:00"),
            _lic(id_externo="C", fecha_publicacion="2026-02-01T00:00:00Z"),
            _lic(id_externo="D", fecha_publicacion=None),
            # Un «2026-02-30» no llega a esta tabla: pasa el CHECK de v59 pero
            # la columna generada de v68 (`iso_prefix_to_date`) lo rechaza al
            # insertar, así que no es un estado que el backfill pueda ver.
        ]
    )
    with connect() as c:
        c.execute(
            "UPDATE licitaciones SET fecha_publicacion_ts = NULL, fecha_limite_ts = NULL, "
            "importe_num = NULL, duracion_valor_num = NULL"
        )

    # S608: fragmento constante de db/sql_fragments.py, sin input.
    consulta = (
        f"SELECT l.id_externo, {clave_canonica_agrupable_sql('l')} "  # noqa: S608
        "FROM licitaciones l ORDER BY l.id_externo"
    )

    def claves() -> list[tuple[str, str]]:
        with connect() as c:
            return [tuple(f) for f in c.execute(consulta).fetchall()]

    monkeypatch.setattr(settings, "NUCLEO_TIPADO_LECTURA", False, raising=False)
    antes = claves()
    assert _verificar_todo()["divergentes"] > 0
    assert _rellenar_todo() > 0
    monkeypatch.setattr(settings, "NUCLEO_TIPADO_LECTURA", True, raising=False)
    assert claves() == antes

    verificacion = _verificar_todo()
    assert verificacion["divergentes"] == 0
    assert verificacion["periodo_distinto"] == 0
    assert verificacion["fecha_publicacion_no_iso"] == 0


def test_indices_de_v134_existen_y_son_validos(db: Any) -> None:
    from db.database import connect

    with connect() as c:
        filas = c.execute(
            "SELECT c.relname, i.indisvalid FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname IN ('idx_lic_fecha_publicacion_ts', 'idx_lic_fecha_limite_ts') "
            "AND c.relnamespace = current_schema()::regnamespace"
        ).fetchall()
    assert sorted(filas) == [
        ("idx_lic_fecha_limite_ts", True),
        ("idx_lic_fecha_publicacion_ts", True),
    ]
