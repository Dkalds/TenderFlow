"""Drift de los modelos predictivos (Fase 6.3, RFC 20260611-2).

PSI por feature numérica entre la distribución de entrenamiento (bins
guardados en la metadata del modelo activo en el momento de entrenar... v1:
recalculada del dataset actual con corte en la fecha de entrenamiento) y la
distribución de las filas de scoring de hoy. Los umbrales son los de
:mod:`services.ml.thresholds`, que es **la** tabla del proyecto: <0.10 estable
· 0.10-0.25 seguimiento · >0.25 drift significativo → alerta por el canal
existente.

Además del PSI se vigila el **delta de nulos** por feature. El PSI compara
solo los valores presentes en ambos lados, así que era ciego al caso más grave
posible: una feature disponible al entrenar y ausente al servir. Ver
:data:`services.ml.thresholds.MISSING_DELTA_WARN`.

Los seis mecanismos de drift/anomalía del repo
----------------------------------------------
Se solapan de forma real —tres calculan un KS o un PSI sobre ``importe``— y
hasta ahora nadie podía saber, leyendo uno, qué hacían los otros cinco. La
tabla dice qué mide cada uno, cada cuánto corre y por dónde sale su resultado;
mientras sigan existiendo los seis, esta es la referencia:

===================================  ================================================================  ====================================  =========================================
Mecanismo                            Qué mide                                                          Cadencia                              Canal de salida
===================================  ================================================================  ====================================  =========================================
``scheduler.anomaly_alerts``         Anomalías **del dato ingerido** (importes fuera de N sigmas,       Diaria, paso ``anomaly_checks`` de    ``observability.alerts`` (email) + log
                                     duplicados, caídas de volumen): calidad de la ingesta, no          la pipeline canónica
                                     del modelo
``scheduler.concept_drift``          Términos **emergentes** (TF-IDF) que ``SAP_KEYWORDS`` no cubre,    Semanal, dentro de ``drift_checks``   Alerta + reentrenamiento condicional del
                                     y ``compute_psi`` sobre ``importe``; puede disparar                                                     clasificador SAP
                                     ``maybe_retrain_classifier``
``scheduler.drift_report``           KS/chi² de las **features de entrada** (importe, ccaa,             Semanal, ``drift_checks``             Resumen JSON en ``ops_events`` (durable)
                                     tecnología, estado) y de la distribución de ``ml_proba``                                                 + HTML/JSON local opcional
``scheduler.drift_monitor``          Orquestador del clasificador SAP: PSI de ``compute_psi`` +         Semanal, justo tras ``drift_report``  ``observability.alerts`` + log
                                     caída de F1 contra el feedback humano                                                                    estructurado
``services.ml.drift`` (este módulo)  PSI **por feature del modelo de baja** entre el dataset de         Diaria, dentro de ``run_scoring``     Log + ``observability.alerts``; el
                                     entrenamiento y las filas de scoring, más el delta de nulos        (``ml-scoring.yml``)                  estado viaja en el resumen del job
``scripts.audit_domain_truth``       Verdad del dato contra la fuente (no es drift: contrasta el        Programada, ``domain-truth.yml``      Informe + email
                                     corpus con PLACSP)
===================================  ================================================================  ====================================  =========================================

Los cuatro primeros vigilan al **clasificador SAP** o a la ingesta; solo este
módulo vigila los **modelos predictivos** (baja/retención). Consolidarlos es
trabajo de arquitectura pendiente; documentar el solape es el paso que evita
que un séptimo mecanismo nazca por no saber que ya había seis.
"""

from __future__ import annotations

from typing import Any

from observability.logging import get_logger
from services.ml.thresholds import (
    MISSING_DELTA_CRIT,
    MISSING_DELTA_WARN,
    PSI_CRIT,
    PSI_WARN,
)

log = get_logger(__name__)


def _numeric_features() -> tuple[str, ...]:
    """Columnas numéricas del dataset, derivadas del orden canónico.

    Se calcula desde ``FEATURE_COLUMNS`` en vez de mantener una lista paralela:
    una feature nueva entra en el monitor sola, sin que nadie tenga que
    acordarse de añadirla aquí.
    """
    from services.ml.features import CATEGORICAL_COLUMNS, FEATURE_COLUMNS

    return FEATURE_COLUMNS[len(CATEGORICAL_COLUMNS) :]


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
        missing_por_feature: dict[str, float] = {}
        for col in _numeric_features():
            ref = [float(f.features[col]) for f in entrenamiento if f.features.get(col) is not None]
            cur = [float(f.features[col]) for f in scoring if f.features.get(col) is not None]
            psi_por_feature[col] = round(_psi(ref, cur), 4)
            # Delta de nulos: positivo = falta más al servir que al entrenar.
            missing_ref = 1.0 - len(ref) / len(entrenamiento)
            missing_cur = 1.0 - len(cur) / len(scoring)
            missing_por_feature[col] = round(missing_cur - missing_ref, 4)

        peor = max(psi_por_feature.values(), default=0.0)
        peor_missing = max((abs(v) for v in missing_por_feature.values()), default=0.0)
        if peor >= PSI_CRIT or peor_missing >= MISSING_DELTA_CRIT:
            severity = "crit"
        elif peor >= PSI_WARN or peor_missing >= MISSING_DELTA_WARN:
            severity = "warn"
        else:
            severity = "ok"
        if severity != "ok":
            log.warning(
                "ml_drift_detected",
                severity=severity,
                psi=psi_por_feature,
                missing_delta=missing_por_feature,
            )
            try:
                from observability.alerts import notify

                notify(
                    "warn" if severity == "warn" else "error",
                    f"Drift en features del modelo de baja "
                    f"(PSI máx {peor:.2f}, delta de nulos máx {peor_missing:.0%})",
                    f"psi={psi_por_feature} missing_delta={missing_por_feature}",
                )
            except Exception:  # canal de alertas opcional
                log.debug("ml_drift_alert_channel_unavailable")
        return {
            "status": severity,
            "psi": psi_por_feature,
            "psi_max": peor,
            "missing_delta": missing_por_feature,
            "missing_delta_max": peor_missing,
        }
    except Exception as e:
        log.warning("ml_drift_check_failed", error=str(e))
        return {"status": "error", "error": str(e)}
