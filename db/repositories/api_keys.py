"""Repository para api_keys."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from db.database import connect, connect_read, now_utc_iso


class ApiKeyRepository:
    def _hash(self, raw: str) -> str:
        from config import settings
        secret = settings.API_HMAC_SECRET
        if secret:
            return hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        with connect_read() as c:
            cols_info = {row[1] for row in c.execute("PRAGMA table_info(api_keys)").fetchall()}
            select_parts = ["id", "expires_at" if "expires_at" in cols_info else "NULL AS expires_at"]
            if "scopes" in cols_info:
                select_parts.append("scopes")
            else:
                select_parts.append("'*' AS scopes")
            row = c.execute(
                f"SELECT {', '.join(select_parts)} FROM api_keys "  # noqa: S608
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
            cols_info = {row[1] for row in c.execute("PRAGMA table_info(api_keys)").fetchall()}
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

    def revoke(self, key_hash: str) -> bool:
        with connect() as c:
            cur = c.execute(
                "UPDATE api_keys SET is_active = 0 WHERE key_hash = ?", (key_hash,)
            )
            return bool(cur.rowcount)

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
