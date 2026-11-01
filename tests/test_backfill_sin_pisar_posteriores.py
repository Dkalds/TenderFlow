"""Backfill de meses anteriores a lo ya ingerido sin regresar versiones.

El ZIP mensual de PLACSP no trae ``<updated>`` por aviso y gana el último mes
escrito: traer 2024 después de la reingesta de 2025-2026 devolvería a su versión
de 2024 todo expediente que reaparece después. ``PlacspBulkConnector`` con
``sin_pisar_posteriores`` salta las claves que ya escribió un mes posterior o el
feed vivo (``db.repositories.identidad.ids_placsp_posteriores_a``).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

from scraper.connectors.base import RawNotice
from tests.test_identidad_placsp_fase_b import _CLAVE, _entry


@pytest.fixture(autouse=True)
def _sin_ml() -> Iterator[None]:
    """El rescate ML depende de un modelo en disco: fuera, como en el golden."""
    with patch("scraper.pipeline._ml_classify_entry", return_value=None):
        yield


def _parse(conector: Any) -> Any:
    return conector.parse(RawNotice("f.atom", (_entry(), None)))


def test_salta_la_clave_que_escribio_un_mes_posterior() -> None:
    from scraper.connectors.placsp import PlacspBulkConnector

    conector = PlacspBulkConnector(2024, 3, sin_pisar_posteriores=True)
    with patch(
        "db.repositories.identidad.ids_placsp_posteriores_a", return_value=frozenset({_CLAVE})
    ) as posteriores:
        assert _parse(conector) is None
        assert _parse(conector) is None
    posteriores.assert_called_once_with("bulk_202403")
    assert conector.contadores_de_descarte()["placsp_bulk_saltada_por_posterior"] == 2


def test_una_clave_que_nadie_escribio_despues_se_parsea() -> None:
    from scraper.connectors.placsp import PlacspBulkConnector

    conector = PlacspBulkConnector(2024, 3, sin_pisar_posteriores=True)
    with patch("db.repositories.identidad.ids_placsp_posteriores_a", return_value=frozenset()):
        parsed = _parse(conector)
    assert parsed is not None
    assert parsed.licitacion.id_externo == _CLAVE
    assert conector.contadores_de_descarte()["placsp_bulk_saltada_por_posterior"] == 0


def test_sin_la_opcion_no_consulta_la_base() -> None:
    from scraper.connectors.placsp import PlacspBulkConnector

    conector = PlacspBulkConnector(2024, 3)
    with patch("db.repositories.identidad.ids_placsp_posteriores_a") as posteriores:
        assert _parse(conector) is not None
    posteriores.assert_not_called()
    assert "placsp_bulk_saltada_por_posterior" not in conector.contadores_de_descarte()


def test_run_update_solo_admite_la_opcion_con_backfill(monkeypatch: pytest.MonkeyPatch) -> None:
    from scheduler import run_update

    monkeypatch.setattr("sys.argv", ["run_update", "--sin-pisar-posteriores"])
    with pytest.raises(SystemExit) as salida:
        run_update.main()
    assert salida.value.code == 2


def test_integration_posteriores_son_el_feed_vivo_y_los_meses_siguientes(tmp_db: Any) -> None:
    from db.database import connect
    from db.repositories.identidad import ids_placsp_posteriores_a

    with connect() as c:
        for id_externo, fuente in (
            ("placsp:1:vivo", "placsp"),
            ("placsp:1:antes", "bulk_202402"),
            ("placsp:1:mismo", "bulk_202403"),
            ("placsp:1:despues", "bulk_202404"),
            ("placsp:1:reingesta", "bulk_202610"),
            ("ted:x", "ted"),
            ("placsp_watched_company_awards:1:x", "placsp_watched_company_awards"),
        ):
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
                "VALUES (%s, 't', %s, '2026-10-31T16:00:00+00:00')",
                (id_externo, fuente),
            )
    assert ids_placsp_posteriores_a("bulk_202403") == {
        "placsp:1:vivo",
        "placsp:1:despues",
        "placsp:1:reingesta",
    }
