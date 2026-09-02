"""Cierre asistido: avisar cuando un expediente con oportunidad abierta ya se adjudicó.

Hasta 2026-09 ganada, perdida e importe adjudicado se tecleaban a mano aunque
la ingesta ya traía adjudicatario, importe y número de ofertas del mismo
expediente: el win rate dependía de que alguien se acordase de volver a la
ficha. Este job cierra ese hueco por la vía honesta —avisa, no decide—: escribe
una alerta in-app a la persona responsable (o a toda la organización si no la
hay) y la ficha de la oportunidad propone el cierre con los datos publicados.
Quién ganó lo confirma una persona: el sistema no conoce el NIF de la
organización y adivinarlo sería fabricar el dato que las métricas de producto
existen para medir.

Idempotente por construcción: ``user_notifications`` lleva ``UNIQUE(user_key,
licitacion_id, type)``, así que repetir la pasada no vuelve a avisar.
"""

from __future__ import annotations

from typing import Any

from db.notifications import insert_user_notification
from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuits import PursuitRepository
from observability.logging import get_logger
from shared.identity import user_key_from_email

log = get_logger(__name__)

TIPO_NOTIFICACION = "adjudicacion_detectada"
_MAX_TITULO = 80


def _formatear_importe(valor: Any) -> str | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return f"{numero:,.0f} EUR".replace(",", ".")


def _destinatarios(row: dict[str, Any]) -> list[tuple[int, str]]:
    """``(user_id, email)`` de quien debe enterarse: responsable, o el equipo."""
    responsable = row.get("responsible_user_id")
    email = row.get("responsible_email")
    if responsable is not None and email:
        return [(int(responsable), str(email))]
    miembros = OrganizationRepository().list_members(int(row["organization_id"]))
    return [
        (int(m["user_id"]), str(m["email"]))
        for m in miembros
        if m.get("status") == "active" and m.get("email")
    ]


def build_notification(row: dict[str, Any]) -> tuple[str, str]:
    """Título y cuerpo de la alerta a partir de una fila de ``open_with_award_rows``."""
    titulo = str(row.get("titulo") or row.get("licitacion_id") or "")[:_MAX_TITULO]
    adjudicatarios = str(row.get("adjudicatarios") or "").strip() or "adjudicatario no publicado"
    importe = _formatear_importe(row.get("importe_total"))
    detalle = f"Adjudicado a {adjudicatarios}"
    if importe:
        detalle += f" por {importe}"
    return (
        f"Adjudicación publicada: {titulo}",
        f"{detalle}. Cierra la oportunidad con el resultado real desde su ficha.",
    )


def notify_detected_awards(*, limit: int = 500) -> int:
    """Escribe las alertas pendientes. Devuelve cuántas insertó de verdad."""
    rows = PursuitRepository().open_with_award_rows(limit=limit)
    written = 0
    for row in rows:
        title, body = build_notification(row)
        for user_id, email in _destinatarios(row):
            try:
                inserted = insert_user_notification(
                    user_key=user_key_from_email(email, user_id),
                    type_=TIPO_NOTIFICACION,
                    title=title,
                    body=body,
                    licitacion_id=str(row["licitacion_id"]),
                    organization_id=int(row["organization_id"]),
                )
            except Exception as exc:
                log.warning(
                    "pursuit_award_notification_failed",
                    pursuit_id=row.get("pursuit_id"),
                    error=str(exc)[:200],
                )
                continue
            written += int(inserted)
    if written:
        log.info("pursuit_awards_notified", pursuits=len(rows), notifications=written)
    return written
