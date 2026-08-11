"""Presupuestos de concurrencia compartidos (bulkheads).

Viven en ``shared/`` y no en ``api/`` porque los consumen los dos lados:
``api.concurrency`` (que envuelve el despacho al threadpool) y ``shared.cache``
(que ya ejecuta el handler en un thread dentro de su lock anti-estampida y solo
necesita el presupuesto). Tenerlos aquí evita que ``shared`` importe ``api``,
que sería una inversión de capas, y garantiza que ambos caminos comparten el
mismo limiter en vez de tener uno cada uno — dos presupuestos de 2 slots no
acotan a 2, acotan a 4.
"""

from __future__ import annotations

from anyio import CapacityLimiter

_ML_LIMITER: CapacityLimiter | None = None
_CPU_LIMITER: CapacityLimiter | None = None


def _limiter_tokens(setting_name: str, default: int) -> int:
    """Lee un tamaño de bulkhead de settings, con default si no está definido."""
    try:
        from config.settings import settings

        value = int(getattr(settings, setting_name, default))
    except Exception:
        return default
    return max(1, value)


def ml_limiter() -> CapacityLimiter:
    """Bulkhead de inferencia ML (``API_ML_TOKENS``)."""
    global _ML_LIMITER
    if _ML_LIMITER is None:
        _ML_LIMITER = CapacityLimiter(_limiter_tokens("API_ML_TOKENS", 2))
    return _ML_LIMITER


def cpu_limiter() -> CapacityLimiter:
    """Bulkhead de trabajo CPU-bound: agregación pandas (``API_CPU_BOUND_TOKENS``)."""
    global _CPU_LIMITER
    if _CPU_LIMITER is None:
        _CPU_LIMITER = CapacityLimiter(_limiter_tokens("API_CPU_BOUND_TOKENS", 2))
    return _CPU_LIMITER


def reset_limiters() -> None:
    """Descarta los limiters cacheados (tests que cambian settings)."""
    global _ML_LIMITER, _CPU_LIMITER
    _ML_LIMITER = None
    _CPU_LIMITER = None
