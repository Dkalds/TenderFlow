"""Tests de llm/budget.py — presupuesto + breaker de coste LLM.

RFC 2026-06-30 (llm-dependencia-gestionada). Reloj inyectado y Redis falso
hand-rolled (sin fakeredis) para determinismo total.
"""

from __future__ import annotations

import pytest

from llm.budget import BudgetGuard, LLMBudgetExceeded, get_budget_guard, reset_budget_guard

_DAY = 86400.0
_T0 = 1_780_000_000.0  # epoch fijo (2026) — solo importa que sea estable


class FrozenClock:
    def __init__(self, t: float = _T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


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


def _guard(mode: str = "monitor", daily: float = 1.0, monthly: float = 10.0, **kw) -> BudgetGuard:
    return BudgetGuard(
        daily_limit_usd=daily,
        monthly_limit_usd=monthly,
        mode=mode,  # type: ignore[arg-type]
        clock=kw.pop("clock", FrozenClock()),
        redis_client=kw.pop("redis_client", FakeRedis()),
    )


def _metric(window: str, mode: str) -> float | None:
    try:
        from prometheus_client import REGISTRY
    except ImportError:
        return None
    val = REGISTRY.get_sample_value("llm_budget_exceeded_total", {"window": window, "mode": mode})
    return float(val) if val is not None else 0.0


# ── record / spent ────────────────────────────────────────────────────────────


def test_record_acumula_en_dia_y_mes():
    g = _guard()
    g.record(0.30)
    g.record(0.20)
    assert g.spent("daily") == pytest.approx(0.50)
    assert g.spent("monthly") == pytest.approx(0.50)


def test_record_ignora_costes_no_positivos():
    g = _guard()
    g.record(0.0)
    g.record(-1.0)
    assert g.spent("daily") == 0.0


def test_ventana_diaria_rota_con_el_reloj():
    clock = FrozenClock()
    g = _guard(clock=clock)
    g.record(0.9)
    clock.advance(_DAY)  # día siguiente: la clave diaria es otra
    assert g.spent("daily") == 0.0
    assert g.spent("monthly") == pytest.approx(0.9)  # el mes sigue acumulando


# ── check: monitor vs enforce ─────────────────────────────────────────────────


def test_monitor_no_corta_pero_instrumenta():
    before = _metric("daily", "monitor")
    g = _guard(mode="monitor", daily=0.5)
    g.record(0.6)
    g.check()  # no lanza
    after = _metric("daily", "monitor")
    if before is not None:
        assert after is not None and after - before == 1.0


def test_enforce_lanza_con_presupuesto_agotado():
    g = _guard(mode="enforce", daily=0.5)
    g.record(0.6)
    with pytest.raises(LLMBudgetExceeded) as exc_info:
        g.check()
    assert exc_info.value.window == "daily"
    assert exc_info.value.spent == pytest.approx(0.6)


def test_enforce_por_debajo_del_limite_no_lanza():
    g = _guard(mode="enforce", daily=1.0)
    g.record(0.99)
    g.check()


def test_enforce_ventana_mensual():
    clock = FrozenClock()
    g = _guard(mode="enforce", daily=100.0, monthly=1.0, clock=clock)
    g.record(1.5)
    clock.advance(_DAY)  # el día rota, el mes no
    with pytest.raises(LLMBudgetExceeded) as exc_info:
        g.check()
    assert exc_info.value.window == "monthly"


def test_limite_cero_desactiva_la_ventana():
    g = _guard(mode="enforce", daily=0.0, monthly=0.0)
    g.record(9999.0)
    g.check()  # sin límites → nunca lanza


# ── Fallback in-memory ────────────────────────────────────────────────────────


def test_redis_roto_cae_a_memoria_y_sigue_contando():
    g = _guard(mode="enforce", daily=0.5, redis_client=BrokenRedis())
    g.record(0.6)  # incrbyfloat falla → in-memory
    with pytest.raises(LLMBudgetExceeded):
        g.check()


def test_sin_redis_url_usa_memoria(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "REDIS_URL", "", raising=False)
    g = BudgetGuard(daily_limit_usd=0.5, monthly_limit_usd=5.0, mode="enforce")
    g.record(0.7)
    with pytest.raises(LLMBudgetExceeded):
        g.check()


# ── Singleton ─────────────────────────────────────────────────────────────────


def test_get_budget_guard_lee_settings(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "LLM_BUDGET_USD_DAILY", 2.5, raising=False)
    monkeypatch.setattr(settings, "LLM_BUDGET_MODE", "enforce", raising=False)
    reset_budget_guard()
    try:
        g = get_budget_guard()
        assert g.daily_limit_usd == 2.5
        assert g.mode == "enforce"
        assert g is get_budget_guard()  # singleton
    finally:
        reset_budget_guard()


# ── Integración con llm.client._record_usage ─────────────────────────────────


def test_record_usage_alimenta_el_presupuesto(monkeypatch):
    import llm.budget as budget_mod
    from llm.client import _record_usage

    g = _guard()
    monkeypatch.setattr(budget_mod, "_guard", g)
    # gpt-4o-mini: (0.15, 0.60) USD/Mtok → 1M input + 1M output = 0.75 USD
    _record_usage("gpt-4o-mini", "openai", {"input_tokens": 1_000_000, "output_tokens": 1_000_000})
    assert g.spent("daily") == pytest.approx(0.75)


def test_stream_llm_response_checkea_presupuesto(monkeypatch):
    import llm.budget as budget_mod
    from llm.client import stream_llm_response

    g = _guard(mode="enforce", daily=0.1)
    g.record(0.2)
    monkeypatch.setattr(budget_mod, "_guard", g)
    gen = stream_llm_response("pregunta de prueba", [], "gpt-4o-mini", [])
    with pytest.raises(LLMBudgetExceeded):
        next(gen)


# ── Endpoint /ask: 429 con enforce ────────────────────────────────────────────


@pytest.fixture()
def ask_client(api_db):
    from fastapi.testclient import TestClient

    from api.app import app
    from api.auth import create_api_key

    key = create_api_key("budget-test-key", scopes="ask:read")
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update({"X-API-Key": key})
    return client


def test_ask_devuelve_429_con_presupuesto_agotado(ask_client, monkeypatch):
    import llm.budget as budget_mod

    g = _guard(mode="enforce", daily=0.0001)
    g.record(1.0)
    monkeypatch.setattr(budget_mod, "_guard", g)

    resp = ask_client.post("/api/v1/ask", json={"question": "¿Cuántas licitaciones hay?"})

    assert resp.status_code == 429
    assert "Presupuesto LLM" in resp.json()["detail"]


def test_ask_en_monitor_no_corta(ask_client, monkeypatch):
    from unittest.mock import patch

    import llm.budget as budget_mod

    g = _guard(mode="monitor", daily=0.0001)
    g.record(1.0)
    monkeypatch.setattr(budget_mod, "_guard", g)

    with patch("api.routes.ask._retrieve_docs", return_value=[]):
        resp = ask_client.post("/api/v1/ask", json={"question": "¿Cuántas licitaciones hay?"})

    assert resp.status_code == 200  # monitor: instrumenta pero no corta
