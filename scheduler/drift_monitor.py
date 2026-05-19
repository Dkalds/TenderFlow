"""Drift monitor programado (F3).

Capa fina sobre :mod:`scheduler.concept_drift` y :mod:`scheduler.drift_report`
que orquesta la detección periódica y dispara alertas vía
:mod:`observability.alerts` cuando los KPIs degradan más de un umbral.

Concebido para ejecutarse desde APScheduler::

    from scheduler.drift_monitor import run_once
    run_once()              # cron diario (06:00 UTC)
"""

from __future__ import annotations

from dataclasses import dataclass

from observability.logging import get_logger

log = get_logger(__name__)

# Umbrales por defecto (sobrescribibles vía settings o args).
_PSI_WARN = 0.10
_PSI_CRIT = 0.25
_F1_DROP_WARN = 0.03   # caída relativa 3 %
_F1_DROP_CRIT = 0.10   # caída relativa 10 %


@dataclass
class DriftStatus:
    psi: float
    f1_drop: float
    severity: str  # "ok" | "warn" | "crit"
    detail: str


def _classify(psi: float, f1_drop: float) -> tuple[str, str]:
    if psi >= _PSI_CRIT or f1_drop >= _F1_DROP_CRIT:
        return "crit", f"PSI={psi:.3f} / Δf1={f1_drop:.3f} sobre umbral crítico"
    if psi >= _PSI_WARN or f1_drop >= _F1_DROP_WARN:
        return "warn", f"PSI={psi:.3f} / Δf1={f1_drop:.3f} sobre umbral de aviso"
    return "ok", "Sin drift relevante"


def run_once(model_name: str = "sap_classifier") -> DriftStatus:
    """Calcula PSI + drop F1 y notifica si supera el umbral.

    Devuelve el ``DriftStatus`` calculado (también escribe log estructurado).
    Las funciones de detección concretas viven en ``scheduler.concept_drift``;
    aquí sólo orquestamos.
    """
    try:
        from scheduler.concept_drift import compute_psi
    except ImportError as exc:
        log.warning("drift_monitor_psi_unavailable", error=str(exc))
        compute_psi = None  # type: ignore[assignment]

    try:
        from scheduler.drift_report import compute_f1_drop
    except ImportError:
        compute_f1_drop = None  # type: ignore[assignment]

    psi = float(compute_psi()) if compute_psi else 0.0
    f1_drop = float(compute_f1_drop(model_name)) if compute_f1_drop else 0.0

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
                title=f"[drift:{severity}] {model_name}",
                body=detail,
                severity=severity,
                tags={"model": model_name, "psi": str(round(psi, 3))},
            )
        except (ImportError, RuntimeError) as exc:
            log.warning("drift_monitor_notify_failed", error=str(exc))

    return status


__all__ = ["DriftStatus", "run_once"]
