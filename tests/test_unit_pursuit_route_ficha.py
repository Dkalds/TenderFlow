"""``_lanzar_ficha_si_falta``: cuándo abrir una oportunidad dispara la extracción."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import api.routes.pursuits as rutas
from config import settings


async def _run_db_directo(fn: Any, *args: Any, **kwargs: Any) -> Any:
    return fn(*args, **kwargs)


def _lanzar(**parches: Any) -> MagicMock:
    background = MagicMock()
    with (
        patch.object(rutas, "run_db", side_effect=_run_db_directo),
        patch("services.rag.fact_sheet.get_fact_sheet", return_value=parches.get("ficha")),
        patch(
            "services.rag.fact_sheet.try_mark_extraction_running",
            return_value=parches.get("marca", True),
        ),
        patch("services.rag.fact_sheet.run_background_extraction") as extraer,
    ):
        asyncio.run(rutas._lanzar_ficha_si_falta(background, "LIC-1", {"user_key": "k1"}))
        if background.add_task.called:
            assert background.add_task.call_args.args[0] is extraer
    return background


def test_con_el_flag_apagado_no_hace_nada(monkeypatch: Any) -> None:
    monkeypatch.setattr(settings, "PLIEGO_FACTS_ON_PURSUIT", False)
    assert _lanzar().add_task.called is False


def test_si_ya_hay_ficha_no_gasta_otra_extraccion(monkeypatch: Any) -> None:
    monkeypatch.setattr(settings, "PLIEGO_FACTS_ON_PURSUIT", True)
    assert _lanzar(ficha={"status": "extracted"}).add_task.called is False


def test_si_otro_proceso_ya_la_esta_extrayendo_no_duplica(monkeypatch: Any) -> None:
    monkeypatch.setattr(settings, "PLIEGO_FACTS_ON_PURSUIT", True)
    assert _lanzar(marca=False).add_task.called is False


def test_sin_ficha_encola_la_extraccion_con_el_presupuesto_del_usuario(monkeypatch: Any) -> None:
    monkeypatch.setattr(settings, "PLIEGO_FACTS_ON_PURSUIT", True)
    background = _lanzar()
    background.add_task.assert_called_once()
    args, kwargs = background.add_task.call_args
    assert args[1] == "LIC-1"
    assert kwargs["budget_subject"] == "k1"
    assert kwargs["model"] == settings.PLIEGO_FACTS_MODEL


def test_un_fallo_al_encolar_no_rompe_la_creacion(monkeypatch: Any) -> None:
    monkeypatch.setattr(settings, "PLIEGO_FACTS_ON_PURSUIT", True)
    background = MagicMock()
    with (
        patch.object(rutas, "run_db", side_effect=RuntimeError("sin base de datos")),
    ):
        asyncio.run(rutas._lanzar_ficha_si_falta(background, "LIC-1", {}))  # no lanza
    assert background.add_task.called is False
