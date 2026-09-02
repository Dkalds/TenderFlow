"""Tests de scripts/check_job_parity.py y de los pasos periódicos de la pipeline.

El valor de un checker está en que **falle** cuando debe. Estos tests
construyen registries sintéticos con huecos deliberados y comprueban que los
detecta, además de cubrir la cadencia de ``_run_periodic``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_job_parity

from scheduler.jobs._base import ScheduledJob


def _job(name: str, **kw) -> ScheduledJob:
    defaults = {
        "fn": lambda: None,
        "interval_env": f"SCHEDULER_{name.upper()}_INTERVAL",
        "default_interval_minutes": 60.0,
    }
    return ScheduledJob(name=name, **{**defaults, **kw})


# ---------------------------------------------------------------------------
# El checker detecta huecos
# ---------------------------------------------------------------------------


def test_detects_actions_job_with_no_workflow():
    """Un job 'actions' cuyo módulo no invoca ningún workflow está muerto."""
    registry = [_job("fantasma", plane="actions", module="scheduler.jobs.inexistente")]
    with (
        patch.object(
            check_job_parity, "_modules_invoked_by_workflows", return_value=(set(), set())
        ),
        patch("scheduler.jobs.build_default_registry", return_value=registry),
    ):
        _rows, problems = check_job_parity.check()

    assert len(problems) == 1
    assert "job muerto en producción" in problems[0]


def test_detects_actions_job_without_module():
    registry = [_job("sin_modulo", plane="actions")]
    with (
        patch.object(
            check_job_parity, "_modules_invoked_by_workflows", return_value=(set(), set())
        ),
        patch("scheduler.jobs.build_default_registry", return_value=registry),
    ):
        _rows, problems = check_job_parity.check()

    assert len(problems) == 1
    assert "sin `module`" in problems[0]


def test_detects_pipeline_job_not_in_canonical_steps():
    """Es exactamente el fallo que tenía digest_daily antes de este cambio."""
    registry = [_job("huerfano", plane="pipeline")]
    with patch("scheduler.jobs.build_default_registry", return_value=registry):
        _rows, problems = check_job_parity.check()

    assert len(problems) == 1
    assert "no está en CANONICAL_STEPS" in problems[0]


def test_accepts_loop_only_job_as_explicit_decision():
    registry = [_job("solo_docker", plane="loop")]
    with patch("scheduler.jobs.build_default_registry", return_value=registry):
        rows, problems = check_job_parity.check()

    assert problems == []
    assert "docker-compose" in rows[0]["cubierto_por"]


# ---------------------------------------------------------------------------
# plane='manual' — dispatch-only a propósito (recent_bulk, 2026-08)
# ---------------------------------------------------------------------------


def test_accepts_manual_job_in_dispatch_only_workflow():
    """El caso de recent_bulk: no corre solo, y eso es la decisión."""
    registry = [_job("a_mano", plane="manual", module="scheduler.run_update")]
    with (
        patch.object(
            check_job_parity,
            "_modules_invoked_by_workflows",
            return_value=(set(), {"scheduler.run_update"}),
        ),
        patch("scheduler.jobs.build_default_registry", return_value=registry),
    ):
        rows, problems = check_job_parity.check()

    assert problems == []
    assert "workflow_dispatch" in rows[0]["cubierto_por"]


def test_detects_manual_job_with_no_dispatch_workflow():
    """Sin workflow que lo invoque no hay forma de dispararlo ni a mano."""
    registry = [_job("a_mano", plane="manual", module="scheduler.run_update")]
    with (
        patch.object(
            check_job_parity,
            "_modules_invoked_by_workflows",
            # Sólo aparece en workflows programados: no hay disparo manual.
            return_value=({"scheduler.run_update"}, set()),
        ),
        patch("scheduler.jobs.build_default_registry", return_value=registry),
    ):
        _rows, problems = check_job_parity.check()

    assert len(problems) == 1
    assert "ni a mano" in problems[0]


def test_detects_manual_job_without_module():
    registry = [_job("a_mano", plane="manual")]
    with (
        patch.object(
            check_job_parity, "_modules_invoked_by_workflows", return_value=(set(), set())
        ),
        patch("scheduler.jobs.build_default_registry", return_value=registry),
    ):
        _rows, problems = check_job_parity.check()

    assert len(problems) == 1
    assert "sin `module`" in problems[0]


def test_actions_job_only_in_dispatch_workflow_suggests_manual_plane():
    """El mensaje tiene que decir cuál es la salida, no sólo que está mal."""
    registry = [_job("mal_declarado", plane="actions", module="scheduler.run_update")]
    with (
        patch.object(
            check_job_parity,
            "_modules_invoked_by_workflows",
            return_value=(set(), {"scheduler.run_update"}),
        ),
        patch("scheduler.jobs.build_default_registry", return_value=registry),
    ):
        _rows, problems = check_job_parity.check()

    assert len(problems) == 1
    assert "plane='manual'" in problems[0]


def test_recent_bulk_is_declared_manual():
    """Gate anti-regresión: el bulk por meses no vuelve a tener cron.

    Si alguien lo re-declara ``actions``, ``test_real_registry_has_no_orphan_jobs``
    ya no basta — pasaría en verde porque ``daily_atom`` comparte ``module``.
    """
    from scheduler.jobs import build_default_registry

    bulk = next(j for j in build_default_registry() if j.name == "recent_bulk")
    assert bulk.plane == "manual"


# ---------------------------------------------------------------------------
# El registry real está limpio
# ---------------------------------------------------------------------------


def test_real_registry_has_no_orphan_jobs():
    """Gate anti-regresión: ningún job del registry sin plano real."""
    _rows, problems = check_job_parity.check()
    assert problems == [], "Jobs sin plano de ejecución:\n" + "\n".join(problems)


def test_wal_checkpoint_is_gone():
    """PRAGMA wal_checkpoint es SQLite-only; producción es Postgres."""
    from scheduler.jobs import build_default_registry

    assert "wal_checkpoint" not in {j.name for j in build_default_registry()}


# ---------------------------------------------------------------------------
# _run_periodic — cadencia propia dentro de la pipeline de 4h
# ---------------------------------------------------------------------------


def test_periodic_runs_once_then_skips_within_window(tmp_db):
    """Segunda pasada dentro de la ventana no re-ejecuta (bug del digest x6)."""
    from scheduler.pipeline_runs import _run_periodic

    llamadas = []

    def _fn():
        llamadas.append(1)

    assert _run_periodic("t_periodic", 3600, _fn) == "ok"
    assert _run_periodic("t_periodic", 3600, _fn) == "skipped"
    assert _run_periodic("t_periodic", 3600, _fn) == "skipped"
    assert len(llamadas) == 1


def test_periodic_releases_lock_on_failure(tmp_db):
    """Si falla, la siguiente pasada reintenta en vez de perder la ventana."""
    from scheduler.pipeline_runs import _run_periodic

    def _boom():
        raise RuntimeError("fallo transitorio")

    with pytest.raises(RuntimeError):
        _run_periodic("t_retry", 3600, _boom)

    # El lock quedó liberado: la siguiente pasada vuelve a intentarlo.
    llamadas = []
    assert _run_periodic("t_retry", 3600, lambda: llamadas.append(1)) == "ok"
    assert len(llamadas) == 1


# ---------------------------------------------------------------------------
# El fix del bug de digests
# ---------------------------------------------------------------------------


def test_digests_step_drains_both_frequencies(tmp_db):
    from scheduler import pipeline_runs

    with (
        patch("scheduler.watchlist_alerts.send_pending_digests", return_value=0) as send,
        patch("scheduler.pipeline_runs._es_ventana_matinal", return_value=True),
    ):
        resultado = pipeline_runs._run_digests()

    assert resultado == {"immediate": "ok", "daily": "ok", "weekly": "ok"}
    assert {c.args[0] for c in send.call_args_list} == {"immediate", "daily", "weekly"}


def test_digests_fuera_de_la_ventana_solo_drena_inmediatas(tmp_db):
    """A las tres de la tarde no sale «el correo de la mañana», pero las
    inmediatas siguen saliendo en cada pasada."""
    from scheduler import pipeline_runs

    with (
        patch("scheduler.watchlist_alerts.send_pending_digests", return_value=0) as send,
        patch("scheduler.pipeline_runs._es_ventana_matinal", return_value=False),
    ):
        resultado = pipeline_runs._run_digests()

    assert resultado == {"immediate": "ok", "daily": "skipped", "weekly": "skipped"}
    assert [c.args[0] for c in send.call_args_list] == ["immediate"]


def test_digests_is_in_canonical_steps_after_watchlist_notify():
    """El orden importa: notify acumula en pending_digests, digests las drena."""
    from scheduler.pipeline_runs import CANONICAL_STEPS

    assert CANONICAL_STEPS.index("digests") > CANONICAL_STEPS.index("watchlist_notify")
