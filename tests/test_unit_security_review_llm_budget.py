"""Tests del presupuesto LLM por usuario (revisión de seguridad, hallazgo #4b).

Antes el acumulador era solo global: una cuenta agotaba la ventana diaria de
todas las demás. Aquí se fija que el tope por sujeto corta únicamente a quien
lo agota, que el global sigue cortando a todos, y que sin sujeto el guard se
comporta igual que antes.

Estilo heredado de ``tests/test_llm_budget.py``: reloj y Redis inyectados,
sin Postgres ni Redis reales.
"""

from __future__ import annotations

import pytest

from llm.budget import (
    BudgetGuard,
    LLMBudgetExceeded,
    bind_budget_subject,
    get_budget_guard,
    reset_budget_guard,
)

_T0 = 1_780_000_000.0  # epoch fijo (2026) — solo importa que sea estable

_ALICE = "a1b2c3d4e5f60718"  # forma de una user_key real (sha256[:16])
_BOB = "0918273645fedcba"


@pytest.fixture(autouse=True)
def _limpia_sujeto_de_contexto():
    """El sujeto vive en un ContextVar del proceso: sin limpiarlo, un test que
    lo fija contamina el orden de ejecución del resto."""
    bind_budget_subject(None)
    yield
    bind_budget_subject(None)


class FrozenClock:
    def __init__(self, t: float = _T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class FakeRedis:
    """Mock mínimo de redis: incrbyfloat/expire/get sobre un dict."""

    def __init__(self) -> None:
        self.store: dict[str, float] = {}
        self.ttls: dict[str, int] = {}

    def incrbyfloat(self, key: str, amount: float) -> float:
        self.store[key] = self.store.get(key, 0.0) + amount
        return self.store[key]

    def expire(self, key: str, ttl: int) -> bool:
        self.ttls[key] = ttl
        return True

    def get(self, key: str) -> str | None:
        val = self.store.get(key)
        return None if val is None else str(val)


class BrokenRedis:
    """Redis que falla en toda operación — fuerza el fallback in-memory."""

    def incrbyfloat(self, *_a: object) -> float:
        raise ConnectionError("redis down")

    def expire(self, *_a: object) -> bool:
        raise ConnectionError("redis down")

    def get(self, *_a: object) -> str | None:
        raise ConnectionError("redis down")


def _guard(
    mode: str = "enforce",
    daily: float = 100.0,
    monthly: float = 1000.0,
    per_user: float = 1.0,
    redis_client: object | None = None,
) -> BudgetGuard:
    return BudgetGuard(
        daily_limit_usd=daily,
        monthly_limit_usd=monthly,
        daily_limit_usd_per_user=per_user,
        mode=mode,  # type: ignore[arg-type]  # BudgetMode es Literal; el default del helper es str
        clock=FrozenClock(),
        redis_client=FakeRedis() if redis_client is None else redis_client,
    )


# ── Tope por usuario: aísla al que se pasa ────────────────────────────────────


def test_tope_por_usuario_corta_solo_a_ese_usuario():
    g = _guard(per_user=1.0)
    g.record(1.5, _ALICE)

    with pytest.raises(LLMBudgetExceeded) as exc_info:
        g.check(_ALICE)
    assert exc_info.value.scope == "user"
    assert exc_info.value.window == "daily"

    g.check(_BOB)  # el gasto de alice no toca la cuota de bob


def test_gasto_de_un_usuario_no_se_acumula_en_la_clave_de_otro():
    g = _guard()
    g.record(0.4, _ALICE)
    g.record(0.1, _BOB)

    assert g.spent("daily", _ALICE) == pytest.approx(0.4)
    assert g.spent("daily", _BOB) == pytest.approx(0.1)
    # El acumulador global sigue viendo el total de ambos.
    assert g.spent("daily") == pytest.approx(0.5)


def test_tope_por_usuario_en_cero_lo_desactiva():
    g = _guard(per_user=0.0)
    # Muy por encima de cualquier tope per-usuario razonable, pero por debajo de
    # los globales (daily=100 / monthly=1000): así el único motivo posible de
    # corte sería el del sujeto, y con el tope en 0 no debe haberlo.
    g.record(50.0, _ALICE)
    g.check(_ALICE)  # misma convención que los topes globales


def test_excepcion_por_usuario_lo_dice_en_el_mensaje():
    g = _guard(per_user=0.5)
    g.record(0.6, _ALICE)
    with pytest.raises(LLMBudgetExceeded, match="de tu cuenta"):
        g.check(_ALICE)


# ── Tope global: sigue cortando a todos ───────────────────────────────────────


def test_tope_global_corta_a_todos_los_usuarios():
    g = _guard(daily=1.0, per_user=100.0)
    g.record(1.2, _ALICE)

    for subject in (_ALICE, _BOB, None):
        with pytest.raises(LLMBudgetExceeded) as exc_info:
            g.check(subject)
        assert exc_info.value.scope == "global"


def test_el_global_gana_sobre_el_del_usuario():
    """Ambas ventanas agotadas: el motivo reportado es el global, que es el
    que realmente corta a todo el mundo."""
    g = _guard(daily=1.0, per_user=0.5)
    g.record(1.2, _ALICE)
    with pytest.raises(LLMBudgetExceeded) as exc_info:
        g.check(_ALICE)
    assert exc_info.value.scope == "global"


# ── Regresión: sin sujeto, el comportamiento de antes ─────────────────────────


def test_sin_scope_key_solo_cuenta_el_global():
    g = _guard(daily=1.0, per_user=0.1)
    g.record(0.5)  # sin sujeto: no alimenta ninguna clave de usuario
    g.check()  # y sin sujeto tampoco se verifica ninguna
    assert g.spent("daily") == pytest.approx(0.5)
    assert g.spent("daily", _ALICE) == 0.0


def test_sin_scope_key_el_global_sigue_lanzando():
    g = _guard(daily=0.5, per_user=0.0)
    g.record(0.6)
    with pytest.raises(LLMBudgetExceeded) as exc_info:
        g.check()
    assert exc_info.value.scope == "global"


# ── Modo monitor: no corta ninguna de las dos dimensiones ─────────────────────


def test_monitor_no_corta_ni_el_global_ni_el_del_usuario():
    g = _guard(mode="monitor", daily=0.5, per_user=0.1)
    g.record(0.9, _ALICE)
    g.check(_ALICE)  # instrumenta ambas ventanas, no lanza
    g.check()


# ── Fallback in-memory (sin Redis) ────────────────────────────────────────────


def test_redis_roto_cae_a_memoria_y_aisla_a_cada_usuario():
    g = _guard(per_user=0.5, redis_client=BrokenRedis())
    g.record(0.6, _ALICE)  # incrbyfloat falla → in-memory
    with pytest.raises(LLMBudgetExceeded):
        g.check(_ALICE)
    g.check(_BOB)


def test_sin_redis_url_usa_memoria_para_el_tope_por_usuario(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "REDIS_URL", "", raising=False)
    g = BudgetGuard(
        daily_limit_usd=100.0,
        monthly_limit_usd=1000.0,
        daily_limit_usd_per_user=0.5,
        mode="enforce",
        clock=FrozenClock(),
    )
    g.record(0.7, _ALICE)
    with pytest.raises(LLMBudgetExceeded) as exc_info:
        g.check(_ALICE)
    assert exc_info.value.scope == "user"
    g.check(_BOB)


# ── Sujeto de contexto (atribución desde llm/client.py) ───────────────────────


def test_el_sujeto_del_contexto_atribuye_el_record(monkeypatch):
    """``_record_usage`` no ve al usuario: el borde HTTP lo deja en el contexto.

    ``monkeypatch.context()`` no aplica a contextvars, así que se restaura a
    mano para no contaminar los tests siguientes.
    """
    g = _guard(per_user=0.5)
    bind_budget_subject(_ALICE)
    try:
        g.record(0.6)  # sin scope_key explícito: lo toma del contexto
        with pytest.raises(LLMBudgetExceeded) as exc_info:
            g.check()
        assert exc_info.value.scope == "user"
    finally:
        bind_budget_subject(None)

    assert g.spent("daily", _ALICE) == pytest.approx(0.6)
    g.check(_BOB)


def test_el_scope_key_explicito_gana_sobre_el_del_contexto():
    g = _guard()
    bind_budget_subject(_ALICE)
    try:
        g.record(0.3, _BOB)
    finally:
        bind_budget_subject(None)
    assert g.spent("daily", _BOB) == pytest.approx(0.3)
    assert g.spent("daily", _ALICE) == 0.0


# ── Singleton ─────────────────────────────────────────────────────────────────


def test_get_budget_guard_pasa_el_tope_por_usuario(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "LLM_BUDGET_USD_DAILY_PER_USER", 3.5, raising=False)
    reset_budget_guard()
    try:
        assert get_budget_guard().daily_limit_usd_per_user == 3.5
    finally:
        reset_budget_guard()
