"""Servicio de watchlist — queries para alertas y digests.

Centraliza las queries SQL que usa ``scheduler/watchlist_alerts.py``
para buscar licitaciones y gestionar ``pending_digests``.
"""

from __future__ import annotations

from typing import Any

from db.repositories.watchlist import WatchlistRepository
from db.watchlist import WatchlistEntry
from db.watchlist import add_entry as _add_entry
from db.watchlist import list_entries as _list_entries
from db.watchlist import remove_entry as _remove_entry
from db.watchlist import update_frequency as _update_frequency
from observability.logging import get_logger

log = get_logger(__name__)

_repo = WatchlistRepository()


def query_licitaciones_since(cpv_prefix: str, since_date: str) -> list[dict[str, Any]]:
    """Devuelve licitaciones con ``fecha_publicacion >= since_date`` y CPV que empiece
    por ``cpv_prefix``."""
    return _repo.query_licitaciones_since(cpv_prefix, since_date)


def query_licitaciones_batch(
    entries: list[dict[str, Any]], default_since: str
) -> dict[str, list[dict[str, Any]]]:
    """Consulta licitaciones para múltiples entradas watchlist en queries agrupadas por fecha."""
    return _repo.query_licitaciones_batch(entries, default_since)


def store_pending_digest(
    user_key: str,
    recipient: str,
    entry_id: int,
    licitacion_id: str,
    frequency: str,
    matched_at: str,
    *,
    user_id: int | None = None,
) -> bool:
    """Persiste una coincidencia en ``pending_digests``. Devuelve ``True`` si tuvo éxito."""
    return _repo.store_pending_digest(
        user_key=user_key,
        recipient=recipient,
        entry_id=entry_id,
        licitacion_id=licitacion_id,
        frequency=frequency,
        matched_at=matched_at,
        user_id=user_id,
    )


def load_pending_digests(frequency: str) -> list[dict[str, Any]]:
    """Carga los digests pendientes (no enviados) para una frecuencia dada."""
    return _repo.load_pending_digests(frequency)


def mark_digests_sent(digest_ids: list[int]) -> None:
    """Marca los digests como enviados."""
    _repo.mark_digests_sent(digest_ids)


# ── CRUD entries (§3.8 — dashboard uses these instead of db.watchlist) ────


def add_entry(entry: WatchlistEntry) -> None:
    """Add a watchlist entry (deduplicates internally)."""
    _add_entry(entry)


def remove_entry(entry_id: int, user_key: str, *, user_id: int | None = None) -> bool:
    """Remove a watchlist entry by ID, scoped to its owner."""
    return _remove_entry(entry_id, user_key, user_id=user_id)


def list_entries(
    user_key: str,
    *,
    user_id: int | None = None,
    organization_id: int | None = None,
) -> list[dict[str, Any]]:
    """List watchlist entries for a user."""
    return _list_entries(user_key, user_id=user_id, organization_id=organization_id)


def update_frequency(
    entry_id: int, frequency: str, user_key: str, *, user_id: int | None = None
) -> bool:
    """Update notification frequency for a watchlist entry, scoped to its owner."""
    return _update_frequency(entry_id, frequency, user_key, user_id=user_id)


#: Tope de reglas que se cruzan por petición del feed.
#:
#: Cada regla es una consulta (``list_matches``), y un lector de feeds pide la
#: URL cada pocos minutos. Las reglas llegan de la más reciente a la más
#: antigua, así que el corte deja fuera las que más tiempo llevan sin tocarse.
MAX_REGLAS_FEED = 25


def _rfc3339(valor: object, por_defecto: str) -> str:
    """Fecha de la licitación en el formato que exige Atom, o ``por_defecto``."""
    from datetime import datetime

    try:
        fecha = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return por_defecto
    return fecha.strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_atom_feed(
    user_key: str,
    limit: int = 50,
    *,
    user_id: int | None = None,
    organization_id: int | None = None,
) -> str:
    """Feed Atom 1.0 con lo que casan las alertas activas del usuario.

    Las alertas son las reglas de ``/mi-watchlist`` (``watchlist_rules``) y lo
    que casa cada una sale de :func:`services.watchlist_rules.list_matches`, el
    mismo predicado que ``GET /watchlist/rules/{id}/matches``: el feed no puede
    ser una versión más ancha de la alerta. Hasta 2026-10 leía la tabla
    heredada ``watchlist_cpv`` y casaba solo por prefijo CPV, de modo que ni
    veía las reglas que la gente crea hoy ni respetaba su importe mínimo.

    Args:
        user_key: Identidad heredada del titular (``user_key_from_email``).
        limit: Número máximo de entradas del feed.
        user_id: Titular; hace dual la lectura de sus reglas (v129).
        organization_id: Organización cuyas reglas se leen: las suyas y las
            que el equipo comparte, las mismas que ve en ``/mi-watchlist``.
            ``None`` lee solo las suyas, en todas sus organizaciones.

    Returns:
        El XML del feed. Sin reglas activas, un feed válido y vacío.
    """
    import html
    from datetime import UTC, datetime

    from services.watchlist_rules import list_matches, list_rules

    ahora = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    reglas = [
        regla for regla in list_rules(user_key, organization_id, user_id=user_id) if regla.active
    ]

    vistas: set[str] = set()
    lics: list[dict[str, Any]] = []
    for regla in reglas[:MAX_REGLAS_FEED]:
        for lic in list_matches(regla, limit=limit):
            fid = str(lic.get("id_externo") or "")
            if fid and fid not in vistas:
                vistas.add(fid)
                lics.append(lic)

    lics.sort(key=lambda lic: str(lic.get("fecha_publicacion") or ""), reverse=True)
    lics = lics[:limit]

    actualizado = _rfc3339(lics[0].get("fecha_publicacion"), ahora) if lics else ahora
    titulo = "Alertas de TenderFlow" if reglas else "Alertas de TenderFlow — sin alertas activas"
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{html.escape(titulo)}</title>",
        f"  <id>urn:watchlist:{html.escape(user_key[:8])}</id>",
        f"  <updated>{actualizado}</updated>",
        # Atom exige autor en el feed si las entradas no lo llevan.
        "  <author><name>TenderFlow</name></author>",
        # Sin la query: el enlace `self` lo lee el lector y no debe repetir la
        # clave que vino en `?token=`.
        '  <link rel="self" type="application/atom+xml" href="/api/v1/watchlist/feed.xml"/>',
    ]

    for lic in lics:
        fid = html.escape(str(lic.get("id_externo", "")))
        title = html.escape(str(lic.get("titulo") or "(Sin título)"))
        url = html.escape(str(lic.get("url") or ""))
        org = html.escape(str(lic.get("organo_contratacion") or ""))
        importe = lic.get("importe")
        importe_str = f"{float(importe):,.0f} €" if importe else "—"
        parts += [
            "  <entry>",
            f"    <id>urn:licitacion:{fid}</id>",
            f"    <title>{title}</title>",
            f"    <updated>{_rfc3339(lic.get('fecha_publicacion'), actualizado)}</updated>",
            f"    <content type='text'>Órgano: {org} | Importe: {importe_str}</content>",
        ]
        if url:
            parts.append(f'    <link href="{url}"/>')
        parts.append("  </entry>")

    parts.append("</feed>")
    return "\n".join(parts)
