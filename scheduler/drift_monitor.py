"""Monitor de drift del clasificador SAP: PSI + caída de F1, con alerta.

Capa fina sobre :mod:`scheduler.concept_drift` y :mod:`scheduler.drift_report`
que calcula los dos KPIs y dispara alertas vía :mod:`observability.alerts`
cuando degradan más de un umbral (:mod:`services.ml.thresholds`).

Lo ejecuta :func:`run_drift_checks` desde el paso ``drift_checks`` de la
pasada canónica (``scheduler/pipeline_pasos_impl.py``): **una vez por
semana** (ventana de ``db.job_locks``) y **advisory** (un fallo no saca la
pasada en rojo). El job ``drift_report`` del registro (``scheduler/jobs``)
apunta a la misma función, así que ambos planos hacen lo mismo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from observability.logging import get_logger
from services.ml.thresholds import F1_DROP_CRIT, F1_DROP_WARN, PSI_CRIT, PSI_WARN

if TYPE_CHECKING:
    from collections.abc import Callable

log = get_logger(__name__)


@dataclass
class DriftStatus:
    psi: float
    f1_drop: float
    severity: str  # "ok" | "warn" | "crit"
    detail: str


def _classify(psi: float, f1_drop: float) -> tuple[str, str]:
    if psi >= PSI_CRIT or f1_drop >= F1_DROP_CRIT:
        return "crit", f"PSI={psi:.3f} / Δf1={f1_drop:.3f} sobre umbral crítico"
    if psi >= PSI_WARN or f1_drop >= F1_DROP_WARN:
        return "warn", f"PSI={psi:.3f} / Δf1={f1_drop:.3f} sobre umbral de aviso"
    return "ok", "Sin drift relevante"


def run_once(model_name: str = "sap_classifier") -> DriftStatus:
    """Calcula PSI + drop F1 y notifica si supera el umbral.

    Devuelve el ``DriftStatus`` calculado (también escribe log estructurado).
    Las funciones de detección concretas viven en ``scheduler.concept_drift``;
    aquí sólo orquestamos.
    """
    # Declaradas antes del import: si falla quedan en ``None``, y sin la
    # anotación mypy fija el tipo de la función importada y rechaza ese ``None``.
    compute_psi: Callable[[], float] | None
    compute_f1_drop: Callable[[str], float] | None

    try:
        from scheduler.concept_drift import compute_psi
    except ImportError as exc:
        log.warning("drift_monitor_psi_unavailable", error=str(exc))
        compute_psi = None

    try:
        from scheduler.drift_report import compute_f1_drop
    except ImportError:
        compute_f1_drop = None

    psi = float(compute_psi()) if compute_psi is not None else 0.0
    f1_drop = float(compute_f1_drop(model_name)) if compute_f1_drop is not None else 0.0

    severity, detail = _classify(psi, f1_drop)
    status = DriftStatus(psi=psi, f1_drop=f1_drop, severity=severity, detail=detail)

    log.info(
        "drift_monitor_result",
        model=model_name,
        psi=round(psi, 4),
        f1_drop=round(f1_drop, 4),
        severity=severity,
    )

    if severity in ("warn", "crit"):
        try:
            from observability.alerts import notify

            notify(
                level=severity,
                title=f"[drift:{severity}] {model_name}",
                body=detail,
                tags={"model": model_name, "psi": str(round(psi, 3))},
            )
        except (ImportError, RuntimeError) as exc:
            log.warning("drift_monitor_notify_failed", error=str(exc))

    return status


def run_drift_checks() -> None:
    """Informe de drift de features y, después, este monitor con alertas.

    Punto de entrada único del paso ``drift_checks`` y del job ``drift_report``.
    """
    from scheduler.drift_report import run_drift_report

    run_drift_report()
    run_once()


__all__ = ["DriftStatus", "run_drift_checks", "run_once"]
