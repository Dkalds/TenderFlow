"""Presupuesto de gasto LLM + circuit-breaker de coste.

RFC 2026-06-30 (llm-dependencia-gestionada): el RFC de tokens cerró la
*medición* (``llm_cost_usd_total``); este módulo cierra la *política*.

- :class:`BudgetGuard` acumula el gasto por ventana (día/mes) en Redis
  (``INCRBYFLOAT`` + TTL, consistente con ADR-006) con fallback in-memory si
  Redis no está disponible.
- ``check()`` se llama antes de iniciar un stream LLM. Si una ventana está
  agotada: en modo ``enforce`` lanza :class:`LLMBudgetExceeded` (que ``/ask``
  traduce a 429); en modo ``monitor`` (default) solo sube la métrica
  ``llm_budget_exceeded_total`` y loguea — medir antes de cortar.
- ``record(cost_usd)`` lo alimenta ``llm/client.py::_record_usage`` con el
  mismo cálculo de coste que ya nutre ``llm_cost_usd_total``.

El estado por-ventana rota solo: las claves llevan la fecha (``YYYY-MM-DD`` /
``YYYY-MM``) y expiran por TTL, así que no hay que resetear contadores.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from observability.logging import get_logger
from observability.runtime_metrics import llm_budget_exceeded_total

log = get_logger(__name__)

_KEY_PREFIX = "llm:budget"
# TTLs holgados: la clave rota por fecha, el TTL solo evita basura en Redis.
_TTL_SECONDS = {"daily": 3 * 86400, "monthly": 40 * 86400}

BudgetMode = Literal["monitor", "enforce"]


class LLMBudgetExceeded(RuntimeError):
    """El presupuesto LLM de una ventana está agotado (solo en modo enforce)."""

    def __init__(self, window: str, spent: float, limit: float) -> None:
        self.window = window
        self.spent = spent
        self.limit = limit
        super().__init__(
            f"Presupuesto LLM {window} agotado ({spent:.4f} USD >= {limit:.4f} USD). "
            "Reintentá cuando la ventana rote o ampliá LLM_BUDGET_USD_*."
        )


class BudgetGuard:
    """Acumulador de gasto LLM por ventana con enforcement configurable.

    ``clock`` y ``redis_client`` son inyectables para tests deterministas
    (reloj congelado, Redis falso) sin dependencias nuevas.
    """

    def __init__(
        self,
        *,
        daily_limit_usd: float,
        monthly_limit_usd: float,
        mode: BudgetMode = "monitor",
        clock: Callable[[], float] | None = None,
        redis_client: Any | None = None,
    ) -> None:
        self.daily_limit_usd = daily_limit_usd
        self.monthly_limit_usd = monthly_limit_usd
        self.mode: BudgetMode = mode
        self._clock = clock or time.time
        self._redis = redis_client
        self._redis_resolved = redis_client is not None
        self._lock = threading.Lock()
        # Fallback in-memory: key -> (acumulado, expira_epoch).
        self._mem: dict[str, tuple[float, float]] = {}

    # ── Backend ──────────────────────────────────────────────────────────

    def _get_redis(self) -> Any | None:
        """Cliente Redis lazy desde settings; None si no hay o falló."""
        if self._redis_resolved:
            return self._redis
        self._redis_resolved = True
        from config import settings

        if not settings.REDIS_URL:
            return None
        try:
            import redis as _redis

            self._redis = _redis.Redis.from_url(
                settings.REDIS_URL,
                password=settings.REDIS_PASSWORD.get_secret_value() or None,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
        except Exception:
            log.warning("llm_budget_redis_unavailable_fallback_memory", exc_info=True)
            self._redis = None
        return self._redis

    def _drop_redis(self) -> None:
        """Una operación Redis falló: degradar a in-memory para este proceso."""
        log.warning("llm_budget_redis_error_fallback_memory")
        self._redis = None
        self._redis_resolved = True

    # ── Claves por ventana ───────────────────────────────────────────────

    def _key(self, window: str) -> str:
        now = datetime.fromtimestamp(self._clock(), tz=UTC)
        stamp = now.strftime("%Y-%m-%d") if window == "daily" else now.strftime("%Y-%m")
        return f"{_KEY_PREFIX}:{window}:{stamp}"

    # ── In-memory fallback ───────────────────────────────────────────────

    def _mem_incr(self, key: str, amount: float, ttl: int) -> None:
        now = self._clock()
        with self._lock:
            current, expires = self._mem.get(key, (0.0, now + ttl))
            if expires <= now:
                current, expires = 0.0, now + ttl
            self._mem[key] = (current + amount, expires)
            # Poda de claves rotadas para que el dict no crezca sin límite.
            expired = [k for k, (_, exp) in self._mem.items() if exp <= now]
            for k in expired:
                del self._mem[k]

    def _mem_get(self, key: str) -> float:
        now = self._clock()
        with self._lock:
            current, expires = self._mem.get(key, (0.0, 0.0))
            return current if expires > now else 0.0

    # ── API pública ──────────────────────────────────────────────────────

    def spent(self, window: str) -> float:
        """Gasto acumulado (USD) de la ventana actual."""
        key = self._key(window)
        client = self._get_redis()
        if client is not None:
            try:
                raw = client.get(key)
                return float(raw) if raw is not None else 0.0
            except Exception:
                self._drop_redis()
        return self._mem_get(key)

    def record(self, cost_usd: float) -> None:
        """Suma ``cost_usd`` al acumulado de ambas ventanas (best-effort)."""
        if cost_usd <= 0:
            return
        for window, ttl in _TTL_SECONDS.items():
            key = self._key(window)
            client = self._get_redis()
            if client is not None:
                try:
                    client.incrbyfloat(key, cost_usd)
                    # La clave rota por fecha: refrescar TTL es inofensivo.
                    client.expire(key, ttl)
                    continue
                except Exception:
                    self._drop_redis()
            self._mem_incr(key, cost_usd, ttl)

    def check(self) -> None:
        """Verifica los presupuestos; lanza :class:`LLMBudgetExceeded` en enforce.

        En modo ``monitor`` no lanza: sube ``llm_budget_exceeded_total`` y
        loguea warning, para poder observar cuántas requests se habrían
        cortado antes de activar el enforcement.
        """
        for window, limit in (
            ("daily", self.daily_limit_usd),
            ("monthly", self.monthly_limit_usd),
        ):
            if limit <= 0:
                continue
            spent = self.spent(window)
            if spent < limit:
                continue
            llm_budget_exceeded_total.labels(window=window, mode=self.mode).inc()
            if self.mode == "enforce":
                raise LLMBudgetExceeded(window, spent, limit)
            log.warning(
                "llm_budget_exceeded_monitor",
                window=window,
                spent_usd=round(spent, 4),
                limit_usd=limit,
            )


# ── Singleton por proceso ────────────────────────────────────────────────

_guard: BudgetGuard | None = None
_guard_lock = threading.Lock()


def get_budget_guard() -> BudgetGuard:
    """Guard singleton configurado desde settings (lazy)."""
    global _guard
    if _guard is None:
        with _guard_lock:
            if _guard is None:
                from config import settings

                _guard = BudgetGuard(
                    daily_limit_usd=settings.LLM_BUDGET_USD_DAILY,
                    monthly_limit_usd=settings.LLM_BUDGET_USD_MONTHLY,
                    mode=settings.LLM_BUDGET_MODE,
                )
    return _guard


def reset_budget_guard() -> None:
    """Descarta el singleton (para tests que cambian settings)."""
    global _guard
    with _guard_lock:
        _guard = None
