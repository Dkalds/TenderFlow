"""Base types for the scheduler job registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

# Plano de orquestación responsable de ejecutar un job (ADR-012).
#
# - ``loop``     — solo el long-running scheduler de Docker Compose.
# - ``actions``  — solo GitHub Actions (workflow propio con ``python -m``).
# - ``pipeline`` — lo ejecuta la pipeline canónica (``scheduler/pipeline_runs.py``),
#                  así que corre en cualquiera de los dos planos sin workflow propio.
#
# ``scripts/check_job_parity.py`` verifica en CI que la declaración coincide
# con la realidad: un job ``actions`` sin step que lo invoque es un job muerto
# en producción, que es exactamente el fallo que este campo previene.
Plane = Literal["loop", "actions", "pipeline"]


@dataclass(frozen=True)
class ScheduledJob:
    """Declarative description of a periodic scheduler job.

    Attributes:
        name: Unique identifier used in logs, metrics, and backoff tracking.
        fn: Zero-argument callable that executes the job's work.
        interval_env: Name of the environment variable that overrides the default interval.
        default_interval_minutes: Default interval between executions in minutes.
        initial_offset_minutes: Delay after scheduler start before first execution (minutes).
        heavy: If True, the job runs in a ``ProcessPoolExecutor`` (cancellable
            on timeout); otherwise it runs in a daemon thread.
        plane: Which orchestration plane is responsible for running this job
            in production. Checked by ``scripts/check_job_parity.py``.
        module: Module invocable with ``python -m`` when ``plane`` is
            ``actions``. Empty for the other planes.
    """

    name: str
    fn: Callable[[], Any]
    interval_env: str
    default_interval_minutes: float
    initial_offset_minutes: float = 0.0
    heavy: bool = False
    plane: Plane = "pipeline"
    module: str = ""
