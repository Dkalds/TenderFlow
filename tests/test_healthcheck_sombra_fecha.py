"""El healthcheck avisa de licitaciones recientes escritas sin ``fecha_extraccion_ts``.

En ``licitaciones`` la sombra la escribe ``db/upsert.py``: una fila reciente sin
ella la escribió otro camino (el 2026-11-22, 701 filas de PLACSP). La consulta
va contra Postgres; el bloque del informe, sin BD.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _incorporar(
    resultado: tuple[int, str | None] | Exception,
) -> tuple[list[dict[str, object]], list[str], dict[str, object], MagicMock]:
    from scheduler.healthcheck import _incorporar_sombra_fecha

    checks: list[dict[str, object]] = []
    warnings: list[str] = []
    info: dict[str, object] = {}
    conexion = MagicMock()
    efecto = (
        {"side_effect": resultado}
        if isinstance(resultado, Exception)
        else {"return_value": resultado}
    )
    with patch("db.healthcheck.licitaciones_sin_sombra_fecha", **efecto):
        _incorporar_sombra_fecha(conexion, checks, warnings, info)
    return checks, warnings, info, conexion


def test_sin_filas_sin_sombra_el_check_pasa() -> None:
    checks, warnings, info, _ = _incorporar((0, None))

    assert warnings == []
    assert checks == [{"name": "sombra_fecha_extraccion", "ok": True}]
    assert info == {}


def test_filas_sin_sombra_degradan_con_un_ejemplo() -> None:
    checks, warnings, info, _ = _incorporar((701, "placsp:1"))

    assert warnings == ["licitaciones_sin_sombra_fecha:701"]
    assert checks == [{"name": "sombra_fecha_extraccion", "ok": False}]
    assert info["licitaciones_sin_sombra_fecha_ejemplo"] == "placsp:1"


def test_si_no_se_puede_medir_lo_dice_y_deshace_la_transaccion() -> None:
    checks, warnings, info, conexion = _incorporar(RuntimeError("columna inexistente"))

    assert warnings == ["sombra_fecha_no_medida"]
    assert checks == [{"name": "sombra_fecha_extraccion", "ok": True}]
    assert "columna inexistente" in str(info["sombra_fecha_error"])
    conexion.rollback.assert_called_once()


@pytest.mark.usefixtures("tmp_db")
def test_la_consulta_cuenta_solo_las_recientes_sin_sombra() -> None:
    from db import healthcheck as sql
    from db.database import connect
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [Licitacion(id_externo=i, titulo="Contrato") for i in ("SF-UPSERT", "SF-MANO", "SF-VIEJA")]
    )
    hoy = datetime.now(UTC)
    with connect() as c:
        # Lo que hizo el escritor del 2026-11-22: texto de Postgres, sin sombra.
        c.execute(
            "UPDATE licitaciones SET fecha_extraccion = now()::text, fecha_extraccion_ts = NULL "
            "WHERE id_externo = 'SF-MANO'"
        )
        c.execute(
            "UPDATE licitaciones SET fecha_extraccion = %s, fecha_extraccion_ts = NULL "
            "WHERE id_externo = 'SF-VIEJA'",
            ((hoy - timedelta(days=30)).isoformat(),),
        )
    desde = (hoy - timedelta(days=7)).date().isoformat()
    with connect() as c:
        filas: tuple[int, Any] = sql.licitaciones_sin_sombra_fecha(c, desde)

    assert filas == (1, "SF-MANO")
