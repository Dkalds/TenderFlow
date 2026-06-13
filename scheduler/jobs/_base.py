"""Base types for the scheduler job registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


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
    """

    name: str
    fn: Callable[[], Any]
    interval_env: str
    default_interval_minutes: float
    initial_offset_minutes: float = 0.0
    heavy: bool = False
