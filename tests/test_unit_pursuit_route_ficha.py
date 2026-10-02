"""``_lanzar_ficha_si_falta``: cuándo abrir una oportunidad encola la extracción."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import api.routes.pursuits as rutas
from config import settings
from shared.jobs import TIPO_FICHA_PLIEGO


async def _run_db_directo(fn: Any, *args: Any, **kwargs: Any) -> Any:
    return fn(*args, **kwargs)


def _lanzar(**parches: Any) -> MagicMock:
    with (
        patch.object(rutas, "run_db", side_effect=_run_db_directo),
        patch("services.rag.fact_sheet.get_fact_sheet", return_value=parches.get("ficha")),
        patch("shared.jobs.enqueue", return_value=7) as encolar,
    ):
        asyncio.run(rutas._lanzar_ficha_si_falta("LIC-1", 3, {"user_key": "k1"}))
    return encolar


def test_con_el_flag_apagado_no_hace_nada(monkeypatch: Any) -> None:
    monkeypatch.setattr(settings, "PLIEGO_FACTS_ON_PURSUIT", False)
    assert _lanzar().called is False


def test_si_ya_hay_ficha_no_gasta_otra_extraccion(monkeypatch: Any) -> None:
    monkeypatch.setattr(settings, "PLIEGO_FACTS_ON_PURSUIT", True)
    assert _lanzar(ficha={"status": "extracted"}).called is False


def test_sin_ficha_encola_la_extraccion_con_el_presupuesto_del_usuario(monkeypatch: Any) -> None:
    """Un job de la cola, de la organización de la oportunidad: es el que
    ``…/ficha-pliego/estado`` ve, así que la pestaña Pliego dice «Extrayendo…»
    en vez de ofrecer lanzarla otra vez."""
    monkeypatch.setattr(settings, "PLIEGO_FACTS_ON_PURSUIT", True)
    encolar = _lanzar()
    encolar.assert_called_once()
    args, kwargs = encolar.call_args
    assert args[0] == TIPO_FICHA_PLIEGO
    assert args[1] == {
        "licitacion_id": "LIC-1",
        "model": settings.PLIEGO_FACTS_MODEL,
        "budget_subject": "k1",
    }
    assert kwargs["organization_id"] == 3


def test_un_fallo_al_encolar_no_rompe_la_creacion(monkeypatch: Any) -> None:
    monkeypatch.setattr(settings, "PLIEGO_FACTS_ON_PURSUIT", True)
    with (
        patch.object(rutas, "run_db", side_effect=RuntimeError("sin base de datos")),
        patch("shared.jobs.enqueue") as encolar,
    ):
        asyncio.run(rutas._lanzar_ficha_si_falta("LIC-1", 3, {}))  # no lanza
    assert encolar.called is False
