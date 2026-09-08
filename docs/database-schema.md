---
tags: [database, schema, generado]
---

# Esquema de base de datos

<!-- generado por scripts/gen_schema_doc.py — no editar a mano -->

Generado: 2026-09-08

Revisión Alembic aplicada: `v127_pursuit_attachments`.

Catálogo de una base Postgres recién migrada con `alembic upgrade head`. Se listan
las tablas de `public` agrupadas por familia, con sus columnas
(`information_schema.columns`, en orden de `ordinal_position`), sus claves primarias
y únicas (`pg_constraint`) y sus índices explícitos (`pg_indexes`, sin los que
respaldan una constraint porque ya se ven arriba). Quedan fuera a propósito la tabla
de control de Alembic, las claves ajenas y los `CHECK` —que se entienden mejor en la
migración que los declara— y, por supuesto, cualquier dato.

> Nota histórica: hasta 2026-09 este fichero se mantenía a mano y describía el esquema SQLite, su tabla virtual FTS5 y las versiones v1-v20 del sistema casero `db/migrations.py`, retirados por ADR-016 y ADR-021.

## Resumen

| Familia | Tablas | Columnas | Índices |
|---|---:|---:|---:|
| Licitaciones y fuente | 11 | 151 | 51 |
| Documentos y pliegos | 4 | 43 | 11 |
| Empresas y mercado | 6 | 34 | 8 |
| Organizaciones y oportunidades | 14 | 127 | 27 |
| Identidad, acceso y auditoría | 15 | 104 | 23 |
| Seguimiento y notificaciones | 12 | 125 | 24 |
| ML y predicciones | 7 | 55 | 13 |
| Operación y observabilidad | 6 | 46 | 11 |
| Otras | 18 | 138 | 22 |
| **Total** | **93** | **823** | **190** |

## Licitaciones y fuente

### `adjudicaciones`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `licitacion_id` | `text` | no |
| `nif` | `text` | sí |
| `nombre` | `text` | no |
| `provincia` | `text` | sí |
| `ccaa` | `text` | sí |
| `nuts_code` | `text` | sí |
| `importe_adjudicado` | `double precision` | sí |
| `importe_pagable` | `double precision` | sí |
| `fecha_adjudicacion` | `text` | sí |
| `es_pyme` | `integer` | sí |
| `n_ofertas_recibidas` | `integer` | sí |
| `oferta_minima` | `double precision` | sí |
| `oferta_maxima` | `double precision` | sí |
| `result_code` | `text` | sí |
| `result_description` | `text` | sí |
| `fecha_extraccion` | `text` | no |
| `empresa_id` | `integer` | sí |
| `lote_id` | `integer` | sí |

Claves: `PRIMARY KEY (id)`

Índices: `idx_adj_ccaa`, `idx_adj_ccaa_nombre`, `idx_adj_empresa`, `idx_adj_fecha`, `idx_adj_lic`, `idx_adj_nif`, `idx_adj_nombre_importe`, `idx_adjudicaciones_lote`, `uq_adjudicaciones_lic_lote_nif_importe` (único), `uq_adjudicaciones_lic_nif_importe_sin_lote` (único)

### `contrato_eventos`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `licitacion_id` | `text` | no |
| `tipo` | `text` | no |
| `fecha` | `text` | no |
| `campo` | `text` | sí |
| `valor_antes` | `text` | sí |
| `valor_despues` | `text` | sí |
| `importe_delta` | `double precision` | sí |
| `detalle` | `text` | sí |
| `history_id` | `integer` | sí |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_eventos_dedupe` (único), `idx_eventos_lic`, `idx_eventos_tipo`

### `extraction_runs`

| Columna | Tipo | Nulo |
|---|---|---|
| `run_id` | `text` | no |
| `started_at` | `text` | no |
| `ended_at` | `text` | sí |
| `duration_ms` | `integer` | sí |
| `status` | `text` | no |
| `months_attempted` | `integer` | sí |
| `months_ok` | `integer` | sí |
| `months_failed` | `integer` | sí |
| `licitaciones_nuevas` | `integer` | sí |
| `licitaciones_actualizadas` | `integer` | sí |
| `adjudicaciones` | `integer` | sí |
| `errores_parseo` | `integer` | sí |
| `errores_descarga` | `integer` | sí |
| `notas` | `text` | sí |

Claves: `PRIMARY KEY (run_id)`

Índices: `idx_runs_started`, `idx_runs_status`

### `failed_extractions`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `run_id` | `text` | sí |
| `fuente` | `text` | no |
| `scope` | `text` | sí |
| `error_type` | `text` | sí |
| `error_message` | `text` | sí |
| `payload_ref` | `text` | sí |
| `retry_count` | `integer` | sí |
| `resolved_at` | `text` | sí |
| `created_at` | `text` | no |
| `last_attempt_at` | `text` | sí |
| `exhausted_at` | `text` | sí |

Claves: `PRIMARY KEY (id)`

Índices: `idx_fail_exhausted`, `idx_fail_run`, `idx_fail_unique_unresolved` (único), `idx_fail_unresolved`

### `ingestion_cursors`

| Columna | Tipo | Nulo |
|---|---|---|
| `source` | `text` | no |
| `last_seen_updated` | `text` | sí |
| `last_entry_id` | `text` | sí |
| `etag` | `text` | sí |
| `last_modified` | `text` | sí |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (source)`

### `licitaciones`

| Columna | Tipo | Nulo |
|---|---|---|
| `id_externo` | `text` | no |
| `titulo` | `text` | no |
| `descripcion` | `text` | sí |
| `organo_contratacion` | `text` | sí |
| `importe` | `double precision` | sí |
| `moneda` | `text` | sí |
| `cpv` | `text` | sí |
| `tipo_contrato` | `text` | sí |
| `estado` | `text` | sí |
| `fecha_publicacion` | `text` | sí |
| `fecha_limite` | `text` | sí |
| `url` | `text` | sí |
| `raw_keywords` | `text` | sí |
| `provincia` | `text` | sí |
| `ccaa` | `text` | sí |
| `nuts_code` | `text` | sí |
| `duracion_valor` | `double precision` | sí |
| `duracion_unidad` | `text` | sí |
| `fecha_inicio` | `text` | sí |
| `fecha_fin` | `text` | sí |
| `prorroga_descripcion` | `text` | sí |
| `ml_proba` | `double precision` | sí |
| `tecnologia` | `text` | sí |
| `ml_tecnologias` | `text` | sí |
| `ml_proba_max` | `double precision` | sí |
| `ml_tech_principal` | `text` | sí |
| `fecha_actualizacion_fuente` | `text` | sí |
| `fuente` | `text` | no |
| `fecha_extraccion` | `text` | no |
| `search_vector` | `tsvector` | sí |
| `filter_version` | `text` | sí |
| `classifier_model_version` | `text` | sí |
| `inclusion_reason` | `text` | sí |
| `analysis_universe` | `text` | sí |
| `fecha_pub_d` | `date` | sí |
| `procedimiento` | `text` | sí |
| `tramitacion` | `text` | sí |
| `peso_precio_pct` | `double precision` | sí |
| `primera_extraccion` | `text` | sí |
| `importe_base_sin_iva` | `double precision` | sí |
| `importe_con_iva` | `double precision` | sí |
| `valor_estimado` | `double precision` | sí |
| `importe_tipo` | `text` | sí |
| `organo_id` | `integer` | sí |

Claves: `PRIMARY KEY (id_externo)`

Índices: `idx_ccaa`, `idx_cpv`, `idx_estado`, `idx_fecha_pub`, `idx_lic_clave_canonica_v101`, `idx_lic_cursor`, `idx_lic_fecha_act_fuente`, `idx_lic_fecha_extraccion`, `idx_lic_fecha_limite`, `idx_lic_fecha_pub_d`, `idx_lic_fecha_pub_tech`, `idx_lic_fuente`, `idx_lic_importe`, `idx_lic_importe_base_sin_iva`, `idx_lic_ml_proba`, `idx_lic_organo_id`, `idx_lic_tecnologia`, `idx_lic_universo_cpv`, `idx_licitaciones_analysis_lineage`, `idx_licitaciones_search_vector`, `idx_licitaciones_titulo_trgm`, `idx_ml_tech_principal`, `idx_organo`

### `licitaciones_duplicados`

| Columna | Tipo | Nulo |
|---|---|---|
| `licitacion_id` | `text` | no |
| `canonical_id` | `text` | no |
| `clave_match` | `text` | sí |
| `confianza` | `double precision` | no |
| `status` | `text` | no |
| `detectado_en` | `text` | no |
| `resolved_at` | `text` | sí |
| `resolved_by` | `text` | sí |

Claves: `PRIMARY KEY (licitacion_id)`

Índices: `idx_lic_dup_canonical`, `idx_lic_dup_status`

### `licitaciones_history`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `id_externo` | `text` | no |
| `captured_at` | `text` | no |
| `source` | `text` | sí |
| `snapshot_json` | `text` | no |
| `changed_fields` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_hist_externo`, `idx_lic_history_id_externo`, `idx_licitaciones_history_externo_date`

### `lotes`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `licitacion_id` | `text` | no |
| `numero` | `text` | no |
| `titulo` | `text` | sí |
| `cpv` | `text` | sí |
| `importe` | `double precision` | sí |
| `fecha_limite` | `text` | sí |
| `fecha_extraccion` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (licitacion_id, numero)`

Índices: `idx_lotes_licitacion`

### `resoluciones_recurso`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `tribunal` | `text` | no |
| `numero_resolucion` | `text` | no |
| `numero_recurso` | `text` | sí |
| `fecha` | `text` | sí |
| `expediente` | `text` | sí |
| `organo` | `text` | sí |
| `sentido` | `text` | sí |
| `url_pdf` | `text` | sí |
| `resumen` | `text` | sí |
| `licitacion_id` | `text` | sí |
| `fecha_extraccion` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (tribunal, numero_resolucion)`

Índices: `idx_resoluciones_fecha`, `idx_resoluciones_lic`, `idx_resoluciones_sentido`

### `source_ingestion_health`

| Columna | Tipo | Nulo |
|---|---|---|
| `source` | `text` | no |
| `status` | `text` | no |
| `last_started_at` | `text` | sí |
| `last_completed_at` | `text` | sí |
| `last_success_at` | `text` | sí |
| `fetched` | `integer` | no |
| `parsed` | `integer` | no |
| `discarded` | `integer` | no |
| `errors` | `integer` | no |
| `cursor_value` | `text` | sí |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (source)`

## Documentos y pliegos

### `documento_chunks`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `documento_id` | `integer` | no |
| `chunk_index` | `integer` | no |
| `texto` | `text` | no |
| `embedding` | `vector` | sí |
| `search_vector` | `tsvector` | sí |
| `embedding_model` | `text` | sí |
| `embedding_version` | `text` | sí |
| `page_number` | `integer` | sí |

Claves: `PRIMARY KEY (id)` · `UNIQUE (documento_id, chunk_index)`

Índices: `idx_documento_chunks_documento`, `idx_documento_chunks_embedding_hnsw`, `idx_documento_chunks_search_vector`, `idx_documento_chunks_version`

### `documento_pages`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `bigint` | no |
| `documento_id` | `integer` | no |
| `page_number` | `integer` | no |
| `texto` | `text` | no |
| `start_offset` | `integer` | no |
| `end_offset` | `integer` | no |
| `ocr` | `boolean` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (documento_id, page_number)`

Índices: `idx_documento_pages_document`

### `documentos`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `licitacion_id` | `text` | no |
| `tipo` | `text` | no |
| `uri` | `text` | no |
| `filename` | `text` | sí |
| `content_type` | `text` | sí |
| `size_bytes` | `integer` | sí |
| `sha256` | `text` | sí |
| `texto` | `text` | sí |
| `status` | `text` | no |
| `error_detail` | `text` | sí |
| `storage_key` | `text` | sí |
| `fetched_at` | `text` | sí |
| `created_at` | `text` | no |
| `updated_at` | `text` | no |
| `source_hash` | `text` | sí |
| `blob_key` | `text` | sí |

Claves: `PRIMARY KEY (id)` · `UNIQUE (licitacion_id, uri)`

Índices: `idx_documentos_blob_key`, `idx_documentos_licitacion`, `idx_documentos_status`, `idx_documentos_status_created`, `uq_documentos_lic_tipo_hash` (único)

### `tender_fact_sheets`

| Columna | Tipo | Nulo |
|---|---|---|
| `licitacion_id` | `text` | no |
| `status` | `text` | no |
| `extraction_version` | `text` | no |
| `model` | `text` | sí |
| `data_json` | `text` | sí |
| `field_count` | `integer` | no |
| `evidence_count` | `integer` | no |
| `error_detail` | `text` | sí |
| `extracted_at` | `text` | sí |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (licitacion_id)`

Índices: `idx_tender_fact_sheets_status`

## Empresas y mercado

### `empresa_aliases`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `empresa_id` | `integer` | no |
| `alias_normalizado` | `text` | no |
| `nif_variante` | `text` | sí |
| `fuente` | `text` | no |
| `confianza` | `double precision` | no |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_empresa_aliases_alias`, `idx_empresa_aliases_nif`, `idx_empresa_aliases_uniq` (único)

### `empresa_review_queue`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `nombre_original` | `text` | no |
| `alias_normalizado` | `text` | no |
| `nif` | `text` | sí |
| `candidato_empresa_id` | `integer` | sí |
| `score` | `double precision` | no |
| `status` | `text` | no |
| `created_at` | `text` | no |
| `resolved_at` | `text` | sí |
| `resolved_by` | `text` | sí |

Claves: `PRIMARY KEY (id)`

Índices: `idx_empresa_review_pending` (único), `idx_empresa_review_status`

### `empresas`

| Columna | Tipo | Nulo |
|---|---|---|
| `empresa_id` | `integer` | no |
| `nif_canonico` | `text` | sí |
| `nombre_canonico` | `text` | no |
| `es_ute` | `integer` | no |
| `es_pyme` | `integer` | sí |
| `grupo_id` | `integer` | sí |
| `created_at` | `text` | no |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (empresa_id)`

Índices: `idx_empresas_grupo`, `idx_empresas_nif` (único)

### `grupos_empresariales`

| Columna | Tipo | Nulo |
|---|---|---|
| `grupo_id` | `integer` | no |
| `nombre` | `text` | no |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (grupo_id)` · `UNIQUE (nombre)`

### `mat_clusters`

| Columna | Tipo | Nulo |
|---|---|---|
| `id_externo` | `text` | no |
| `cluster_id` | `integer` | no |
| `cluster_label` | `text` | no |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (id_externo)`

Índices: `idx_mat_clusters_cluster`

### `ute_miembros`

| Columna | Tipo | Nulo |
|---|---|---|
| `ute_empresa_id` | `integer` | no |
| `miembro_empresa_id` | `integer` | no |

Claves: `PRIMARY KEY (ute_empresa_id, miembro_empresa_id)`

## Organizaciones y oportunidades

### `organization_certifications`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organization_id` | `integer` | no |
| `created_at` | `timestamp with time zone` | no |
| `nombre` | `text` | no |
| `ambito` | `text` | no |
| `vigente_hasta` | `date` | sí |

Claves: `PRIMARY KEY (id)`

Índices: `ix_organization_certifications_org`

### `organization_invitations`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organization_id` | `integer` | no |
| `email` | `text` | no |
| `role` | `text` | no |
| `token_hash` | `text` | no |
| `invited_by_user_id` | `integer` | sí |
| `created_at` | `timestamp with time zone` | no |
| `expires_at` | `timestamp with time zone` | no |
| `accepted_at` | `timestamp with time zone` | sí |
| `accepted_user_id` | `integer` | sí |
| `revoked_at` | `timestamp with time zone` | sí |
| `revoked_by_user_id` | `integer` | sí |

Claves: `PRIMARY KEY (id)` · `UNIQUE (token_hash)`

Índices: `ix_organization_invitations_email_pendiente`, `uq_organization_invitations_pendiente` (único)

### `organization_memberships`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organization_id` | `integer` | no |
| `user_id` | `integer` | no |
| `role` | `text` | no |
| `status` | `text` | no |
| `invited_by_user_id` | `integer` | sí |
| `created_at` | `text` | no |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (organization_id, user_id)`

Índices: `idx_org_memberships_user_status`

### `organization_nifs`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organization_id` | `integer` | no |
| `nif` | `text` | no |
| `razon_social` | `text` | sí |
| `principal` | `boolean` | no |
| `created_by_user_id` | `integer` | sí |
| `created_at` | `timestamp with time zone` | no |
| `updated_at` | `timestamp with time zone` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (organization_id, nif)`

Índices: `ix_organization_nifs_nif`, `uq_organization_nifs_principal` (único)

### `organization_references`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organization_id` | `integer` | no |
| `created_at` | `timestamp with time zone` | no |
| `organo` | `text` | no |
| `importe_eur` | `numeric` | sí |
| `anio` | `integer` | no |
| `tecnologia` | `text` | sí |
| `expediente_id` | `text` | sí |

Claves: `PRIMARY KEY (id)`

Índices: `ix_organization_references_org`

### `organization_revenues`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organization_id` | `integer` | no |
| `created_at` | `timestamp with time zone` | no |
| `ejercicio` | `integer` | no |
| `importe_eur` | `numeric` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (organization_id, ejercicio)`

Índices: `ix_organization_revenues_org`

### `organization_team_profiles`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organization_id` | `integer` | no |
| `created_at` | `timestamp with time zone` | no |
| `rol` | `text` | no |
| `anios` | `numeric` | no |
| `cantidad` | `integer` | no |

Claves: `PRIMARY KEY (id)`

Índices: `ix_organization_team_profiles_org`

### `organizations`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `name` | `text` | no |
| `is_personal` | `boolean` | no |
| `personal_owner_user_id` | `integer` | sí |
| `created_by_user_id` | `integer` | sí |
| `settings_json` | `text` | no |
| `created_at` | `text` | no |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (personal_owner_user_id)`

### `pursuit_attachments`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `pursuit_id` | `integer` | no |
| `organization_id` | `integer` | no |
| `blob_key` | `text` | no |
| `filename` | `text` | no |
| `content_type` | `text` | no |
| `size_bytes` | `bigint` | no |
| `sha256` | `text` | no |
| `uploaded_by_user_id` | `integer` | sí |
| `indexable` | `boolean` | no |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (blob_key)`

Índices: `idx_pursuit_attachments_org`, `idx_pursuit_attachments_pursuit`

### `pursuit_comment_mentions`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `comment_id` | `integer` | no |
| `user_id` | `integer` | no |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_pursuit_comment_mentions_user`, `uq_pursuit_comment_mentions` (único)

### `pursuit_comments`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `pursuit_id` | `integer` | no |
| `organization_id` | `integer` | no |
| `author_user_id` | `integer` | sí |
| `body` | `text` | no |
| `idempotency_key` | `text` | sí |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_pursuit_comments_author`, `idx_pursuit_comments_pursuit_id`, `uq_pursuit_comments_idempotency` (único)

### `pursuit_events`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `pursuit_id` | `integer` | no |
| `organization_id` | `integer` | no |
| `event_type` | `text` | no |
| `actor_user_id` | `integer` | sí |
| `payload_json` | `text` | no |
| `idempotency_key` | `text` | sí |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_pursuit_events_org_created`, `idx_pursuit_events_pursuit_created`, `uq_pursuit_events_idempotency` (único)

### `pursuit_tasks`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `pursuit_id` | `integer` | no |
| `organization_id` | `integer` | no |
| `titulo` | `text` | no |
| `responsable_user_id` | `integer` | sí |
| `vence` | `text` | sí |
| `estado` | `text` | no |
| `created_at` | `text` | no |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_pursuit_tasks_agenda`, `idx_pursuit_tasks_pursuit`, `idx_pursuit_tasks_responsable`

### `pursuits`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organization_id` | `integer` | no |
| `licitacion_id` | `text` | no |
| `responsible_user_id` | `integer` | sí |
| `status` | `text` | no |
| `decision` | `text` | no |
| `decision_reason` | `text` | sí |
| `offer_price_eur` | `numeric` | sí |
| `outcome` | `text` | no |
| `awarded_amount_eur` | `numeric` | sí |
| `outcome_reason` | `text` | sí |
| `identified_at` | `text` | no |
| `decision_at` | `text` | sí |
| `submitted_at` | `text` | sí |
| `closed_at` | `text` | sí |
| `created_by_user_id` | `integer` | sí |
| `updated_by_user_id` | `integer` | sí |
| `created_at` | `text` | no |
| `updated_at` | `text` | no |
| `version` | `integer` | no |
| `next_action` | `text` | sí |
| `next_action_due` | `text` | sí |
| `score_al_abrir` | `smallint` | sí |
| `banda_al_abrir` | `text` | sí |
| `outcome_reason_code` | `text` | sí |
| `lote_numero` | `text` | sí |
| `desglose_al_abrir` | `text` | sí |

Claves: `PRIMARY KEY (id)`

Índices: `idx_pursuits_org_responsible`, `idx_pursuits_org_status_updated`, `idx_pursuits_outcome_reason_code`, `uq_pursuits_org_lic_lote` (único), `uq_pursuits_org_lic_sin_lote` (único)

## Identidad, acceso y auditoría

### `access_grants`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `kind` | `text` | no |
| `value` | `text` | no |
| `active` | `boolean` | no |
| `granted_by` | `integer` | sí |
| `created_at` | `timestamp with time zone` | no |
| `updated_at` | `timestamp with time zone` | no |
| `revoked_at` | `timestamp with time zone` | sí |

Claves: `PRIMARY KEY (id)` · `UNIQUE (kind, value)`

Índices: `ix_access_grants_active_kind_value`

### `access_log`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `user_id` | `integer` | sí |
| `email` | `text` | sí |
| `auth_method` | `text` | no |
| `logged_in_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_access_log_time`, `idx_access_log_user`

### `api_key_tiers`

| Columna | Tipo | Nulo |
|---|---|---|
| `tier` | `text` | no |
| `daily_quota` | `integer` | no |
| `per_minute_limit` | `integer` | no |
| `description` | `text` | sí |

Claves: `PRIMARY KEY (tier)`

### `api_keys`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `key_hash` | `text` | no |
| `name` | `text` | no |
| `created_at` | `text` | no |
| `last_used` | `text` | sí |
| `is_active` | `integer` | no |
| `expires_at` | `text` | sí |
| `prefix` | `text` | sí |
| `tier` | `text` | no |
| `user_id` | `integer` | sí |
| `scopes` | `text` | no |
| `organization_id` | `integer` | sí |
| `created_by` | `integer` | sí |

Claves: `PRIMARY KEY (id)` · `UNIQUE (key_hash)`

Índices: `idx_api_keys_hash`, `idx_api_keys_organization`, `idx_api_keys_user_id`

### `audit_chain_state`

| Columna | Tipo | Nulo |
|---|---|---|
| `chain_name` | `text` | no |
| `head_hash` | `text` | no |
| `entry_count` | `bigint` | no |
| `state_hmac` | `text` | no |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (chain_name)`

### `audit_log`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `user_key` | `text` | no |
| `session_hash` | `text` | no |
| `action` | `text` | no |
| `detail` | `text` | no |
| `created_at` | `text` | no |
| `prev_hash` | `text` | sí |
| `this_hash` | `text` | sí |
| `hash_version` | `text` | sí |

Claves: `PRIMARY KEY (id)`

Índices: `idx_audit_log_action`, `idx_audit_log_created_id`, `idx_audit_log_user`

### `csp_violations`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `blocked_uri` | `text` | sí |
| `violated_directive` | `text` | sí |
| `document_uri` | `text` | sí |
| `source_file` | `text` | sí |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_csp_created`

### `idempotency_keys`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `idem_key` | `text` | no |
| `endpoint` | `text` | no |
| `response_json` | `text` | no |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (idem_key, endpoint)`

Índices: `idx_idem_created`, `idx_idem_key`

### `password_reset_tokens`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `user_id` | `integer` | no |
| `token_hash` | `text` | no |
| `created_at` | `timestamp with time zone` | no |
| `expires_at` | `timestamp with time zone` | no |
| `used_at` | `timestamp with time zone` | sí |

Claves: `PRIMARY KEY (id)` · `UNIQUE (token_hash)`

Índices: `ix_password_reset_tokens_user_pending`

### `rate_limits`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `key` | `text` | no |
| `ts` | `double precision` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_rate_limits_expires`

### `sessions`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `token_hash` | `text` | no |
| `user_id` | `integer` | no |
| `created_at` | `text` | no |
| `expires_at` | `text` | no |
| `ip` | `text` | sí |
| `user_agent` | `text` | sí |
| `revoked` | `integer` | no |
| `revoked_at` | `text` | sí |
| `last_seen_at` | `text` | sí |
| `mfa_verified_at` | `text` | sí |

Claves: `PRIMARY KEY (id)` · `UNIQUE (token_hash)`

Índices: `idx_sessions_expires`, `idx_sessions_token`, `idx_sessions_user`

### `solicitudes_acceso`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `email` | `text` | no |
| `empresa` | `text` | sí |
| `mensaje` | `text` | sí |
| `origen` | `text` | sí |
| `estado` | `text` | no |
| `consentimiento_at` | `timestamp with time zone` | no |
| `created_at` | `timestamp with time zone` | no |

Claves: `PRIMARY KEY (id)`

Índices: `ix_solicitudes_acceso_estado_created`, `ux_solicitudes_acceso_pendiente_email` (único)

### `totp_recovery_codes`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `user_id` | `integer` | no |
| `code_hash` | `text` | no |
| `used` | `integer` | no |
| `used_at` | `text` | sí |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_recovery_user`

### `totp_secrets`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `user_id` | `integer` | no |
| `secret` | `text` | no |
| `confirmed` | `integer` | no |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (user_id)`

Índices: `idx_totp_user`

### `users`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `email` | `text` | sí |
| `oauth_provider` | `text` | sí |
| `oauth_sub` | `text` | sí |
| `display_name` | `text` | sí |
| `created_at` | `text` | no |
| `password_hash` | `text` | sí |
| `is_admin` | `integer` | no |
| `deactivated_at` | `text` | sí |
| `admin_granted_by` | `text` | sí |

Claves: `PRIMARY KEY (id)` · `UNIQUE (email)` · `UNIQUE (oauth_provider, oauth_sub)`

Índices: `idx_users_email`, `idx_users_oauth`

## Seguimiento y notificaciones

### `notification_reads`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `user_key` | `text` | no |
| `notification_id` | `text` | no |
| `read_at` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (user_key, notification_id)`

Índices: `idx_notif_reads_user`

### `pending_digests`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `user_key` | `text` | no |
| `recipient_email` | `text` | no |
| `entry_id` | `integer` | no |
| `licitacion_id` | `text` | no |
| `frequency` | `text` | no |
| `matched_at` | `text` | no |
| `sent` | `integer` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (entry_id, licitacion_id)`

Índices: `idx_pending_digests_recipient`

### `radar_dismissals`

| Columna | Tipo | Nulo |
|---|---|---|
| `user_key` | `text` | no |
| `id_externo` | `text` | no |
| `created_at` | `timestamp with time zone` | no |
| `score` | `smallint` | sí |
| `banda` | `text` | sí |
| `hasta` | `timestamp with time zone` | sí |
| `accion` | `text` | sí |
| `organization_id` | `integer` | sí |

Claves: `PRIMARY KEY (user_key, id_externo)`

Índices: `idx_radar_dismissals_user_hasta`

### `saved_filters`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `user_key` | `text` | no |
| `name` | `text` | no |
| `filters_json` | `text` | no |
| `created_at` | `text` | no |
| `organization_id` | `integer` | sí |
| `visibility` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (user_key, name)`

Índices: `idx_saved_filters_organization`, `idx_saved_filters_user`

### `user_notifications`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `user_key` | `text` | no |
| `created_at` | `text` | no |
| `type` | `text` | no |
| `title` | `text` | sí |
| `body` | `text` | sí |
| `licitacion_id` | `text` | sí |
| `rule_id` | `integer` | sí |
| `read_at` | `text` | sí |
| `organization_id` | `integer` | sí |

Claves: `PRIMARY KEY (id)` · `UNIQUE (user_key, licitacion_id, type)`

Índices: `idx_user_notif_user_read`, `idx_user_notifications_organization`

### `user_profiles`

| Columna | Tipo | Nulo |
|---|---|---|
| `user_key` | `text` | no |
| `weights_json` | `text` | sí |
| `afinidad_keywords_json` | `text` | sí |
| `cpvs_json` | `text` | sí |
| `ccaa_json` | `text` | sí |
| `importe_min` | `double precision` | sí |
| `importe_max` | `double precision` | sí |
| `updated_at` | `text` | no |
| `organization_id` | `integer` | sí |
| `visibility` | `text` | no |

Claves: `PRIMARY KEY (user_key)`

Índices: `idx_user_profiles_organization`

### `watchlist_cpv`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `user_key` | `text` | no |
| `cpv_prefix` | `text` | no |
| `keyword` | `text` | sí |
| `min_importe` | `double precision` | sí |
| `ccaa` | `text` | sí |
| `created_at` | `text` | no |
| `last_notified_at` | `text` | sí |
| `email` | `text` | sí |
| `user_id` | `integer` | sí |
| `frequency` | `text` | no |
| `organization_id` | `integer` | sí |
| `visibility` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (user_key, cpv_prefix, keyword, ccaa)`

Índices: `idx_watchlist_cpv_organization`, `idx_wl_user`, `idx_wl_user_id`

### `watchlist_empresas`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `user_key` | `text` | no |
| `empresa_id` | `integer` | no |
| `email` | `text` | sí |
| `frequency` | `text` | no |
| `created_at` | `text` | no |
| `last_notified_at` | `text` | sí |
| `organization_id` | `integer` | sí |
| `visibility` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (user_key, empresa_id)`

Índices: `idx_watchlist_empresas_organization`, `idx_wl_emp_user`

### `watchlist_items`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `user_key` | `text` | no |
| `user_id` | `integer` | sí |
| `id_externo` | `text` | no |
| `created_at` | `text` | no |
| `organization_id` | `integer` | sí |
| `visibility` | `text` | no |
| `nota` | `text` | sí |

Claves: `PRIMARY KEY (id)` · `UNIQUE (user_key, id_externo)`

Índices: `idx_watchlist_items_organization`, `idx_wl_items_user`

### `watchlist_rules`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `user_key` | `text` | no |
| `user_id` | `integer` | sí |
| `nombre` | `text` | sí |
| `keyword` | `text` | sí |
| `cpv` | `text` | sí |
| `min_importe` | `double precision` | sí |
| `ccaa` | `text` | sí |
| `frequency` | `text` | no |
| `active` | `integer` | no |
| `created_at` | `text` | no |
| `last_notified_at` | `text` | sí |
| `email` | `text` | sí |
| `organization_id` | `integer` | sí |
| `visibility` | `text` | no |
| `tecnologia` | `text` | sí |
| `organo` | `text` | sí |
| `organo_norm` | `text` | sí |
| `procedimiento` | `text` | sí |
| `tipo_contrato` | `text` | sí |
| `banda_min` | `text` | sí |
| `plazo_min_dias` | `integer` | sí |

Claves: `PRIMARY KEY (id)`

Índices: `idx_watchlist_rules_organization`, `idx_wl_rules_active`, `idx_wl_rules_user`

### `webhook_deliveries`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `webhook_id` | `integer` | no |
| `event_type` | `text` | no |
| `status_code` | `integer` | no |
| `success` | `integer` | no |
| `payload_size` | `integer` | no |
| `created_at` | `text` | no |
| `delivery_uid` | `text` | sí |
| `payload_json` | `text` | sí |
| `error_detail` | `text` | sí |
| `proximo_intento` | `text` | sí |
| `estado` | `text` | sí |
| `intentos` | `integer` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_wh_del_created`, `idx_wh_del_reintento`, `idx_wh_del_uid` (único), `idx_wh_del_webhook`

### `webhooks`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `name` | `text` | no |
| `url` | `text` | no |
| `secret` | `text` | no |
| `event_types` | `text` | no |
| `active` | `integer` | no |
| `created_at` | `text` | no |
| `last_triggered_at` | `text` | sí |
| `last_status` | `integer` | sí |
| `failure_count` | `integer` | no |
| `organization_id` | `integer` | sí |
| `created_by` | `integer` | sí |
| `formato` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_webhooks_active`, `idx_webhooks_organizacion`

## ML y predicciones

### `feature_store`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `entity_type` | `text` | no |
| `entity_id` | `text` | no |
| `feature_name` | `text` | no |
| `value_json` | `text` | no |
| `version` | `text` | no |
| `computed_at` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (entity_type, entity_id, feature_name, version)`

Índices: `idx_feature_store_entity`, `idx_feature_store_name`

### `licitacion_tecnologia_pliego`

| Columna | Tipo | Nulo |
|---|---|---|
| `licitacion_id` | `text` | no |
| `tecnologia` | `text` | no |
| `method` | `text` | no |
| `score` | `double precision` | no |
| `matched_terms` | `text` | sí |
| `evidence_json` | `text` | sí |
| `signal_version` | `text` | no |
| `computed_at` | `text` | no |
| `merged_at` | `text` | sí |

Claves: `PRIMARY KEY (licitacion_id, tecnologia, method)`

### `licitacion_tecnologia_score`

| Columna | Tipo | Nulo |
|---|---|---|
| `licitacion_id` | `text` | no |
| `tecnologia` | `text` | no |
| `probabilidad` | `real` | no |
| `threshold_aplicado` | `real` | no |
| `computed_at` | `text` | no |

Claves: `PRIMARY KEY (licitacion_id, tecnologia)`

Índices: `idx_lts_lic`, `idx_lts_tecnologia`

### `ml_feedback`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `expediente` | `text` | no |
| `relevante` | `integer` | no |
| `nota` | `text` | no |
| `created_at` | `text` | no |
| `tecnologia` | `text` | sí |
| `tecnologias_secundarias` | `text` | sí |
| `model_version` | `integer` | sí |
| `user_id` | `integer` | sí |
| `source` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_ml_feedback_created_at`, `idx_ml_feedback_expediente`, `idx_ml_feedback_source_human`, `idx_ml_feedback_tecnologia`, `idx_ml_feedback_user_id`

### `model_versions`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `name` | `text` | no |
| `version` | `integer` | no |
| `path` | `text` | no |
| `sha256` | `text` | no |
| `metrics_json` | `text` | no |
| `trained_at` | `text` | no |
| `trained_on_n_samples` | `integer` | sí |
| `trained_on_n_feedbacks` | `integer` | sí |
| `is_active` | `integer` | no |
| `notes` | `text` | sí |

Claves: `PRIMARY KEY (id)` · `UNIQUE (name, version)`

Índices: `idx_model_versions_active`

### `predicciones_baja`

| Columna | Tipo | Nulo |
|---|---|---|
| `licitacion_id` | `text` | no |
| `p10` | `double precision` | no |
| `p50` | `double precision` | no |
| `p90` | `double precision` | no |
| `model_version` | `integer` | sí |
| `computed_at` | `text` | no |
| `lote_id` | `integer` | sí |

Claves: `PRIMARY KEY (licitacion_id)`

Índices: `idx_pred_baja_computed`, `uq_pred_baja_lic_lote` (único)

### `predicciones_retencion`

| Columna | Tipo | Nulo |
|---|---|---|
| `licitacion_id` | `text` | no |
| `empresa_id` | `integer` | sí |
| `prob_retencion` | `double precision` | no |
| `riesgo_cambio` | `double precision` | no |
| `model_version` | `integer` | sí |
| `computed_at` | `text` | no |

Claves: `PRIMARY KEY (licitacion_id)`

Índices: `idx_pred_ret_riesgo`

## Operación y observabilidad

### `domain_events`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `event_type` | `text` | no |
| `aggregate_id` | `text` | no |
| `aggregate_type` | `text` | no |
| `payload_json` | `text` | no |
| `actor_id` | `integer` | sí |
| `created_at` | `text` | no |
| `organization_id` | `integer` | sí |
| `dispatched_at` | `text` | sí |

Claves: `PRIMARY KEY (id)`

Índices: `idx_domain_events_actor`, `idx_domain_events_aggregate`, `idx_domain_events_created`, `idx_domain_events_organizacion`, `idx_domain_events_pendientes`, `idx_domain_events_type`

### `feature_flags`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `name` | `text` | no |
| `enabled` | `integer` | no |
| `rollout_pct` | `integer` | no |
| `user_emails` | `text` | no |
| `description` | `text` | sí |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (name)`

### `job_locks`

| Columna | Tipo | Nulo |
|---|---|---|
| `name` | `text` | no |
| `acquired_at` | `text` | no |
| `expires_at` | `text` | no |
| `holder` | `text` | no |

Claves: `PRIMARY KEY (name)`

### `jobs`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `bigint` | no |
| `tipo` | `text` | no |
| `payload_json` | `text` | no |
| `organization_id` | `integer` | sí |
| `estado` | `text` | no |
| `intentos` | `integer` | no |
| `run_after` | `timestamp with time zone` | no |
| `locked_by` | `text` | sí |
| `locked_at` | `timestamp with time zone` | sí |
| `resultado_json` | `text` | sí |
| `error_detail` | `text` | sí |
| `created_at` | `timestamp with time zone` | no |
| `updated_at` | `timestamp with time zone` | no |

Claves: `PRIMARY KEY (id)`

Índices: `ix_jobs_corriendo`, `ix_jobs_organizacion`, `ix_jobs_pendientes`

### `kpi_snapshots`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `computed_at` | `text` | no |
| `metrica` | `text` | no |
| `dimension` | `text` | no |
| `valor` | `double precision` | sí |
| `valor_text` | `text` | sí |

Claves: `PRIMARY KEY (id)`

Índices: `idx_kpi_snapshots_fecha`

### `ops_events`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `ts` | `text` | no |
| `event_type` | `text` | no |
| `value` | `double precision` | sí |
| `plane` | `text` | sí |
| `pid` | `integer` | sí |
| `detail` | `text` | sí |

Claves: `PRIMARY KEY (id)`

Índices: `idx_ops_events_type_ts`

## Otras

### `asistente_feedback`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `pregunta_hash` | `text` | no |
| `modo` | `text` | no |
| `modelo` | `text` | sí |
| `licitacion_id` | `text` | sí |
| `voto` | `text` | no |
| `motivo` | `text` | sí |
| `pregunta_texto` | `text` | sí |
| `user_id` | `integer` | sí |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_asistente_feedback_created`, `idx_asistente_feedback_hash`

### `client_errors`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `fingerprint` | `text` | no |
| `origen` | `text` | sí |
| `ruta` | `text` | sí |
| `mensaje` | `text` | sí |
| `build` | `text` | sí |
| `ocurrencias` | `integer` | no |
| `primera_vez` | `text` | no |
| `ultima_vez` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_client_errors_fingerprint` (único), `idx_client_errors_ultima_vez`

### `contratos_cartera`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organization_id` | `integer` | no |
| `pursuit_id` | `integer` | no |
| `licitacion_id` | `text` | no |
| `fecha_inicio` | `text` | sí |
| `fecha_fin_efectiva` | `text` | sí |
| `fecha_fin_origen` | `text` | sí |
| `importe_adjudicado` | `double precision` | sí |
| `prorrogas_aplicadas` | `integer` | no |
| `renovacion_pursuit_id` | `integer` | sí |
| `created_at` | `text` | no |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (pursuit_id)`

Índices: `idx_cartera_org_fin`

### `cuentas_objetivo`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organization_id` | `integer` | no |
| `organo_nombre` | `text` | no |
| `organo_norm` | `text` | no |
| `organo_id` | `integer` | sí |
| `created_by_user_id` | `integer` | sí |
| `created_at` | `text` | no |
| `nota` | `text` | sí |

Claves: `PRIMARY KEY (id)` · `UNIQUE (organization_id, organo_norm)`

### `domain_event_dispatches`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `event_id` | `integer` | no |
| `canal` | `text` | no |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (event_id, canal)`

Índices: `idx_domain_event_dispatches_evento`

### `etiquetas`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organization_id` | `integer` | no |
| `nombre` | `text` | no |
| `nombre_norm` | `text` | no |
| `color` | `text` | no |
| `created_by_user_id` | `integer` | sí |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (organization_id, nombre_norm)`

### `etiquetas_aplicadas`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organization_id` | `integer` | no |
| `etiqueta_id` | `integer` | no |
| `objeto_tipo` | `text` | no |
| `objeto_id` | `text` | no |
| `aplicada_por_user_id` | `integer` | sí |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (etiqueta_id, objeto_tipo, objeto_id)`

Índices: `idx_etiquetas_aplicadas_objeto`

### `extracciones_retirada`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `fecha` | `text` | no |
| `fuente` | `text` | no |
| `nuevas` | `integer` | sí |
| `actualizadas` | `integer` | sí |
| `total_revisadas` | `integer` | sí |
| `notas` | `text` | sí |

Claves: `PRIMARY KEY (id)`

Índices: `idx_extr_fecha`

### `go_no_go_scores`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `pursuit_id` | `integer` | no |
| `organization_id` | `integer` | no |
| `criterio` | `text` | no |
| `puntuacion` | `integer` | no |
| `motivo` | `text` | sí |
| `author_user_id` | `integer` | sí |
| `created_at` | `text` | no |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `uq_go_no_go_scores` (único)

### `go_no_go_weights`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organization_id` | `integer` | no |
| `criterio` | `text` | no |
| `peso` | `double precision` | no |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `uq_go_no_go_weights` (único)

### `notification_preferences`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `user_id` | `integer` | no |
| `organization_id` | `integer` | sí |
| `tipo` | `text` | no |
| `canal` | `text` | no |
| `frecuencia` | `text` | no |
| `created_at` | `text` | no |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_notif_pref_uniq` (único), `idx_notif_pref_user`

### `organo_aliases`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organo_id` | `integer` | no |
| `alias_normalizado` | `text` | no |
| `alias_original` | `text` | sí |
| `dir3_variante` | `text` | sí |
| `fuente` | `text` | no |
| `confianza` | `double precision` | no |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_organo_aliases_alias`, `idx_organo_aliases_uniq` (único)

### `organo_review_queue`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `nombre_original` | `text` | no |
| `alias_normalizado` | `text` | no |
| `dir3` | `text` | sí |
| `candidato_organo_id` | `integer` | sí |
| `score` | `double precision` | no |
| `status` | `text` | no |
| `created_at` | `text` | no |
| `resolved_at` | `text` | sí |
| `resolved_by` | `text` | sí |

Claves: `PRIMARY KEY (id)`

Índices: `idx_organo_review_pending` (único), `idx_organo_review_status`

### `organos`

| Columna | Tipo | Nulo |
|---|---|---|
| `organo_id` | `integer` | no |
| `dir3` | `text` | sí |
| `nombre_canonico` | `text` | no |
| `nombre_normalizado` | `text` | no |
| `ccaa` | `text` | sí |
| `tipo` | `text` | sí |
| `url_perfil` | `text` | sí |
| `created_at` | `text` | no |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (organo_id)`

Índices: `idx_organos_ccaa`, `idx_organos_dir3` (único), `idx_organos_nombre_norm` (único)

### `plantillas_aplicadas`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organization_id` | `integer` | no |
| `user_id` | `integer` | no |
| `aplicada_en` | `text` | no |
| `copias` | `integer` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (organization_id, user_id)`

### `plantillas_organizacion`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `organization_id` | `integer` | no |
| `tipo` | `text` | no |
| `nombre` | `text` | no |
| `contenido_json` | `text` | no |
| `created_by_user_id` | `integer` | sí |
| `created_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_plantillas_org`

### `tecnologias_keywords`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `tecnologia` | `text` | no |
| `keyword` | `text` | no |
| `activa` | `boolean` | no |
| `origen` | `text` | no |
| `created_by_user_id` | `integer` | sí |
| `created_at` | `text` | no |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (id)`

Índices: `idx_tecnologias_keywords_activas`, `uq_tecnologias_keywords` (único)

### `user_event_prefs`

| Columna | Tipo | Nulo |
|---|---|---|
| `id` | `integer` | no |
| `user_key` | `text` | no |
| `event_type` | `text` | no |
| `modo` | `text` | no |
| `updated_at` | `text` | no |

Claves: `PRIMARY KEY (id)` · `UNIQUE (user_key, event_type)`

## Vistas materializadas

| Vista materializada | Índices |
|---|---|
| `licitaciones_canonicas` | `idx_licitaciones_canonicas_ccaa`, `idx_licitaciones_canonicas_cpv`, `idx_licitaciones_canonicas_fecha_pub`, `uq_licitaciones_canonicas_id_externo` (único) |

## Vistas

| Vista | Índices |
|---|---|
| `extracciones` | — |
| `licitaciones_history_2022` | — |
| `licitaciones_history_2023` | — |
| `licitaciones_history_2024` | — |
| `licitaciones_history_2025` | — |
| `licitaciones_history_2026` | — |
