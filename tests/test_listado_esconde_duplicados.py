"""El listado esconde las republicaciones igual que el Radar (ADR-026 D23).

D23 fija «Radar, listados: esconde ``pending`` y ``confirmed``», pero hasta el
2026-10-17 solo el Radar lo hacía: ``_base_filters`` —listado, cursor y export—
no excluía ningún duplicado y la rama FTS tampoco. Con las marcas de TED de
2026-09-24 el Radar dejó de enseñar la copia del DOUE y el listado la seguía
enseñando, y los KPIs de encima del listado contaban la copia.

Aquí se fija la regla de punta a punta sobre Postgres: las cuatro superficies
que comparten el universo del listado (paginado, cursor, texto libre y export)
esconden ``pending`` y ``confirmed`` y dejan ver ``rejected``; los KPIs que
abren el listado cuentan lo mismo que la lista enseña; el Radar no cambia; las
agregaciones de Mercado siguen contando («métrica cuenta»); y la ficha del
duplicado sigue respondiendo, porque un enlace guardado no puede romperse por
una marca del job nocturno.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from db.database import connect
from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from db.repositories.licitaciones import LicitacionRepository
from db.upsert import Licitacion, upsert_licitaciones

CANONICA = "PLACSP-1/2026"
PENDING = "ted:111-2026"
CONFIRMED = "ted:222-2026"
REJECTED = "pscp:333"
OTRA = "PLACSP-2/2026"

#: Lo que el listado tiene que enseñar: la canónica, la otra y la rechazada.
VISIBLES = {CANONICA, OTRA, REJECTED}


def _hoy() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _licitacion(id_externo: str, titulo: str) -> Licitacion:
    hoy = _hoy()
    return Licitacion(
        id_externo=id_externo,
        titulo=titulo,
        descripcion="Mantenimiento y evolutivos SAP S/4HANA",
        organo_contratacion="Ministerio de Pruebas",
        estado="PUB",
        fecha_publicacion=hoy.isoformat(),
        fecha_limite=(hoy + timedelta(days=20)).isoformat(),
        fecha_extraccion=hoy.date().isoformat(),
        tecnologia="SAP",
        cpv="72000000",
        ccaa="Madrid",
        importe=100_000.0,
    )


def _marcar(licitacion_id: str, status: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones_duplicados "
            "(licitacion_id, canonical_id, clave_match, confianza, status) "
            "VALUES (%s, %s, 'republicacion', %s, %s)",
            (licitacion_id, CANONICA, 1.0 if status == "confirmed" else 0.8, status),
        )


@pytest.fixture
def corpus(tmp_db: object) -> None:
    """Cinco expedientes clasificados y abiertos; tres marcados contra la canónica."""
    upsert_licitaciones(
        [
            _licitacion(CANONICA, "Mantenimiento SAP del Ministerio"),
            _licitacion(PENDING, "Mantenimiento SAP del Ministerio"),
            _licitacion(CONFIRMED, "Mantenimiento SAP del Ministerio"),
            _licitacion(REJECTED, "Mantenimiento SAP del Ministerio"),
            _licitacion(OTRA, "Licencias SAP de otro órgano"),
        ]
    )
    _marcar(PENDING, "pending")
    _marcar(CONFIRMED, "confirmed")
    _marcar(REJECTED, "rejected")


def _ids(filas: list[dict[str, object]]) -> set[object]:
    return {f["id_externo"] for f in filas}


@pytest.mark.usefixtures("corpus")
class TestListado:
    def test_el_paginado_esconde_pending_y_confirmed_y_deja_ver_rejected(self) -> None:
        items, total = LicitacionRepository().list_paginated(limit=50)
        assert _ids(items) == VISIBLES
        assert total == len(VISIBLES)

    def test_el_cursor_y_su_total_miden_lo_mismo_que_el_paginado(self) -> None:
        repo = LicitacionRepository()
        assert _ids(repo.list_cursor(limit=50)) == VISIBLES
        assert repo.count_cursor() == len(VISIBLES)

    def test_la_busqueda_de_texto_tambien_los_esconde(self) -> None:
        """La rama FTS construye su propio WHERE: tiene que aplicar la misma regla."""
        items, total = LicitacionRepository().list_paginated(q="SAP", limit=50)
        assert CANONICA in _ids(items), "la búsqueda de texto no encontró ni la canónica"
        assert _ids(items) == VISIBLES
        assert total == len(VISIBLES)

    def test_el_export_baja_lo_que_el_listado_ensena(self) -> None:
        assert _ids(LicitacionRepository().fetch_for_pdf(limit=50)) == VISIBLES

    def test_el_feed_en_vivo_no_anuncia_lo_que_la_lista_esconde(self) -> None:
        """El SSE del dashboard es otra cara del listado: misma regla."""
        recientes = LicitacionRepository().fetch_recent(
            since_extraccion="2000-01-01", since_actualizacion="2000-01-01", limit=50
        )
        assert _ids(recientes) == VISIBLES


@pytest.mark.usefixtures("corpus")
class TestLasCifrasDeEncima:
    def test_los_kpis_cuentan_lo_que_la_lista_ensena(self) -> None:
        """Los KPIs del ámbito y el listado comparten universo: mismo total."""
        _items, total_listado = LicitacionRepository().list_paginated(limit=50, ccaa="Madrid")
        kpis = AggregateRepository().overview_kpis(LicitacionesFilters(ccaa="Madrid"))
        assert kpis["total"] == total_listado == len(VISIBLES)

    def test_el_snapshot_global_cuenta_lo_mismo_que_el_listado(self) -> None:
        """El camino precalculado del overview mide el universo del listado."""
        from db.kpi_precompute import compute_all_kpis

        with connect() as c:
            filas = compute_all_kpis(c)
        total = next(
            f["valor"]
            for f in filas
            if f["metrica"] == "total_licitaciones" and f["dimension"] == "global"
        )
        assert total == len(VISIBLES)
        assert AggregateRepository().count_total_activas() == len(VISIBLES)

    def test_el_radar_sigue_escondiendolos(self) -> None:
        candidatas = AggregateRepository().scoring_candidates(hoy_iso=_hoy().isoformat())
        assert _ids(candidatas) == VISIBLES

    def test_el_calendario_cuenta_los_cierres_que_el_listado_abre(self) -> None:
        """Cada día del calendario enlaza al listado filtrado por cierre: mismo universo."""
        hoy = _hoy()
        dias = AggregateRepository().vencimientos_diarios(
            LicitacionesFilters(),
            desde_iso=hoy.date().isoformat(),
            hasta_exclusivo_iso=(hoy + timedelta(days=30)).date().isoformat(),
        )
        assert sum(int(d["count"]) for d in dias) == len(VISIBLES)


@pytest.mark.usefixtures("corpus")
class TestLaMetricaCuenta:
    """Mercado no es una lista: agrega sobre el ámbito entero (ADR-026 D23)."""

    def test_las_agregaciones_de_mercado_no_esconden(self) -> None:
        repo = AggregateRepository()
        total, _sin_clasificar = repo.tecnologias_total_y_sin_clasificar(LicitacionesFilters())
        assert total == 5
        por_ccaa = repo.geography_by_ccaa(LicitacionesFilters())
        assert sum(int(f["count"]) for f in por_ccaa) == 5


@pytest.mark.usefixtures("corpus")
class TestLaFichaNoCambia:
    def test_la_ficha_de_un_duplicado_sigue_respondiendo(self) -> None:
        """Esconder es cosa del listado; un enlace guardado no puede romperse."""
        repo = LicitacionRepository()
        for id_externo in (PENDING, CONFIRMED):
            assert repo.get_by_id(id_externo) is not None, id_externo
            assert repo.exists(id_externo), id_externo
