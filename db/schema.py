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
    fecha_publicacion   TEXT,
    fecha_limite        TEXT,
    url                 TEXT,
    raw_keywords        TEXT,
    provincia           TEXT,
    ccaa                TEXT,
    nuts_code           TEXT,
    duracion_valor      REAL,
    duracion_unidad     TEXT,
    fecha_inicio        TEXT,
    fecha_fin           TEXT,
    prorroga_descripcion TEXT,
    ml_proba            REAL,
    tecnologia          TEXT,
    ml_tecnologias      TEXT,
    ml_proba_max        REAL,
    ml_tech_principal   TEXT,
    fecha_actualizacion_fuente TEXT,
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
    fecha_adjudicacion      TEXT,
    es_pyme                 INTEGER,
    n_ofertas_recibidas     INTEGER,
    oferta_minima           REAL,
    oferta_maxima           REAL,
    result_code             TEXT,
    result_description      TEXT,
    fecha_extraccion        TEXT NOT NULL,
    UNIQUE(licitacion_id, nif, importe_adjudicado),
    FOREIGN KEY(licitacion_id) REFERENCES licitaciones(id_externo)
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
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente  TEXT NOT NULL,
    relevante   INTEGER NOT NULL,
    nota        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ml_feedback_expediente ON ml_feedback(expediente);
CREATE INDEX IF NOT EXISTS idx_ml_feedback_created_at ON ml_feedback(created_at);

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
