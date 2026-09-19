"""Núcleo tipado (T2, ``v133``/``v134``): traducción, escritura dual y lectura dual.

Sin BD. Lo que necesita Postgres —el round-trip exacto de ``importe_num``, la
paridad de las gemelas contra la función SQL y la clave canónica antes y
después del backfill— está en ``tests/test_nucleo_tipado_pg.py``.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from db import sql_fragments as sf
from db.nucleo_tipado import (
    _RE_FECHA_HORA,
    _RE_OFFSET,
    _RE_SOLO_FECHA,
    COLUMNAS_SOMBRA,
    Lote,
    a_duracion_num,
    a_importe_num,
    a_timestamptz,
    sombras_disponibles,
    valores_sombra,
)

_VERSIONS = Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions"


def _cargar(nombre: str) -> Any:
    spec = importlib.util.spec_from_file_location(nombre, _VERSIONS / f"{nombre}.py")
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# ── Traducción de fechas ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("2026-09-18", datetime(2026, 9, 18, tzinfo=UTC)),
        ("2026-09-18T09:30:00+00:00", datetime(2026, 9, 18, 9, 30, tzinfo=UTC)),
        ("2026-09-18T09:30:00Z", datetime(2026, 9, 18, 9, 30, tzinfo=UTC)),
        ("2026-09-18 09:30", datetime(2026, 9, 18, 9, 30, tzinfo=UTC)),
        ("2026-09-18T09:30:00.123456", datetime(2026, 9, 18, 9, 30, 0, 123456, tzinfo=UTC)),
        (
            "2026-09-18T23:59:00+02:00",
            datetime(2026, 9, 18, 23, 59, tzinfo=timezone(timedelta(hours=2))),
        ),
        ("2026-09-18T23:59:00+0200", datetime(2026, 9, 18, 21, 59, tzinfo=UTC)),
        ("2026-09-18T23:59:00-03", datetime(2026, 9, 19, 2, 59, tzinfo=UTC)),
    ],
)
def test_a_timestamptz_traduce_los_formatos_iso(texto: str, esperado: datetime) -> None:
    assert a_timestamptz(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        None,
        "",
        "18/09/2026",
        "2026-02-30",
        "2026-13-01",
        "0000-01-01",
        "2026-09-18T24:00:00",
        "2026-09-18T09:30:00+99:00",
        "2026-09-18 extra",
        # Dígitos de ancho completo: `\d` los casaría, `[0-9]` no.
        "".join(chr(0xFF10 + d) for d in (2, 0, 2, 6)) + "-09-18",
    ],
)
def test_a_timestamptz_devuelve_none_para_lo_que_no_es_fecha(texto: str | None) -> None:
    assert a_timestamptz(texto) is None


def test_fecha_sola_cae_en_su_mismo_mes_leida_en_utc() -> None:
    """La componente temporal de la clave canónica es el prefijo del texto.

    Para que la sombra pueda sustituirla algún día, el año-mes leído en UTC
    tiene que coincidir con ese prefijo. Con fecha sola y con UTC explícito, lo
    hace por construcción.
    """
    for texto in ("2026-01-31", "2026-01-31T23:59:59+00:00", "2026-02-01T00:00:00Z"):
        ts = a_timestamptz(texto)
        assert ts is not None
        assert ts.astimezone(UTC).strftime("%Y-%m") == texto[:7]


def test_offset_que_cruza_fin_de_mes_si_cambia_el_mes_en_utc() -> None:
    """El caso que la verificación cuenta como ``periodo_distinto``."""
    ts = a_timestamptz("2026-02-01T00:30:00+02:00")
    assert ts is not None
    assert ts.astimezone(UTC).strftime("%Y-%m") == "2026-01"


def test_las_expresiones_regulares_son_las_de_la_funcion_sql() -> None:
    """Gemela Python y gemela SQL (``v133``) casan exactamente los mismos textos."""
    fn = _cargar("v133_nucleo_tipado_sombra")._FN_ISO_A_TIMESTAMPTZ
    for patron in (_RE_SOLO_FECHA.pattern, _RE_FECHA_HORA.pattern, _RE_OFFSET.pattern):
        assert f"'{patron}'" in fn, patron


# ── Traducción numérica ───────────────────────────────────────────────────


def test_importe_num_conserva_los_centimos_que_float4_pierde() -> None:
    """El importe del bug de 2026-08-16: float4 lo redondea, la sombra no."""
    assert a_importe_num(12_345_678.91) == Decimal("12345678.91")


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (0.125, Decimal("0.13")),  # empate: se aleja de cero, como `numeric`
        (-0.125, Decimal("-0.13")),
        (0.1 + 0.2, Decimal("0.30")),
        (500000.0, Decimal("500000.00")),
        (999_999_999_999.99, Decimal("999999999999.99")),
    ],
)
def test_importe_num_redondea_a_centimo(valor: float, esperado: Decimal) -> None:
    assert a_importe_num(valor) == esperado


@pytest.mark.parametrize(
    "valor", [None, float("nan"), float("inf"), -float("inf"), 1e12, -1e12, 999_999_999_999.996]
)
def test_importe_num_sin_sombra_para_lo_que_no_cabe(valor: float | None) -> None:
    """Fuera de ``numeric(14,2)`` la sombra queda a NULL en vez de abortar el lote."""
    assert a_importe_num(valor) is None


def test_duracion_num_no_redondea_a_centimos() -> None:
    assert a_duracion_num(2.5) == Decimal("2.5")
    assert a_duracion_num(1 / 3) == Decimal("0.333333333333333")
    assert a_duracion_num(None) is None
    assert a_duracion_num(float("nan")) is None


def test_valores_sombra_sigue_el_orden_de_columnas_sombra() -> None:
    data = {
        "fecha_publicacion": "2026-09-01",
        "fecha_limite": "2026-09-30T12:00:00+00:00",
        "importe": 1000.5,
        "duracion_valor": 12.0,
    }
    assert [s for s, _ in COLUMNAS_SOMBRA] == [
        "fecha_publicacion_ts",
        "fecha_limite_ts",
        "importe_num",
        "duracion_valor_num",
    ]
    assert valores_sombra(data) == [
        datetime(2026, 9, 1, tzinfo=UTC),
        datetime(2026, 9, 30, 12, tzinfo=UTC),
        Decimal("1000.50"),
        Decimal("12.0"),
    ]


# ── Escritura dual en db/upsert.py ────────────────────────────────────────


def test_sin_sombras_el_upsert_es_el_de_siempre() -> None:
    """Antes de ``v133`` el SQL no cambia ni un carácter."""
    from db.upsert import (
        _LIC_COLS,
        _LIC_PLACEHOLDERS,
        _LIC_UPDATES,
        _sql_upsert_licitaciones,
    )

    # S608: se compone con las constantes del propio módulo, no con input.
    esperado = (
        f"INSERT INTO licitaciones ({_LIC_COLS}) VALUES ({_LIC_PLACEHOLDERS}) "  # noqa: S608
        f"ON CONFLICT(id_externo) DO UPDATE SET {_LIC_UPDATES}"
    )
    assert _sql_upsert_licitaciones(con_sombras=False) == esperado
    assert "_ts" not in _LIC_UPDATES
    assert "_num" not in _LIC_UPDATES


def test_con_sombras_el_upsert_escribe_las_cuatro() -> None:
    from db.upsert import _LIC_KEYS, _sql_upsert_licitaciones

    sql = _sql_upsert_licitaciones(con_sombras=True)
    columnas = sql.split("(", 1)[1].split(")", 1)[0].split(", ")
    assert columnas == [*_LIC_KEYS, *(s for s, _ in COLUMNAS_SOMBRA)]
    assert sql.count("%s") == len(columnas)


def test_cada_sombra_sigue_la_regla_de_update_de_su_columna_vieja() -> None:
    """``fecha_limite`` se conserva si la reingesta no la trae; su sombra también.

    Y no con ``COALESCE`` propio: si la reingesta trae un texto no ISO, la vieja
    se actualiza y la sombra tiene que pasar a NULL con ella, no quedarse con la
    fecha anterior.
    """
    from db.upsert import _LIC_SOMBRA_UPDATES

    asignaciones = dict(a.split("=", 1) for a in _LIC_SOMBRA_UPDATES.split(", "))
    assert asignaciones["fecha_limite_ts"] == (
        "CASE WHEN excluded.fecha_limite IS NULL THEN licitaciones.fecha_limite_ts "
        "ELSE excluded.fecha_limite_ts END"
    )
    for sombra in ("fecha_publicacion_ts", "importe_num", "duracion_valor_num"):
        assert asignaciones[sombra] == f"excluded.{sombra}"


def test_fila_licitacion_solo_anade_sombras_si_existen() -> None:
    from dataclasses import asdict

    from db.upsert import _LIC_KEYS, Licitacion, _fila_licitacion

    data = asdict(Licitacion(id_externo="X", titulo="t", importe=12_345_678.91))
    assert _fila_licitacion(data, con_sombras=False) == [data[k] for k in _LIC_KEYS]
    con = _fila_licitacion(data, con_sombras=True)
    assert con[: len(_LIC_KEYS)] == [data[k] for k in _LIC_KEYS]
    assert con[len(_LIC_KEYS) :] == valores_sombra(data)
    assert con[len(_LIC_KEYS) + 2] == Decimal("12345678.91")


class _ConexionCatalogo:
    """Doble mínimo de conexión: responde al conteo de columnas del catálogo."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.consultas = 0

    def execute(self, _sql: str, _params: Any = None) -> _ConexionCatalogo:
        self.consultas += 1
        return self

    def fetchone(self) -> tuple[int]:
        return (self.n,)


def test_sombras_disponibles_exige_las_cuatro_columnas() -> None:
    assert sombras_disponibles(_ConexionCatalogo(4)) is True
    assert sombras_disponibles(_ConexionCatalogo(3)) is False
    assert sombras_disponibles(_ConexionCatalogo(0)) is False


def test_cada_chunk_pregunta_al_catalogo() -> None:
    """Sin caché: aplicar o revertir ``v133`` surte efecto sin reiniciar nada."""
    import db.upsert as upsert

    conexion = _ConexionCatalogo(4)
    assert upsert._con_sombras(conexion) is True
    conexion.n = 0  # downgrade en caliente
    assert upsert._con_sombras(conexion) is False
    assert conexion.consultas == 2


# ── Lectura dual en db/sql_fragments.py ───────────────────────────────────


@pytest.fixture()
def lectura(monkeypatch: pytest.MonkeyPatch) -> Any:
    from config import settings

    def fijar(valor: bool) -> None:
        monkeypatch.setattr(settings, "NUCLEO_TIPADO_LECTURA", valor, raising=False)

    return fijar


def test_el_flag_nace_apagado() -> None:
    from config.settings import Settings

    assert Settings.model_fields["NUCLEO_TIPADO_LECTURA"].default is False


@pytest.mark.parametrize(
    ("nombre", "vieja", "sombra"),
    [
        ("fecha_publicacion", "l.fecha_publicacion", "l.fecha_publicacion_ts"),
        ("fecha_limite", "l.fecha_limite", "l.fecha_limite_ts"),
        ("importe", "l.importe", "l.importe_num"),
        ("duracion_valor", "l.duracion_valor", "l.duracion_valor_num"),
    ],
)
def test_columna_nucleo_sigue_el_flag(lectura: Any, nombre: str, vieja: str, sombra: str) -> None:
    lectura(False)
    assert sf.columna_nucleo_sql(nombre) == vieja
    lectura(True)
    assert sf.columna_nucleo_sql(nombre) == sombra
    # El argumento explícito manda sobre el setting.
    assert sf.columna_nucleo_sql(nombre, tipada=False) == vieja


def test_con_el_flag_apagado_la_guarda_es_iso_guard_byte_a_byte(lectura: Any) -> None:
    lectura(False)
    assert sf.fecha_valida_sql("fecha_publicacion") == sf.iso_guard("l.fecha_publicacion")
    assert sf.fecha_valida_sql("fecha_limite", "x") == sf.iso_guard("x.fecha_limite")


def test_con_el_flag_encendido_la_guarda_conserva_las_cotas(lectura: Any) -> None:
    lectura(True)
    guarda = sf.fecha_valida_sql("fecha_limite")
    assert guarda == (
        "(l.fecha_limite_ts >= TIMESTAMPTZ '1900-01-01 00:00:00+00' "
        "AND l.fecha_limite_ts < TIMESTAMPTZ '3000-01-01 00:00:00+00')"
    )
    with pytest.raises(ValueError):
        sf.fecha_valida_sql("importe")


def test_importe_proyectado_nunca_llega_como_decimal(lectura: Any) -> None:
    lectura(False)
    assert sf.importe_sql() == "l.importe"
    lectura(True)
    assert sf.importe_sql() == "CAST(l.importe_num AS double precision)"


def test_la_clave_canonica_es_identica_durante_la_lectura_dual(lectura: Any) -> None:
    """Trampa 1 del plan: la clave no se puede mover durante la ventana.

    ``periodo_publicacion_sql`` es componente de la clave, y la clave está
    indexada (``v92``), materializada (``v101``/``v102``) y decide el sitemap.
    Encender el flag no puede cambiar ni un byte de ninguno de sus fragmentos.
    """
    fragmentos = (
        lambda: sf.clave_canonica_sql("l"),
        lambda: sf.clave_canonica_agrupable_sql("l"),
        lambda: sf.orden_canonico_sql("l"),
        lambda: sf.componentes_republicacion_sql("l"),
        lambda: sf.periodo_publicacion_sql("l"),
        lambda: sf.fila_canonica_sql(filtro_gemelo="TRUE"),
    )
    lectura(False)
    antes = [f() for f in fragmentos]
    lectura(True)
    despues = [f() for f in fragmentos]
    assert antes == despues
    for texto in map(str, despues):
        assert "_ts" not in texto
        assert "importe_num" not in texto


# ── Script de backfill ────────────────────────────────────────────────────


class _LotesFalsos:
    """Sustituto de ``rellenar_lote``/``verificar_lote`` que sirve lotes fijos."""

    def __init__(self, *lotes: Lote) -> None:
        self.pendientes = list(lotes)
        self.llamadas: list[str] = []

    def __call__(self, desde: str, _tamano: int) -> Lote:
        self.llamadas.append(desde)
        return self.pendientes.pop(0) if self.pendientes else Lote(None, 0, 0, {})


def test_backfill_avanza_por_cursor_hasta_el_final(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.backfill_nucleo_tipado as script

    paso = _LotesFalsos(Lote("a", 2, 1, {}), Lote("c", 2, 0, {}))
    monkeypatch.setattr(script, "rellenar_lote", paso)
    assert script.main(["--pausa", "0"]) == 0
    assert paso.llamadas == ["", "a", "c"]


def test_backfill_verificar_falla_si_hay_divergencias(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.backfill_nucleo_tipado as script

    detalle = dict.fromkeys(script.DETALLE_VERIFICACION, 0) | {"importe_num": 3}
    monkeypatch.setattr(script, "verificar_lote", _LotesFalsos(Lote("z", 10, 3, detalle)))
    monkeypatch.setattr(
        script, "rellenar_lote", lambda *_: pytest.fail("--verificar no debe escribir")
    )
    assert script.main(["--verificar", "--pausa", "0"]) == 1


def test_backfill_verificar_limpio_sale_con_cero(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.backfill_nucleo_tipado as script

    detalle = dict.fromkeys(script.DETALLE_VERIFICACION, 0) | {"fecha_limite_no_iso": 5}
    monkeypatch.setattr(script, "verificar_lote", _LotesFalsos(Lote("z", 10, 0, detalle)))
    assert script.main(["--verificar", "--pausa", "0"]) == 0


def test_backfill_reintenta_los_locks_y_aborta_con_cursor(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import psycopg

    import scripts.backfill_nucleo_tipado as script

    def bloqueado(_desde: str, _tamano: int) -> Lote:
        raise psycopg.errors.LockNotAvailable("lock timeout")

    monkeypatch.setattr(script, "rellenar_lote", bloqueado)
    monkeypatch.setattr(script.time, "sleep", lambda _s: None)
    assert script.main(["--desde", "k", "--pausa", "0"]) == 2
    assert "--desde 'k'" in capsys.readouterr().out
