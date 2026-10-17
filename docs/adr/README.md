---
title: "Índice de ADR"
tags: [adr, indice, generado]
---

# Architecture Decision Records

Un ADR registra una decisión estructural que sigue rigiendo: qué se decidió, por
qué y qué se descartó. Cuándo hace falta uno nuevo lo dice
[AGENTS.md](../../AGENTS.md) §5 (post-flight, paso 3): cuando un cambio
contradice una decisión registrada aquí o un invariante de §3. Los RFC
(propuestas que se discuten antes de implementarse) viven en
[docs/rfc/](../rfc/README.md).

## Frontmatter

Cada ADR empieza con este bloque. El índice de abajo sale de él, y en Obsidian
son las propiedades de la nota:

```yaml
---
id: ADR-037
title: "Qué se decide, en una frase"
status: accepted        # proposed | accepted | rejected | superseded
date: 2026-10-17
deciders: "Nombre Apellido"
supersedes: "[[ADR-0NN-slug]]"            # opcional
superseded_by: "[[ADR-0NN-slug]]"         # obligatorio si status: superseded
superseded_parcialmente_por: "[[ADR-0NN-slug]]"  # opcional
related:
  - "[[ADR-0NN-slug]]"
tags: [adr]
---
```

Las referencias del frontmatter van como wikilink porque dentro de una propiedad
es el único formato que Obsidian convierte en link; en el cuerpo del ADR, en
cambio, los links son markdown relativos (`[ADR-022](ADR-022-frontera-de-persistencia.md)`),
que es lo que GitHub renderiza. `make check-agent-docs` rechaza un wikilink en
el cuerpo.

## Índice

<!-- BEGIN indice-adr (generado por scripts/gen_adr_index.py — no editar a mano) -->

**35 ADR**, de los cuales **30** están vigentes. `accepted` 30 · `rejected` 1 · `superseded` 4.

Esta tabla se genera con `python scripts/gen_adr_index.py` a partir del frontmatter de cada ADR; `make check-agent-docs` y la suite (`tests/test_unit_ratchet_indice_adr.py`) la verifican con `--check`. Un ADR sin `id` o `status` —o con un estado fuera del vocabulario— la hace fallar.

| Estado | Significado |
|---|---|
| `accepted` | Vigente. |
| `proposed` | Propuesto; todavía no rige. |
| `rejected` | Se evaluó y se descartó. |
| `superseded` | Sustituido por otro ADR (`superseded_by`). |

| ADR | Título | Estado | Fecha | Sustituido por |
|---|---|---|---|---|
| [ADR-001](ADR-001-sql-crudo-vs-orm.md) | SQL crudo vs ORM | `accepted` | 2024-01-01 | — |
| [ADR-002](ADR-002-streamlit-vs-fastapi-react.md) | Streamlit vs FastAPI + React | `accepted` | 2024-01-01 | — |
| [ADR-003](ADR-003-migraciones-caseras-plus-alembic.md) | Sistema de migraciones casero + plan Alembic | `accepted` | 2024-01-01 | — |
| [ADR-004](ADR-004-sqlite-turso-vs-postgres.md) | SQLite + Turso vs PostgreSQL | `superseded` | 2024-01-01 | [ADR-016](ADR-016-destino-persistencia-supabase.md) |
| [ADR-005](ADR-005-clustering-ctfidf-minibatch.md) | Clustering: MiniBatchKMeans + c-TF-IDF + stopwords externas | `accepted` | — | — |
| [ADR-006](ADR-006-etag-pdf-export-ratelimit-redis.md) | ETag middleware + async PDF export endpoint | `accepted` | 2026-05-19 | — |
| [ADR-007](ADR-007-services-domain-layer.md) | Capa `services/` como dominio compartido | `accepted` | 2026-05-19 | — |
| [ADR-008](ADR-008-consolidacion-migraciones-alembic.md) | Consolidación hacia Alembic como sistema canónico de migraciones | `accepted` | 2026-05-23 | — |
| [ADR-009](ADR-009-framework-conectores-multifuente.md) | Framework de conectores multi-fuente y namespacing de id_externo | `accepted` | 2026-06-11 | — |
| [ADR-0011](0011-cdc-debezium.md) | CDC con Debezium — Decisión y Alternativas | `rejected` | 2026-05-16 | — |
| [ADR-012](ADR-012-plano-unico-orquestacion.md) | Plano único de orquestación por entorno + convergencia de entrypoints | `accepted` | 2026-06-10 | [ADR-028](ADR-028-cola-de-trabajo-y-worker.md) (en parte) |
| [ADR-013](ADR-013-jerarquia-materializaciones-analiticas.md) | Jerarquía de materializaciones analíticas | `superseded` | 2026-06-10 | [ADR-017](ADR-017-camino-lectura-analitico.md) |
| [ADR-014](ADR-014-integridad-analitica-frontend.md) | Integridad analítica del frontend | `accepted` | 2026-06-22 | — |
| [ADR-015](ADR-015-identidad-tenderflow.md) | Identidad del producto — Tenderflow (plataforma genérica de licitaciones) | `accepted` | 2026-07-04 | — |
| [ADR-016](ADR-016-destino-persistencia-supabase.md) | Destino de persistencia: Supabase + psycopg3 | `accepted` | 2026-07-05 | — |
| [ADR-017](ADR-017-camino-lectura-analitico.md) | Camino de lectura analítico tras el cutover a Postgres | `superseded` | 2026-07-26 | [ADR-023](ADR-023-computo-en-vivo-agregacion-sql.md) |
| [ADR-018](ADR-018-paridad-motor-tests-produccion.md) | Paridad de motor entre la suite de tests y producción | `superseded` | 2026-07-26 | [ADR-021](ADR-021-retirada-sqlite.md) |
| [ADR-019](ADR-019-observabilidad-desplegada.md) | Observabilidad desplegada: Prometheus y Grafana en Render | `accepted` | 2026-07-26 | — |
| [ADR-020](ADR-020-retirada-turso.md) | Retirada de Turso/libSQL como backend cloud | `accepted` | 2026-07-26 | — |
| [ADR-021](ADR-021-retirada-sqlite.md) | Retirada de SQLite como backend soportado — mono-dialecto Postgres | `accepted` | 2026-07-27 | — |
| [ADR-022](ADR-022-frontera-de-persistencia.md) | Frontera de persistencia: qué es un repository y qué pasa con db/*.py | `accepted` | 2026-07-28 | — |
| [ADR-023](ADR-023-computo-en-vivo-agregacion-sql.md) | Cómputo en vivo del camino de lectura analítico: agregación SQL, no scan pandas en proceso | `accepted` | 2026-07-28 | [ADR-026](ADR-026-caminos-de-lectura-y-precedencia-tecnologica.md) (en parte) |
| [ADR-024](ADR-024-services-biblioteca-no-frontera.md) | services/ es biblioteca de dominio, no frontera obligatoria de persistencia | `accepted` | 2026-07-28 | — |
| [ADR-025](ADR-025-construccion-de-sql-y-pools.md) | Cómo se construye el SQL y cómo se abren las conexiones | `accepted` | 2026-08-10 | — |
| [ADR-026](ADR-026-caminos-de-lectura-y-precedencia-tecnologica.md) | Caminos de lectura analítica y precedencia de la señal tecnológica | `accepted` | 2026-09-03 | — |
| [ADR-027](ADR-027-backbone-de-eventos-outbox.md) | Un solo backbone de eventos: outbox sobre `domain_events` | `accepted` | 2026-09-06 | — |
| [ADR-028](ADR-028-cola-de-trabajo-y-worker.md) | Cola de trabajo y worker: un plano de cron, un plano de trabajo a demanda | `accepted` | 2026-09-06 | — |
| [ADR-029](ADR-029-almacen-de-objetos.md) | Almacén de objetos para binarios: se revoca «texto por página, sin blob store» | `accepted` | 2026-09-06 | — |
| [ADR-030](ADR-030-identidad-user-id-y-oidc.md) | La identidad interna es `user_id`; los proveedores OIDC son intercambiables | `accepted` | 2026-09-06 | — |
| [ADR-031](ADR-031-seguimiento-unificado.md) | Seguimiento unificado: una tabla `follows`, un control «Seguir» | `accepted` | 2026-09-06 | — |
| [ADR-032](ADR-032-semantica-del-importe-y-maestro-de-organos.md) | Semántica del importe y maestro de órganos | `accepted` | 2026-09-06 | — |
| [ADR-033](ADR-033-plano-de-cron-en-el-worker.md) | Plano de cron dentro del worker de Render | `accepted` | 2026-09-14 | — |
| [ADR-034](ADR-034-rls-por-tenant.md) | Aislamiento por organización en dos capas: filtro de aplicación + RLS por tenant | `accepted` | 2026-09-14 | — |
| [ADR-035](ADR-035-camino-de-peticion-sin-bloquear-el-event-loop.md) | El camino de cada petición no bloquea el event loop: cuota en Redis por defecto, ETag al cachear y consulta cancelada como 503 | `accepted` | 2026-09-25 | — |
| [ADR-036](ADR-036-acceso-interno-por-mcp.md) | Acceso interno por MCP con rol de solo lectura: un servicio aparte, OAuth propio y el SQL lo limita Postgres | `accepted` | 2026-10-15 | — |

<!-- END indice-adr -->
