"""Alertas de movimientos de competidores (watchlist por empresa).

Para cada empresa vigilada detecta, desde ``last_notified_at``:

1. **Adjudicaciones nuevas** — con marca de si suponen entrada en una CCAA
   o familia CPV (2 dígitos) donde la empresa no tenía historial previo.
2. **Vencimientos próximos** — contratos de la empresa que vencen en los
   próximos 90 días (oportunidad de disputa o señal de renovación).

Un email por destinatario y ejecución, agrupando todas sus empresas.
Pensado para correr tras el pipeline de ingesta (mismo punto que
watchlist_alerts.check_and_notify).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from db.watchlist_empresas import list_all, update_last_notified
from observability import AlertLevel, get_logger, notify

log = get_logger(__name__)

# Ventana inicial cuando la entrada nunca ha notificado
_LOOKBACK_DAYS = 30
# Horizonte de vencimientos incluidos en la alerta
_RENOVACION_DIAS = 90


def _nuevas_adjudicaciones(empresa_id: int, since: str) -> list[dict[str, Any]]:
    """Adjudicaciones de la empresa extraídas después de ``since``.

    Marca ``ccaa_nueva``/``cpv_nuevo`` comparando contra el historial previo
    de la propia empresa (anterior a ``since``).
    """
    sql = """
        SELECT a.licitacion_id, l.titulo, l.organo_contratacion, l.cpv, l.ccaa,
               a.importe_adjudicado, a.fecha_adjudicacion, l.url,
               (l.ccaa IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM adjudicaciones a2
                   JOIN licitaciones l2 ON l2.id_externo = a2.licitacion_id
                   WHERE a2.empresa_id = a.empresa_id
                     AND l2.ccaa = l.ccaa
                     AND a2.fecha_extraccion < ?
               )) AS ccaa_nueva,
               (l.cpv IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM adjudicaciones a3
                   JOIN licitaciones l3 ON l3.id_externo = a3.licitacion_id
                   WHERE a3.empresa_id = a.empresa_id
                     AND substr(l3.cpv, 1, 2) = substr(l.cpv, 1, 2)
                     AND a3.fecha_extraccion < ?
               )) AS cpv_nuevo
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        WHERE a.empresa_id = ? AND a.fecha_extraccion >= ?
        ORDER BY a.fecha_adjudicacion DESC
        LIMIT 50
    """
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, (since, since, empresa_id, since)))


def _vencimientos_proximos(empresa_id: int) -> list[dict[str, Any]]:
    from services.competitive.renovaciones import proximas_renovaciones

    return proximas_renovaciones(months_ahead=3, empresa_id=empresa_id, limit=20)


def _build_body(secciones: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]]) -> str:
    lines: list[str] = []
    for nombre, nuevas, vencimientos in secciones:
        lines.append(f"\n══ {nombre} ════════════════════")
        if nuevas:
            lines.append(f"\n  Adjudicaciones nuevas ({len(nuevas)}):")
            for adj in nuevas[:10]:
                marcas = []
                if adj.get("ccaa_nueva"):
                    marcas.append(f"⚑ CCAA nueva: {adj.get('ccaa')}")
                if adj.get("cpv_nuevo"):
                    marcas.append("⚑ CPV nuevo")
                marca_str = f"  [{' · '.join(marcas)}]" if marcas else ""
                importe = (
                    f"{adj['importe_adjudicado']:,.0f} €" if adj.get("importe_adjudicado") else "—"
                )
                lines.append(
                    f"  • [{adj.get('fecha_adjudicacion', '?')}] {adj['titulo']}\n"
                    f"    {adj.get('organo_contratacion') or '—'} | {importe}{marca_str}"
                )
            if len(nuevas) > 10:
                lines.append(f"  … y {len(nuevas) - 10} más.")
        if vencimientos:
            lines.append(f"\n  Contratos que vencen en 90 días ({len(vencimientos)}):")
            for v in vencimientos[:10]:
                importe = (
                    f"{v['importe_adjudicado']:,.0f} €" if v.get("importe_adjudicado") else "—"
                )
                lines.append(
                    f"  • vence {v.get('fecha_fin_efectiva', '?')} "
                    f"({v.get('dias_restantes', '?')} días): {v['titulo']} | {importe}"
                )
    return "\n".join(lines)


def check_and_notify() -> int:
    """Revisa todas las entradas y envía un email por destinatario.

    Devuelve el número de alertas (secciones de empresa con novedades).
    """
    entries = list_all()
    if not entries:
        return 0

    now_ts = datetime.now(UTC).isoformat()
    default_since = (datetime.now(UTC) - timedelta(days=_LOOKBACK_DAYS)).isoformat()

    by_recipient: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_recipient.setdefault(entry["email"], []).append(entry)

    total_alertas = 0
    for recipient, recipient_entries in by_recipient.items():
        secciones: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]] = []
        for entry in recipient_entries:
            since = entry.get("last_notified_at") or default_since
            try:
                nuevas = _nuevas_adjudicaciones(int(entry["empresa_id"]), since)
                vencimientos = _vencimientos_proximos(int(entry["empresa_id"]))
            except Exception as e:
                log.warning(
                    "competitor_alert_query_failed",
                    empresa_id=entry["empresa_id"],
                    error=str(e),
                )
                continue
            if nuevas or vencimientos:
                secciones.append((entry["nombre_canonico"], nuevas, vencimientos))
            update_last_notified(int(entry["id"]), now_ts)

        if not secciones:
            continue
        total_alertas += len(secciones)
        notify(
            AlertLevel.INFO,
            f"Competidores: novedades en {len(secciones)} empresa(s) vigilada(s)",
            _build_body(secciones),
            to_addr=recipient,
            empresas_con_novedades=len(secciones),
        )

    if total_alertas:
        log.info("competitor_alerts_sent", alertas=total_alertas)
    return total_alertas
