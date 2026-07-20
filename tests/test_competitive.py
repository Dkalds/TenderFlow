"""Tests para services/competitive (renovaciones, bajas, mercado) y watchlist de empresas."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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


# ---------------------------------------------------------------------------
# Watchlist de empresas + alertas
# ---------------------------------------------------------------------------


def _watched_empresa(db, nombre="Watched SL", nif="B99999999"):
    from db.database import connect_read

    insert_contract(db, "W-01", nombre, nif=nif)
    resolve(db)
    with connect_read() as c:
        return int(
            c.execute("SELECT empresa_id FROM empresas WHERE nif_canonico = ?", (nif,)).fetchone()[
                0
            ]
        )


def test_watchlist_crud(db):
    from db.watchlist_empresas import WatchlistEmpresaEntry, add_entry, list_entries, remove_entry

    empresa_id = _watched_empresa(db)
    entry = WatchlistEmpresaEntry(user_key="u1", empresa_id=empresa_id, email="a@b.com")

    assert add_entry(entry) is not None
    assert add_entry(entry) is None  # duplicado → no-op
    assert len(list_entries("u1")) == 1
    assert list_entries("u1")[0]["nombre_canonico"] == "Watched SL"
    assert remove_entry("u1", empresa_id) is True
    assert remove_entry("u1", empresa_id) is False
    assert list_entries("u1") == []


def test_competitor_alerts_detecta_nuevas_y_territorio(db, monkeypatch):
    from db.watchlist_empresas import WatchlistEmpresaEntry, add_entry
    from scheduler import competitor_alerts

    empresa_id = _watched_empresa(db)  # historial: 1 contrato en Madrid (W-01)
    add_entry(WatchlistEmpresaEntry(user_key="u1", empresa_id=empresa_id, email="a@b.com"))

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
