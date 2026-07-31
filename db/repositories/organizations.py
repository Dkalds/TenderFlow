"""Persistencia de organizaciones y membresías."""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts


class OrganizationRepository:
    """Queries finas para el scope colaborativo."""

    def ensure_personal_organization(self, user_id: int) -> dict[str, Any]:
        """Devuelve o crea la organización personal y su membresía owner."""
        now = now_utc_iso()
        with connect() as conn:
            existing = self._personal_for_user(conn, user_id)
            if existing is None:
                user_row = conn.execute(
                    "SELECT display_name, email FROM users WHERE id = ?",
                    (user_id,),
                ).fetchone()
                if user_row is None:
                    raise ValueError("Usuario no encontrado.")
                name = str(user_row[0] or user_row[1] or f"Usuario {user_id}")[:200]
                inserted = conn.execute(
                    "INSERT INTO organizations "
                    "(name, is_personal, personal_owner_user_id, created_by_user_id, "
                    " created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(personal_owner_user_id) DO NOTHING RETURNING id",
                    (name, True, user_id, user_id, now, now),
                ).fetchone()
                organization_id = int(inserted[0]) if inserted else None
                if organization_id is None:
                    row = conn.execute(
                        "SELECT id FROM organizations WHERE personal_owner_user_id = ?",
                        (user_id,),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError("No se pudo crear la organización personal.")
                    organization_id = int(row[0])
                conn.execute(
                    "INSERT INTO organization_memberships "
                    "(organization_id, user_id, role, status, created_at, updated_at) "
                    "VALUES (?, ?, 'owner', 'active', ?, ?) "
                    "ON CONFLICT(organization_id, user_id) DO UPDATE SET "
                    "role = 'owner', status = 'active', updated_at = excluded.updated_at",
                    (organization_id, user_id, now, now),
                )
            else:
                organization_id = int(existing["id"])
                conn.execute(
                    "INSERT INTO organization_memberships "
                    "(organization_id, user_id, role, status, created_at, updated_at) "
                    "VALUES (?, ?, 'owner', 'active', ?, ?) "
                    "ON CONFLICT(organization_id, user_id) DO NOTHING",
                    (organization_id, user_id, now, now),
                )
            result = self._organization_with_role(conn, organization_id, user_id)
        if result is None:
            raise RuntimeError("La organización personal quedó sin membresía.")
        return result

    def create_organization(self, name: str, owner_user_id: int) -> dict[str, Any]:
        """Crea una organización compartida y asigna owner atómicamente."""
        now = now_utc_iso()
        with connect() as conn:
            row = conn.execute(
                "INSERT INTO organizations "
                "(name, is_personal, created_by_user_id, created_at, updated_at) "
                "VALUES (?, FALSE, ?, ?, ?) RETURNING id",
                (name, owner_user_id, now, now),
            ).fetchone()
            organization_id = int(row[0])
            conn.execute(
                "INSERT INTO organization_memberships "
                "(organization_id, user_id, role, status, created_at, updated_at) "
                "VALUES (?, ?, 'owner', 'active', ?, ?)",
                (organization_id, owner_user_id, now, now),
            )
            result = self._organization_with_role(conn, organization_id, owner_user_id)
        if result is None:
            raise RuntimeError("No se pudo crear la organización.")
        return result

    def add_membership(
        self,
        organization_id: int,
        user_id: int,
        role: str,
        *,
        invited_by_user_id: int | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        """Crea o actualiza una membresía de forma idempotente."""
        now = now_utc_iso()
        with connect() as conn:
            conn.execute(
                "INSERT INTO organization_memberships "
                "(organization_id, user_id, role, status, invited_by_user_id, "
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(organization_id, user_id) DO UPDATE SET "
                "role = excluded.role, status = excluded.status, "
                "invited_by_user_id = excluded.invited_by_user_id, "
                "updated_at = excluded.updated_at",
                (
                    organization_id,
                    user_id,
                    role,
                    status,
                    invited_by_user_id,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT organization_id, user_id, role, status, created_at, updated_at "
                "FROM organization_memberships "
                "WHERE organization_id = ? AND user_id = ?",
                (organization_id, user_id),
            )
            results = rows_to_dicts(row)
        return results[0]

    def get_active_membership(self, organization_id: int, user_id: int) -> dict[str, Any] | None:
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT organization_id, user_id, role, status, created_at, updated_at "
                "FROM organization_memberships "
                "WHERE organization_id = ? AND user_id = ? AND status = 'active'",
                (organization_id, user_id),
            )
            rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def list_for_user(self, user_id: int) -> list[dict[str, Any]]:
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT o.id, o.name, o.is_personal, m.role, o.created_at "
                "FROM organization_memberships m "
                "JOIN organizations o ON o.id = m.organization_id "
                "WHERE m.user_id = ? AND m.status = 'active' "
                "ORDER BY o.is_personal DESC, o.name, o.id",
                (user_id,),
            )
            return rows_to_dicts(cur)

    def get_for_user(self, organization_id: int, user_id: int) -> dict[str, Any] | None:
        with connect_read() as conn:
            return self._organization_with_role(conn, organization_id, user_id)

    def list_members(self, organization_id: int) -> list[dict[str, Any]]:
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT m.organization_id, m.user_id, m.role, m.status, "
                "m.created_at, m.updated_at "
                "FROM organization_memberships m "
                "WHERE m.organization_id = ? ORDER BY m.role, m.user_id",
                (organization_id,),
            )
            return rows_to_dicts(cur)

    def scope_coverage(self) -> dict[str, int]:
        """Filas totales y sin ``organization_id`` en las tablas escopadas (v64).

        Métrica de retirada del scope legacy ``user_key``-only: mientras
        ``sin_organizacion`` no llegue a 0, ``claim_legacy_scope`` todavía
        tiene trabajo pendiente (se dispara solo cuando un usuario pasa por
        una ruta org-aware, no en un backfill único).
        """
        tables = (
            "watchlist_items",
            "watchlist_rules",
            "watchlist_empresas",
            "watchlist_cpv",
            "saved_filters",
            "user_profiles",
            "user_notifications",
        )
        total = 0
        sin_organizacion = 0
        with connect_read() as conn:
            for table in tables:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                total += int(row[0]) if row else 0
                row = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE organization_id IS NULL"
                ).fetchone()
                sin_organizacion += int(row[0]) if row else 0
        return {"total": total, "sin_organizacion": sin_organizacion}

    def claim_legacy_rows(self, user_id: int, user_key: str) -> int:
        """Asigna filas sin scope al espacio personal, nunca a uno compartido."""
        personal = self.ensure_personal_organization(user_id)
        organization_id = int(personal["id"])
        tables = {
            "watchlist_items": True,
            "watchlist_rules": True,
            "watchlist_empresas": False,
            "watchlist_cpv": True,
            "saved_filters": False,
            "user_profiles": False,
            "user_notifications": False,
        }
        changed = 0
        with connect() as conn:
            for table, has_user_id in tables.items():
                if has_user_id:
                    cur = conn.execute(
                        f"UPDATE {table} SET organization_id = ? "
                        "WHERE organization_id IS NULL AND (user_id = ? OR user_key = ?)",
                        (organization_id, user_id, user_key),
                    )
                else:
                    cur = conn.execute(
                        f"UPDATE {table} SET organization_id = ? "
                        "WHERE organization_id IS NULL AND user_key = ?",
                        (organization_id, user_key),
                    )
                changed += max(0, int(getattr(cur, "rowcount", 0) or 0))
        return changed

    def export_memberships_for_user(self, user_id: int) -> list[dict[str, Any]]:
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT m.organization_id, o.name AS organization_name, "
                "m.user_id, m.role, m.status, m.created_at, m.updated_at "
                "FROM organization_memberships m "
                "JOIN organizations o ON o.id = m.organization_id "
                "WHERE m.user_id = ? ORDER BY m.organization_id",
                (user_id,),
            )
            return rows_to_dicts(cur)

    def remove_memberships_for_user(self, user_id: int) -> None:
        """Elimina vínculos personales; no borra datos corporativos."""
        with connect() as conn:
            conn.execute(
                "DELETE FROM organization_memberships WHERE user_id = ?",
                (user_id,),
            )

    @staticmethod
    def _personal_for_user(conn: Any, user_id: int) -> dict[str, Any] | None:
        cur = conn.execute(
            "SELECT id, name, is_personal, created_at "
            "FROM organizations WHERE personal_owner_user_id = ?",
            (user_id,),
        )
        rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    @staticmethod
    def _organization_with_role(
        conn: Any, organization_id: int, user_id: int
    ) -> dict[str, Any] | None:
        cur = conn.execute(
            "SELECT o.id, o.name, o.is_personal, m.role, o.created_at "
            "FROM organizations o JOIN organization_memberships m "
            "ON m.organization_id = o.id "
            "WHERE o.id = ? AND m.user_id = ? AND m.status = 'active'",
            (organization_id, user_id),
        )
        rows = rows_to_dicts(cur)
        return rows[0] if rows else None
