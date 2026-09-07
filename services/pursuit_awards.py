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

**Desde S2.1 el sistema sí conoce el NIF de la organización** (tabla
``organization_nifs``), así que la ficha ya no llega en blanco: propone
``won``/``lost`` preseleccionado (:func:`sugerir_resultado`) y quien confirma
sigue siendo una persona. La misma identidad fiscal, resuelta contra el maestro
de empresas, es la que permite que «contra quién» no cuente a la propia
organización entre sus competidores (:meth:`IdentidadFiscal.reconoce`).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from db.notifications import insert_user_notification
from db.repositories.organization_nifs import OrganizationNifRepository
from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuits import PursuitRepository
from observability.logging import get_logger
from services.normalization import normalize_nif
from shared.dto import PursuitAdjudicatario
from shared.identity import user_key_from_email

log = get_logger(__name__)

TIPO_NOTIFICACION = "adjudicacion_detectada"
_MAX_TITULO = 80

_nif_repo = OrganizationNifRepository()


@dataclass(frozen=True)
class IdentidadFiscal:
    """Quién es una organización a efectos de contratación pública.

    Dos claves y no una: el NIF es lo que publica la fuente en cada
    adjudicación, y el ``empresa_id`` es cómo agrupa la analítica competitiva
    —que resuelve grupos, UTEs y variantes de nombre—. Comparar solo por NIF
    dejaría a la propia organización dentro de su lista de competidores en
    cuanto la fuente publicara una variante; comparar solo por ``empresa_id``
    fallaría con la organización que aún no ha ganado nada y por tanto no está
    en el maestro.
    """

    nifs: frozenset[str] = frozenset()
    empresa_ids: frozenset[int] = frozenset()

    @property
    def conocida(self) -> bool:
        """``False`` si la organización no ha declarado ningún NIF."""
        return bool(self.nifs)

    def reconoce(
        self,
        *,
        nifs: Iterable[str | None] = (),
        empresa_ids: Iterable[int | None] = (),
    ) -> bool:
        """¿Alguna de esas identidades es la de esta organización?"""
        for nif in nifs:
            normalizado = normalize_nif(nif)
            if normalizado is not None and normalizado in self.nifs:
                return True
        return any(
            empresa_id is not None and int(empresa_id) in self.empresa_ids
            for empresa_id in empresa_ids
        )


def identidad_fiscal(organization_id: int) -> IdentidadFiscal:
    """Lee la identidad fiscal declarada por la organización."""
    nifs = {
        normalizado
        for nif in _nif_repo.nifs(organization_id)
        if (normalizado := normalize_nif(nif)) is not None
    }
    return IdentidadFiscal(
        nifs=frozenset(nifs),
        empresa_ids=frozenset(_nif_repo.empresa_ids(organization_id)),
    )


def sugerir_resultado(
    adjudicatarios: Sequence[PursuitAdjudicatario],
    identidad: IdentidadFiscal,
) -> Literal["won", "lost"] | None:
    """Qué resultado proponer para una adjudicación ya publicada.

    ``None`` significa «no lo sé», nunca «no ganó». Sale así en los dos casos
    en los que afirmar cualquier cosa sería inventar: la organización no ha
    declarado ningún NIF, o la fuente no publicó el del adjudicatario. Solo
    con NIF a los dos lados se puede decir ``lost`` con fundamento.
    """
    if not identidad.conocida:
        return None
    publicados = [
        normalizado
        for adjudicatario in adjudicatarios
        if (normalizado := normalize_nif(adjudicatario.nif)) is not None
    ]
    if not publicados:
        return None
    if any(nif in identidad.nifs for nif in publicados):
        return "won"
    return "lost"


def resultado_sugerido(
    organization_id: int,
    adjudicatarios: Sequence[PursuitAdjudicatario],
) -> Literal["won", "lost"] | None:
    """:func:`sugerir_resultado` leyendo la identidad de la organización."""
    return sugerir_resultado(adjudicatarios, identidad_fiscal(organization_id))


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
