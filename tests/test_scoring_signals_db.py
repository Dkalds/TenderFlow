"""Tests del SQL real de las señales de scoring, contra Postgres.

Existen por una regresión concreta: ``_load_margen_stats_raw`` referenciaba
``a.importe_licitacion``, una columna que no existe en el esquema. La query
fallaba entera, el ``except`` devolvía ``MargenStats()`` vacías y el scoring
degradaba a neutro — en silencio, durante semanas. Ningún test lo detectó
porque todos mockeaban los loaders. Estos tests **ejecutan las queries**: con
solo llegar al final sin excepción y con datos, esa clase de bug muere.

Marcados ``integration`` automáticamente por la fixture ``tmp_db``
(``tests/conftest.py``): requieren Postgres y solo corren en CI.
"""

from __future__ import annotations

from typing import Any

import pytest

from services.analytics.scoring_signals import (
    _load_competencia_stats_raw,
    _load_importe_percentiles_raw,
    _load_margen_stats_raw,
    clear_scoring_signals_cache,
)

_EXTRACCION = "2026-06-01T00:00:00+00:00"
# Plazo deliberadamente lejano: los tests que llaman al loader real usan el
# reloj del sistema para el corte, y no deben empezar a fallar con el tiempo.
_VIVA = "2099-12-31T00:00:00+00:00"


@pytest.fixture(autouse=True)
def _sin_cache_de_senales():
    """Las señales cachean su snapshot; sin esto un test leería el del anterior."""
    clear_scoring_signals_cache()
    yield
    clear_scoring_signals_cache()


def _insert_licitacion(
    c: Any,
    id_externo: str,
    *,
    cpv: str | None = "72000000",
    importe: float | None = 100_000.0,
    estado: str | None = "ADM",
    fecha_limite: str | None = None,
    analysis_universe: str | None = "technology_observed",
) -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, cpv, importe, estado, "
        "fecha_limite, analysis_universe, fecha_extraccion) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            id_externo,
            f"Contrato {id_externo}",
            cpv,
            importe,
            estado,
            fecha_limite,
            analysis_universe,
            _EXTRACCION,
        ),
    )


def _insert_adjudicacion(
    c: Any,
    licitacion_id: str,
    *,
    importe_adjudicado: float = 80_000.0,
    n_ofertas: int | None = None,
    fecha_adjudicacion: str = "2026-05-01",
    lote_id: int | None = None,
) -> None:
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
        "n_ofertas_recibidas, fecha_adjudicacion, lote_id, fecha_extraccion) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            licitacion_id,
            f"Empresa de {licitacion_id}",
            importe_adjudicado,
            n_ofertas,
            fecha_adjudicacion,
            lote_id,
            _EXTRACCION,
        ),
    )


def _insert_lote(c: Any, licitacion_id: str, *, numero: str, importe: float) -> int:
    row = c.execute(
        "INSERT INTO lotes (licitacion_id, numero, importe, fecha_extraccion) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (licitacion_id, numero, importe, _EXTRACCION),
    ).fetchone()
    return int(row[0])


# ---------------------------------------------------------------------------
# Competencia
# ---------------------------------------------------------------------------


def test_competencia_agrega_ofertas_por_cpv4(tmp_db) -> None:
    """La media por CPV-4 sale de datos reales y la query llega hasta el final."""
    from db.database import connect

    with connect() as c:
        for i in range(3):
            _insert_licitacion(c, f"COMP-{i}", cpv=f"7200000{i}")
            _insert_adjudicacion(c, f"COMP-{i}", n_ofertas=3 + i)

    stats = _load_competencia_stats_raw()

    # 3 adjudicaciones con 3, 4 y 5 ofertas sobre el mismo CPV-4 → media 4.
    assert stats.media_por_cpv4["7200"] == pytest.approx(4.0)
    assert stats.media_global == pytest.approx(4.0)


def test_competencia_toma_el_maximo_por_licitacion_multilote(tmp_db) -> None:
    """Un expediente con varias adjudicaciones cuenta una vez, no una por lote."""
    from db.database import connect

    with connect() as c:
        for i in range(3):
            _insert_licitacion(c, f"MULTI-{i}")
        # MULTI-0 tiene tres adjudicaciones (multi-lote): sin el MAX por
        # licitación, sus 9 ofertas pesarían el triple en la media del CPV.
        _insert_adjudicacion(c, "MULTI-0", n_ofertas=9)
        _insert_adjudicacion(c, "MULTI-0", n_ofertas=2)
        _insert_adjudicacion(c, "MULTI-0", n_ofertas=1)
        _insert_adjudicacion(c, "MULTI-1", n_ofertas=3)
        _insert_adjudicacion(c, "MULTI-2", n_ofertas=3)

    stats = _load_competencia_stats_raw()

    assert stats.media_por_cpv4["7200"] == pytest.approx((9 + 3 + 3) / 3)


def test_competencia_exige_tres_licitaciones_por_segmento(tmp_db) -> None:
    """HAVING COUNT(*) >= 3: un CPV-4 con dos expedientes no publica media propia."""
    from db.database import connect

    with connect() as c:
        for i in range(2):
            _insert_licitacion(c, f"POCO-{i}", cpv="48000000")
            _insert_adjudicacion(c, f"POCO-{i}", n_ofertas=2)

    stats = _load_competencia_stats_raw()

    assert "4800" not in stats.media_por_cpv4
    # La global sí las cuenta: es el fallback cuando el segmento no da muestra.
    assert stats.media_global == pytest.approx(2.0)


def test_competencia_ignora_adjudicaciones_fuera_de_la_ventana(tmp_db) -> None:
    """La ventana de 24 meses de calendario acota qué historia entra."""
    from db.database import connect

    with connect() as c:
        for i in range(3):
            _insert_licitacion(c, f"VIEJA-{i}")
            _insert_adjudicacion(c, f"VIEJA-{i}", n_ofertas=8, fecha_adjudicacion="2019-01-01")

    stats = _load_competencia_stats_raw()

    assert stats.media_por_cpv4 == {}
    assert stats.media_global is None


def test_competencia_respeta_el_universo_analitico(tmp_db) -> None:
    """Las filas de otro analysis_universe no entran en la señal del radar."""
    from db.database import connect

    with connect() as c:
        for i in range(3):
            _insert_licitacion(c, f"OTRO-{i}", analysis_universe="watched_company_awards_observed")
            _insert_adjudicacion(c, f"OTRO-{i}", n_ofertas=5)

    stats = _load_competencia_stats_raw()

    assert stats.media_por_cpv4 == {}
    assert stats.media_global is None


# ---------------------------------------------------------------------------
# Margen
# ---------------------------------------------------------------------------


def test_margen_lee_las_predicciones_por_licitacion(tmp_db) -> None:
    """p50_por_licitacion sale de predicciones_baja, la fuente de primera opción."""
    from db.database import connect

    with connect() as c:
        _insert_licitacion(c, "PRED-1")
        c.execute(
            "INSERT INTO predicciones_baja (licitacion_id, p10, p50, p90, computed_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("PRED-1", 0.05, 0.18, 0.30, _EXTRACCION),
        )

    stats = _load_margen_stats_raw()

    assert stats.p50_por_licitacion["PRED-1"] == pytest.approx(0.18)


def test_margen_historico_por_cpv4_es_fraccion_no_porcentaje(tmp_db) -> None:
    """La baja media viaja en 0-1 porque el scoring la divide entre 0.40."""
    from db.database import connect

    with connect() as c:
        for i in range(3):
            _insert_licitacion(c, f"BAJA-{i}", importe=100_000.0)
            _insert_adjudicacion(c, f"BAJA-{i}", importe_adjudicado=75_000.0)

    stats = _load_margen_stats_raw()

    assert stats.baja_media_por_cpv4["7200"] == pytest.approx(0.25)
    assert stats.baja_media_global == pytest.approx(0.25)


def test_margen_usa_el_presupuesto_del_lote_no_el_del_expediente(tmp_db) -> None:
    """Con lotes, el denominador es el del lote: si no, la baja sale inflada.

    Expediente de 100.000 € en dos lotes de 50.000 €, cada uno adjudicado en
    40.000 €: la baja real es del 20%. Con ``l.importe`` de denominador saldría
    60%, y el scoring leería guerra de precios donde no la hay.
    """
    from db.database import connect

    with connect() as c:
        for i in range(3):
            lic = f"LOTE-{i}"
            _insert_licitacion(c, lic, importe=100_000.0)
            for numero in ("1", "2"):
                lote_id = _insert_lote(c, lic, numero=numero, importe=50_000.0)
                _insert_adjudicacion(c, lic, importe_adjudicado=40_000.0, lote_id=lote_id)

    stats = _load_margen_stats_raw()

    assert stats.baja_media_por_cpv4["7200"] == pytest.approx(0.20)


def test_margen_descarta_pares_presupuesto_adjudicado_imposibles(tmp_db) -> None:
    """VALID_PAIR_LOTE deja fuera un adjudicado que supera el presupuesto en +50%."""
    from db.database import connect

    with connect() as c:
        for i in range(3):
            _insert_licitacion(c, f"OUT-{i}", importe=100_000.0)
            _insert_adjudicacion(c, f"OUT-{i}", importe_adjudicado=90_000.0)
        _insert_licitacion(c, "OUT-X", importe=100_000.0)
        _insert_adjudicacion(c, "OUT-X", importe_adjudicado=400_000.0)

    stats = _load_margen_stats_raw()

    # Solo las tres válidas (10% de baja); el outlier no arrastra la media.
    assert stats.baja_media_por_cpv4["7200"] == pytest.approx(0.10)


def test_margen_sin_datos_devuelve_stats_vacias_sin_reventar(tmp_db) -> None:
    """BD sin historia: neutral y sin crash, que es el contrato con el scoring."""
    stats = _load_margen_stats_raw()

    assert stats.p50_por_licitacion == {}
    assert stats.baja_media_por_cpv4 == {}
    assert stats.baja_media_global is None


# ---------------------------------------------------------------------------
# Percentiles del universo puntuable
# ---------------------------------------------------------------------------


def test_percentiles_solo_cuentan_las_oportunidades_vivas(tmp_db) -> None:
    """La referencia de la dimensión importe es el mercado abierto de hoy.

    Las cerradas y las de plazo vencido no son oportunidades, así que sus
    importes no pueden mover los percentiles contra los que se normaliza.
    """
    from db.database import connect
    from db.repositories.aggregates import AggregateRepository

    with connect() as c:
        for i in range(60):
            _insert_licitacion(c, f"VIVA-{i:03d}", importe=1_000.0 * (i + 1), fecha_limite=_VIVA)
        # Ruido que el predicado debe excluir: adjudicada, vencida y sin plazo.
        _insert_licitacion(c, "CERRADA", importe=99_000_000.0, estado="ADJ", fecha_limite=_VIVA)
        _insert_licitacion(c, "VENCIDA", importe=99_000_000.0, fecha_limite="2020-01-01T00:00:00Z")
        _insert_licitacion(c, "SIN-PLAZO", importe=99_000_000.0, fecha_limite=None)

    p10, p90, n = AggregateRepository().importe_percentiles_universo(hoy_iso="2026-08-12")

    assert n == 60
    assert p90 < 99_000_000.0
    # percentile_cont interpola: 0.10 * (60-1) = 5.9 → entre 6.000 y 7.000.
    assert p10 == pytest.approx(6_900.0)


def test_percentiles_caen_al_global_si_el_universo_es_minusculo(tmp_db) -> None:
    """Con menos de 50 importes vivos, gana la distribución global estable."""
    from db.database import connect

    with connect() as c:
        _insert_licitacion(c, "UNA", importe=5_000.0, fecha_limite=_VIVA)
        for i in range(10):
            _insert_licitacion(c, f"HIST-{i}", importe=1_000.0 * (i + 1), fecha_limite=None)

    pct = _load_importe_percentiles_raw()

    assert pct.fuente == "global"
    assert pct.p90 > pct.p10
