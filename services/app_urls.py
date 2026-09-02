"""URLs absolutas del frontend, deducidas de la configuración existente.

No hay una variable de entorno «URL pública del sitio»: ``FRONTEND_URL`` existe
en ``render.yaml`` pero no en ``config/settings.py`` ni en ``.env.example``
(deuda anotada en el backlog), y tocar ``.env*`` requiere OK humano (AGENTS.md
§6). Así que se deduce de lo que ya está declarado y validado —el primer origen
de ``CORS_ALLOWED_ORIGINS``, que es el sitio que puede hablar con esta API— y,
si está vacío, del origen del callback de OAuth.

Lo consumen los correos de producto (acceso concedido, digests de watchlist) y
el enlace de suscripción al calendario: sitios donde un enlace roto es peor que
ninguno, por eso las funciones devuelven ``None`` antes que inventar un host.
"""

from __future__ import annotations

from urllib.parse import urlparse

from config import settings


def frontend_base_url() -> str | None:
    """Origen del frontend (``https://host``) sin barra final, o ``None``."""
    origenes = [o.strip().rstrip("/") for o in (settings.CORS_ALLOWED_ORIGINS or "").split(",")]
    for origen in origenes:
        if origen.startswith("http"):
            return origen

    partes = urlparse(settings.OAUTH_REDIRECT_URI or "")
    if partes.scheme and partes.netloc:
        return f"{partes.scheme}://{partes.netloc}"
    return None


def url_absoluta(path: str) -> str | None:
    """``path`` (con barra inicial) sobre el origen del frontend, o ``None``."""
    base = frontend_base_url()
    if base is None:
        return None
    return f"{base}{path if path.startswith('/') else '/' + path}"


def url_de_detalle(licitacion_id: str) -> str | None:
    """Ficha del expediente en la consola (inspector de Detalle)."""
    from urllib.parse import quote

    return url_absoluta(f"/detalle?lic={quote(licitacion_id, safe='')}")


def url_de_oportunidad(pursuit_id: int) -> str | None:
    """Ficha de la oportunidad."""
    return url_absoluta(f"/oportunidades/{int(pursuit_id)}")
