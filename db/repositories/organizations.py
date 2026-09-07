"""Persistencia de organizaciones y membresías."""

from __future__ import annotations

import json
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)


class OrganizationRepository:
    """Queries finas para el scope colaborativo."""

    def ensure_personal_organization(self, user_id: int) -> dict[str, Any]:
        """Devuelve o crea la organización personal y su membresía owner."""
        now = now_utc_iso()
        with connect() as conn:
            existing = self._personal_for_user(conn, user_id)
            if existing is None:
                user_row = conn.execute(
                    "SELECT display_name, email FROM users WHERE id = %s",
                    (user_id,),
                ).fetchone()
                if user_row is None:
                    raise ValueError("Usuario no encontrado.")
                name = str(user_row[0] or user_row[1] or f"Usuario {user_id}")[:200]
                inserted = conn.execute(
                    "INSERT INTO organizations "
                    "(name, is_personal, personal_owner_user_id, created_by_user_id, "
                    " created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT(personal_owner_user_id) DO NOTHING RETURNING id",
                    (name, True, user_id, user_id, now, now),
                ).fetchone()
                organization_id = int(inserted[0]) if inserted else None
                if organization_id is None:
                    row = conn.execute(
                        "SELECT id FROM organizations WHERE personal_owner_user_id = %s",
                        (user_id,),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError("No se pudo crear la organización personal.")
                    organization_id = int(row[0])
                conn.execute(
                    "INSERT INTO organization_memberships "
                    "(organization_id, user_id, role, status, created_at, updated_at) "
                    "VALUES (%s, %s, 'owner', 'active', %s, %s) "
                    "ON CONFLICT(organization_id, user_id) DO UPDATE SET "
                    "role = 'owner', status = 'active', updated_at = excluded.updated_at",
                    (organization_id, user_id, now, now),
                )
            else:
                organization_id = int(existing["id"])
                conn.execute(
                    "INSERT INTO organization_memberships "
                    "(organization_id, user_id, role, status, created_at, updated_at) "
                    "VALUES (%s, %s, 'owner', 'active', %s, %s) "
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
                "VALUES (%s, FALSE, %s, %s, %s) RETURNING id",
                (name, owner_user_id, now, now),
            ).fetchone()
            organization_id = int(row[0])
            conn.execute(
                "INSERT INTO organization_memberships "
                "(organization_id, user_id, role, status, created_at, updated_at) "
                "VALUES (%s, %s, 'owner', 'active', %s, %s)",
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
                " created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s) "
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
                "SELECT m.organization_id, m.user_id, m.role, m.status, "
                "m.created_at, m.updated_at, u.display_name, u.email "
                "FROM organization_memberships m "
                "JOIN users u ON u.id = m.user_id "
                "WHERE m.organization_id = %s AND m.user_id = %s",
                (organization_id, user_id),
            )
            results = rows_to_dicts(row)
        return results[0]

    def get_active_membership(self, organization_id: int, user_id: int) -> dict[str, Any] | None:
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT organization_id, user_id, role, status, created_at, updated_at "
                "FROM organization_memberships "
                "WHERE organization_id = %s AND user_id = %s AND status = 'active'",
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
                "WHERE m.user_id = %s AND m.status = 'active' "
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
                "m.created_at, m.updated_at, u.display_name, u.email "
                "FROM organization_memberships m "
                "JOIN users u ON u.id = m.user_id "
                "WHERE m.organization_id = %s ORDER BY m.role, m.user_id",
                (organization_id,),
            )
            return rows_to_dicts(cur)

    def get_settings(self, organization_id: int) -> dict[str, Any]:
        """``settings_json`` deserializado; ``{}`` si la fila no existe o está corrupta."""
        with connect_read() as conn:
            row = conn.execute(
                "SELECT settings_json FROM organizations WHERE id = %s",
                (organization_id,),
            ).fetchone()
        if row is None or not row[0]:
            return {}
        try:
            parsed = json.loads(str(row[0]))
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def update_settings(self, organization_id: int, patch: dict[str, Any]) -> dict[str, Any]:
        """Fusiona ``patch`` sobre ``settings_json`` y devuelve el resultado.

        Fusión superficial a propósito: cada clave es una configuración entera
        (``tecnologias`` es la lista completa), no un árbol que haya que
        recorrer. Leer y escribir en la misma transacción evita que dos
        administradores pisándose se pierdan mutuamente una clave.
        """
        with connect() as conn:
            row = conn.execute(
                "SELECT settings_json FROM organizations WHERE id = %s FOR UPDATE",
                (organization_id,),
            ).fetchone()
            current: dict[str, Any] = {}
            if row is not None and row[0]:
                try:
                    parsed = json.loads(str(row[0]))
                    current = parsed if isinstance(parsed, dict) else {}
                except (json.JSONDecodeError, TypeError):
                    current = {}
            merged = {**current, **patch}
            conn.execute(
                "UPDATE organizations SET settings_json = %s, updated_at = %s WHERE id = %s",
                (json.dumps(merged, ensure_ascii=False), now_utc_iso(), organization_id),
            )
        return merged

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
                        f"UPDATE {table} SET organization_id = %s "
                        "WHERE organization_id IS NULL AND (user_id = %s OR user_key = %s)",
                        (organization_id, user_id, user_key),
                    )
                else:
                    cur = conn.execute(
                        f"UPDATE {table} SET organization_id = %s "
                        "WHERE organization_id IS NULL AND user_key = %s",
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
                "WHERE m.user_id = %s ORDER BY m.organization_id",
                (user_id,),
            )
            return rows_to_dicts(cur)

    def remove_memberships_for_user(self, user_id: int) -> None:
        """Elimina vínculos personales; no borra datos corporativos."""
        with connect() as conn:
            conn.execute(
                "DELETE FROM organization_memberships WHERE user_id = %s",
                (user_id,),
            )

    @staticmethod
    def _personal_for_user(conn: Any, user_id: int) -> dict[str, Any] | None:
        cur = conn.execute(
            "SELECT id, name, is_personal, created_at "
            "FROM organizations WHERE personal_owner_user_id = %s",
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
            "WHERE o.id = %s AND m.user_id = %s AND m.status = 'active'",
            (organization_id, user_id),
        )
        rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    # ── Ciclo de vida de la organización (C2.2, ADR-030 §D) ─────────────────

    def es_personal(self, organization_id: int) -> bool:
        """¿Es la organización personal de alguien?

        La personal no se traspasa ni se borra: es el contenedor por defecto de
        una cuenta, y borrarla dejaría al usuario sin sitio donde escribir.
        Borrar la cuenta es otra operación, con su propio endpoint.
        """
        with connect_read() as c:
            fila = c.execute(
                "SELECT is_personal FROM organizations WHERE id = %s", (organization_id,)
            ).fetchone()
        return bool(fila and fila[0])

    def contar_por_rol(self, organization_id: int, rol: str) -> int:
        """Miembros ACTIVOS con ese rol."""
        with connect_read() as c:
            fila = c.execute(
                "SELECT COUNT(*) FROM organization_members "
                "WHERE organization_id = %s AND role = %s AND status = 'active'",
                (organization_id, rol),
            ).fetchone()
        return int(fila[0]) if fila else 0

    def traspasar_propiedad(self, organization_id: int, *, de_user_id: int, a_user_id: int) -> bool:
        """Mueve el rol `owner` de un miembro a otro, en UNA transacción.

        Las dos escrituras van juntas a propósito: una organización con dos
        owners es un estado que ningún flujo sabe leer, y una sin ninguno no la
        puede administrar nadie. Si el `UPDATE` de destino falla, el de origen
        se deshace con él.

        Devuelve `False` si el destino no es miembro activo — invitar y
        traspasar son cosas distintas, y hacerlas de una convertiría un error de
        tipeo en el email en una organización cuyo owner no existe.
        """
        with connect() as c:
            destino = c.execute(
                "SELECT 1 FROM organization_members "
                "WHERE organization_id = %s AND user_id = %s AND status = 'active'",
                (organization_id, a_user_id),
            ).fetchone()
            if not destino:
                return False
            ahora = now_utc_iso()
            c.execute(
                "UPDATE organization_members SET role = 'owner', updated_at = %s "
                "WHERE organization_id = %s AND user_id = %s",
                (ahora, organization_id, a_user_id),
            )
            c.execute(
                "UPDATE organization_members SET role = 'admin', updated_at = %s "
                "WHERE organization_id = %s AND user_id = %s",
                (ahora, organization_id, de_user_id),
            )
        return True

    def salir(self, organization_id: int, user_id: int) -> bool:
        """Marca la membresía como `revoked`. No borra: el histórico se conserva.

        Un comentario firmado por alguien que ya no está sigue siendo suyo
        (ADR-030 §D: el dato corporativo sobrevive con el autor anonimizado, no
        desaparece con él).
        """
        with connect() as c:
            cur = c.execute(
                "UPDATE organization_members SET status = 'revoked', updated_at = %s "
                "WHERE organization_id = %s AND user_id = %s AND status = 'active'",
                (now_utc_iso(), organization_id, user_id),
            )
            return bool(getattr(cur, "rowcount", 0))

    def contar_dato_corporativo(self, organization_id: int) -> dict[str, int]:
        """Cuánto trabajo se llevaría por delante el borrado.

        Es lo que la confirmación literal enseña antes de pedirla: «vas a borrar
        14 oportunidades y 37 comentarios» es una advertencia; «¿seguro?» no.
        """
        conteos: dict[str, int] = {}
        with connect_read() as c:
            for etiqueta, sql in (
                ("oportunidades", "SELECT COUNT(*) FROM pursuits WHERE organization_id = %s"),
                (
                    "comentarios",
                    "SELECT COUNT(*) FROM pursuit_comments pc "
                    "JOIN pursuits p ON p.id = pc.pursuit_id "
                    "WHERE p.organization_id = %s",
                ),
                (
                    "miembros",
                    "SELECT COUNT(*) FROM organization_members "
                    "WHERE organization_id = %s AND status = 'active'",
                ),
            ):
                try:
                    fila = c.execute(sql, (organization_id,)).fetchone()
                    conteos[etiqueta] = int(fila[0]) if fila else 0
                except Exception:
                    # Una tabla que aún no existe no puede impedir que el owner
                    # vea el resto del recuento.
                    log.debug("conteo_dato_corporativo_fallo", tabla=etiqueta, exc_info=True)
                    conteos[etiqueta] = -1
        return conteos

    def borrar(self, organization_id: int) -> bool:
        """Borra la organización. El `ON DELETE CASCADE` se lleva lo suyo.

        Lo que cae con ella es **dato corporativo** (ADR-030 §D): oportunidades,
        comentarios, capacidades, claves de organización. Lo personal de cada
        miembro —perfil, favoritos, reglas, notas privadas— cuelga del usuario y
        sobrevive.
        """
        with connect() as c:
            cur = c.execute("DELETE FROM organizations WHERE id = %s", (organization_id,))
            return bool(getattr(cur, "rowcount", 0))
