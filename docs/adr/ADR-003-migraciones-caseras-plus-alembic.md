---
id: ADR-003
title: "Sistema de migraciones casero + plan Alembic"
status: accepted
date: 2024-01-01
deciders: "Daniel Kalitovics"
tags: [adr]
---

# ADR-003: Sistema de migraciones casero + plan Alembic

**Status:** Accepted  
**Date:** 2024-01-01  
**Deciders:** Daniel Kalitovics

## Context

As the schema evolved, a mechanism was needed to apply changes in order,
track which versions had been applied, and provide rollback capability for
reversible changes.

## Decision

Use a **hand-rolled migration system** (`db/migrations.py`) for versions 1–13
(the baseline), and introduce **Alembic** (`db/alembic/`) for all new migrations
from v14 onwards.

## Rationale

### Why hand-rolled for v1–v13

- The system was written before Alembic was introduced; migrating the 13
  existing migrations retroactively would risk breaking production databases.
- The hand-rolled system is simple: a list of `(version, description, sql)`
  tuples, applied once, tracked in `schema_version`.
- Rollback SQL is co-located with the forward migration, making it easy to audit.

### Why Alembic for v14+

- Alembic provides auto-diff generation (`alembic revision --autogenerate`)
  which reduces human error when writing DDL.
- The Alembic revision history is reviewable via `alembic history` and
  deployable in CI without custom tooling.
- The cut-point (v14) is a clean separation: existing databases receive a
  `baseline001` stamp that tells Alembic "everything before this is already applied".

## Consequences

- **Positive:** No disruption to existing databases; Alembic handles new changes
  with better tooling.
- **Negative:** Two migration systems must coexist; developers must know which
  system governs which version range.
- **Operational procedure for new databases:**
  1. `apply_pending()` (runs v1–v13)
  2. `alembic stamp head` (marks baseline as applied)
  3. `alembic upgrade head` (applies any pending v14+ migrations)

## Known Issues Fixed

- **B3 (2026-05-09):** `apply_pending()` silently skipped SQL statements whose
  first non-blank line was a `--` comment. This caused migration v11's partial
  index (`idx_fail_unique_unresolved`) to never be created. Fixed by stripping
  comment lines before executing each statement.

## Alternatives Considered

| Alternative | Reason rejected |
|-------------|----------------|
| Migrate all 13 to Alembic | Risk of breaking existing prod DBs; high effort |
| Flyway | Java runtime dependency; overkill |
| Liquibase | XML/YAML schema definitions; mismatches with project style |
