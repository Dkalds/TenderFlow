"""Derivación centralizada de user_key a partir de la configuración."""

from __future__ import annotations

import hashlib
import os


def user_key() -> str:
    """Deriva una clave opaca para el usuario actual.

    Usa el password del dashboard o el nombre de host; nunca el valor en claro.
    """
    seed = os.environ.get("DASHBOARD_PASSWORD") or os.environ.get("COMPUTERNAME", "default")
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
