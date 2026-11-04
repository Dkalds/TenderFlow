"""Reproceso dirigido de los expedientes de PLACSP que esperan avisos TED (``scraper.reproceso_ted``).

Lo que fija: del ZIP solo se parsea lo que un aviso TED sin pareja enlaza, una
fila que ya existe nunca se pisa, los meses van del más nuevo al más viejo, y
tras escribir el aviso TED queda detrás del expediente de PLACSP.

Los unitarios doblan la descarga y la BD; los ``test_integration_*`` corren
contra Postgres.
"""

from __future__ import annotations

from typing import Any

import pytest

from scraper.connectors.base import RawNotice
from scraper.connectors.placsp import EsperadasPorTed, PlacspBulkConnector
from scraper.reproceso_ted import BulkEsperadasPorTed
from tests.test_placsp_esperadas_por_ted import _DEEPLINK, _entry_fuera_de_la_puerta

_ID_PLACSP = "placsp:10000000000001:2026-JARDIN"


@pytest.fixture()
def zip_falso(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    """El ZIP de cualquier mes trae la entry de jardinería; devuelve los meses pedidos."""
    pedidos: list[tuple[int, int]] = []

    def fetch(self: PlacspBulkConnector, cursor: Any) -> Any:
        pedidos.append((self.year, self.month))
        yield RawNotice(natural_id="x.atom", payload=(_entry_fuera_de_la_puerta(), None))

    monkeypatch.setattr(PlacspBulkConnector, "fetch", fetch)
    monkeypatch.setattr("scraper.pipeline._ml_classify_entry", lambda entry: None)
    return pedidos


def _conector(objetivo: set[str], *, ya_existe: bool = False) -> BulkEsperadasPorTed:
    conector = BulkEsperadasPorTed(2026, 10, frozenset(objetivo), ya_existe=lambda _id: ya_existe)
    conector._core.esperadas = EsperadasPorTed(cargar=lambda: [f"{_DEEPLINK}JARDIN%3D%3D"])
    return conector


def _parsear(conector: BulkEsperadasPorTed) -> list[Any]:
    return [conector.parse(raw) for raw in conector.fetch(None)]


def test_parsea_la_entry_que_espera_un_aviso_ted(zip_falso: list[tuple[int, int]]):
    conector = _conector({"JARDIN=="})

    [parsed] = _parsear(conector)

    assert parsed is not None
    assert parsed.licitacion.id_externo == _ID_PLACSP
    assert parsed.licitacion.inclusion_reason == "referencia_ted"
    assert parsed.licitacion.fuente == "bulk_202610"
    assert (conector.candidatas, conector.escribibles) == (1, 1)


def test_ignora_la_entry_que_no_espera_ninguno(zip_falso: list[tuple[int, int]]):
    conector = _conector({"OTRO=="})

    assert _parsear(conector) == [None]
    assert conector.candidatas == 0


def test_no_pisa_una_fila_que_ya_existe(zip_falso: list[tuple[int, int]]):
    """El ZIP no trae ``<updated>``: su versión puede ser más vieja que la guardada."""
    conector = _conector({"JARDIN=="}, ya_existe=True)

    assert _parsear(conector) == [None]
    assert (conector.candidatas, conector.ya_existian, conector.escribibles) == (1, 1, 0)


def test_recorre_los_meses_del_mas_nuevo_al_mas_viejo(
    zip_falso: list[tuple[int, int]], monkeypatch: pytest.MonkeyPatch
):
    """Así la primera versión escrita es la más reciente y las viejas la encuentran."""
    from scraper import reproceso_ted

    monkeypatch.setattr(reproceso_ted, "id_evls_esperados", lambda: frozenset({"JARDIN=="}))
    monkeypatch.setattr(reproceso_ted, "_ya_existe", lambda _id: False)
    monkeypatch.setattr(
        "scraper.connectors.placsp._urls_ted_con_id_evl", lambda: [f"{_DEEPLINK}JARDIN%3D%3D"]
    )

    resumen = reproceso_ted.reprocesar("2026-08", "2026-10", aplicar=False)

    assert zip_falso == [(2026, 10), (2026, 9), (2026, 8)]
    assert (resumen.meses, resumen.candidatas, resumen.escribibles) == (3, 3, 3)


def test_sin_avisos_ted_esperando_no_descarga_nada(
    zip_falso: list[tuple[int, int]], monkeypatch: pytest.MonkeyPatch
):
    from scraper import reproceso_ted

    monkeypatch.setattr(reproceso_ted, "id_evls_esperados", lambda: frozenset())

    resumen = reproceso_ted.reprocesar("2026-09", "2026-10", aplicar=True)

    assert zip_falso == []
    assert resumen.meses == 0


# ── Recorrido real contra Postgres ───────────────────────────────────────────


@pytest.fixture()
def db(tmp_db: Any) -> Any:
    db_mod, _ = tmp_db
    return db_mod


def _insertar_ted(c: Any) -> None:
    from datetime import UTC, datetime, timedelta

    hoy = datetime.now(UTC).date()
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, importe, url, "
        "fecha_publicacion, fecha_limite, estado, fuente, fecha_extraccion, "
        "analysis_universe) VALUES (%s, %s, %s, %s, %s, %s, %s, 'PUB', 'ted', %s, "
        "'technology_observed')",
        (
            "ted:500000-2026",
            "Servicio de limpieza de jardines municipales",
            "Ayuntamiento de Prueba",
            90000.0,
            f"{_DEEPLINK}JARDIN%3d%3d",
            (hoy - timedelta(days=30)).isoformat(),
            (hoy + timedelta(days=20)).isoformat(),
            hoy.isoformat(),
        ),
    )


def test_integration_el_aviso_ted_queda_detras_del_expediente_reprocesado(
    db: Any, zip_falso: list[tuple[int, int]]
) -> None:
    from db.database import connect, connect_read
    from scraper.reproceso_ted import reprocesar

    with connect() as c:
        _insertar_ted(c)

    resumen = reprocesar("2026-10", "2026-10", aplicar=True)
    # Ya emparejado, el aviso deja de esperar: repetir no escribe nada.
    segunda = reprocesar("2026-10", "2026-10", aplicar=True)

    assert (resumen.objetivo, resumen.nuevas, resumen.emparejadas) == (1, 1, 1)
    assert segunda.objetivo == 0
    with connect_read() as c:
        marca = c.execute(
            "SELECT canonical_id, status FROM licitaciones_duplicados WHERE licitacion_id = %s",
            ("ted:500000-2026",),
        ).fetchone()
        pliegos = c.execute(
            "SELECT count(*) FROM documentos WHERE licitacion_id = %s", (_ID_PLACSP,)
        ).fetchone()
    assert tuple(marca) == (_ID_PLACSP, "confirmed")
    assert pliegos[0] == 1


def test_integration_no_pisa_la_fila_de_placsp_que_ya_estaba(
    db: Any, zip_falso: list[tuple[int, int]]
) -> None:
    from db.database import connect, connect_read
    from scraper.reproceso_ted import reprocesar

    with connect() as c:
        _insertar_ted(c)
        # La fila del expediente ya existe, con un título que el ZIP no trae.
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES (%s, 'Versión del ATOM', 'placsp', '2026-11-03')",
            (_ID_PLACSP,),
        )

    resumen = reprocesar("2026-10", "2026-10", aplicar=True)

    assert (resumen.ya_existian, resumen.nuevas) == (1, 0)
    with connect_read() as c:
        titulo = c.execute(
            "SELECT titulo FROM licitaciones WHERE id_externo = %s", (_ID_PLACSP,)
        ).fetchone()
    assert titulo[0] == "Versión del ATOM"
