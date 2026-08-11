"""Tests para OLA 2 — performance y caching.

Cubre:
- Response cache (api/cache.py): hit/miss, TTL, invalidación
- Bulk endpoint POST /licitaciones/bulk-get
- Migración 24 (índice compuesto fecha/id)
- run_ml bulkhead (CapacityLimiter dedicado)
- X-Cache header en /meta/filters
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def app_and_client(api_db, monkeypatch):
    """App sobre el schema Postgres aislado del test."""
    monkeypatch.setenv("ENV", "dev")

    from api.app import app

    with TestClient(app, raise_server_exceptions=True) as client:
        yield app, client


@pytest.fixture()
def api_key(app_and_client):
    from api.auth import create_api_key

    return create_api_key("ola2-test", scopes="*")


# ── OLA 2.1: Cache in-memory ─────────────────────────────────────────────────


def test_cache_get_miss_returns_none():
    from api.cache import cache_clear_all, cache_get

    cache_clear_all()
    assert cache_get("nonexistent-key-xyz") is None


def test_cache_set_and_get():
    from api.cache import cache_clear_all, cache_get, cache_set

    cache_clear_all()
    cache_set("mykey", {"data": [1, 2, 3]}, ttl=60)
    result = cache_get("mykey")
    assert result == {"data": [1, 2, 3]}


def test_cache_ttl_expiry():
    import time

    from api.cache import cache_clear_all, cache_get, cache_set

    cache_clear_all()
    cache_set("expiring-key", "hello", ttl=0.01)  # 10ms TTL
    time.sleep(0.05)
    assert cache_get("expiring-key") is None


def test_cache_delete():
    from api.cache import cache_clear_all, cache_delete, cache_get, cache_set

    cache_clear_all()
    cache_set("del-key", "value", ttl=60)
    cache_delete("del-key")
    assert cache_get("del-key") is None


def test_cache_key_deterministic():
    from api.cache import cache_key

    k1 = cache_key("meta", "filters", "v1")
    k2 = cache_key("meta", "filters", "v1")
    k3 = cache_key("meta", "filters", "v2")
    assert k1 == k2
    assert k1 != k3
    assert k1.startswith("licsap:")


def test_meta_filters_returns_xcache_header(app_and_client, api_key):
    """GET /meta/filters debe devolver X-Cache: MISS en primera request y HIT en segunda."""
    from api.cache import cache_clear_all

    cache_clear_all()
    _, client = app_and_client
    headers = {"X-API-Key": api_key}

    r1 = client.get("/api/v1/meta/filters", headers=headers)
    assert r1.status_code == 200
    assert r1.headers.get("X-Cache") == "MISS"

    r2 = client.get("/api/v1/meta/filters", headers=headers)
    assert r2.status_code == 200
    assert r2.headers.get("X-Cache") == "HIT"


def test_meta_last_extraction_sirve_del_cache(app_and_client, api_key, monkeypatch):
    """La segunda llamada a /meta/last-extraction no vuelve a tocar la BD.

    El endpoint no lleva cabecera ``X-Cache``, así que el contador sobre el
    repositorio es lo que distingue un HIT de un MISS.
    """
    from api.cache import cache_clear_all

    cache_clear_all()
    _, client = app_and_client
    headers = {"X-API-Key": api_key}

    from db.repositories.licitaciones import LicitacionRepository

    llamadas = {"n": 0}
    original = LicitacionRepository.get_last_extraction_date

    def contando(self):
        llamadas["n"] += 1
        return original(self)

    monkeypatch.setattr(LicitacionRepository, "get_last_extraction_date", contando)

    r1 = client.get("/api/v1/meta/last-extraction", headers=headers)
    assert r1.status_code == 200
    assert "last_extraction" in r1.json()
    assert llamadas["n"] == 1

    r2 = client.get("/api/v1/meta/last-extraction", headers=headers)
    assert r2.status_code == 200
    assert r2.json() == r1.json()
    assert llamadas["n"] == 1, "la segunda llamada debía salir del caché"


def test_meta_last_extraction_cachea_corpus_vacio(app_and_client, api_key, monkeypatch):
    """``None`` (corpus vacío) es un valor cacheable, no un fallo de caché.

    Es el motivo por el que se cachea un ``dict`` y no el ``str`` pelado: con el
    valor desnudo, ``cache_get`` devolvería ``None`` tanto para "no hay entrada"
    como para "la entrada dice que no hay extracción", y el endpoint repetiría
    la consulta en cada petición justo cuando la tabla está vacía.
    """
    from api.cache import cache_clear_all

    cache_clear_all()
    _, client = app_and_client
    headers = {"X-API-Key": api_key}

    from db.repositories.licitaciones import LicitacionRepository

    llamadas = {"n": 0}

    def sin_datos(self):
        llamadas["n"] += 1
        return None

    monkeypatch.setattr(LicitacionRepository, "get_last_extraction_date", sin_datos)

    r1 = client.get("/api/v1/meta/last-extraction", headers=headers)
    assert r1.status_code == 200
    assert r1.json()["last_extraction"] is None

    r2 = client.get("/api/v1/meta/last-extraction", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["last_extraction"] is None
    assert llamadas["n"] == 1, "None debe cachearse igual que cualquier otro valor"


# ── OLA 2.3: Bulk endpoint ────────────────────────────────────────────────────


def test_bulk_get_empty_returns_empty(app_and_client, api_key):
    """bulk-get con IDs no existentes devuelve lista vacía."""
    _, client = app_and_client
    r = client.post(
        "/api/v1/licitaciones/bulk-get",
        json={"ids": ["NONEXISTENT-001", "NONEXISTENT-002"]},
        headers={"X-API-Key": api_key},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["items"] == []
    assert data["requested"] == 2


def test_bulk_get_deduplicates_ids(app_and_client, api_key, tmp_path):
    """IDs duplicados en el input deben contarse una sola vez."""
    _, client = app_and_client
    r = client.post(
        "/api/v1/licitaciones/bulk-get",
        json={"ids": ["ID-001", "ID-001", "ID-002"]},
        headers={"X-API-Key": api_key},
    )
    assert r.status_code == 200
    data = r.json()
    # requested debe ser 2 (deduplicado), no 3
    assert data["requested"] == 2


def test_bulk_get_requires_auth(app_and_client):
    """bulk-get sin API key debe devolver 401 o 403."""
    _, client = app_and_client
    r = client.post(
        "/api/v1/licitaciones/bulk-get",
        json={"ids": ["ID-001"]},
    )
    assert r.status_code in (401, 403)


def test_bulk_get_max_100_ids(app_and_client, api_key):
    """Más de 100 IDs debe devolver 422."""
    _, client = app_and_client
    r = client.post(
        "/api/v1/licitaciones/bulk-get",
        json={"ids": [f"ID-{i:04d}" for i in range(101)]},
        headers={"X-API-Key": api_key},
    )
    assert r.status_code == 422


def test_bulk_get_csv_format(app_and_client, api_key):
    """?format=csv devuelve Content-Type text/csv."""
    _, client = app_and_client
    r = client.post(
        "/api/v1/licitaciones/bulk-get?format=csv",
        json={"ids": ["NONEXISTENT-CSV"]},
        headers={"X-API-Key": api_key},
    )
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]


# ── OLA 2.4: Migración 24 ────────────────────────────────────────────────────


def test_cursor_pagination_index_exists(tmp_db):
    """Debe existir el índice compuesto que sostiene la cursor pagination.

    Se llama ``idx_lic_cursor`` sobre ``(fecha_publicacion DESC, id_externo)``,
    creado por la migración Alembic v21 (v24 es un no-op que lo documenta). El
    test asertaba antes ``idx_lic_fecha_id``, que era el nombre que le daba el
    sistema de migraciones casero de SQLite: nunca existió en Postgres, y el
    test pasaba porque corría sobre el otro motor. Justo la clase de
    divergencia que ADR-021 elimina.
    """
    db_mod, _ = tmp_db

    with db_mod.connect_read() as c:
        row = c.execute(
            "SELECT indexname FROM pg_indexes WHERE indexname = 'idx_lic_cursor'"
        ).fetchone()

    assert row is not None, "Índice idx_lic_cursor no encontrado"


# ── OLA 2.5: Bulkhead run_ml ─────────────────────────────────────────────────


def test_run_ml_bulkhead_exists():
    """run_ml debe estar exportado desde api.concurrency."""
    from api.concurrency import run_ml

    assert callable(run_ml)


def test_run_ml_capacity_limiter_is_2():
    """El CapacityLimiter de ML debe tener capacidad máxima de 2.

    El limiter pasó a `shared.concurrency` en 2026-08 para que `shared.cache`
    pudiera usar el mismo presupuesto sin importar `api` (inversión de capas);
    `api.concurrency` lo reexporta con nombre público.
    """
    import asyncio

    from api.concurrency import ml_limiter, reset_limiters

    async def _check():
        reset_limiters()
        return ml_limiter().total_tokens

    total = asyncio.run(_check())
    assert total == 2


def test_run_ml_executes_function():
    """run_ml debe ejecutar la función en el threadpool y devolver el resultado."""
    import asyncio

    from api.concurrency import run_ml

    async def _test():
        result = await run_ml(lambda: 42 * 2)
        return result

    assert asyncio.run(_test()) == 84
