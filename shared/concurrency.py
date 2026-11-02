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
_KDF_LIMITER: CapacityLimiter | None = None

#: Contraseñas que se pueden estar hasheando o verificando a la vez. Argon2id con
#: los parámetros por defecto reserva 64 MiB por operación y mantiene 4 carriles
#: de CPU: con los 24 hilos del pool general serían 1,5 GiB sobre una instancia
#: de 2 GB. Tres bastan para cualquier login legítimo (~100 ms cada uno).
KDF_TOKENS = 3


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


def kdf_limiter() -> CapacityLimiter:
    """Bulkhead del KDF de contraseñas (:data:`KDF_TOKENS`): login y recuperación."""
    global _KDF_LIMITER
    if _KDF_LIMITER is None:
        _KDF_LIMITER = CapacityLimiter(KDF_TOKENS)
    return _KDF_LIMITER


def reset_limiters() -> None:
    """Descarta los limiters cacheados (tests que cambian settings)."""
    global _ML_LIMITER, _CPU_LIMITER, _KDF_LIMITER
    _ML_LIMITER = None
    _CPU_LIMITER = None
    _KDF_LIMITER = None
