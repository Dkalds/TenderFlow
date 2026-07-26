"""Helpers de identidad estable para datos pertenecientes a un usuario."""

from __future__ import annotations

import hashlib


def user_key_from_email(email: str | None, user_id: int) -> str:
    """Deriva una clave opaca de la identidad humana, nunca de una credencial."""
    seed = (email or f"user:{user_id}").strip().lower()
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
