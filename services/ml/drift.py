"""Drift de los modelos predictivos (Fase 6.3, RFC 20260611-2).

PSI por feature numérica entre la distribución de entrenamiento (bins
guardados en la metadata del modelo activo en el momento de entrenar... v1:
recalculada del dataset actual con corte en la fecha de entrenamiento) y la
distribución de las filas de scoring de hoy. Umbrales estándar del proyecto
(scheduler.drift_monitor): <0.10 estable · 0.10-0.25 seguimiento · >0.25
drift significativo → alerta por el canal existente.
"""

from __future__ import annotations

from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

_PSI_WARN = 0.10
_PSI_CRIT = 0.25
_NUMERIC_FEATURES = (
    "log_importe",
    "n_ofertas",
    "baja_media_organo",
    "baja_media_cpv4",
    "baja_media_organo_cpv4",
    "hhi_segmento",
)


def _psi(ref: list[float], cur: list[float], n_bins: int = 10, eps: float = 1e-6) -> float:
    """PSI entre dos muestras con bins por cuantiles de la referencia."""
    if len(ref) < 20 or len(cur) < 20:
        return 0.0
    ref_sorted = sorted(ref)
    cortes = [ref_sorted[int(len(ref_sorted) * i / n_bins)] for i in range(1, n_bins)]

    def _hist(valores: list[float]) -> list[float]:
        conteos = [0] * n_bins
        for v in valores:
            b = 0
            while b < len(cortes) and v >= cortes[b]:
                b += 1
            conteos[b] += 1
        total = len(valores)
        return [c / total for c in conteos]

    import math

    h_ref, h_cur = _hist(ref), _hist(cur)
    return sum(
        (pc - pr) * math.log((pc + eps) / (pr + eps)) for pr, pc in zip(h_ref, h_cur, strict=True)
    )


def comprobar_drift_baja() -> dict[str, Any]:
    """PSI de las features de scoring de hoy vs el dataset de entrenamiento.

    Fail-open: cualquier error se loguea y devuelve estado desconocido (el
    scoring no se bloquea por el monitor).
    """
    try:
        from services.ml.features import construir_dataset_baja, features_licitaciones_abiertas

        entrenamiento, _ = construir_dataset_baja()
        scoring = features_licitaciones_abiertas()
        if not entrenamiento or not scoring:
            return {"status": "sin_datos"}

        psi_por_feature: dict[str, float] = {}
        for col in _NUMERIC_FEATURES:
            ref = [float(f.features[col]) for f in entrenamiento if f.features.get(col) is not None]
            cur = [float(f.features[col]) for f in scoring if f.features.get(col) is not None]
            psi_por_feature[col] = round(_psi(ref, cur), 4)

        peor = max(psi_por_feature.values(), default=0.0)
        severity = "crit" if peor >= _PSI_CRIT else "warn" if peor >= _PSI_WARN else "ok"
        if severity != "ok":
            log.warning("ml_drift_detected", severity=severity, psi=psi_por_feature)
            try:
                from observability.alerts import notify

                notify(
                    "warn" if severity == "warn" else "error",
                    f"Drift en features del modelo de baja (PSI máx {peor:.2f})",
                    str(psi_por_feature),
                )
            except Exception:  # canal de alertas opcional
                log.debug("ml_drift_alert_channel_unavailable")
        return {"status": severity, "psi": psi_por_feature, "psi_max": peor}
    except Exception as e:
        log.warning("ml_drift_check_failed", error=str(e))
        return {"status": "error", "error": str(e)}
