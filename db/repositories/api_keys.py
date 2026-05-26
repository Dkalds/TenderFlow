"""Repository para api_keys."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from db.database import connect, connect_read, get_table_columns, now_utc_iso
from db.repositories.base import rows_to_dicts


class ApiKeyRepository:
    def _hash(self, raw: str) -> str:
        from config import settings

        secret = settings.API_HMAC_SECRET.get_secret_value()
        if secret:
            return hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
        return hashlib.sha256(raw.encode()).hexdigest()

    # ── Lookups ──────────────────────────────────────────────

    def get_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        with connect_read() as c:
            cols_info = get_table_columns(c, "api_keys")
            select_parts = [
                "id",
                "expires_at" if "expires_at" in cols_info else "NULL AS expires_at",
            ]
            if "scopes" in cols_info:
                select_parts.append("scopes")
            else:
                select_parts.append("'*' AS scopes")
            row = c.execute(
                "SELECT " + ", ".join(select_parts) + " FROM api_keys "
                "WHERE key_hash = ? AND is_active = 1",
                (key_hash,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "expires_at": row[1],
            "scopes": row[2] if len(row) > 2 else "*",
        }

    def get_stored_hash(self, key_id: int) -> str | None:
        """Devuelve el ``key_hash`` almacenado para validación en tiempo constante."""
        with connect_read() as c:
            row = c.execute("SELECT key_hash FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        return str(row[0]) if row else None

    def get_active_scopes(self, key_hash: str) -> str | None:
        """Devuelve scopes de una key activa, o ``None`` si no existe."""
        try:
            with connect_read() as c:
                row = c.execute(
                    "SELECT scopes FROM api_keys WHERE key_hash = ? AND is_active = 1",
                    (key_hash,),
                ).fetchone()
        except Exception:
            return None
        if not row:
            return None
        return str(row[0]) if row[0] is not None else "*"

    def get_user_id(self, key_id: int) -> int | None:
        """Obtiene ``user_id`` vinculado a la API key, si la columna existe."""
        with connect_read() as c:
            try:
                cols = get_table_columns(c, "api_keys")
                if "user_id" not in cols:
                    return None
                row = c.execute(
                    "SELECT user_id FROM api_keys WHERE id = ? LIMIT 1", (key_id,)
                ).fetchone()
                if row and row[0]:
                    return int(row[0])
                return None
            except Exception:
                return None

    def get_name_and_scopes(self, key_id: int) -> tuple[str, str] | None:
        """Obtiene nombre y scopes de una API key por ID."""
        with connect_read() as c:
            row = c.execute("SELECT name, scopes FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        if not row:
            return None
        return row[0], str(row[1] or "*")

    def get_name(self, key_hash: str) -> str | None:
        with connect_read() as c:
            row = c.execute(
                "SELECT name FROM api_keys WHERE key_hash = ? LIMIT 1", (key_hash,)
            ).fetchone()
        return str(row[0]) if row else None

    def get_all_for_user(self, user_id: int) -> list[dict[str, Any]]:
        with connect_read() as c:
            try:
                cur = c.execute(
                    "SELECT name, created_at, expires_at FROM api_keys WHERE user_id = ?",
                    (user_id,),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]
            except Exception:
                return []

    # ── Listings ─────────────────────────────────────────────

    def list_all(self) -> list[dict[str, Any]]:
        """Lista todas las API keys (sin exponer el hash)."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, name, created_at, last_used, is_active "
                "FROM api_keys ORDER BY created_at DESC"
            )
            return rows_to_dicts(cur)

    def list_for_export(self, key_hash: str) -> list[dict[str, Any]]:
        """Exporta las API keys vinculadas al ``key_hash`` (GDPR)."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT name, created_at, expires_at FROM api_keys WHERE key_hash = ?",
                (key_hash,),
            )
            return rows_to_dicts(cur)

    def get_by_key_id(self, key_id: int) -> list[dict[str, Any]]:
        """Devuelve datos de la API key por ID con columnas dinámicas."""
        with connect_read() as c:
            try:
                cols_info = get_table_columns(c, "api_keys")
                select_cols = "id, name, created_at, is_active, scopes"
                if "prefix" in cols_info:
                    select_cols += ", prefix"
                if "expires_at" in cols_info:
                    select_cols += ", expires_at"
                cur = c.execute(
                    "SELECT " + select_cols + " FROM api_keys WHERE id = ?",
                    (key_id,),
                )
                return rows_to_dicts(cur)
            except Exception:
                return []

    # ── Mutations ────────────────────────────────────────────

    def update_last_used(self, key_id: int) -> None:
        try:
            with connect() as c:
                c.execute(
                    "UPDATE api_keys SET last_used = ? WHERE id = ?",
                    (now_utc_iso(), key_id),
                )
        except Exception:
            pass

    def create(self, name: str, scopes: str = "*") -> str:
        raw = secrets.token_urlsafe(32)
        key_hash = self._hash(raw)
        with connect() as c:
            cols_info = get_table_columns(c, "api_keys")
            if "scopes" in cols_info:
                c.execute(
                    "INSERT INTO api_keys (key_hash, name, created_at, is_active, scopes) VALUES (?, ?, ?, 1, ?)",
                    (key_hash, name, now_utc_iso(), scopes),
                )
            else:
                c.execute(
                    "INSERT INTO api_keys (key_hash, name, created_at, is_active) VALUES (?, ?, ?, 1)",
                    (key_hash, name, now_utc_iso()),
                )
        return raw

    def insert(
        self,
        *,
        key_hash: str,
        name: str,
        scopes: str,
        prefix: str,
        user_id: int | None,
        expires_at: str | None,
    ) -> None:
        """Inserta una API key pre-hasheada respetando columnas presentes."""
        now = now_utc_iso()
        with connect() as c:
            cols = get_table_columns(c, "api_keys")
            fields = ["key_hash", "name", "created_at", "is_active"]
            values: list[Any] = [key_hash, name, now, 1]

            if "scopes" in cols:
                fields.append("scopes")
                values.append(scopes)
            if "user_id" in cols:
                fields.append("user_id")
                values.append(user_id)
            if "prefix" in cols:
                fields.append("prefix")
                values.append(prefix)
            if "expires_at" in cols and expires_at is not None:
                fields.append("expires_at")
                values.append(expires_at)

            placeholders = ",".join("?" * len(fields))
            c.execute(
                "INSERT INTO api_keys (" + ", ".join(fields) + ") VALUES (" + placeholders + ")",
                values,
            )

    def revoke(self, key_hash: str) -> bool:
        with connect() as c:
            cur = c.execute("UPDATE api_keys SET is_active = 0 WHERE key_hash = ?", (key_hash,))
            return bool(cur.rowcount)

    def revoke_by_id(self, key_id: int) -> None:
        """Revoca una API key por su ID interno."""
        with connect() as c:
            c.execute("UPDATE api_keys SET is_active = 0 WHERE id = ?", (key_id,))

    def deactivate_by_id(self, key_id: int) -> None:
        """Desactiva una key por ID y actualiza ``last_used`` (GDPR)."""
        with connect() as c:
            c.execute(
                "UPDATE api_keys SET is_active = 0, last_used = ? WHERE id = ?",
                (now_utc_iso(), key_id),
            )

    def set_expiry(self, key_id: int, expires_at: str) -> None:
        """Establece ``expires_at`` en una API key (rotación con grace period)."""
        with connect() as c:
            cols_info = get_table_columns(c, "api_keys")
            if "expires_at" in cols_info:
                c.execute(
                    "UPDATE api_keys SET expires_at = ? WHERE id = ?",
                    (expires_at, key_id),
                )
