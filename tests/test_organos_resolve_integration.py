"""Resolución incremental de órganos en la pipeline (ADR-032 §C, 2026-09-14)."""

from __future__ import annotations

import pytest

from db.upsert import Licitacion, upsert_licitaciones
from services.organos import resolver_pendientes


def _lic(id_externo: str, organo: str, ccaa: str = "Madrid") -> Licitacion:
    return Licitacion(
        id_externo=id_externo,
        titulo=f"Expediente {id_externo}",
        organo_contratacion=organo,
        ccaa=ccaa,
        fuente="placsp",
        fecha_publicacion="2026-09-01",
    )


@pytest.fixture()
def corpus(tmp_db):
    upsert_licitaciones(
        [
            _lic("L-1", "Ayuntamiento de Madrid"),
            _lic("L-2", "AYUNTAMIENTO DE MADRID"),
            _lic("L-3", "Excmo. Ayuntamiento de Madrid"),
            _lic("L-4", "Diputación Provincial de Sevilla", ccaa="Andalucía"),
        ]
    )
    return tmp_db


def _organo_ids() -> dict[str, int | None]:
    from db.database import connect_read

    with connect_read() as c:
        filas = c.execute("SELECT id_externo, organo_id FROM licitaciones ORDER BY 1").fetchall()
    return {str(r[0]): r[1] for r in filas}


def test_pasada_crea_el_maestro_y_asigna_las_grafias(corpus) -> None:
    resumen = resolver_pendientes(max_grafias=50, presupuesto_s=60)

    assert resumen.grafias_vistas == 4
    assert resumen.creadas == 2  # Madrid y Sevilla
    assert resumen.por_nombre == 2  # las dos variantes de Madrid colapsan
    assert resumen.filas_actualizadas == 4
    assert not resumen.agotado_por_tiempo

    ids = _organo_ids()
    assert None not in ids.values()
    assert ids["L-1"] == ids["L-2"] == ids["L-3"]
    assert ids["L-4"] != ids["L-1"]


def test_segunda_pasada_no_hace_nada(corpus) -> None:
    resolver_pendientes(max_grafias=50, presupuesto_s=60)
    segunda = resolver_pendientes(max_grafias=50, presupuesto_s=60)
    assert segunda.grafias_vistas == 0
    assert segunda.filas_actualizadas == 0


def test_respeta_la_cuenta_y_deja_el_resto_para_la_siguiente(corpus) -> None:
    primera = resolver_pendientes(max_grafias=1, presupuesto_s=60)
    assert primera.grafias_vistas == 1
    # Una grafía resuelta puede asignar más de una fila (la comparación es
    # case-insensitive), pero nunca todas: quedan pendientes para la siguiente.
    sin_resolver = sum(1 for v in _organo_ids().values() if v is None)
    assert 1 <= sin_resolver <= 3


def test_presupuesto_agotado_se_declara(corpus) -> None:
    resumen = resolver_pendientes(max_grafias=50, presupuesto_s=-1)
    assert resumen.agotado_por_tiempo
    assert resumen.grafias_vistas == 0


def test_dry_run_cuenta_sin_escribir(corpus) -> None:
    resumen = resolver_pendientes(max_grafias=50, presupuesto_s=60, aplicar=False)
    assert resumen.grafias_vistas == 4
    assert resumen.filas_actualizadas == 0
    assert all(v is None for v in _organo_ids().values())


def test_el_paso_canonico_esta_registrado_con_tier() -> None:
    from scheduler.pipeline_runs import CANONICAL_STEPS, STEP_TIER, step_tier

    assert "organos_resolve" in CANONICAL_STEPS
    assert CANONICAL_STEPS.index("organos_resolve") < CANONICAL_STEPS.index("kpi_precompute")
    assert STEP_TIER["organos_resolve"] == "advisory"
    assert step_tier("organos_resolve") == "advisory"


def test_el_paso_corre_y_devuelve_ok_o_skipped(corpus) -> None:
    from scheduler.pipeline_runs import _run_organos_resolve

    assert _run_organos_resolve() == "ok"
    assert _run_organos_resolve() == "skipped"


def test_quality_publica_cobertura_y_cola(corpus) -> None:
    from services.analytics.quality import get_quality

    antes = get_quality()
    assert antes.organos_cobertura_pct == 0.0
    assert antes.organos_revision_pendiente == 0

    resolver_pendientes(max_grafias=50, presupuesto_s=60)
    despues = get_quality()
    assert despues.organos_cobertura_pct == 100.0
    assert despues.organos_revision_pendiente == 0
