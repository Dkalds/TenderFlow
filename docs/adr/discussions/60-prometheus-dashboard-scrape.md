# Discussion: Issue #60 — Prometheus no scrapea el servicio dashboard

**Issue**: https://github.com/Dkalds/Licitaciones_sap_SP/issues/60
**RFC**: docs/rfc/060-prometheus-dashboard-scrape.md
**Date**: 2026-05-24

## Summary

Added Prometheus scrape target for the dashboard service. The dashboard registers in-process metrics via `observability.runtime_metrics` (FAISS rebuild, DB pool, etc.) but had no HTTP endpoint to expose them. Solution: `prometheus_client.start_http_server(9092)` in `dashboard/bootstrap.py`, new scrape job in `observability/prometheus.yml`, and a consistency fix (`service_started` → `service_healthy`) in `docker-compose.yml`.

## Decision rationale

- Simplest approach: reuse `prometheus_client.start_http_server` on a secondary port (9092) rather than trying to inject middleware into Streamlit or use textfile collector.
- Idempotent and gracefully degrading (no-op if `prometheus_client` not installed).
- No new dependencies required.

## Review outcome

- Reviewer: approved, minimal and clean change.
- Security triage: no concerns, port is container-internal only.
