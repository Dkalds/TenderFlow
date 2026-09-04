"""Tabla única de umbrales de drift del proyecto.

Los mismos dos números (``0.10`` de aviso, ``0.25`` de crítico para el PSI)
vivían copiados en ``scheduler/drift_monitor.py`` y en ``services/ml/drift.py``,
cada uno con su comentario diciendo que eran "los umbrales estándar del
proyecto". Dos copias de una constante que se presenta como estándar es una
invitación a que un día dejen de coincidir y a que dos paneles digan cosas
distintas del mismo dato.

Los valores no cambian respecto a los que había; lo único que cambia es que
ahora hay un solo sitio donde cambiarlos.

Referencia de los cortes de PSI (convención de la industria, no algo medido
sobre este corpus): <0.10 estable · 0.10-0.25 seguimiento · >0.25 drift
significativo.
"""

from __future__ import annotations

from typing import Final

# ── PSI (Population Stability Index) ─────────────────────────────────────────
PSI_WARN: Final = 0.10
PSI_CRIT: Final = 0.25

# ── Caída relativa de F1 contra las métricas de entrenamiento ────────────────
# Solo la usa el monitor del clasificador SAP (`scheduler.drift_monitor`), pero
# vive aquí para que la tabla de umbrales de drift sea una sola.
F1_DROP_WARN: Final = 0.03
F1_DROP_CRIT: Final = 0.10

# ── Delta de tasa de nulos por feature ───────────────────────────────────────
# El PSI compara solo los valores **presentes**, así que es ciego al caso más
# grave: una feature disponible al entrenar y ausente al servir. Es la
# asimetría que dejó `n_ofertas` con PSI 0.00 "estable" mientras el modelo se
# partía sobre una columna NaN en el 100% de las filas de scoring.
MISSING_DELTA_WARN: Final = 0.20
MISSING_DELTA_CRIT: Final = 0.50

# ── p-value de los tests de distribución (KS / chi²) ─────────────────────────
KS_ALPHA: Final = 0.05


def clasificar_psi(psi: float) -> str:
    """``"ok"`` | ``"warn"`` | ``"crit"`` para un PSI suelto."""
    if psi >= PSI_CRIT:
        return "crit"
    if psi >= PSI_WARN:
        return "warn"
    return "ok"


__all__ = [
    "F1_DROP_CRIT",
    "F1_DROP_WARN",
    "KS_ALPHA",
    "MISSING_DELTA_CRIT",
    "MISSING_DELTA_WARN",
    "PSI_CRIT",
    "PSI_WARN",
    "clasificar_psi",
]
