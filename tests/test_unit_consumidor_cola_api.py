"""ADR-028 §G: la API consume la cola a demanda mientras no exista el worker.

Hasta el 2026-10-01 los jobs ``ficha_pliego`` se encolaban y no los reclamaba
nadie: ``tenderflow-worker`` está declarado en ``render.yaml`` pero el Blueprint
nunca se vinculó, así que el servicio no existe. La pestaña Pliego decía
«Extrayendo…» para siempre (siete jobs ``pending`` desde el 14 de septiembre).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

import api.app as app_mod
from config import settings
from config.settings import jobs_consumidor_en_api


@pytest.mark.parametrize(("env", "esperado"), [("prod", True), ("staging", True), ("dev", False)])
def test_por_defecto_solo_consume_en_prod_y_staging(
    monkeypatch: pytest.MonkeyPatch, env: str, esperado: bool
) -> None:
    """En dev y test un hilo reclamando jobs ejecutaría handlers reales en
    mitad de los tests que encolan para mirar la fila."""
    monkeypatch.delenv("JOBS_CONSUMIDOR_EN_API", raising=False)
    assert jobs_consumidor_en_api(env) is esperado


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("0", False), ("false", False), ("off", False), ("1", True), ("true", True)],
)
def test_la_variable_manda_sobre_el_entorno(
    monkeypatch: pytest.MonkeyPatch, valor: str, esperado: bool
) -> None:
    """``=0`` es el interruptor para cuando exista el worker dedicado."""
    monkeypatch.setenv("JOBS_CONSUMIDOR_EN_API", valor)
    assert jobs_consumidor_en_api("prod") is esperado
    assert jobs_consumidor_en_api("dev") is esperado


def _ciclo_de_vida(
    monkeypatch: pytest.MonkeyPatch, *, perfil: str, env: str, variable: str | None = None
) -> tuple[MagicMock, MagicMock]:
    """Arranca y para el lifespan real con la BD y el hilo sustituidos."""
    monkeypatch.setattr(settings, "APP_PROFILE", perfil)
    monkeypatch.setattr(settings, "ENV", env)
    if variable is None:
        monkeypatch.delenv("JOBS_CONSUMIDOR_EN_API", raising=False)
    else:
        monkeypatch.setenv("JOBS_CONSUMIDOR_EN_API", variable)
    worker = MagicMock()

    async def _arrancar_y_parar() -> None:
        async with app_mod.lifespan(FastAPI()):
            pass

    with (
        patch.object(app_mod, "init_db"),
        patch("db.database.close_pool"),
        patch("scheduler.worker.arrancar_en_hilo", return_value=worker) as arrancar,
    ):
        asyncio.run(_arrancar_y_parar())
    return arrancar, worker


def test_la_api_en_produccion_arranca_y_para_el_consumidor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrancar, worker = _ciclo_de_vida(monkeypatch, perfil="api", env="prod")
    arrancar.assert_called_once_with()
    # Al apagar se para antes de cerrar el pool: lo que no termine vuelve a
    # `pending` por TTL y lo remata la instancia siguiente.
    worker.detener.assert_called_once_with()


@pytest.mark.parametrize(
    ("perfil", "env", "variable"),
    [
        ("api", "prod", "0"),  # ya existe el worker dedicado
        ("api", "dev", None),  # local y tests
        ("scraper", "prod", None),  # los jobs de Actions no consumen la cola
    ],
)
def test_no_arranca_el_consumidor_fuera_de_su_caso(
    monkeypatch: pytest.MonkeyPatch, perfil: str, env: str, variable: Any
) -> None:
    arrancar, _ = _ciclo_de_vida(monkeypatch, perfil=perfil, env=env, variable=variable)
    arrancar.assert_not_called()
