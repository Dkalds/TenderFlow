"""Detección de anomalías en licitaciones y alertas automáticas.

Reglas implementadas:
1. Importe anómalo — importe > media + N*σ del historial del órgano contratante.
2. Baja temeraria — porcentaje de baja en adjudicación > umbral configurado.
3. Spike de publicaciones — volumen diario > factor * media de los últimos 30 días.

Se ejecuta desde el scheduler loop tras cada ingesta. Las alertas se envían
usando el sistema de observabilidad existente (observability.alerts).
"""

from __future__ import annotations

import math
from typing import Any

from config import settings
from db.database import connect
from observability import AlertLevel, get_logger, notify

log = get_logger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────


def _query_historico_organo(
    organo: str, months: int = 12
) -> tuple[float, float]:
    """Devuelve (media, desv_std) del importe para el órgano en los últimos N meses."""
    with connect() as c:
        cur = c.execute(
            "SELECT importe FROM licitaciones "
            "WHERE organo_contratacion = ? "
            "  AND fecha_publicacion >= date('now', ? || ' months') "
            "  AND importe IS NOT NULL",
            (organo, f"-{months}"),
        )
        importes = [row[0] for row in cur.fetchall() if row[0] is not None]
    if len(importes) < 5:  # sin suficientes muestras, no alertar
        return 0.0, 0.0
    n = len(importes)
    mean = sum(importes) / n
    variance = sum((x - mean) ** 2 for x in importes) / n
    std = math.sqrt(variance) if variance > 0 else 0.0
    return mean, std


def _query_licitaciones_nuevas_hoy() -> list[dict[str, Any]]:
    """Licitaciones publicadas en las últimas 24 horas."""
    with connect() as c:
        cur = c.execute(
            "SELECT id_externo, titulo, organo_contratacion, importe, cpv, url "
            "FROM licitaciones "
            "WHERE fecha_publicacion >= datetime('now', '-1 day') "
            "ORDER BY fecha_publicacion DESC",
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def _query_adjudicaciones_recientes() -> list[dict[str, Any]]:
    """Adjudicaciones registradas en las últimas 24 horas con datos de baja."""
    with connect() as c:
        cur = c.execute(
            "SELECT a.id, a.licitacion_id, a.nombre, a.importe_adjudicado, "
            "       l.importe AS importe_licitacion, l.titulo, l.organo_contratacion "
            "FROM adjudicaciones a "
            "JOIN licitaciones l ON l.id_externo = a.licitacion_id "
            "WHERE a.fecha_adjudicacion >= date('now', '-1 day') "
            "  AND a.importe_adjudicado IS NOT NULL "
            "  AND l.importe IS NOT NULL AND l.importe > 0",
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def _query_volumen_diario_30d() -> float:
    """Media diaria de nuevas licitaciones en los últimos 30 días."""
    with connect() as c:
        cur = c.execute(
            "SELECT COUNT(*) FROM licitaciones "
            "WHERE fecha_publicacion >= date('now', '-30 days')",
        )
        total = cur.fetchone()[0] or 0
    return float(total) / 30.0


def _query_volumen_hoy() -> int:
    with connect() as c:
        cur = c.execute(
            "SELECT COUNT(*) FROM licitaciones "
            "WHERE fecha_publicacion >= date('now', '-1 day')",
        )
        return int(cur.fetchone()[0] or 0)


# ── reglas ────────────────────────────────────────────────────────────────


def check_importe_anomalo(licitaciones: list[dict[str, Any]], sigma: float) -> list[str]:
    """Detecta licitaciones con importe > media + sigma*std de su órgano."""
    alerts: list[str] = []
    for lic in licitaciones:
        importe = lic.get("importe")
        organo = lic.get("organo_contratacion", "")
        if not importe or not organo:
            continue
        mean, std = _query_historico_organo(organo)
        if std == 0.0:
            continue
        threshold = mean + sigma * std
        if float(importe) > threshold and float(importe) > 0:
            msg = (
                f"Importe anómalo detectado: {lic.get('titulo', 'Sin título')[:80]} | "
                f"Órgano: {organo[:60]} | "
                f"Importe: {importe:,.0f}€ (umbral: {threshold:,.0f}€, "
                f"media: {mean:,.0f}€, σ={std:,.0f}€)"
            )
            alerts.append(msg)
            log.warning("anomaly_importe", licitacion_id=lic.get("id_externo"), importe=importe, threshold=threshold)
    return alerts


def check_baja_temeraria(adjudicaciones: list[dict[str, Any]], threshold_pct: float) -> list[str]:
    """Detecta adjudicaciones con baja > threshold_pct %."""
    alerts: list[str] = []
    for adj in adjudicaciones:
        imp_lic = adj.get("importe_licitacion") or 0
        imp_adj = adj.get("importe_adjudicado") or 0
        if imp_lic <= 0 or imp_adj <= 0:
            continue
        baja_pct = (1 - imp_adj / imp_lic) * 100
        if baja_pct >= threshold_pct:
            msg = (
                f"Posible baja temeraria: {adj.get('titulo', '')[:80]} | "
                f"Adjudicatario: {adj.get('nombre', '')[:60]} | "
                f"Baja: {baja_pct:.1f}% "
                f"({imp_lic:,.0f}€ → {imp_adj:,.0f}€)"
            )
            alerts.append(msg)
            log.warning(
                "anomaly_baja_temeraria",
                licitacion_id=adj.get("licitacion_id"),
                baja_pct=round(baja_pct, 1),
            )
    return alerts


def check_spike_publicaciones(factor: float) -> list[str]:
    """Detecta spike de publicaciones respecto a la media diaria de los últimos 30d."""
    media_diaria = _query_volumen_diario_30d()
    if media_diaria < 1:
        return []
    hoy = _query_volumen_hoy()
    if hoy > media_diaria * factor:
        msg = (
            f"Spike de publicaciones: {hoy} licitaciones hoy vs. "
            f"media diaria {media_diaria:.1f} (factor x{hoy / media_diaria:.1f})"
        )
        log.warning("anomaly_spike_publicaciones", hoy=hoy, media_diaria=media_diaria)
        return [msg]
    return []


# ── orquestador ───────────────────────────────────────────────────────────


def run_anomaly_checks() -> int:
    """Ejecuta todas las reglas de detección y envía alertas agregadas.

    Returns:
        Número total de anomalías detectadas.
    """
    if not settings.ANOMALY_ALERT_ENABLED:
        log.debug("anomaly_checks_disabled")
        return 0

    log.info("anomaly_checks_start")
    all_alerts: list[str] = []

    try:
        lics = _query_licitaciones_nuevas_hoy()
        all_alerts.extend(
            check_importe_anomalo(lics, settings.ANOMALY_IMPORTE_SIGMA)
        )
    except Exception as exc:
        log.warning("anomaly_importe_check_failed", error=str(exc))

    try:
        adjs = _query_adjudicaciones_recientes()
        all_alerts.extend(
            check_baja_temeraria(adjs, settings.ANOMALY_BAJA_THRESHOLD)
        )
    except Exception as exc:
        log.warning("anomaly_baja_check_failed", error=str(exc))

    try:
        all_alerts.extend(
            check_spike_publicaciones(settings.ANOMALY_SPIKE_FACTOR)
        )
    except Exception as exc:
        log.warning("anomaly_spike_check_failed", error=str(exc))

    if all_alerts:
        body = "\n\n".join(f"• {a}" for a in all_alerts)
        notify(
            subject=f"[Licitaciones SAP] {len(all_alerts)} anomalía(s) detectada(s)",
            body=body,
            level=AlertLevel.WARN,
            context={"n_anomalias": len(all_alerts)},
        )
        log.warning("anomaly_checks_done", n_anomalias=len(all_alerts))
    else:
        log.info("anomaly_checks_done", n_anomalias=0)

    return len(all_alerts)
