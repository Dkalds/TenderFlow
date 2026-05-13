"""Comprueba la watchlist tras cada ejecución del pipeline y envía alertas por email.

Lógica:
- Entradas con ``frequency='immediate'``: se envían en el momento (máx 1 email por usuario
  por ejecución agrupando todas sus coincidencias).
- Entradas con ``frequency='daily'`` o ``'weekly'``: las coincidencias se acumulan en
  ``pending_digests`` y se envían en batch cuando se llama ``send_pending_digests()``.
- Siempre se actualiza ``last_notified_at`` para que la próxima ejecución solo vea
  licitaciones publicadas después de este momento.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from db.database import connect, now_utc_iso
from db.watchlist import list_entries, matches_licitacion, update_last_notified
from observability import AlertLevel, get_logger, notify

log = get_logger(__name__)

# Ventana de búsqueda inicial cuando no hay last_notified_at previo
_LOOKBACK_DAYS = 30
# Máximo de emails inmediatos enviados por usuario por ejecución
_MAX_IMMEDIATE_EMAILS_PER_RUN = 1


def _user_key() -> str:
    """Misma derivación que usa el dashboard (hash del DASHBOARD_PASSWORD)."""
    from config import settings

    seed = settings.DASHBOARD_PASSWORD or os.environ.get("COMPUTERNAME", "default")
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _query_licitaciones_since(cpv_prefix: str, since_date: str) -> list[dict[str, Any]]:
    """Devuelve licitaciones con fecha_publicacion >= since_date y CPV que empiece
    por cpv_prefix. El filtrado fino (keyword, importe, ccaa) lo hace
    matches_licitacion() en Python."""
    pattern = cpv_prefix + "%"
    with connect() as c:
        cur = c.execute(
            "SELECT id_externo, titulo, descripcion, organo_contratacion, "
            "cpv, importe, ccaa, estado, fecha_publicacion, url "
            "FROM licitaciones "
            "WHERE fecha_publicacion >= ? AND cpv LIKE ? "
            "ORDER BY fecha_publicacion DESC",
            (since_date, pattern),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def _query_licitaciones_batch(
    entries: list[dict[str, Any]], default_since: str
) -> dict[str, list[dict[str, Any]]]:
    """Consulta licitaciones para múltiples entradas en una sola query por fecha.

    Agrupa todos los CPV prefixes con el mismo ``since_date``, ejecuta una única
    query con OR de LIKE y devuelve un dict ``{cpv_prefix: [licitaciones]}``.

    Para entradas con ``since_date`` distintos se agrupan por fecha y se hace una
    query por grupo — normalmente 1-2 queries en vez de N.
    """
    from collections import defaultdict

    # Agrupar por since_date para minimizar queries
    by_since: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        raw_since = entry.get("last_notified_at") or default_since
        by_since[str(raw_since)].append(entry)

    result: dict[str, list[dict[str, Any]]] = {}

    with connect() as c:
        for since_date, grp_entries in by_since.items():
            cpv_prefixes = [e["cpv_prefix"] for e in grp_entries]
            placeholders = " OR ".join("cpv LIKE ?" for _ in cpv_prefixes)
            params: list[Any] = [since_date] + [p + "%" for p in cpv_prefixes]
            cur = c.execute(
                "SELECT id_externo, titulo, descripcion, organo_contratacion, "  # noqa: S608
                "cpv, importe, ccaa, estado, fecha_publicacion, url "
                "FROM licitaciones "
                f"WHERE fecha_publicacion >= ? AND ({placeholders}) "
                "ORDER BY fecha_publicacion DESC",
                params,
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

            # Distribuir resultados por CPV prefix (una licitación puede coincidir
            # con varios prefixes — matches_licitacion() hará el filtro fino)
            for prefix in cpv_prefixes:
                result[prefix] = [r for r in rows if (r.get("cpv") or "").startswith(prefix)]

    return result


def _build_body(matches_by_entry: list[tuple[dict[str, Any], list[dict[str, Any]]]]) -> str:
    total = sum(len(lics) for _, lics in matches_by_entry)
    lines: list[str] = [f"Se han encontrado {total} licitación(es) que encajan con tu watchlist:\n"]
    for entry, lics in matches_by_entry:
        parts = [f"CPV: {entry['cpv_prefix']}"]
        if entry.get("keyword"):
            parts.append(f"keyword: {entry['keyword']}")
        if entry.get("min_importe"):
            parts.append(f"importe ≥ {entry['min_importe']:,.0f} €")
        if entry.get("ccaa"):
            parts.append(f"CCAA: {entry['ccaa']}")
        lines.append(f"\n── {' | '.join(parts)} ──────────────────")
        for lic in lics[:10]:
            importe_str = f"{lic['importe']:,.0f} €" if lic.get("importe") else "—"
            url = lic.get("url") or ""
            lines.append(
                f"  • [{lic.get('fecha_publicacion', '?')}] {lic['titulo']}\n"
                f"    {lic.get('organo_contratacion') or '—'} | {importe_str}\n"
                f"    {url}"
            )
        if len(lics) > 10:
            lines.append(f"  … y {len(lics) - 10} más.")
    return "\n".join(lines)


def _store_pending_digests(
    recipient: str,
    user_key: str,
    matches_by_entry: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    frequency: str,
    now_ts: str,
) -> int:
    """Persiste coincidencias en ``pending_digests`` para envío posterior."""
    stored = 0
    with connect() as c:
        for entry, lics in matches_by_entry:
            entry_id = int(entry["id"])
            for lic in lics:
                try:
                    c.execute(
                        "INSERT OR IGNORE INTO pending_digests "
                        "(user_key, recipient_email, entry_id, licitacion_id, frequency, matched_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (user_key, recipient, entry_id, str(lic["id_externo"]), frequency, now_ts),
                    )
                    stored += 1
                except Exception as exc:
                    log.warning(
                        "pending_digest_store_failed",
                        entry_id=entry_id,
                        licitacion_id=lic.get("id_externo"),
                        error=str(exc),
                    )
    return stored


def check_and_notify() -> int:
    """Comprueba la watchlist del usuario y gestiona las alertas según frecuencia.

    - ``frequency='immediate'``: envía un email inmediato por destinatario.
    - ``frequency='daily'`` / ``'weekly'``: acumula en ``pending_digests``.

    Returns:
        Número total de licitaciones notificadas de forma inmediata.
    """
    user_key = _user_key()
    entries = list_entries(user_key)

    if not entries:
        log.debug("watchlist_empty", user_key=user_key)
        return 0

    now_ts = datetime.now(UTC).isoformat()
    default_since = (datetime.now(UTC) - timedelta(days=_LOOKBACK_DAYS)).date().isoformat()

    # Separar entradas por modo: inmediato vs digest
    from collections import defaultdict

    immediate_by_email: dict[str, list[dict[str, Any]]] = defaultdict(list)
    digest_by_email: dict[str, list[dict[str, Any]]] = defaultdict(list)
    entries_without_email: list[dict[str, Any]] = []

    for entry in entries:
        freq = entry.get("frequency") or "daily"
        if not entry.get("email"):
            entries_without_email.append(entry)
        elif freq == "immediate":
            immediate_by_email[entry["email"]].append(entry)
        else:
            # 'daily' o 'weekly' → digest
            digest_by_email[entry["email"]].append(entry)

    total_notified = 0

    # ── Entradas inmediatas: un email por destinatario ─────────────────
    for recipient, recipient_entries in immediate_by_email.items():
        matches_by_entry: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        candidates_by_prefix = _query_licitaciones_batch(recipient_entries, default_since)

        for entry in recipient_entries:
            candidates = candidates_by_prefix.get(entry["cpv_prefix"], [])
            matched = [lic for lic in candidates if matches_licitacion(entry, lic)]
            log.debug(
                "watchlist_entry_checked",
                cpv=entry["cpv_prefix"],
                keyword=entry.get("keyword"),
                candidates=len(candidates),
                matches=len(matched),
                recipient=recipient,
                frequency="immediate",
            )
            if matched:
                matches_by_entry.append((entry, matched))

        for entry in recipient_entries:
            update_last_notified(int(entry["id"]), now_ts)

        if not matches_by_entry:
            continue

        n = sum(len(lics) for _, lics in matches_by_entry)
        body = _build_body(matches_by_entry)
        notify(
            AlertLevel.INFO,
            f"Watchlist: {n} licitación(es) nueva(s)",
            body,
            to_addr=recipient,
            entradas_con_coincidencias=len(matches_by_entry),
            total_coincidencias=n,
        )
        log.info("watchlist_alert_sent", recipient=recipient, total=n, frequency="immediate")
        total_notified += n

    # ── Entradas digest: acumular en pending_digests ───────────────────
    for recipient, recipient_entries in digest_by_email.items():
        candidates_by_prefix = _query_licitaciones_batch(recipient_entries, default_since)
        matches_by_entry = []

        for entry in recipient_entries:
            candidates = candidates_by_prefix.get(entry["cpv_prefix"], [])
            matched = [lic for lic in candidates if matches_licitacion(entry, lic)]
            log.debug(
                "watchlist_entry_checked",
                cpv=entry["cpv_prefix"],
                keyword=entry.get("keyword"),
                candidates=len(candidates),
                matches=len(matched),
                recipient=recipient,
                frequency=entry.get("frequency"),
            )
            if matched:
                matches_by_entry.append((entry, matched))

        for entry in recipient_entries:
            update_last_notified(int(entry["id"]), now_ts)

        if matches_by_entry:
            freq = recipient_entries[0].get("frequency") or "daily"
            stored = _store_pending_digests(recipient, user_key, matches_by_entry, freq, now_ts)
            log.info(
                "watchlist_digest_queued",
                recipient=recipient,
                stored=stored,
                frequency=freq,
            )

    # ── Entradas sin email: solo actualizar timestamp ──────────────────
    for entry in entries_without_email:
        update_last_notified(int(entry["id"]), now_ts)

    if total_notified == 0 and not digest_by_email:
        log.info("watchlist_no_new_matches", entries=len(entries))

    return total_notified


def send_pending_digests(frequency: str = "daily") -> int:
    """Envía los digests pendientes para la frecuencia indicada.

    Agrupa todas las coincidencias pendientes no enviadas por destinatario,
    construye un único email resumen y marca las entradas como enviadas.

    Args:
        frequency: ``'daily'`` o ``'weekly'`` — filtra qué pending_digests procesar.

    Returns:
        Número total de emails de digest enviados.
    """
    if frequency not in ("daily", "weekly"):
        raise ValueError(f"frequency debe ser 'daily' o 'weekly', no {frequency!r}")

    with connect() as c:
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
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    if not rows:
        log.debug("send_pending_digests_nothing", frequency=frequency)
        return 0

    # Agrupar por destinatario → entry → licitaciones
    from collections import defaultdict

    by_recipient: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    digest_ids: list[int] = []
    for row in rows:
        by_recipient[row["recipient_email"]][int(row["entry_id"])].append(row)
        digest_ids.append(int(row["id"]))

    emails_sent = 0
    for recipient, by_entry in by_recipient.items():
        matches_by_entry: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        for entry_id, lics in by_entry.items():
            # Reconstruir entry-like dict desde primera fila
            first = lics[0]
            entry = {
                "id": entry_id,
                "cpv_prefix": first.get("cpv_prefix") or "",
                "keyword": first.get("keyword"),
                "min_importe": first.get("min_importe"),
                "ccaa": first.get("entry_ccaa"),
            }
            # Reconstruir licitacion-like dicts
            lic_dicts = [
                {
                    "id_externo": r["licitacion_id"],
                    "titulo": r.get("titulo") or r["licitacion_id"],
                    "organo_contratacion": r.get("organo_contratacion"),
                    "cpv": r.get("cpv"),
                    "importe": r.get("importe"),
                    "ccaa": r.get("ccaa"),
                    "estado": r.get("estado"),
                    "fecha_publicacion": r.get("fecha_publicacion"),
                    "url": r.get("url"),
                }
                for r in lics
            ]
            matches_by_entry.append((entry, lic_dicts))

        n = sum(len(lics) for _, lics in matches_by_entry)
        body = _build_body(matches_by_entry)
        notify(
            AlertLevel.INFO,
            f"Watchlist ({frequency}): {n} licitación(es)",
            body,
            to_addr=recipient,
            total_coincidencias=n,
            frecuencia=frequency,
        )
        log.info("watchlist_digest_sent", recipient=recipient, total=n, frequency=frequency)
        emails_sent += 1

    # Marcar todos como enviados
    if digest_ids:
        placeholders = ",".join("?" for _ in digest_ids)
        with connect() as c:
            c.execute(
                f"UPDATE pending_digests SET sent = 1 WHERE id IN ({placeholders})",  # noqa: S608
                digest_ids,
            )

    log.info("send_pending_digests_done", emails=emails_sent, frequency=frequency)
    return emails_sent
