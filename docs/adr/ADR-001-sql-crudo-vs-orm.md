---
id: ADR-001
title: "SQL crudo vs ORM"
status: accepted
date: 2024-01-01
deciders: "Daniel Kalitovics"
tags: [adr]
---

# ADR-001: SQL crudo vs ORM

**Status:** Accepted  
**Date:** 2024-01-01  
**Deciders:** Daniel Kalitovics

## Context

The project requires persistent storage for licitaciones, adjudicaciones, watchlist
entries, users, and operational metadata (extraction runs, KPI snapshots, etc.).
The two main options were raw SQL via `sqlite3` or an ORM (SQLAlchemy, Tortoise-ORM).

## Decision

Use **raw SQL via `sqlite3`** from the standard library with a hand-rolled migration
system (`db/migrations.py`).

## Rationale

- **Simplicity:** No additional dependency, no model classes to keep in sync with
  the schema, no ORM quirks.
- **SQLite-specific features:** FTS5 virtual tables, partial indexes with expressions
  (`WHERE resolved_at IS NULL`), and `INSERT OR REPLACE` are all straightforward
  in SQL but awkward through most ORMs.
- **Small team / prototype velocity:** Direct SQL is faster to iterate on when the
  schema evolves frequently.
- **Observability:** Query strings in logs are human-readable SQL rather than
  ORM-generated queries.

## Consequences

- **Positive:** Full control over SQL, easy to reason about index usage, no ORM
  overhead.
- **Negative:** No automatic migration diffing (Alembic was added for v14+), manual
  schema validation required, no built-in relationship traversal.
- **Migration path:** Alembic (`db/alembic/`) manages schema changes from v14+.
  The SQLAlchemy dependency that Alembic brings does NOT introduce ORM usage; only
  Alembic's DDL migration tooling is used.

## Alternatives Considered

| Alternative | Reason rejected |
|-------------|----------------|
| SQLAlchemy ORM | Added complexity without clear benefit for a single-DB, single-process app |
| Tortoise-ORM (async) | Async not needed; Streamlit runs synchronously |
| Peewee | Another dependency; raw SQL already sufficient |
