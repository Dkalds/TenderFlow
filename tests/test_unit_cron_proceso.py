"""ADR-033, enmienda 2026-11-09: la API lanza el plano de cron como proceso hijo."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

import api.app as app_mod
from config import settings
from scheduler import cron_plane, cron_proceso
from scheduler.cron_proceso import CronProceso, arrancar_en_proceso


def _hijo(*, codigo: int = 0, vivo: bool = True) -> MagicMock:
    hijo = MagicMock(pid=4242)
    hijo.wait.return_value = codigo
    hijo.poll.return_value = None if vivo else codigo
    return hijo


@pytest.mark.parametrize("valor", [None, "", "actions", "docker"])
def test_sin_el_plano_declarado_no_lanza_nada(
    monkeypatch: pytest.MonkeyPatch, valor: str | None
) -> None:
    """Con el cron en Actions, un hijo aquí correría cada pasada dos veces."""
    if valor is None:
        monkeypatch.delenv("SCHEDULER_PLANE", raising=False)
    else:
        monkeypatch.setenv("SCHEDULER_PLANE", valor)
    with patch.object(cron_proceso.subprocess, "Popen") as popen:
        assert arrancar_en_proceso() is None
    popen.assert_not_called()


def test_el_hijo_arranca_con_el_perfil_de_los_workflows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``APP_PROFILE=scraper`` es lo que le da el techo de sentencia de batch:
    con el de la API (30 s) el cierre de la pasada se cancelaría a medias."""
    monkeypatch.setenv("APP_PROFILE", "api")
    monkeypatch.setenv("SCHEDULER_PLANE", "worker")
    with patch.object(cron_proceso.subprocess, "Popen", return_value=_hijo()) as popen:
        CronProceso()._lanzar()

    args, kwargs = popen.call_args
    assert args[0] == [sys.executable, "-m", "scheduler.cron_plane"]
    assert kwargs["env"]["APP_PROFILE"] == "scraper"
    assert kwargs["env"]["SCHEDULER_PLANE"] == "worker"


def test_el_hijo_no_hereda_el_pool_ni_el_techo_de_la_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Los 12 + 12 de la API, sumados a los del hijo, pasan del pooler de sesión;
    y un techo de sentencia explícito anularía el de batch de su perfil."""
    monkeypatch.setenv("DB_POOL_SIZE", "12")
    monkeypatch.setenv("DB_READ_POOL_SIZE", "12")
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "30000")
    with patch.object(cron_proceso.subprocess, "Popen", return_value=_hijo()) as popen:
        CronProceso()._lanzar()

    env = popen.call_args.kwargs["env"]
    assert (env["DB_POOL_SIZE"], env["DB_READ_POOL_SIZE"]) == ("2", "2")
    assert "DB_STATEMENT_TIMEOUT_MS" not in env


def test_el_perfil_del_hijo_sube_el_techo_de_sentencia_a_batch() -> None:
    """Lo que el perfil compra: con el de la API el cierre se cancelaría a 30 s."""
    from config.settings import Settings
    from config.settings_bd import _BATCH_STATEMENT_TIMEOUT_MS

    hijo = Settings(ENV="dev", APP_PROFILE=cron_proceso.PERFIL_DEL_HIJO, _env_file=None)
    assert hijo.DB_STATEMENT_TIMEOUT_MS == _BATCH_STATEMENT_TIMEOUT_MS


def test_un_hijo_caido_se_relanza() -> None:
    cron = CronProceso(espera_relanzado_s=0)
    segundo = _hijo()
    segundo.wait.side_effect = lambda: cron._parar.set()  # corta el bucle en la 2.ª vuelta

    with patch.object(cron, "_lanzar", side_effect=[_hijo(codigo=1), segundo]) as lanzar:
        cron.supervisar()

    assert lanzar.call_count == 2


def test_cada_caida_dobla_la_espera_hasta_el_techo() -> None:
    """Cada relanzado empieza con una ingesta: sin freno, un hijo que muere
    siempre las encadenaría."""
    cron = CronProceso(espera_relanzado_s=1500)
    esperas: list[float] = []

    def _esperar(segundos: float) -> bool:
        esperas.append(segundos)
        if len(esperas) == 3:
            cron._parar.set()
        return True

    with (
        patch.object(cron, "_lanzar", side_effect=lambda: _hijo(codigo=137)),
        patch.object(cron._parar, "wait", side_effect=_esperar),
    ):
        cron.supervisar()

    assert esperas == [1500, 3000, cron_proceso.ESPERA_RELANZADO_MAX_S]


def test_un_hijo_lanzado_durante_la_parada_se_termina() -> None:
    """``detener()`` pudo no verlo: se lanzó después de que leyera el proceso."""
    cron = CronProceso(espera_relanzado_s=0)
    hijo = _hijo()

    def _lanzar_y_parar() -> MagicMock:
        cron._parar.set()
        return hijo

    with patch.object(cron, "_lanzar", side_effect=_lanzar_y_parar):
        cron.supervisar()

    hijo.terminate.assert_called_once_with()
    hijo.wait.assert_not_called()


def test_si_el_hijo_no_puede_lanzarse_se_reintenta() -> None:
    """Un ``OSError`` al lanzar no puede matar al supervisor: sin él no hay cron."""
    cron = CronProceso(espera_relanzado_s=0)
    hijo = _hijo()
    hijo.wait.side_effect = lambda: cron._parar.set()

    with patch.object(cron, "_lanzar", side_effect=[OSError("sin memoria"), hijo]) as lanzar:
        cron.supervisar()

    assert lanzar.call_count == 2


def test_detener_termina_al_hijo_y_no_lo_relanza() -> None:
    cron = CronProceso(espera_relanzado_s=0)
    hijo = _hijo()
    cron._proceso = hijo

    cron.detener()

    hijo.terminate.assert_called_once_with()
    hijo.kill.assert_not_called()
    with patch.object(cron, "_lanzar") as lanzar:
        cron.supervisar()
    lanzar.assert_not_called()


def test_detener_mata_al_hijo_que_no_sale_a_tiempo() -> None:
    cron = CronProceso()
    hijo = _hijo()
    hijo.wait.side_effect = subprocess.TimeoutExpired(cmd="cron", timeout=1)
    cron._proceso = hijo

    cron.detener()

    hijo.kill.assert_called_once_with()


def test_detener_no_toca_un_hijo_ya_muerto() -> None:
    cron = CronProceso()
    hijo = _hijo(vivo=False)
    cron._proceso = hijo

    cron.detener()

    hijo.terminate.assert_not_called()


def _ciclo_de_vida(monkeypatch: pytest.MonkeyPatch, *, perfil: str) -> tuple[MagicMock, MagicMock]:
    """Arranca y para el lifespan real con la BD, la cola y el hijo sustituidos."""
    monkeypatch.setattr(settings, "APP_PROFILE", perfil)
    monkeypatch.setattr(settings, "ENV", "prod")
    cron = MagicMock()

    async def _arrancar_y_parar() -> None:
        async with app_mod.lifespan(FastAPI()):
            pass

    with (
        patch.object(app_mod, "init_db"),
        patch("db.database.close_pool"),
        patch("scheduler.worker.arrancar_en_hilo"),
        patch("scheduler.cron_plane.arrancar_en_hilo", return_value=None),
        patch("scheduler.cron_proceso.arrancar_en_proceso", return_value=cron) as arrancar,
    ):
        asyncio.run(_arrancar_y_parar())
    return arrancar, cron


def test_la_api_lanza_el_hijo_y_lo_para_al_apagar(monkeypatch: pytest.MonkeyPatch) -> None:
    arrancar, cron = _ciclo_de_vida(monkeypatch, perfil="api")
    arrancar.assert_called_once_with()
    cron.detener.assert_called_once_with()


@pytest.mark.parametrize("perfil", ["worker", "scraper"])
def test_los_demas_perfiles_no_lanzan_el_hijo(monkeypatch: pytest.MonkeyPatch, perfil: str) -> None:
    """El perfil ``worker`` lleva el plano en un hilo propio, como antes."""
    arrancar, _ = _ciclo_de_vida(monkeypatch, perfil=perfil)
    arrancar.assert_not_called()


# ── El entry point del hijo ──────────────────────────────────────────────────


def test_el_hijo_configura_su_propio_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """Es otro intérprete: sin esto no hay redacción de secretos ni filtro de nivel."""
    monkeypatch.delenv("SCHEDULER_PLANE", raising=False)
    with (
        patch.object(cron_plane, "configure_logging") as configurar,
        patch.object(cron_plane, "CronPlane") as plano,
    ):
        assert cron_plane.main() == 0

    configurar.assert_called_once()
    plano.assert_not_called()  # sin el plano declarado no corre nada


def test_sigterm_suelta_los_locks_y_sale_sin_esperar_al_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una pasada dura hasta 140 min y un despliegue da segundos: si el hijo no
    soltara sus locks, el de la instancia nueva encontraría la pasada bloqueada."""
    monkeypatch.setenv("SCHEDULER_PLANE", "worker")
    plano = MagicMock(jobs=[MagicMock()])
    plano.jobs[0].name = "daily_atom"
    manejadores: dict[int, object] = {}

    with (
        patch.object(cron_plane, "configure_logging"),
        patch.object(cron_plane, "CronPlane", return_value=plano),
        patch.object(cron_plane.signal, "signal", side_effect=manejadores.__setitem__),
        patch("db.job_locks.release_many") as soltar,
        patch.object(cron_plane.os, "_exit") as salir,
    ):
        assert cron_plane.main() == 0
        manejadores[cron_plane.signal.SIGTERM](cron_plane.signal.SIGTERM, None)  # type: ignore[operator]

    soltar.assert_called_once_with(["cron:daily_atom"], holder=cron_plane._holder())
    salir.assert_called_once_with(0)


def test_sigterm_sale_aunque_no_pueda_soltar_los_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con la BD caída el TTL los suelta; lo que no puede pasar es quedarse vivo."""
    monkeypatch.setenv("SCHEDULER_PLANE", "worker")
    manejadores: dict[int, object] = {}

    with (
        patch.object(cron_plane, "configure_logging"),
        patch.object(cron_plane, "CronPlane", return_value=MagicMock(jobs=[])),
        patch.object(cron_plane.signal, "signal", side_effect=manejadores.__setitem__),
        patch("db.job_locks.release_many", side_effect=RuntimeError("bd caída")),
        patch.object(cron_plane.os, "_exit") as salir,
    ):
        cron_plane.main()
        manejadores[cron_plane.signal.SIGTERM](cron_plane.signal.SIGTERM, None)  # type: ignore[operator]

    salir.assert_called_once_with(0)
