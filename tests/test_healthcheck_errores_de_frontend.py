"""El healthcheck mira lo que falla en el navegador.

``client_errors`` (v117) guarda los errores de JavaScript agregados por huella,
y hasta 2026-10 lo único que los leía era la purga a 30 días: la tabla era un
destino al que no llegaba nadie. Estos tests fijan que un error que se repite
entra en el informe —y por tanto en el correo de estado degradado— y que no
poder medirlo no se lleva el informe por delante.

Sin BD: se sustituye la consulta del repositorio.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

_ERROR_DEL_RADAR = {
    "fingerprint": "a" * 32,
    "origen": "onerror",
    "ruta": "/radar",
    "mensaje": "TypeError: Cannot read properties of undefined (reading 'map')",
    "build": "abc1234",
    "ocurrencias": 12,
    "primera_vez": "2026-10-03T08:00:00+00:00",
    "ultima_vez": "2026-10-03T19:00:00+00:00",
}


def _incorporar(
    activos: tuple[int, list[dict[str, Any]]] | Exception,
) -> tuple[list[dict[str, object]], list[str], dict[str, object]]:
    from scheduler.healthcheck import _incorporar_errores_de_frontend

    checks: list[dict[str, object]] = []
    warnings: list[str] = []
    info: dict[str, object] = {}
    efecto = (
        {"side_effect": activos} if isinstance(activos, Exception) else {"return_value": activos}
    )
    with patch("scheduler.healthcheck.errores_activos_del_frontend", **efecto) as consulta:
        _incorporar_errores_de_frontend(checks, warnings, info, horas=24, min_ocurrencias=2)
    consulta.assert_called_once()
    assert consulta.call_args.kwargs["min_ocurrencias"] == 2
    return checks, warnings, info


def test_un_error_de_frontend_que_se_repite_degrada_el_estado() -> None:
    checks, warnings, _ = _incorporar((1, [_ERROR_DEL_RADAR]))

    assert warnings == ["client_errors_activos:1"]
    assert checks == [{"name": "client_errors_sin_actividad", "ok": False}]


def test_el_informe_dice_que_error_es_sin_tener_que_ir_a_buscarlo() -> None:
    """El correo solo lleva los valores planos de ``info``: el ejemplo va como texto."""
    _, _, info = _incorporar((3, [_ERROR_DEL_RADAR]))

    assert info["client_errors_top"] == (
        "TypeError: Cannot read properties of undefined (reading 'map') · /radar · 12 veces"
    )
    assert info["client_errors"] == {"ventana_horas": 24, "activos": 3, "top": [_ERROR_DEL_RADAR]}


def test_sin_errores_activos_el_check_pasa_y_no_avisa() -> None:
    checks, warnings, info = _incorporar((0, []))

    assert warnings == []
    assert checks == [{"name": "client_errors_sin_actividad", "ok": True}]
    assert "client_errors_top" not in info


def test_no_poder_medirlo_no_tumba_el_informe() -> None:
    """Mismo trato que sus vecinos: «no lo pude medir» es un aviso, no una caída."""
    checks, warnings, info = _incorporar(RuntimeError("relation client_errors does not exist"))

    assert warnings == ["client_errors_no_medido"]
    assert checks == [{"name": "client_errors_sin_actividad", "ok": True}]
    assert "does not exist" in str(info["client_errors_error"])


def test_la_ventana_se_pide_en_utc_y_hacia_atras() -> None:
    from datetime import UTC, datetime, timedelta

    from scheduler.healthcheck import _incorporar_errores_de_frontend

    with patch(
        "scheduler.healthcheck.errores_activos_del_frontend", return_value=(0, [])
    ) as consulta:
        _incorporar_errores_de_frontend([], [], {}, horas=24, min_ocurrencias=2)

    desde = datetime.fromisoformat(consulta.call_args.kwargs["desde"])
    hace_un_dia = datetime.now(UTC) - timedelta(hours=24)
    assert abs((desde - hace_un_dia).total_seconds()) < 60
