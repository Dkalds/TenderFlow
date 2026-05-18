"""Servicio de watchlist — queries para alertas y digests.

Centraliza las queries SQL que usa ``scheduler/watchlist_alerts.py``
para buscar licitaciones y gestionar ``pending_digests``.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

_WATCHLIST_LIC_COLS = (
    "id_externo, titulo, descripcion, organo_contratacion, "
    "cpv, importe, ccaa, estado, fecha_publicacion, url"
)


def query_licitaciones_since(cpv_prefix: str, since_date: str) -> list[dict[str, Any]]:
    """Devuelve licitaciones con ``fecha_publicacion >= since_date`` y CPV que empiece
    por ``cpv_prefix``."""
    pattern = cpv_prefix + "%"
    with connect_read() as c:
        cur = c.execute(
            f"SELECT {_WATCHLIST_LIC_COLS} FROM licitaciones "  # noqa: S608
            "WHERE fecha_publicacion >= ? AND cpv LIKE ? "
            "ORDER BY fecha_publicacion DESC",
            (since_date, pattern),
        )
        return rows_to_dicts(cur)


def query_licitaciones_batch(
    entries: list[dict[str, Any]], default_since: str
) -> dict[str, list[dict[str, Any]]]:
    """Consulta licitaciones para múltiples entradas watchlist en queries agrupadas por fecha."""
    from collections import defaultdict

    by_since: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        raw_since = entry.get("last_notified_at") or default_since
        by_since[str(raw_since)].append(entry)

    result: dict[str, list[dict[str, Any]]] = {}

    with connect_read() as c:
        for since_date, grp_entries in by_since.items():
            cpv_prefixes = [e["cpv_prefix"] for e in grp_entries]
            placeholders = " OR ".join("cpv LIKE ?" for _ in cpv_prefixes)
            params: list[Any] = [since_date] + [p + "%" for p in cpv_prefixes]
            cur = c.execute(
                f"SELECT {_WATCHLIST_LIC_COLS} FROM licitaciones "  # noqa: S608
                f"WHERE fecha_publicacion >= ? AND ({placeholders}) "
                "ORDER BY fecha_publicacion DESC",
                params,
            )
            rows = rows_to_dicts(cur)

            for prefix in cpv_prefixes:
                result[prefix] = [r for r in rows if (r.get("cpv") or "").startswith(prefix)]

    return result


def store_pending_digest(
    user_key: str,
    recipient: str,
    entry_id: int,
    licitacion_id: str,
    frequency: str,
    matched_at: str,
) -> bool:
    """Persiste una coincidencia en ``pending_digests``. Devuelve ``True`` si tuvo éxito."""
    try:
        with connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO pending_digests "
                "(user_key, recipient_email, entry_id, licitacion_id, frequency, matched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_key, recipient, entry_id, licitacion_id, frequency, matched_at),
            )
        return True
    except Exception as exc:
        log.warning(
            "pending_digest_store_failed",
            entry_id=entry_id,
            licitacion_id=licitacion_id,
            error=str(exc),
        )
        return False


def load_pending_digests(frequency: str) -> list[dict[str, Any]]:
    """Carga los digests pendientes (no enviados) para una frecuencia dada."""
    with connect_read() as c:
        cur = c.execute(
            "SELECT pd.id, pd.recipient_email, pd.entry_id, pd.licitacion_id, pd.user_key, "
            "       l.titulo, l.descripcion, l.organo_contratacion, "
            "       l.cpv, l.importe, l.ccaa, l.estado, l.fecha_publicacion, l.url, "
            "       w.cpv_prefix, w.keyword, w.min_importe, w.ccaa AS entry_ccaa "
            "FROM pending_digests pd "
            "LEFT JOIN licitaciones l ON l.id_externo = pd.licitacion_id "
            "LEFT JOIN watchlist_cpv w ON w.id = pd.entry_id "
            "WHERE pd.sent = 0 AND pd.frequency = ? "
            "ORDER BY pd.recipient_email, pd.entry_id",
            (frequency,),
        )
        return rows_to_dicts(cur)


def mark_digests_sent(digest_ids: list[int]) -> None:
    """Marca los digests como enviados."""
    if not digest_ids:
        return
    with connect() as c:
        placeholders = ",".join("?" for _ in digest_ids)
        c.execute(
            f"UPDATE pending_digests SET sent = 1 WHERE id IN ({placeholders})",  # noqa: S608
            digest_ids,
        )


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

    updated = lics[0].get("fecha_publicacion", datetime.now(UTC).isoformat()) if lics else datetime.now(UTC).isoformat()
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
