"""El camino precalculado del overview cuenta lo mismo que el camino en vivo.

`/analytics/overview` y `/analytics/resumen/hoy` dejaron de agregar la tabla
entera en cada fallo de caché: los valores globales los deja el precálculo de
KPIs tras cada ingesta y las ventanas de horas se resuelven por índice. Eso solo
es aceptable si las dos ramas dan el mismo número, así que aquí se comparan
entre sí sobre el mismo corpus — nunca contra cifras escritas a mano, que se
quedarían obsoletas en cuanto cambie el seed.

El corpus incluye a propósito los casos que distinguen una rama de la otra: un
importe justo por debajo del P75, un expediente cerrado con importe alto, un
plazo ya vencido, fechas malformadas que el guard tiene que excluir, y una CCAA
en blanco (que `COUNT(DISTINCT)` sí cuenta y un selector de filtros no).
"""

from __future__ import annotations

import json

import pytest

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters

# Instantes de referencia: fijos, para que el resultado no dependa del reloj.
HOY_ISO = "2026-08-12T10:00:00+00:00"
LIMITE_48H_ISO = "2026-08-14T10:00:00+00:00"
HACE_24H_ISO = "2026-08-11T10:00:00+00:00"

# (id, estado, fecha_publicacion, fecha_limite, importe, ccaa)
_FILAS = (
    # Abierta, en plazo y por encima del P75: la única "caliente".
    ("SNAP-CALIENTE", "ADM", "2026-08-01", "2026-09-01", 1_000_000.0, "Madrid"),
    # Publicada y vence dentro de 48 h, pero su importe queda bajo el P75.
    (
        "SNAP-VENCE",
        "PUB",
        "2026-08-11T12:00:00+00:00",
        "2026-08-13T00:00:00+00:00",
        950_000.0,
        "Cataluña",
    ),
    # Abierta y en plazo, importe irrelevante.
    ("SNAP-BARATA", "PUB", "2026-08-01", "2026-09-01", 10.0, "Madrid"),
    # Importe alto pero adjudicada: el estado la deja fuera de "calientes".
    ("SNAP-CERRADA", "ADJ", "2026-08-01", "2026-09-01", 900_000.0, ""),
    # Plazo ya pasado.
    ("SNAP-VENCIDA", "PUB", "2026-07-01", "2026-08-01", 700_000.0, "Andalucía"),
    # Cerrada, pero "vencen_48h" cuenta por plazo y no por estado.
    ("SNAP-48H", "RES", "2026-08-01", "2026-08-13T09:00:00+00:00", 5.0, None),
    # Fechas fuera de rango: el _iso_guard tiene que descartarla pese al importe.
    ("SNAP-FECHA-MALA", "PUB", "0001-01-01", "9999-12-31", 999_999.0, "Madrid"),
    # Publicada en las últimas 24 h y sin plazo propio.
    ("SNAP-NUEVA", "PUB", "2026-08-11T18:00:00+00:00", None, 400_000.0, "Galicia"),
)


@pytest.fixture()
def snapshot_db(tmp_db):
    db_mod, _ = tmp_db
    with db_mod.connect() as conn:
        for id_externo, estado, pub, limite, importe, ccaa in _FILAS:
            conn.execute(
                "INSERT INTO licitaciones (id_externo, titulo, estado, fecha_publicacion, "
                "fecha_limite, fecha_extraccion, tecnologia, importe, ccaa, cpv, "
                "organo_contratacion) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    id_externo,
                    f"Licitación {id_externo}",
                    estado,
                    pub,
                    limite,
                    "2026-08-11T00:00:00+00:00",
                    "SAP",
                    importe,
                    ccaa,
                    "72000000",
                    "Ministerio",
                ),
            )
    return db_mod


# ---------------------------------------------------------------------------
# overview_para_hoy: rama rápida contra rama en vivo
# ---------------------------------------------------------------------------


def test_para_hoy_precalculado_cuenta_lo_mismo_que_en_vivo(snapshot_db):
    """Inyectar P75 y activas no cambia ninguno de los cuatro contadores.

    Es el invariante de la partición: se cambió el plan de ejecución —de un CTE
    materializado sobre 1,64 M filas a tres consultas por rango— y no la
    pregunta. El oráculo es la propia rama en vivo sobre el mismo corpus.
    """
    repo = AggregateRepository()
    sin_filtros = LicitacionesFilters()

    en_vivo = repo.overview_para_hoy(
        sin_filtros, hoy_iso=HOY_ISO, limite_48h_iso=LIMITE_48H_ISO, hace_24h_iso=HACE_24H_ISO
    )
    precalculado = repo.overview_para_hoy(
        sin_filtros,
        hoy_iso=HOY_ISO,
        limite_48h_iso=LIMITE_48H_ISO,
        hace_24h_iso=HACE_24H_ISO,
        p75=repo.importe_p75(),
        total_activas=repo.count_total_activas(),
    )

    assert precalculado == en_vivo
    # Que no sea todo cero: un corpus donde ambas ramas devuelven nada no
    # demostraría gran cosa.
    assert en_vivo["calientes_hoy"] == 1, (
        "solo SNAP-CALIENTE supera el P75 estando abierta y en plazo"
    )
    assert en_vivo["vencen_48h"] == 2
    assert en_vivo["nuevas_24h"] == 2
    assert en_vivo["total_activas"] == 6


def test_para_hoy_con_filtros_ignora_los_valores_precalculados(snapshot_db):
    """Con un filtro activo, el P75 global no aplica y se recalcula todo.

    Aplicarlo sería servir el umbral de la tabla entera a una pregunta sobre un
    subconjunto: el número saldría plausible y sería falso.
    """
    repo = AggregateRepository()
    filtrado = LicitacionesFilters(ccaa="Madrid")

    con_snapshot = repo.overview_para_hoy(
        filtrado,
        hoy_iso=HOY_ISO,
        limite_48h_iso=LIMITE_48H_ISO,
        hace_24h_iso=HACE_24H_ISO,
        p75=repo.importe_p75(),
        total_activas=repo.count_total_activas(),
    )
    en_vivo = repo.overview_para_hoy(
        filtrado, hoy_iso=HOY_ISO, limite_48h_iso=LIMITE_48H_ISO, hace_24h_iso=HACE_24H_ISO
    )

    assert con_snapshot == en_vivo
    assert con_snapshot["total_activas"] == 3, "Madrid tiene tres abiertas, no las seis globales"


def test_para_hoy_sin_p75_no_toma_el_atajo(snapshot_db):
    """Un corpus sin importes deja el P75 en None y la rama rápida no aplica."""
    repo = AggregateRepository()
    with snapshot_db.connect() as conn:
        conn.execute("UPDATE licitaciones SET importe = NULL")

    assert repo.importe_p75() is None
    resultado = repo.overview_para_hoy(
        LicitacionesFilters(),
        hoy_iso=HOY_ISO,
        limite_48h_iso=LIMITE_48H_ISO,
        hace_24h_iso=HACE_24H_ISO,
        p75=repo.importe_p75(),
        total_activas=repo.count_total_activas(),
    )
    assert resultado["calientes_hoy"] == 0


# ---------------------------------------------------------------------------
# loose index scan
# ---------------------------------------------------------------------------


def test_ccaa_cubiertas_equivale_a_count_distinct(snapshot_db):
    """El salto por el btree cuenta lo mismo que COUNT(DISTINCT), con '' incluida.

    La cadena vacía es justo donde las dos semillas del loose scan divergen:
    ``COUNT(DISTINCT)`` solo ignora NULL, así que ``SNAP-CERRADA`` con
    ``ccaa = ''`` cuenta como un valor más. Arrancar en ``ccaa > ''`` —lo que
    hace la variante que alimenta los selectores de filtro— devolvería uno
    menos.
    """
    repo = AggregateRepository()
    with snapshot_db.connect() as conn:
        esperado = conn.execute("SELECT COUNT(DISTINCT ccaa) FROM licitaciones").fetchone()[0]

    assert repo.overview_ccaa_cubiertas(LicitacionesFilters()) == esperado
    assert esperado == 5, "Madrid, Cataluña, Andalucía, Galicia y la cadena vacía"


def test_filtros_excluyen_la_ccaa_vacia(snapshot_db):
    """El selector de filtros no ofrece la cadena vacía como opción."""
    from db.repositories.licitaciones import LicitacionRepository

    opciones = LicitacionRepository().get_filter_options()

    assert opciones["ccaa"] == ["Andalucía", "Cataluña", "Galicia", "Madrid"]
    assert "" not in opciones["ccaa"]


def test_get_filter_options_usa_los_cpv_inyectados(snapshot_db):
    """La lista de CPV precalculada sustituye al cálculo, sin tocar las otras."""
    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    en_vivo = repo.get_filter_options()
    inyectado = repo.get_filter_options(cpv_values=["11111111", "22222222"])

    assert en_vivo["cpv"] == ["72000000"]
    assert inyectado["cpv"] == ["11111111", "22222222"]
    assert inyectado["ccaa"] == en_vivo["ccaa"]


# ---------------------------------------------------------------------------
# Ida y vuelta por kpi_snapshots
# ---------------------------------------------------------------------------


def test_snapshot_persistido_coincide_con_el_calculo_en_vivo(snapshot_db):
    """Tras el precálculo, lo leído es lo mismo que devuelve el repository."""
    from db.repositories.kpi_snapshots import read_meta_cpv, read_overview_snapshot
    from scheduler.kpi_precompute import run_kpi_precompute

    run_kpi_precompute()

    repo = AggregateRepository()
    snap = read_overview_snapshot()

    assert snap is not None
    assert snap.kpis == repo.overview_kpis(LicitacionesFilters())
    assert snap.importe_p75 == repo.importe_p75()
    assert snap.total_activas == repo.count_total_activas()
    assert snap.adj_indicadores == repo.overview_adjudicaciones_indicadores()
    assert read_meta_cpv() == ["72000000"]


def test_snapshot_caducado_se_ignora(snapshot_db):
    """Pasado el umbral de frescura se vuelve al cálculo en vivo.

    Servir cifras de anteayer como si fueran de hoy es peor que tardar: el
    consumidor tiene que poder distinguir "no hay snapshot" de "hay uno viejo".
    """
    from db.repositories.kpi_snapshots import read_overview_snapshot
    from scheduler.kpi_precompute import run_kpi_precompute

    run_kpi_precompute()
    with snapshot_db.connect() as conn:
        conn.execute("UPDATE kpi_snapshots SET computed_at = %s", ("2020-01-01T00:00:00+00:00",))

    assert read_overview_snapshot() is None
    assert read_overview_snapshot(max_age_seconds=10**9) is not None


def test_snapshot_incompleto_se_ignora(snapshot_db):
    """Si falta una métrica no se sirve un snapshot a medias."""
    from db.repositories.kpi_snapshots import OV_IMPORTE_P75, read_overview_snapshot
    from scheduler.kpi_precompute import run_kpi_precompute

    run_kpi_precompute()
    with snapshot_db.connect() as conn:
        conn.execute("DELETE FROM kpi_snapshots WHERE metrica = %s", (OV_IMPORTE_P75,))

    assert read_overview_snapshot() is None


def test_snapshot_con_json_corrupto_degrada_esa_pieza(snapshot_db):
    """Un JSON ilegible anula su métrica, no el snapshot entero ni el endpoint."""
    from db.repositories.kpi_snapshots import OV_KPIS, read_overview_snapshot
    from scheduler.kpi_precompute import run_kpi_precompute

    run_kpi_precompute()
    with snapshot_db.connect() as conn:
        conn.execute(
            "UPDATE kpi_snapshots SET valor_text = %s WHERE metrica = %s",
            ("{esto no es json", OV_KPIS),
        )

    snap = read_overview_snapshot()
    assert snap is not None
    assert snap.kpis is None
    assert snap.importe_p75 is not None, "las demás métricas siguen siendo utilizables"


def test_snapshot_al_que_le_faltan_claves_se_descarta(snapshot_db):
    """Un JSON válido pero incompleto tampoco vale: el servicio haría KeyError."""
    from db.repositories.kpi_snapshots import OV_KPIS, read_overview_snapshot
    from scheduler.kpi_precompute import run_kpi_precompute

    run_kpi_precompute()
    with snapshot_db.connect() as conn:
        conn.execute(
            "UPDATE kpi_snapshots SET valor_text = %s WHERE metrica = %s",
            (json.dumps({"total": 1}), OV_KPIS),
        )

    snap = read_overview_snapshot()
    assert snap is not None
    assert snap.kpis is None


def test_snapshot_no_aplica_con_filtros(snapshot_db):
    """`read_overview_snapshot_for` solo devuelve algo si la pregunta es global."""
    from db.repositories.kpi_snapshots import read_overview_snapshot_for
    from scheduler.kpi_precompute import run_kpi_precompute

    run_kpi_precompute()

    assert read_overview_snapshot_for(LicitacionesFilters()) is not None
    assert read_overview_snapshot_for(LicitacionesFilters(ccaa="Madrid")) is None


def test_overview_da_el_mismo_resultado_con_y_sin_snapshot(snapshot_db):
    """El endpoint completo no cambia de respuesta por leer el precálculo."""
    from services.analytics.overview import OverviewFilters, get_overview

    sin_snapshot = get_overview(OverviewFilters())

    from scheduler.kpi_precompute import run_kpi_precompute

    run_kpi_precompute()
    con_snapshot = get_overview(OverviewFilters())

    assert con_snapshot.model_dump() == sin_snapshot.model_dump()
