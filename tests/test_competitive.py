"""Tests para services/competitive (renovaciones, bajas, mercado) y watchlist de empresas."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

# ---------------------------------------------------------------------------
# Fixtures y helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _date(days_from_now: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days_from_now)).strftime("%Y-%m-%d")


def insert_contract(
    db,
    lic_id: str,
    empresa: str,
    *,
    nif: str | None = None,
    importe: float = 100000.0,
    adjudicado: float = 80000.0,
    fecha_fin: str | None = None,
    fecha_inicio: str | None = None,
    duracion_valor: float | None = None,
    duracion_unidad: str | None = None,
    fecha_adjudicacion: str = "2025-06-01",
    cpv: str = "72000000",
    ccaa: str = "Madrid",
    organo: str = "Ministerio X",
    n_ofertas: int = 4,
    tecnologia: str | None = None,
    analysis_universe: str | None = None,
):
    """Inserta licitación + adjudicación y resuelve la empresa contra el maestro."""
    from db.upsert import (
        Adjudicacion,
        Licitacion,
        replace_adjudicaciones_batch,
        upsert_licitaciones,
    )

    lic = Licitacion(
        id_externo=lic_id,
        titulo=f"Contrato {lic_id}",
        organo_contratacion=organo,
        importe=importe,
        cpv=cpv,
        ccaa=ccaa,
        fecha_publicacion="2025-05-01",
        fecha_fin=fecha_fin,
        fecha_inicio=fecha_inicio,
        duracion_valor=duracion_valor,
        duracion_unidad=duracion_unidad,
        tecnologia=tecnologia,
        analysis_universe=analysis_universe,
    )
    upsert_licitaciones([lic])
    adj = Adjudicacion(
        licitacion_id=lic_id,
        nombre=empresa,
        nif=nif,
        importe_adjudicado=adjudicado,
        fecha_adjudicacion=fecha_adjudicacion,
        n_ofertas_recibidas=n_ofertas,
        ccaa=ccaa,
    )
    _total, _dropped, failed = replace_adjudicaciones_batch({lic_id: [adj]})
    assert failed == 0


def resolve(db):
    from services.entity_resolution import resolve_all_unlinked

    return resolve_all_unlinked()


def test_market_aggregates_exclude_watched_company_awards_universe(db):
    """El namespace de observación NIF no duplica el corpus tecnológico."""
    from services.competitive.bajas import bajas_agregadas
    from services.competitive.mercado import (
        cuota_mercado,
        listar_adjudicaciones_empresa,
        metric_scope,
    )

    insert_contract(db, "TECH-ONE", "Tecnológica S.L.", adjudicado=100.0)
    insert_contract(
        db,
        "WATCHED-ONE",
        "Empresa vigilada S.L.",
        adjudicado=900.0,
        analysis_universe="watched_company_awards_observed",
    )
    resolve(db)

    scope = metric_scope()
    ranking = cuota_mercado()
    bajas = bajas_agregadas(min_contratos=1)

    assert scope.denominator_records == 1
    assert scope.denominator_amount_eur == 100.0
    assert len(ranking) == 1
    assert ranking[0]["empresa"] != "Empresa vigilada S.L."
    assert bajas[0]["contratos"] == 1

    with db.connect_read() as c:
        watched_empresa_id = c.execute(
            "SELECT empresa_id FROM adjudicaciones WHERE licitacion_id = 'WATCHED-ONE'"
        ).fetchone()[0]
    watched_rows = listar_adjudicaciones_empresa(
        watched_empresa_id,
        analysis_universe="watched_company_awards_observed",
    )
    assert watched_rows["total"] == 1
    assert watched_rows["items"][0]["licitacion_id"] == "WATCHED-ONE"


# ---------------------------------------------------------------------------
# Renovaciones — fecha de fin efectiva por las tres vías
# ---------------------------------------------------------------------------


def test_renovacion_por_fecha_fin_explicita(db):
    from services.competitive.renovaciones import proximas_renovaciones

    insert_contract(db, "R-001", "Acme S.L.", fecha_fin=_date(60))
    resolve(db)

    items = proximas_renovaciones(months_ahead=6)
    assert len(items) == 1
    assert items[0]["fecha_fin_efectiva"] == _date(60)
    assert 55 <= items[0]["dias_restantes"] <= 60


def test_renovacion_por_fecha_inicio_mas_duracion(db):
    from services.competitive.renovaciones import proximas_renovaciones

    # Empezó hace ~10 meses con duración 12 meses → vence en ~2 meses
    inicio = _date(-300)
    insert_contract(
        db,
        "R-002",
        "Beta Consulting",
        fecha_inicio=inicio,
        duracion_valor=12.0,
        duracion_unidad="MON",
    )
    resolve(db)

    items = proximas_renovaciones(months_ahead=6)
    assert len(items) == 1
    assert items[0]["licitacion_id"] == "R-002"


def test_renovacion_por_fecha_adjudicacion_mas_duracion_ann(db):
    from services.competitive.renovaciones import proximas_renovaciones

    # Adjudicado hace ~11 meses, duración 1 año → vence en ~1 mes
    adj_date = _date(-335)
    insert_contract(
        db,
        "R-003",
        "Gamma Corp",
        fecha_adjudicacion=adj_date,
        duracion_valor=1.0,
        duracion_unidad="ANN",
    )
    resolve(db)

    items = proximas_renovaciones(months_ahead=3)
    assert len(items) == 1
    assert items[0]["licitacion_id"] == "R-003"


def test_renovacion_fuera_de_ventana_no_aparece(db):
    from services.competitive.renovaciones import proximas_renovaciones

    insert_contract(db, "R-004", "Delta SA", fecha_fin=_date(400))  # > 6 meses
    insert_contract(db, "R-005", "Epsilon SL", fecha_fin=_date(-10))  # ya vencido
    resolve(db)

    assert proximas_renovaciones(months_ahead=6) == []


def test_renovaciones_filtro_por_empresa(db):
    from db.database import connect_read
    from services.competitive.renovaciones import proximas_renovaciones

    insert_contract(db, "R-006", "Zeta Solutions", nif="B11111111", fecha_fin=_date(30))
    insert_contract(db, "R-007", "Omega Digital", nif="B22222222", fecha_fin=_date(30))
    resolve(db)

    with connect_read() as c:
        zeta_id = c.execute(
            "SELECT empresa_id FROM empresas WHERE nif_canonico = 'B11111111'"
        ).fetchone()[0]
    items = proximas_renovaciones(months_ahead=2, empresa_id=zeta_id)
    assert len(items) == 1
    assert items[0]["empresa"] == "Zeta Solutions"


def test_renovaciones_filtro_por_tecnologia(db):
    from services.competitive.renovaciones import (
        proximas_renovaciones,
        resumen_renovaciones,
    )

    insert_contract(db, "R-T01", "Sap Partner SL", fecha_fin=_date(30), tecnologia="SAP")
    insert_contract(db, "R-T02", "Sf Partner SL", fecha_fin=_date(30), tecnologia="SALESFORCE")
    resolve(db)

    # Sin filtro: ambos contratos.
    assert len(proximas_renovaciones(months_ahead=3)) == 2

    # Filtro por una tecnología.
    solo_sap = proximas_renovaciones(months_ahead=3, tecnologias=["SAP"])
    assert len(solo_sap) == 1
    assert solo_sap[0]["licitacion_id"] == "R-T01"

    # Filtro multi-valor (IN) devuelve ambos.
    ambas = proximas_renovaciones(months_ahead=3, tecnologias=["SAP", "SALESFORCE"])
    assert len(ambas) == 2

    # Lista vacía / None se ignora (equivale a sin filtro).
    assert len(proximas_renovaciones(months_ahead=3, tecnologias=[])) == 2

    # El resumen agregado respeta el mismo filtro.
    resumen_sap = resumen_renovaciones(months_ahead=3, tecnologias=["SAP"])
    assert len(resumen_sap) == 1
    assert resumen_sap[0]["empresa"] == "Sap Partner SL"


def test_perfil_empresa_por_ccaa_es_por_empresa_y_completo(db):
    """perfil_empresa.por_ccaa cubre TODAS las CCAA de la empresa.

    El drill-down de Competidores consume este desglose por empresa; antes el
    frontend lo derivaba de un heatmap global recortado al top-10 empresas, así
    que salía vacío para cualquier empresa fuera de ese top (ADR-014).
    """
    from db.database import connect_read
    from services.competitive.mercado import perfil_empresa

    # Una empresa (mismo NIF) con adjudicaciones en 3 CCAA distintas.
    insert_contract(db, "P-1", "Solo SL", nif="B99999999", ccaa="Madrid")
    insert_contract(db, "P-2", "Solo SL", nif="B99999999", ccaa="Madrid")
    insert_contract(db, "P-3", "Solo SL", nif="B99999999", ccaa="Cataluña")
    insert_contract(db, "P-4", "Solo SL", nif="B99999999", ccaa="Galicia")
    resolve(db)

    with connect_read() as c:
        empresa_id = c.execute(
            "SELECT empresa_id FROM empresas WHERE nif_canonico = 'B99999999'"
        ).fetchone()[0]

    perfil = perfil_empresa(empresa_id)
    por_ccaa = {r["ccaa"]: r["contratos"] for r in perfil["por_ccaa"]}
    assert por_ccaa == {"Madrid": 2, "Cataluña": 1, "Galicia": 1}
    assert perfil["totales"]["contratos"] == 4


def test_perfil_empresa_por_anio_traza_la_trayectoria(db):
    """perfil_empresa.por_anio da la serie temporal (creciendo/declinando)."""
    from db.database import connect_read
    from services.competitive.mercado import perfil_empresa

    # 1 contrato en 2023, 3 en 2024 → trayectoria al alza.
    insert_contract(db, "A-1", "Trend SL", nif="B12121212", fecha_adjudicacion="2023-04-01")
    for i in range(3):
        insert_contract(db, f"A-2{i}", "Trend SL", nif="B12121212", fecha_adjudicacion="2024-07-01")
    resolve(db)

    with connect_read() as c:
        empresa_id = c.execute(
            "SELECT empresa_id FROM empresas WHERE nif_canonico = 'B12121212'"
        ).fetchone()[0]

    perfil = perfil_empresa(empresa_id)
    serie = [(r["anio"], r["contratos"]) for r in perfil["por_anio"]]
    assert serie == [(2023, 1), (2024, 3)]  # orden cronológico, sin años nulos


def test_resumen_renovaciones_agrega_por_empresa(db):
    from services.competitive.renovaciones import resumen_renovaciones

    insert_contract(
        db, "R-008", "Acme S.L.", nif="B33333333", fecha_fin=_date(30), adjudicado=50000
    )
    insert_contract(db, "R-009", "ACME SL", nif="B33333333", fecha_fin=_date(60), adjudicado=70000)
    resolve(db)

    items = resumen_renovaciones(months_ahead=6)
    assert len(items) == 1  # mismo NIF → misma empresa canónica
    assert items[0]["contratos_venciendo"] == 2
    assert items[0]["importe_en_juego"] == 120000


def test_totales_renovaciones_suma_sobre_todas_las_empresas(db):
    """totales_renovaciones — mismos filtros que resumen_renovaciones pero sin
    GROUP BY: usado por el banner de Pipeline & Alertas (server-side, ADR-014)."""
    from services.competitive.renovaciones import totales_renovaciones

    insert_contract(
        db, "R-T10", "Acme S.L.", nif="B44444444", fecha_fin=_date(30), adjudicado=50000
    )
    insert_contract(
        db, "R-T11", "Beta S.L.", nif="B55555555", fecha_fin=_date(60), adjudicado=70000
    )
    resolve(db)

    totales = totales_renovaciones(months_ahead=6)
    assert totales["contratos_venciendo"] == 2
    assert totales["importe_en_juego"] == 120000


def test_totales_renovaciones_filtro_por_tecnologia(db):
    from services.competitive.renovaciones import totales_renovaciones

    insert_contract(db, "R-T12", "Sap Partner SL", fecha_fin=_date(30), tecnologia="SAP")
    insert_contract(db, "R-T13", "Sf Partner SL", fecha_fin=_date(30), tecnologia="SALESFORCE")
    resolve(db)

    todos = totales_renovaciones(months_ahead=3)
    assert todos["contratos_venciendo"] == 2

    solo_sap = totales_renovaciones(months_ahead=3, tecnologias=["SAP"])
    assert solo_sap["contratos_venciendo"] == 1


def test_totales_renovaciones_dataset_vacio(db):
    from services.competitive.renovaciones import totales_renovaciones

    totales = totales_renovaciones(months_ahead=6)
    assert totales["contratos_venciendo"] == 0
    assert totales["importe_en_juego"] == 0


# ---------------------------------------------------------------------------
# Bajas
# ---------------------------------------------------------------------------


def test_bajas_agregadas_por_empresa(db):
    from services.competitive.bajas import bajas_agregadas

    # 3 contratos con baja del 20% cada uno
    for i in range(3):
        insert_contract(
            db,
            f"B-{i}",
            "Lowball SL",
            nif="B44444444",
            importe=100000,
            adjudicado=80000,
        )
    resolve(db)

    items = bajas_agregadas(group_by="empresa", min_contratos=3)
    assert len(items) == 1
    assert items[0]["baja_media_pct"] == 20.0
    assert items[0]["contratos"] == 3


def test_bajas_descarta_outliers_e_invalidos(db):
    from services.competitive.bajas import bajas_agregadas

    insert_contract(db, "B-10", "Weird SL", importe=100000, adjudicado=200000)  # adj > 1.5x
    insert_contract(db, "B-11", "Weird SL", importe=0, adjudicado=50000)  # sin presupuesto
    resolve(db)

    assert bajas_agregadas(group_by="empresa", min_contratos=1) == []


def test_baja_de_referencia_por_organo(db):
    from services.competitive.bajas import baja_de_referencia

    insert_contract(db, "B-20", "Empresa A", organo="Ayto Madrid", importe=100000, adjudicado=90000)
    insert_contract(db, "B-21", "Empresa B", organo="Ayto Madrid", importe=100000, adjudicado=70000)
    insert_contract(db, "B-22", "Empresa C", organo="Otro Organo", importe=100000, adjudicado=50000)
    resolve(db)

    ref = baja_de_referencia(organo="Ayto Madrid")
    assert ref["contratos"] == 2
    assert ref["baja_media_pct"] == 20.0  # (10 + 30) / 2


def test_bajas_group_by_invalido(db):
    from services.competitive.bajas import bajas_agregadas

    with pytest.raises(ValueError):
        bajas_agregadas(group_by="'; DROP TABLE--")


# ---------------------------------------------------------------------------
# Bajas: presupuesto efectivo del lote (v65_lotes)
# ---------------------------------------------------------------------------


def _insert_lote_contract(
    db,
    lic_id: str,
    empresa: str,
    *,
    importe_expediente: float,
    importe_lote: float,
    adjudicado: float,
):
    """Como insert_contract, pero la adjudicación referencia un lote propio
    cuyo presupuesto es distinto (menor) que el del expediente completo."""
    from db.upsert import (
        Adjudicacion,
        Licitacion,
        Lote,
        replace_adjudicaciones_batch,
        replace_lotes,
    )
    from db.upsert import upsert_licitaciones as _upsert_licitaciones

    lic = Licitacion(
        id_externo=lic_id,
        titulo=f"Contrato {lic_id}",
        organo_contratacion="Ministerio X",
        importe=importe_expediente,
        cpv="72000000",
        ccaa="Madrid",
        fecha_publicacion="2025-05-01",
    )
    _upsert_licitaciones([lic])
    lote_ids = replace_lotes(lic_id, [Lote(licitacion_id=lic_id, numero="1", importe=importe_lote)])
    adj = Adjudicacion(
        licitacion_id=lic_id,
        nombre=empresa,
        importe_adjudicado=adjudicado,
        fecha_adjudicacion="2025-06-01",
        n_ofertas_recibidas=3,
        lote_id=lote_ids["1"],
    )
    _total, _dropped, failed = replace_adjudicaciones_batch({lic_id: [adj]})
    assert failed == 0


def test_bajas_usa_presupuesto_del_lote_no_del_expediente(db):
    """Regresión directa: antes de v65_lotes esto daba 85% (contra los
    100000 del expediente) en vez del 25% real (contra los 20000 del lote)."""
    from services.competitive.bajas import bajas_agregadas

    _insert_lote_contract(
        db, "LB-01", "Lotera SL", importe_expediente=100_000, importe_lote=20_000, adjudicado=15_000
    )
    resolve(db)

    items = bajas_agregadas(group_by="empresa", min_contratos=1)
    assert len(items) == 1
    assert items[0]["baja_media_pct"] == 25.0


def test_baja_de_referencia_usa_presupuesto_del_lote(db):
    from services.competitive.bajas import baja_de_referencia

    _insert_lote_contract(
        db, "LB-02", "Lotera SL", importe_expediente=100_000, importe_lote=20_000, adjudicado=15_000
    )
    resolve(db)

    ref = baja_de_referencia()
    assert ref["contratos"] == 1
    assert ref["baja_media_pct"] == 25.0


def test_bajas_sin_lote_sigue_usando_presupuesto_del_expediente(db):
    """Compatibilidad: una adjudicación sin lote_id (el caso de siempre) no
    cambia de comportamiento."""
    from services.competitive.bajas import bajas_agregadas

    insert_contract(db, "LB-03", "Sin Lote SL", importe=100_000, adjudicado=80_000)
    resolve(db)

    items = bajas_agregadas(group_by="empresa", min_contratos=1)
    assert len(items) == 1
    assert items[0]["baja_media_pct"] == 20.0


# ---------------------------------------------------------------------------
# Mercado: cuota y HHI
# ---------------------------------------------------------------------------


def test_cuota_mercado_suma_100(db):
    from services.competitive.mercado import cuota_mercado

    insert_contract(db, "M-01", "Big Corp", nif="B55555555", adjudicado=750000)
    insert_contract(db, "M-02", "Small SL", nif="B66666666", adjudicado=250000)
    resolve(db)

    items = cuota_mercado()
    assert len(items) == 2
    assert items[0]["empresa"] == "Big Corp"
    assert items[0]["cuota_pct"] == 75.0
    assert sum(i["cuota_pct"] for i in items) == 100.0


def test_perfil_empresa_dossier_filtrado_y_posicion(db):
    from db.database import connect_read
    from services.competitive.mercado import perfil_empresa
    from shared.dto import CompetitiveCompanyProfileDTO

    insert_contract(
        db,
        "M-DOSSIER-PREV",
        "Dossier Alpha SL",
        nif="B12340001",
        adjudicado=100000,
        fecha_adjudicacion=_date(-500),
        ccaa="Madrid",
        organo="Ministerio A",
    )
    insert_contract(
        db,
        "M-DOSSIER-1",
        "Dossier Alpha SL",
        nif="B12340001",
        adjudicado=100000,
        fecha_adjudicacion=_date(-60),
        ccaa="Madrid",
        organo="Ministerio A",
        n_ofertas=1,
    )
    insert_contract(
        db,
        "M-DOSSIER-2",
        "Dossier Alpha SL",
        nif="B12340001",
        adjudicado=200000,
        fecha_adjudicacion=_date(-30),
        ccaa="Galicia",
        organo="Xunta de Galicia",
        n_ofertas=3,
    )
    insert_contract(
        db,
        "M-DOSSIER-RIVAL",
        "Dossier Beta SA",
        nif="B12340002",
        adjudicado=400000,
        fecha_adjudicacion=_date(-20),
    )
    resolve(db)

    with connect_read() as c:
        empresa_id = int(
            c.execute(
                "SELECT empresa_id FROM empresas WHERE nif_canonico = 'B12340001'"
            ).fetchone()[0]
        )

    profile = perfil_empresa(
        empresa_id,
        fecha_desde=date.today() - timedelta(days=364),
        fecha_hasta=date.today(),
    )

    assert profile["_exists"] is True
    assert profile["actividad_historica"]["contratos"] == 3
    assert profile["actividad_historica"]["importe_total"] == 400000
    assert profile["totales"]["contratos"] == 2
    assert profile["totales"]["importe_total"] == 300000
    assert profile["totales"]["importe_mediano"] == 150000
    assert profile["totales"]["cobertura_ofertas_pct"] == 100
    assert profile["posicion_mercado"]["rank"] == 2
    assert profile["posicion_mercado"]["empresas"] == 2
    assert profile["por_ccaa"][0]["label"] == "Galicia"
    assert any(item["kind"] == "territory" for item in profile["movimientos"])
    CompetitiveCompanyProfileDTO.model_validate(
        {key: value for key, value in profile.items() if not key.startswith("_")}
    )


def test_listar_adjudicaciones_empresa_filtra_ordena_y_pagina(db):
    from db.database import connect_read
    from services.competitive.mercado import listar_adjudicaciones_empresa

    for suffix, amount in (("A", 10000), ("B", 30000), ("C", 20000)):
        insert_contract(
            db,
            f"M-LIST-{suffix}",
            "Listado Profile SL",
            nif="B12340003",
            adjudicado=amount,
            fecha_adjudicacion=_date(-10),
        )
    resolve(db)
    with connect_read() as c:
        empresa_id = int(
            c.execute(
                "SELECT empresa_id FROM empresas WHERE nif_canonico = 'B12340003'"
            ).fetchone()[0]
        )

    page = listar_adjudicaciones_empresa(empresa_id, sort="importe_desc", limit=2)
    assert page["total"] == 3
    assert [item["licitacion_id"] for item in page["items"]] == ["M-LIST-B", "M-LIST-C"]
    filtered = listar_adjudicaciones_empresa(empresa_id, q="M-LIST-A")
    assert filtered["total"] == 1
    assert filtered["items"][0]["presupuesto_licitacion"] == 100000


def test_hhi_monopolio_es_10000(db):
    from services.competitive.mercado import concentracion_hhi

    for i in range(5):
        insert_contract(db, f"M-1{i}", "Monopolist SA", nif="B77777777", cpv="48000000")
    resolve(db)

    items = concentracion_hhi(segment_by="cpv", min_contratos=5)
    assert len(items) == 1
    assert items[0]["segmento"] == "48"
    assert items[0]["hhi"] == 10000


def test_perfil_empresa(db):
    from db.database import connect_read
    from services.competitive.mercado import perfil_empresa

    insert_contract(
        db,
        "M-20",
        "Profiled SL",
        nif="B88888888",
        cpv="72000000",
        ccaa="Madrid",
        fecha_adjudicacion="2025-01-01",
    )
    insert_contract(
        db,
        "M-21",
        "Profiled SL",
        nif="B88888888",
        cpv="48000000",
        ccaa="Cataluña",
        fecha_adjudicacion="2025-03-01",
    )
    resolve(db)

    with connect_read() as c:
        empresa_id = c.execute(
            "SELECT empresa_id FROM empresas WHERE nif_canonico = 'B88888888'"
        ).fetchone()[0]
    perfil = perfil_empresa(empresa_id)
    assert perfil["totales"]["contratos"] == 2
    assert len(perfil["por_cpv"]) == 2
    assert len(perfil["por_ccaa"]) == 2
    assert len(perfil["contratos_recientes"]) == 2
    assert perfil["contratos_recientes"][0]["licitacion_id"] == "M-21"


def test_perfil_empresa_incluye_participaciones_ute_sin_duplicar_totales(db):
    """Corrección del diagnóstico original de UTE (docs/IMPROVEMENT_BACKLOG.md):
    CODICE publica la UTE como un único WinningParty con nombre compuesto, y
    entity_resolution.py ya crea una empresa UTE propia (es_ute=1) con sus
    miembros en ute_miembros -- el dinero NO se cuenta dos veces. El gap real
    era que el dossier de un miembro no mostraba esa participación en
    absoluto. Este test fija ambas mitades: los 180k de la UTE no entran en
    los totales propios de Alfa (ya se cuentan bajo la UTE en
    cuota_mercado()), pero sí aparecen en participaciones_ute."""
    from db.database import connect_read
    from services.competitive.mercado import perfil_empresa

    insert_contract(
        db, "UTE-01", "UTE Empresa Alfa - Empresa Beta", importe=200_000, adjudicado=180_000
    )
    insert_contract(db, "SOLO-01", "Empresa Alfa", importe=100_000, adjudicado=90_000)
    resolve(db)

    with connect_read() as c:
        alfa_id = c.execute(
            "SELECT empresa_id FROM empresas WHERE nombre_canonico = 'EMPRESA ALFA'"
        ).fetchone()[0]

    perfil = perfil_empresa(alfa_id)

    assert perfil["totales"]["contratos"] == 1
    assert perfil["totales"]["importe_total"] == pytest.approx(90_000.0)

    assert len(perfil["participaciones_ute"]) == 1
    participacion = perfil["participaciones_ute"][0]
    assert participacion["contratos"] == 1
    assert participacion["importe_total"] == pytest.approx(180_000.0)
    assert any("BETA" in m.upper() for m in participacion["otros_miembros"])


def test_perfil_empresa_sin_ute_devuelve_lista_vacia(db):
    from db.database import connect_read
    from services.competitive.mercado import perfil_empresa

    insert_contract(db, "SOLO-02", "Empresa Gamma", nif="B77777777", importe=50_000)
    resolve(db)

    with connect_read() as c:
        gamma_id = c.execute(
            "SELECT empresa_id FROM empresas WHERE nif_canonico = 'B77777777'"
        ).fetchone()[0]

    perfil = perfil_empresa(gamma_id)
    assert perfil["participaciones_ute"] == []


# ---------------------------------------------------------------------------
# Watchlist de empresas + alertas
# ---------------------------------------------------------------------------


def _watched_empresa(db, nombre="Watched SL", nif="B99999999"):
    from db.database import connect_read

    insert_contract(db, "W-01", nombre, nif=nif)
    resolve(db)
    with connect_read() as c:
        return int(
            c.execute("SELECT empresa_id FROM empresas WHERE nif_canonico = %s", (nif,)).fetchone()[
                0
            ]
        )


def _organizacion_de_pruebas(nombre: str) -> int:
    """Crea una organización real (con su owner) y devuelve su id.

    ``watchlist_empresas.organization_id`` es FK contra ``organizations``
    (v64), así que un id inventado revienta el INSERT con
    ``ForeignKeyViolation`` antes de ejercitar nada del CRUD.
    """
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    owner = create_user(
        email=f"{nombre}@example.test",
        password_hash="test-hash",  # pragma: allowlist secret -- literal de test
        display_name=nombre,
    )
    return int(OrganizationRepository().create_organization(nombre, owner)["id"])


def test_watchlist_crud(db):
    """CRUD de la vigilancia de competidores, con la organización obligatoria.

    ``WatchlistEmpresaEntry.organization_id`` perdió su default ``None``
    (S4.3): construir una entrada sin ámbito escribía una fila que la consulta
    con ámbito no volvía a ver — la empresa quedaba vigilada y ausente de la
    pantalla a la vez. Además del roundtrip, el test comprueba que la
    organización es condición necesaria tanto para listar como para borrar.
    """
    from db.watchlist_empresas import WatchlistEmpresaEntry, add_entry, list_entries, remove_entry

    empresa_id = _watched_empresa(db)
    equipo = _organizacion_de_pruebas("competidores-equipo")
    otro_equipo = _organizacion_de_pruebas("competidores-otro-equipo")
    entry = WatchlistEmpresaEntry(
        user_key="u1",
        empresa_id=empresa_id,
        organization_id=equipo,
        email="a@b.com",
    )

    assert add_entry(entry) is not None
    assert add_entry(entry) is None  # duplicado → no-op
    assert len(list_entries("u1", equipo)) == 1
    assert list_entries("u1", equipo)[0]["nombre_canonico"] == "Watched SL"

    # La entrada no se ve ni se borra desde otra organización.
    assert list_entries("u1", otro_equipo) == []
    assert remove_entry("u1", empresa_id, otro_equipo) is False
    assert len(list_entries("u1", equipo)) == 1

    # Ni desde la propia organización si el que borra no es el dueño.
    assert remove_entry("otro-usuario", empresa_id, equipo) is False
    assert len(list_entries("u1", equipo)) == 1

    assert remove_entry("u1", empresa_id, equipo) is True
    assert remove_entry("u1", empresa_id, equipo) is False
    assert list_entries("u1", equipo) == []


def test_competitor_alerts_detecta_nuevas_y_territorio(db, monkeypatch):
    from db.watchlist_empresas import WatchlistEmpresaEntry, add_entry
    from scheduler import competitor_alerts

    empresa_id = _watched_empresa(db)  # historial: 1 contrato en Madrid (W-01)
    # El job de alertas recorre ``list_all()``, que es deliberadamente global
    # (notifica a todos los destinatarios, no a una organización); la entrada
    # se crea igualmente con su organización porque el modelo ya no admite
    # construirla sin ámbito.
    add_entry(
        WatchlistEmpresaEntry(
            user_key="u1",
            empresa_id=empresa_id,
            organization_id=_organizacion_de_pruebas("competidores-alertas"),
            email="a@b.com",
        )
    )

    sent: list[dict] = []
    monkeypatch.setattr(
        competitor_alerts,
        "notify",
        lambda level, title, body, **kw: sent.append({"title": title, "body": body, **kw}),
    )

    # Primera pasada: el contrato W-01 cae dentro del lookback inicial → alerta
    n = competitor_alerts.check_and_notify()
    assert n == 1
    assert sent[0]["to_addr"] == "a@b.com"
    assert "Watched SL" in sent[0]["body"]

    # Segunda pasada sin novedades → silencio
    sent.clear()
    assert competitor_alerts.check_and_notify() == 0

    # Nueva adjudicación en CCAA nueva → alerta con marca de territorio
    insert_contract(db, "W-02", "Watched SL", nif="B99999999", ccaa="Galicia")
    resolve(db)
    assert competitor_alerts.check_and_notify() == 1
    assert "Galicia" in sent[0]["body"]


def test_competitor_alerts_sin_entradas(db):
    from scheduler.competitor_alerts import check_and_notify

    assert check_and_notify() == 0


def test_totales_renovaciones_incluye_kpis_de_riesgo(db):
    """Los cuatro KPIs del panel se calculan en servidor sobre el dataset completo.

    Antes `importe_alto_riesgo` y `calientes` se derivaban en el cliente sumando
    la lista paginada (`limit=1000`) y se presentaban como totales: con más
    contratos que el tope, las cifras salían silenciosamente bajas (patrón nº2
    de ADR-014).
    """
    from db.database import connect
    from services.competitive.renovaciones import (
        DIAS_CALIENTE,
        RIESGO_ALTO,
        totales_renovaciones,
    )

    # Alto riesgo y vence pronto → cuenta como "caliente".
    insert_contract(db, "R-K1", "Alpha SL", nif="B10000001", fecha_fin=_date(10), adjudicado=50000)
    # Alto riesgo pero lejos → suma a importe_alto_riesgo, no a calientes.
    insert_contract(db, "R-K2", "Beta SL", nif="B10000002", fecha_fin=_date(120), adjudicado=30000)
    # Riesgo bajo → no suma a ninguno de los dos.
    insert_contract(db, "R-K3", "Gamma SL", nif="B10000003", fecha_fin=_date(15), adjudicado=20000)
    resolve(db)

    with connect() as c:
        for lic_id, riesgo in (
            ("R-K1", RIESGO_ALTO + 0.1),
            ("R-K2", RIESGO_ALTO + 0.1),
            ("R-K3", RIESGO_ALTO - 0.3),
        ):
            c.execute(
                "INSERT INTO predicciones_retencion "
                "(licitacion_id, prob_retencion, riesgo_cambio) VALUES (%s, %s, %s)",
                (lic_id, 1.0 - riesgo, riesgo),
            )

    totales = totales_renovaciones(months_ahead=6)

    assert totales["contratos_venciendo"] == 3
    assert totales["importe_en_juego"] == 100000
    # Solo K1 y K2 superan el umbral de riesgo.
    assert totales["importe_alto_riesgo"] == 80000
    # Solo K1 supera el umbral Y vence dentro de la ventana caliente.
    assert totales["calientes"] == 1
    assert DIAS_CALIENTE == 30
