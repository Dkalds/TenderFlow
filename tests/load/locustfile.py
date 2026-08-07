"""Load test contra la API REST (E4 — Locust).

Uso::

    pip install locust
    LICITACIONES_API_KEY=xxx locust -f tests/load/locustfile.py \
        --host http://127.0.0.1:8080 -u 50 -r 5 -t 1m --headless

Métricas objetivo (SLO):
* p95 latency < 300 ms en ``/api/v1/licitaciones``
* p99 latency < 800 ms
* error rate < 0.5 %
* throughput > 100 req/s con 50 usuarios concurrentes
"""

from __future__ import annotations

import os
import random

from locust import HttpUser, between, task


class APIUser(HttpUser):
    """Simula un cliente externo consumiendo la API REST."""

    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        """Carga la API key desde el entorno."""
        api_key = os.environ.get("LICITACIONES_API_KEY")
        if not api_key:
            raise RuntimeError("LICITACIONES_API_KEY no configurada — abortando carga.")
        self.client.headers.update({"X-API-Key": api_key})

    @task(10)
    def list_licitaciones(self) -> None:
        """Endpoint más caliente: listado paginado."""
        self.client.get(
            "/api/v1/licitaciones",
            params={"limit": 50, "offset": random.randint(0, 1000)},
            name="/licitaciones%slimit&offset",
        )

    @task(5)
    def list_cursor(self) -> None:
        """Cursor pagination — más eficiente para offsets profundos."""
        self.client.get(
            "/api/v1/licitaciones/cursor",
            params={"limit": 50},
            name="/licitaciones/cursor",
        )

    @task(2)
    def health(self) -> None:
        """Health check (sin auth)."""
        with self.client.get("/api/v1/health", catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"Health falló: {r.status_code}")

    @task(1)
    def filter_by_tech(self) -> None:
        """Filtro frecuente: por tecnología SAP."""
        self.client.get(
            "/api/v1/licitaciones",
            params={"tecnologia": random.choice(["S/4HANA", "FIORI", "BTP"])},
            name="/licitaciones?tecnologia",
        )
