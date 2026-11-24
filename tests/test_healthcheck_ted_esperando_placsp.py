"""El healthcheck avisa del aviso TED cuyo expediente de PLACSP no llega.

Un aviso TED que enlaza PLACSP por ``idEvl`` espera a que el ATOM re-emita el
expediente; si la entry pasó antes que el aviso, el cursor ya la dejó atrás y
solo la trae ``scraper.reproceso_ted``. La consulta se prueba contra Postgres en
``tests/test_documentos_plataforma.py``; aquí, sin BD, qué hace el informe con
ella.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch


def _incorporar(
    resultado: list[str] | Exception,
) -> tuple[list[dict[str, object]], list[str], dict[str, object], str]:
    from scheduler.healthcheck import _incorporar_ted_esperando_placsp

    checks: list[dict[str, object]] = []
    warnings: list[str] = []
    info: dict[str, object] = {}
    efecto = (
        {"side_effect": resultado}
        if isinstance(resultado, Exception)
        else {"return_value": resultado}
    )
    with patch("db.repositories.dedupe.ted_esperando_placsp", **efecto) as consulta:
        _incorporar_ted_esperando_placsp(checks, warnings, info)
    return checks, warnings, info, consulta.call_args.args[0]


def test_sin_avisos_esperando_el_check_pasa_y_no_avisa() -> None:
    checks, warnings, info, _ = _incorporar([])

    assert warnings == []
    assert checks == [{"name": "ted_con_expediente_placsp", "ok": True}]
    assert "ted_esperando_placsp" not in info


def test_un_aviso_que_sigue_esperando_degrada_y_dice_cual() -> None:
    checks, warnings, info, _ = _incorporar(["ted:759105-2026", "ted:760321-2026"])

    assert warnings == ["ted_esperando_placsp:2"]
    assert checks == [{"name": "ted_con_expediente_placsp", "ok": False}]
    # Plano: el correo de alerta descarta los valores que no lo son.
    assert info["ted_esperando_placsp"] == "ted:759105-2026, ted:760321-2026"


def test_no_poder_medirlo_no_tumba_el_informe() -> None:
    checks, warnings, info, _ = _incorporar(RuntimeError("BD caída"))

    assert warnings == ["ted_esperando_placsp_no_medido"]
    assert checks == [{"name": "ted_con_expediente_placsp", "ok": True}]
    assert "BD caída" in str(info["ted_esperando_placsp_error"])


def test_solo_cuentan_los_que_llevan_mas_de_tres_dias() -> None:
    from scheduler.healthcheck import TED_ESPERA_PLACSP_HORAS

    *_, antes_de = _incorporar([])

    corte = datetime.fromisoformat(antes_de)
    esperado = datetime.now(UTC) - timedelta(hours=TED_ESPERA_PLACSP_HORAS)
    assert TED_ESPERA_PLACSP_HORAS == 72
    assert abs((corte - esperado).total_seconds()) < 60
    # El mismo formato que `primera_extraccion`, que se compara como texto.
    assert antes_de.endswith("+00:00")
