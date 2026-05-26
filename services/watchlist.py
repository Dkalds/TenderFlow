"""Servicio de watchlist — queries para alertas y digests.

Centraliza las queries SQL que usa ``scheduler/watchlist_alerts.py``
para buscar licitaciones y gestionar ``pending_digests``.
"""

from __future__ import annotations

from typing import Any

from db.repositories.watchlist import WatchlistRepository
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
) -> bool:
    """Persiste una coincidencia en ``pending_digests``. Devuelve ``True`` si tuvo éxito."""
    return _repo.store_pending_digest(
        user_key=user_key,
        recipient=recipient,
        entry_id=entry_id,
        licitacion_id=licitacion_id,
        frequency=frequency,
        matched_at=matched_at,
    )


def load_pending_digests(frequency: str) -> list[dict[str, Any]]:
    """Carga los digests pendientes (no enviados) para una frecuencia dada."""
    return _repo.load_pending_digests(frequency)


def mark_digests_sent(digest_ids: list[int]) -> None:
    """Marca los digests como enviados."""
    _repo.mark_digests_sent(digest_ids)


def generate_atom_feed(user_key: str, limit: int = 50) -> str:
    """Genera un feed Atom 1.0 con las últimas licitaciones que coinciden con la watchlist del usuario.

    Args:
        user_key: Identificador opaco del usuario (hash de email/nombre).
        limit: Número máximo de entradas a incluir en el feed.

    Returns:
        XML del feed como string. Devuelve un feed vacío si no hay entradas.
    """
    import html
    from datetime import UTC, datetime

    from db.watchlist import list_entries

    entries = list_entries(user_key)
    if not entries:
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            f"<title>Watchlist — sin entradas</title>"
            f"<id>urn:watchlist:{html.escape(user_key[:8])}</id>"
            f"<updated>{now_iso}</updated>"
            "</feed>"
        )

    # Calcular since_date: 30 días atrás como ventana de consulta
    since_date = (datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)).isoformat()
    from datetime import timedelta

    since_date = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")

    matches = query_licitaciones_batch(entries, default_since=since_date)

    # Aplanar resultados, deduplicar por id_externo, ordenar por fecha_publicacion
    seen: set[str] = set()
    lics: list[dict[str, Any]] = []
    for lic_list in matches.values():
        for lic in lic_list:
            fid = str(lic.get("id_externo", ""))
            if fid and fid not in seen:
                seen.add(fid)
                lics.append(lic)

    lics.sort(key=lambda x: x.get("fecha_publicacion") or "", reverse=True)
    lics = lics[:limit]

    updated = (
        lics[0].get("fecha_publicacion", datetime.now(UTC).isoformat())
        if lics
        else datetime.now(UTC).isoformat()
    )
    # Normalise to RFC3339
    try:
        updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        updated_str = updated_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, AttributeError):
        updated_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>Watchlist licitaciones SAP — {html.escape(user_key[:8])}</title>",
        f"  <id>urn:watchlist:{html.escape(user_key[:8])}</id>",
        f"  <updated>{updated_str}</updated>",
        '  <link rel="self" type="application/atom+xml" href="/api/v1/watchlist/feed.xml"/>',
    ]

    for lic in lics:
        fid = html.escape(str(lic.get("id_externo", "")))
        title = html.escape(str(lic.get("titulo") or "(Sin título)"))
        summary = html.escape(str(lic.get("descripcion") or ""))[:500]
        url = html.escape(str(lic.get("url") or ""))
        org = html.escape(str(lic.get("organo_contratacion") or ""))
        importe = lic.get("importe")
        importe_str = f"{float(importe):,.0f} €" if importe else "—"
        pub_raw = lic.get("fecha_publicacion") or ""
        try:
            pub_dt = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
            pub_str = pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, AttributeError):
            pub_str = updated_str

        parts += [
            "  <entry>",
            f"    <id>urn:licitacion:{fid}</id>",
            f"    <title>{title}</title>",
            f"    <updated>{pub_str}</updated>",
            f"    <summary>{summary}</summary>",
            f"    <content type='text'>Órgano: {org} | Importe: {importe_str}</content>",
        ]
        if url:
            parts.append(f'    <link href="{url}"/>')
        parts.append("  </entry>")

    parts.append("</feed>")
    return "\n".join(parts)
