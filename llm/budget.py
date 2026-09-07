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

Además del tope global hay un tope diario **por sujeto** (``scope_key``, la
``user_key`` opaca de ``shared/identity.py``): sin él una sola cuenta agota la
ventana de todos los demás, que es una denegación de servicio barata. Los
acumuladores viven en claves distintas, así que el gasto de un usuario nunca
enmascara el del resto. ``scope_key`` es opcional: sin sujeto el guard se
comporta exactamente como antes (solo global).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Literal

from observability.logging import get_logger
from observability.runtime_metrics import llm_budget_exceeded_total

log = get_logger(__name__)

_KEY_PREFIX = "llm:budget"
# TTLs holgados: la clave rota por fecha, el TTL solo evita basura en Redis.
_TTL_SECONDS = {"daily": 3 * 86400, "monthly": 40 * 86400}

BudgetMode = Literal["monitor", "enforce"]
BudgetScope = Literal["global", "user", "org"]

# Sujeto al que atribuir el gasto cuando el llamador no puede pasarlo explícito.
# El coste real solo se conoce dentro de ``llm/client.py::_record_usage``, que no
# recibe al usuario; el borde HTTP lo deja aquí antes de arrancar el stream.
_current_subject: ContextVar[str | None] = ContextVar("llm_budget_subject", default=None)
# Organización a la que atribuir el gasto (C2.9). Mismo mecanismo y mismo
# motivo que el de arriba: `llm/client.py::_record_usage` calcula el coste
# real y no recibe ni al usuario ni a su organización.
_current_org: ContextVar[str | None] = ContextVar("llm_budget_org", default=None)


def bind_budget_org(org_key: str | None) -> None:
    """Fija la organización del gasto para el contexto actual (C2.9).

    Gemela de :func:`bind_budget_subject`, con las mismas reglas: sin token de
    reset, pensada para un contexto ya copiado.
    """
    _current_org.set(org_key or None)


def bind_budget_subject(scope_key: str | None) -> None:
    """Fija el sujeto del gasto para el contexto actual, sin token de reset.

    Pensado para llamarse dentro de un contexto ya copiado (``asyncio.to_thread``
    copia el contexto por llamada), donde la mutación muere con el thread y no
    puede filtrarse a otra request. Fuera de ese caso usá ``scope_key`` explícito.
    """
    _current_subject.set(scope_key)


class LLMBudgetExceeded(RuntimeError):
    """El presupuesto LLM de una ventana está agotado (solo en modo enforce)."""

    def __init__(
        self, window: str, spent: float, limit: float, scope: BudgetScope = "global"
    ) -> None:
        self.window = window
        self.spent = spent
        self.limit = limit
        self.scope = scope
        # El mensaje llega al usuario en el 429: sin distinguir el ámbito, quien
        # agota su propia cuota cree que el servicio entero está caído.
        ambito = {
            "user": "de tu cuenta",
            "org": "de tu organización",
        }.get(scope, "global")
        super().__init__(
            f"Presupuesto LLM {window} {ambito} agotado "
            f"({spent:.4f} USD >= {limit:.4f} USD). "
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
        daily_limit_usd_per_user: float = 0.0,
        daily_limit_usd_per_org: float = 0.0,
        mode: BudgetMode = "monitor",
        clock: Callable[[], float] | None = None,
        redis_client: Any | None = None,
    ) -> None:
        self.daily_limit_usd = daily_limit_usd
        self.monthly_limit_usd = monthly_limit_usd
        self.daily_limit_usd_per_user = daily_limit_usd_per_user
        self.daily_limit_usd_per_org = daily_limit_usd_per_org
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

    def _key(self, window: str, scope_key: str | None = None) -> str:
        now = datetime.fromtimestamp(self._clock(), tz=UTC)
        stamp = now.strftime("%Y-%m-%d") if window == "daily" else now.strftime("%Y-%m")
        if scope_key:
            return f"{_KEY_PREFIX}:u:{scope_key}:{window}:{stamp}"
        return f"{_KEY_PREFIX}:{window}:{stamp}"

    def _org(self, org_key: str | None) -> str | None:
        """Organización efectiva: la explícita gana sobre la del contexto.

        El prefijo `org:` va aquí y en un solo sitio: sin él, una organización
        con id "7" y un usuario con `user_key` "7" compartirían acumulador.
        """
        efectiva = org_key or _current_org.get()
        return f"org:{efectiva}" if efectiva else None

    def _subject(self, scope_key: str | None) -> str | None:
        """Sujeto efectivo: el explícito gana sobre el del contexto."""
        return scope_key or _current_subject.get()

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

    def spent(self, window: str, scope_key: str | None = None) -> float:
        """Gasto acumulado (USD) de la ventana actual, global o del sujeto."""
        key = self._key(window, scope_key)
        client = self._get_redis()
        if client is not None:
            try:
                raw = client.get(key)
                return float(raw) if raw is not None else 0.0
            except Exception:
                self._drop_redis()
        return self._mem_get(key)

    def _incr(self, key: str, cost_usd: float, ttl: int) -> None:
        client = self._get_redis()
        if client is not None:
            try:
                client.incrbyfloat(key, cost_usd)
                # La clave rota por fecha: refrescar TTL es inofensivo.
                client.expire(key, ttl)
                return
            except Exception:
                self._drop_redis()
        self._mem_incr(key, cost_usd, ttl)

    def record(
        self, cost_usd: float, scope_key: str | None = None, org_key: str | None = None
    ) -> None:
        """Suma ``cost_usd`` al acumulado de ambas ventanas (best-effort).

        Con sujeto (explícito o del contexto) alimenta además su acumulador
        diario, y con organización el de ella. Solo los diarios: los topes por
        sujeto y por organización son diarios, y un contador mensual que nadie
        lee es estado que hay que purgar sin ganar nada.

        **Un cubo que no se alimenta nunca corta.** Es el modo de fallo de
        cualquier tope por ámbito: la comprobación existe, el límite está
        configurado, y el acumulador se queda en cero porque `record` no lo
        toca. Por eso el cubo de organización se escribe aquí y no solo se
        comprueba en `check`.
        """
        if cost_usd <= 0:
            return
        for window, ttl in _TTL_SECONDS.items():
            self._incr(self._key(window), cost_usd, ttl)
        subject = self._subject(scope_key)
        if subject:
            self._incr(self._key("daily", subject), cost_usd, _TTL_SECONDS["daily"])
        org = self._org(org_key)
        if org:
            self._incr(self._key("daily", org), cost_usd, _TTL_SECONDS["daily"])

    def _check_window(
        self, window: str, limit: float, scope: BudgetScope, subject: str | None
    ) -> None:
        if limit <= 0:
            return
        spent = self.spent(window, subject)
        if spent < limit:
            return
        # La métrica no tiene label de ámbito (su definición es de otro módulo):
        # el sufijo en `window` distingue las series sin tocar el contrato.
        label = window if scope == "global" else f"{window}_{scope}"
        llm_budget_exceeded_total.labels(window=label, mode=self.mode).inc()
        if self.mode == "enforce":
            raise LLMBudgetExceeded(window, spent, limit, scope=scope)
        log.warning(
            "llm_budget_exceeded_monitor",
            window=window,
            scope=scope,
            spent_usd=round(spent, 4),
            limit_usd=limit,
        )

    def check(self, scope_key: str | None = None, org_key: str | None = None) -> None:
        """Verifica los presupuestos; lanza :class:`LLMBudgetExceeded` en enforce.

        Con sujeto se verifica también su ventana diaria. El orden importa: los
        topes globales se evalúan primero porque agotarlos corta a todo el
        mundo, mientras que el del sujeto solo corta a ese usuario.

        En modo ``monitor`` no lanza: sube ``llm_budget_exceeded_total`` y
        loguea warning, para poder observar cuántas requests se habrían
        cortado antes de activar el enforcement.
        """
        self._check_window("daily", self.daily_limit_usd, "global", None)
        self._check_window("monthly", self.monthly_limit_usd, "global", None)
        # C2.9 — el cubo de la ORGANIZACIÓN va antes que el del usuario, por el
        # mismo criterio que pone el global el primero: agotar el de la
        # organización corta a todo su equipo, y el del usuario solo a uno. El
        # 429 dice cuál se agotó, así que quien lo recibe sabe si esperar o
        # hablar con su administrador.
        org = self._org(org_key)
        if org:
            self._check_window("daily", self.daily_limit_usd_per_org, "org", org)
        subject = self._subject(scope_key)
        if subject:
            self._check_window("daily", self.daily_limit_usd_per_user, "user", subject)


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
                    daily_limit_usd_per_user=settings.LLM_BUDGET_USD_DAILY_PER_USER,
                    daily_limit_usd_per_org=settings.LLM_BUDGET_USD_DAILY_PER_ORG,
                    mode=settings.LLM_BUDGET_MODE,
                )
    return _guard


def reset_budget_guard() -> None:
    """Descarta el singleton (para tests que cambian settings)."""
    global _guard
    with _guard_lock:
        _guard = None
