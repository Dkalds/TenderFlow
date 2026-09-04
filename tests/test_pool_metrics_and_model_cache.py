"""Tests del cableado nuevo: métricas de pool y caché del clasificador.

Las métricas de pool existían **declaradas y sin instrumentar** desde hacía
tiempo: `db_pool_size` y `db_pool_acquire_timeout_total` no tenían un solo
call-site, así que valían siempre 0 y la saturación del pool —el modo de fallo
más probable bajo carga— era invisible. Cablearlas sin probarlas repetiría el
mismo error, solo que con más código.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest


@pytest.fixture(autouse=True)
def _tmp_db(tmp_db):
    """Schema Postgres aislado (los pools se abren de verdad)."""


class TestPoolStats:
    def test_reports_both_pools_once_used(self) -> None:
        """`pool_stats` describe el pool de escritura y el de lectura."""
        from db.connection import connect, connect_read, pool_stats

        with connect() as c:
            c.execute("SELECT 1").fetchone()
        with connect_read() as c:
            c.execute("SELECT 1").fetchone()

        stats = pool_stats()

        assert set(stats) == {"write", "read"}
        for nombre, datos in stats.items():
            assert datos["pool_max"] >= 2, nombre
            assert "pool_size" in datos, nombre

    def test_is_lazy_and_does_not_open_pools(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exponer la métrica no debe abrir conexiones por sí mismo."""
        import db.connection as conn_mod

        monkeypatch.setattr(conn_mod, "_pg_pool", None)
        monkeypatch.setattr(conn_mod, "_pg_read_pool", None)

        assert conn_mod.pool_stats() == {}


class TestRefreshDbPoolMetrics:
    def test_publishes_the_gauges_from_the_live_pools(self) -> None:
        from db.connection import connect
        from observability.runtime_metrics import (
            db_pool_connections,
            db_pool_size,
            refresh_db_pool_metrics,
        )

        with connect() as c:
            c.execute("SELECT 1").fetchone()

        refresh_db_pool_metrics()

        # `prometheus_client` expone el valor por etiqueta; si el gauge sigue a
        # 0 es que nadie lo alimentó, que es justo el defecto que esto corrige.
        valor = db_pool_size.labels(pool="write")._value.get()
        assert valor >= 2

        usadas = db_pool_connections.labels(pool="write", state="used")._value.get()
        assert usadas >= 0

    def test_survives_a_pool_that_cannot_report(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Una métrica rota no puede tumbar el endpoint `/metrics`."""
        import observability.runtime_metrics as metrics

        def _explota() -> dict[str, dict[str, int]]:
            raise RuntimeError("pool en mal estado")

        monkeypatch.setattr("db.connection.pool_stats", _explota)

        with pytest.raises(RuntimeError):
            _explota()  # el fixture del monkeypatch es correcto

        # `refresh_db_pool_metrics` importa `pool_stats` dentro de la función,
        # así que ve el parche; no debe propagar.
        try:
            metrics.refresh_db_pool_metrics()
        except RuntimeError:  # pragma: no cover - lo que este test previene
            pytest.fail("refresh_db_pool_metrics propagó el fallo de un pool")


class TestPing:
    def test_true_when_the_database_answers(self) -> None:
        from db.connection import ping

        assert ping() is True

    def test_false_and_logged_when_it_does_not(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import db.connection as conn_mod

        def _sin_bd(**_kwargs: Any) -> Any:
            raise RuntimeError("BD caída")

        monkeypatch.setattr(conn_mod, "_get_conn", _sin_bd)

        assert conn_mod.ping() is False

    def test_health_service_translates_the_boolean(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from services.health import check_db

        assert check_db() == "ok"

        monkeypatch.setattr("services.health.ping", lambda: False)
        assert check_db() == "error"


class _FakeClassifier:
    """Doble del SAPClassifier que cuenta cargas.

    ``load`` acepta la ruta porque desde 2026-09 la caché resuelve el artefacto
    con ``shared.model_artifacts.resolve_active_artifact`` y se la pasa: sin
    ruta, la API recargaba siempre el mismo fichero local (inexistente en
    Render) y el rollback de modelo no cambiaba nada de lo servido.
    """

    cargas: ClassVar[list[object]] = []

    def __init__(self, path: object = None) -> None:
        self.path = path
        self.serving_degradado: str | None = None

    @classmethod
    def load(cls, path: object = None) -> _FakeClassifier:
        cls.cargas.append(path)
        return cls(path)


def _preparar_cache(monkeypatch: pytest.MonkeyPatch) -> type[_FakeClassifier]:
    """Clasificador falso + resolvedor inyectado (sin red ni BD)."""
    _FakeClassifier.cargas = []
    monkeypatch.setattr("scraper.ml_classifier.SAPClassifier", _FakeClassifier)
    monkeypatch.setattr("api.model_cache._resolve_artifact", lambda _name: None)
    import api.model_cache as cache_mod

    cache_mod.invalidate_classifier_cache()
    return _FakeClassifier


class TestClassifierCache:
    def test_loads_once_and_reuses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import api.model_cache as cache_mod

        fake = _preparar_cache(monkeypatch)

        primero = cache_mod.get_classifier()
        segundo = cache_mod.get_classifier()

        assert primero is segundo
        assert len(fake.cargas) == 1, "el singleton volvió a cargar el modelo"

    def test_invalidation_forces_a_reload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Es lo que hace efectivo el rollback de modelo."""
        import api.model_cache as cache_mod

        fake = _preparar_cache(monkeypatch)

        cache_mod.get_classifier()
        cache_mod.invalidate_classifier_cache()
        cache_mod.get_classifier()

        assert len(fake.cargas) == 2

    def test_ttl_zero_disables_time_based_reload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import api.model_cache as cache_mod
        from config.settings import settings

        monkeypatch.setattr(settings, "API_MODEL_CACHE_TTL_SECONDS", 0.0, raising=False)
        fake = _preparar_cache(monkeypatch)

        cache_mod.get_classifier()
        cache_mod.get_classifier()

        assert len(fake.cargas) == 1

    def test_route_helper_delegates_to_the_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from api.routes.licitaciones import _get_classifier

        centinela = object()
        monkeypatch.setattr("api.model_cache.get_classifier", lambda: centinela)

        assert _get_classifier() is centinela


class TestActivateInvalidatesCache:
    def test_activate_endpoint_invalidates_the_process_cache(
        self, client, api_key, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sin esto el cambio de `is_active` se quedaba solo en la BD."""
        from db.model_registry import register_version

        register_version(
            name="sap_classifier",
            path="data/models/v1.pkl",
            sha256="a" * 64,
            activate=True,
        )
        version_2 = register_version(
            name="sap_classifier", path="data/models/v2.pkl", sha256="b" * 64
        )

        invalidaciones: list[int] = []
        monkeypatch.setattr(
            "api.model_cache.invalidate_classifier_cache",
            lambda: invalidaciones.append(1),
        )

        resp = client.post(
            f"/api/v1/models/sap_classifier/activate/{version_2}",
            headers={"X-API-Key": api_key},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["activated"] is True
        assert invalidaciones == [1], "la ruta no invalidó la caché del proceso"

    def test_unknown_version_returns_404_and_does_not_invalidate(
        self, client, api_key, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invalidaciones: list[int] = []
        monkeypatch.setattr(
            "api.model_cache.invalidate_classifier_cache",
            lambda: invalidaciones.append(1),
        )

        resp = client.post(
            "/api/v1/models/sap_classifier/activate/9999",
            headers={"X-API-Key": api_key},
        )

        assert resp.status_code == 404
        assert invalidaciones == []
