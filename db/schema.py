"""DDL del esquema SQLite / Turso y lógica de inicialización.

Contiene la constante ``SCHEMA`` con todas las sentencias ``CREATE TABLE``
e índices, más ``init_db()`` que aplica el schema y las migraciones pendientes.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any

import db.connection as _conn_module
from db.connection import connect, get_table_columns, log

# ---------------------------------------------------------------------------
# DDL del schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS licitaciones (
    id_externo          TEXT PRIMARY KEY,
    titulo              TEXT NOT NULL,
    descripcion         TEXT,
    organo_contratacion TEXT,
    importe             REAL,
    moneda              TEXT DEFAULT 'EUR',
    cpv                 TEXT,
    tipo_contrato       TEXT,
    estado              TEXT,
    fecha_publicacion   TEXT CHECK(fecha_publicacion IS NULL OR fecha_publicacion GLOB '????-??-??*'),
    fecha_limite        TEXT CHECK(fecha_limite IS NULL OR fecha_limite GLOB '????-??-??*'),
    url                 TEXT,
    raw_keywords        TEXT,
    provincia           TEXT,
    ccaa                TEXT,
    nuts_code           TEXT,
    duracion_valor      REAL,
    duracion_unidad     TEXT,
    fecha_inicio        TEXT CHECK(fecha_inicio IS NULL OR fecha_inicio GLOB '????-??-??*'),
    fecha_fin           TEXT CHECK(fecha_fin IS NULL OR fecha_fin GLOB '????-??-??*'),
    prorroga_descripcion TEXT,
    ml_proba            REAL,
    tecnologia          TEXT,
    ml_tecnologias      TEXT,
    ml_proba_max        REAL,
    ml_tech_principal   TEXT,
    fecha_actualizacion_fuente TEXT CHECK(fecha_actualizacion_fuente IS NULL OR fecha_actualizacion_fuente GLOB '????-??-??*'),
    fuente              TEXT NOT NULL DEFAULT 'placsp',
    fecha_extraccion    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fecha_pub ON licitaciones(fecha_publicacion);
CREATE INDEX IF NOT EXISTS idx_organo    ON licitaciones(organo_contratacion);
CREATE INDEX IF NOT EXISTS idx_estado    ON licitaciones(estado);
CREATE INDEX IF NOT EXISTS idx_cpv       ON licitaciones(cpv);
CREATE INDEX IF NOT EXISTS idx_ccaa      ON licitaciones(ccaa);
CREATE INDEX IF NOT EXISTS idx_ml_tech_principal ON licitaciones(ml_tech_principal);

CREATE TABLE IF NOT EXISTS licitacion_tecnologia_score (
    licitacion_id      TEXT NOT NULL,
    tecnologia         TEXT NOT NULL,
    probabilidad       REAL NOT NULL,
    threshold_aplicado REAL NOT NULL,
    computed_at        TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (licitacion_id, tecnologia),
    FOREIGN KEY (licitacion_id) REFERENCES licitaciones(id_externo) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_lts_tecnologia
    ON licitacion_tecnologia_score(tecnologia, probabilidad DESC);
CREATE INDEX IF NOT EXISTS idx_lts_lic
    ON licitacion_tecnologia_score(licitacion_id);

CREATE TABLE IF NOT EXISTS grupos_empresariales (
    grupo_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre      TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS empresas (
    empresa_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nif_canonico    TEXT,
    nombre_canonico TEXT NOT NULL,
    es_ute          INTEGER NOT NULL DEFAULT 0,
    es_pyme         INTEGER,
    grupo_id        INTEGER REFERENCES grupos_empresariales(grupo_id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_empresas_nif ON empresas(nif_canonico)
    WHERE nif_canonico IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_empresas_grupo ON empresas(grupo_id);

CREATE TABLE IF NOT EXISTS empresa_aliases (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id        INTEGER NOT NULL REFERENCES empresas(empresa_id) ON DELETE CASCADE,
    alias_normalizado TEXT NOT NULL,
    nif_variante      TEXT,
    fuente            TEXT NOT NULL DEFAULT '',
    confianza         REAL NOT NULL DEFAULT 1.0,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_empresa_aliases_alias ON empresa_aliases(alias_normalizado);
CREATE INDEX IF NOT EXISTS idx_empresa_aliases_nif   ON empresa_aliases(nif_variante);
CREATE UNIQUE INDEX IF NOT EXISTS idx_empresa_aliases_uniq
    ON empresa_aliases(empresa_id, alias_normalizado, COALESCE(nif_variante, ''));

CREATE TABLE IF NOT EXISTS ute_miembros (
    ute_empresa_id     INTEGER NOT NULL REFERENCES empresas(empresa_id) ON DELETE CASCADE,
    miembro_empresa_id INTEGER NOT NULL REFERENCES empresas(empresa_id) ON DELETE CASCADE,
    PRIMARY KEY (ute_empresa_id, miembro_empresa_id)
);

CREATE TABLE IF NOT EXISTS empresa_review_queue (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_original      TEXT NOT NULL,
    alias_normalizado    TEXT NOT NULL,
    nif                  TEXT,
    candidato_empresa_id INTEGER REFERENCES empresas(empresa_id) ON DELETE CASCADE,
    score                REAL NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending'
                         CHECK(status IN ('pending','accepted','rejected')),
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at          TEXT,
    resolved_by          TEXT
);
CREATE INDEX IF NOT EXISTS idx_empresa_review_status ON empresa_review_queue(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_empresa_review_pending
    ON empresa_review_queue(alias_normalizado, COALESCE(nif, ''), candidato_empresa_id)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS contrato_eventos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    licitacion_id TEXT NOT NULL REFERENCES licitaciones(id_externo) ON DELETE CASCADE,
    tipo          TEXT NOT NULL CHECK(tipo IN
                  ('adjudicacion','formalizacion','modificacion','prorroga','anulacion','cambio_estado','recurso')),
    fecha         TEXT NOT NULL,
    campo         TEXT,
    valor_antes   TEXT,
    valor_despues TEXT,
    importe_delta REAL,
    detalle       TEXT,
    history_id    INTEGER,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_eventos_lic  ON contrato_eventos(licitacion_id, fecha);
CREATE INDEX IF NOT EXISTS idx_eventos_tipo ON contrato_eventos(tipo, fecha);
CREATE UNIQUE INDEX IF NOT EXISTS idx_eventos_dedupe
    ON contrato_eventos(history_id, tipo, COALESCE(campo, ''))
    WHERE history_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS licitaciones_duplicados (
    licitacion_id TEXT PRIMARY KEY REFERENCES licitaciones(id_externo) ON DELETE CASCADE,
    canonical_id  TEXT NOT NULL REFERENCES licitaciones(id_externo) ON DELETE CASCADE,
    clave_match   TEXT,
    confianza     REAL NOT NULL DEFAULT 1.0,
    status        TEXT NOT NULL DEFAULT 'confirmed'
                  CHECK(status IN ('confirmed','pending','rejected')),
    detectado_en  TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at   TEXT,
    resolved_by   TEXT
);
CREATE INDEX IF NOT EXISTS idx_lic_dup_canonical ON licitaciones_duplicados(canonical_id);
CREATE INDEX IF NOT EXISTS idx_lic_dup_status    ON licitaciones_duplicados(status);

CREATE TABLE IF NOT EXISTS resoluciones_recurso (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tribunal          TEXT NOT NULL DEFAULT 'tacrc',
    numero_resolucion TEXT NOT NULL,
    numero_recurso    TEXT,
    fecha             TEXT,
    expediente        TEXT,
    organo            TEXT,
    sentido           TEXT CHECK(sentido IS NULL OR sentido IN
                      ('estimado','desestimado','inadmitido','desistimiento')),
    url_pdf           TEXT,
    resumen           TEXT,
    licitacion_id     TEXT REFERENCES licitaciones(id_externo),
    fecha_extraccion  TEXT NOT NULL,
    UNIQUE(tribunal, numero_resolucion)
);
CREATE INDEX IF NOT EXISTS idx_resoluciones_lic     ON resoluciones_recurso(licitacion_id);
CREATE INDEX IF NOT EXISTS idx_resoluciones_fecha   ON resoluciones_recurso(fecha);
CREATE INDEX IF NOT EXISTS idx_resoluciones_sentido ON resoluciones_recurso(sentido, fecha);

CREATE TABLE IF NOT EXISTS predicciones_baja (
    licitacion_id TEXT PRIMARY KEY REFERENCES licitaciones(id_externo) ON DELETE CASCADE,
    p10           REAL NOT NULL,
    p50           REAL NOT NULL,
    p90           REAL NOT NULL,
    model_version INTEGER,
    computed_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pred_baja_computed ON predicciones_baja(computed_at);

CREATE TABLE IF NOT EXISTS predicciones_retencion (
    licitacion_id  TEXT PRIMARY KEY REFERENCES licitaciones(id_externo) ON DELETE CASCADE,
    empresa_id     INTEGER REFERENCES empresas(empresa_id),
    prob_retencion REAL NOT NULL,
    riesgo_cambio  REAL NOT NULL,
    model_version  INTEGER,
    computed_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pred_ret_riesgo ON predicciones_retencion(riesgo_cambio DESC);

CREATE TABLE IF NOT EXISTS watchlist_empresas (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_key         TEXT NOT NULL,
    empresa_id       INTEGER NOT NULL REFERENCES empresas(empresa_id) ON DELETE CASCADE,
    email            TEXT,
    frequency        TEXT NOT NULL DEFAULT 'daily',
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    last_notified_at TEXT,
    UNIQUE(user_key, empresa_id)
);
CREATE INDEX IF NOT EXISTS idx_wl_emp_user ON watchlist_empresas(user_key);

CREATE TABLE IF NOT EXISTS watchlist_rules (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_key         TEXT NOT NULL,
    user_id          INTEGER,
    nombre           TEXT,
    keyword          TEXT,
    cpv              TEXT,
    min_importe      REAL,
    ccaa             TEXT,
    frequency        TEXT NOT NULL DEFAULT 'daily',
    active           INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    last_notified_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_wl_rules_user ON watchlist_rules(user_key);
CREATE INDEX IF NOT EXISTS idx_wl_rules_active ON watchlist_rules(active, frequency);

CREATE TABLE IF NOT EXISTS adjudicaciones (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    licitacion_id           TEXT NOT NULL,
    nif                     TEXT,
    nombre                  TEXT NOT NULL,
    provincia               TEXT,
    ccaa                    TEXT,
    nuts_code               TEXT,
    importe_adjudicado      REAL,
    importe_pagable         REAL,
    fecha_adjudicacion      TEXT CHECK(fecha_adjudicacion IS NULL OR fecha_adjudicacion GLOB '????-??-??*'),
    es_pyme                 INTEGER,
    n_ofertas_recibidas     INTEGER,
    oferta_minima           REAL,
    oferta_maxima           REAL,
    result_code             TEXT,
    result_description      TEXT,
    fecha_extraccion        TEXT NOT NULL,
    empresa_id              INTEGER REFERENCES empresas(empresa_id),
    UNIQUE(licitacion_id, nif, importe_adjudicado),
    FOREIGN KEY(licitacion_id) REFERENCES licitaciones(id_externo) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_adj_lic    ON adjudicaciones(licitacion_id);
CREATE INDEX IF NOT EXISTS idx_adj_nif    ON adjudicaciones(nif);
CREATE INDEX IF NOT EXISTS idx_adj_ccaa   ON adjudicaciones(ccaa);
CREATE INDEX IF NOT EXISTS idx_adj_fecha  ON adjudicaciones(fecha_adjudicacion);

CREATE TABLE IF NOT EXISTS extracciones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha           TEXT NOT NULL,
    fuente          TEXT NOT NULL,
    nuevas          INTEGER DEFAULT 0,
    actualizadas    INTEGER DEFAULT 0,
    total_revisadas INTEGER DEFAULT 0,
    notas           TEXT
);
CREATE INDEX IF NOT EXISTS idx_extr_fecha ON extracciones(fecha);

CREATE TABLE IF NOT EXISTS ml_feedback (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente               TEXT NOT NULL,
    relevante                INTEGER NOT NULL,
    nota                     TEXT NOT NULL DEFAULT '',
    tecnologia               TEXT,
    tecnologias_secundarias  TEXT,
    model_version            INTEGER,
    created_at               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ml_feedback_expediente ON ml_feedback(expediente);
CREATE INDEX IF NOT EXISTS idx_ml_feedback_created_at ON ml_feedback(created_at);
-- NOTA: idx_ml_feedback_tecnologia se crea en _ensure_ml_feedback_columns (no aquí)
-- para no fallar en BDs legacy donde ml_feedback existe sin la columna tecnologia.

CREATE TABLE IF NOT EXISTS webhooks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    url                 TEXT NOT NULL,
    secret              TEXT NOT NULL,
    event_types         TEXT NOT NULL,
    active              INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL,
    last_triggered_at   TEXT,
    last_status         INTEGER,
    failure_count       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_webhooks_active ON webhooks(active);

CREATE TABLE IF NOT EXISTS model_versions (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    name                     TEXT NOT NULL,
    version                  INTEGER NOT NULL,
    path                     TEXT NOT NULL,
    sha256                   TEXT NOT NULL,
    metrics_json             TEXT NOT NULL DEFAULT '{}',
    trained_at               TEXT NOT NULL,
    trained_on_n_samples     INTEGER,
    trained_on_n_feedbacks   INTEGER,
    is_active                INTEGER NOT NULL DEFAULT 0,
    notes                    TEXT,
    UNIQUE (name, version)
);
CREATE INDEX IF NOT EXISTS idx_model_versions_active ON model_versions(name, is_active);

CREATE TABLE IF NOT EXISTS totp_secrets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL UNIQUE,
    secret     TEXT NOT NULL,
    confirmed  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_totp_user ON totp_secrets(user_id);

CREATE TABLE IF NOT EXISTS totp_recovery_codes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    code_hash  TEXT NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0,
    used_at    TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recovery_user ON totp_recovery_codes(user_id);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash  TEXT NOT NULL UNIQUE,
    user_id     INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    ip          TEXT,
    user_agent  TEXT,
    revoked     INTEGER NOT NULL DEFAULT 0,
    revoked_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user    ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_token   ON sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS feature_flags (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    enabled      INTEGER NOT NULL DEFAULT 0,
    rollout_pct  INTEGER NOT NULL DEFAULT 100,
    user_emails  TEXT NOT NULL DEFAULT '',
    description  TEXT,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feature_store (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type   TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    feature_name  TEXT NOT NULL,
    value_json    TEXT NOT NULL,
    version       TEXT NOT NULL DEFAULT 'v1',
    computed_at   TEXT NOT NULL,
    UNIQUE(entity_type, entity_id, feature_name, version)
);
CREATE INDEX IF NOT EXISTS idx_feature_store_entity ON feature_store(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_feature_store_name   ON feature_store(entity_type, feature_name);

CREATE TABLE IF NOT EXISTS domain_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type   TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    actor_id     INTEGER,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_domain_events_aggregate ON domain_events(aggregate_type, aggregate_id);
CREATE INDEX IF NOT EXISTS idx_domain_events_type      ON domain_events(event_type);
CREATE INDEX IF NOT EXISTS idx_domain_events_created   ON domain_events(created_at);

CREATE TABLE IF NOT EXISTS job_locks (
    name         TEXT PRIMARY KEY,
    acquired_at  TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    holder       TEXT NOT NULL DEFAULT ''
);
"""


# ---------------------------------------------------------------------------
# Inicialización
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Aplica el schema y migraciones pendientes. Idempotente (no-op si ya init)."""
    if _conn_module._db_initialized:
        return
    from config import ensure_data_dirs
    from db.migrations import apply_pending

    ensure_data_dirs()
    with connect() as c:
        for stmt in SCHEMA.split(";"):
            stmt = stmt.strip()
            if stmt:
                c.execute(stmt)
        apply_pending(c)
        _ensure_licitaciones_columns(c)
        _ensure_adjudicaciones_columns(c)
        _ensure_ml_feedback_columns(c)
    _conn_module._db_initialized = True


def _ensure_licitaciones_columns(conn: Any) -> None:
    """Asegura que todas las columnas del dataclass Licitacion existen en la tabla.

    Defence-in-depth: en Turso/Hrana, ``PRAGMA table_info`` y ``sqlite_master``
    pueden comportarse diferente al SQLite local, causando que migraciones
    programáticas salten sentencias ``ALTER TABLE`` silenciosamente.
    Esta función añade las columnas faltantes directamente.
    """
    # Importación diferida para evitar ciclo: upsert → schema → upsert
    from db.upsert import Licitacion

    expected = {f.name for f in fields(Licitacion)}
    existing = get_table_columns(conn, "licitaciones")
    if not existing:
        return
    missing = expected - existing
    # Mapeo tipo Python → SQL
    _TYPE_MAP: dict[type | str, str] = {
        float: "REAL",
        int: "INTEGER",
    }
    for col in sorted(missing):
        fld = next((f for f in fields(Licitacion) if f.name == col), None)
        if fld is None:
            continue
        origin = getattr(fld.type, "__origin__", None) if hasattr(fld.type, "__origin__") else None
        base = getattr(fld.type, "__args__", (fld.type,))[0] if origin else fld.type
        sql_type = _TYPE_MAP.get(base, "TEXT")
        try:
            conn.execute(f"ALTER TABLE licitaciones ADD COLUMN {col} {sql_type}")
            log.info("ensure_column_added", column=col, sql_type=sql_type)
        except Exception:
            # Columna ya existe (race) o nombre inválido
            log.debug("ensure_column_skip", column=col)
    # Índice de fuente (v37): se crea aquí y no en SCHEMA para no fallar en
    # BDs legacy donde la columna acaba de añadirse en el bucle anterior.
    if "fuente" in expected:
        conn.execute("UPDATE licitaciones SET fuente = 'placsp' WHERE fuente IS NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lic_fuente ON licitaciones(fuente)")


def _ensure_adjudicaciones_columns(conn: Any) -> None:
    """Asegura las columnas de adjudicaciones ajenas al dataclass Adjudicacion.

    ``empresa_id`` (FK al maestro de empresas, v35 Alembic) no forma parte del
    dataclass porque el parser no la produce — la asigna a posteriori
    services.entity_resolution. En BDs legacy que solo ejecutan ``init_db()``
    la añadimos aquí; el índice se crea después para no fallar en SCHEMA
    cuando la tabla existe sin la columna.
    """
    existing = get_table_columns(conn, "adjudicaciones")
    if not existing:
        return
    if "empresa_id" not in existing:
        try:
            conn.execute(
                "ALTER TABLE adjudicaciones ADD COLUMN empresa_id INTEGER "
                "REFERENCES empresas(empresa_id)"
            )
            log.info("ensure_column_added", column="empresa_id", sql_type="INTEGER")
        except Exception:
            log.debug("ensure_column_skip", column="empresa_id")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_adj_empresa ON adjudicaciones(empresa_id)")


def _ensure_ml_feedback_columns(conn: Any) -> None:
    """Asegura las columnas multi-tecnología de ml_feedback (v44 Alembic).

    En BDs legacy (Turso/Hrana) la tabla ``ml_feedback`` puede existir sin las
    columnas ``tecnologia`` / ``tecnologias_secundarias`` / ``model_version``,
    porque ``CREATE TABLE IF NOT EXISTS`` en SCHEMA es no-op y la migración
    Alembic v44 no corre en el path de ``init_db()``. Las añadimos aquí y el
    índice se crea después, para no fallar en SCHEMA cuando la tabla existe sin
    la columna ``tecnologia``.
    """
    existing = get_table_columns(conn, "ml_feedback")
    if not existing:
        return
    for col, sql_type in (
        ("tecnologia", "TEXT"),
        ("tecnologias_secundarias", "TEXT"),
        ("model_version", "INTEGER"),
    ):
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE ml_feedback ADD COLUMN {col} {sql_type}")
                log.info("ensure_column_added", column=col, sql_type=sql_type)
            except Exception:
                log.debug("ensure_column_skip", column=col)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ml_feedback_tecnologia ON ml_feedback(tecnologia)")
