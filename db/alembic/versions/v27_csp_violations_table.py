"""Migración v27 — Tabla de violaciones CSP (Content Security Policy).

Crea la tabla ``csp_violations`` para almacenar los reportes de violación
de CSP enviados por el navegador de los usuarios. Usada para monitorizar
inyecciones XSS y errores de configuración de la política de seguridad.

Campos:
- ``blocked_uri`` — recurso bloqueado por la política CSP.
- ``violated_directive`` — directiva que se violó (``script-src``, etc.).
- ``document_uri`` — página desde la que se originó la violación.
- ``source_file`` — fichero JS/CSS que causó la violación (si aplica).
- ``created_at`` — timestamp de recepción del reporte.

Revision ID: v27_csp_violations_table
Revises: v26_audit_hash_chain
Create Date: 2026-06-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v27_csp_violations_table"
down_revision: str | Sequence[str] | None = "v26_audit_hash_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS csp_violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            blocked_uri TEXT,
            violated_directive TEXT,
            document_uri TEXT,
            source_file TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_csp_created ON csp_violations(created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_csp_created")
    op.execute("DROP TABLE IF EXISTS csp_violations")
