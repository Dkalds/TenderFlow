# ADR-004: SQLite + Turso vs PostgreSQL

**Status:** Accepted  
**Date:** 2024-01-01  
**Deciders:** Daniel Kalitovics

## Context

The project needs a database that is easy to run locally (no server process),
simple to back up, and potentially accessible from multiple environments (local
dev, CI, a remote VPS). PostgreSQL and SQLite+Turso were evaluated.

## Decision

Use **SQLite** as the local storage engine with **Turso** (`libsql`) as an
optional remote replica for production deployments.

## Rationale

- **SQLite:**
  - Zero-config: a single file, no server process, trivially backed up with `cp`.
  - FTS5 and partial indexes cover all current query requirements.
  - The dataset (licitaciones for a single agency) is small enough that a single
    SQLite file fits in RAM comfortably.
  - Python's `sqlite3` stdlib module handles the connection; no extra dependency.

- **Turso (libsql):**
  - Provides a hosted replica for production access without managing a Postgres
    server.
  - The `libsql` Python driver is a drop-in replacement for `sqlite3` for most
    queries.
  - Edge deployments and branching are possible if needed.

## Consequences

- **Positive:** Local development requires no Docker, no service, no port.
  CI runs with an in-memory SQLite DB — fast and isolated.
- **Negative:**
  - SQLite's write concurrency is limited (single writer). Acceptable for the
    scraper-only write pattern (one pipeline run at a time).
  - `ALTER TABLE DROP COLUMN` is unsupported before SQLite 3.35; some migrations
    are irreversible as a result (see ADR-003).
  - Turso adds a managed-service dependency for production; outages affect
    read/write access.
- **Migration path:** If write concurrency becomes a bottleneck (e.g., multiple
  concurrent scrapers or a public API), migrate to PostgreSQL. The SQL is
  standard enough that most queries port directly; FTS5 would need to be
  replaced with `pg_trgm` or a dedicated search engine.

## Alternatives Considered

| Alternative | Reason rejected |
|-------------|----------------|
| PostgreSQL (self-hosted) | Server process overhead; more ops burden for a solo project |
| PostgreSQL (managed, e.g. Supabase) | Cost; more complexity than needed at current scale |
| DuckDB | Optimised for analytics, not OLTP; limited concurrent write support |
| MySQL/MariaDB | No meaningful advantage over PostgreSQL; less standard SQL |
