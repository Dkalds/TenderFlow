"""Dominio de oportunidades: permisos, transiciones y métricas."""

from __future__ import annotations

from datetime import UTC, datetime
from statistics import median
from typing import Any

from db.database import now_utc_iso
from db.repositories.pursuits import PursuitConcurrencyError, PursuitRepository
from services.organizations import require_active_member, resolve_organization
from shared.dto import (
    PursuitCreate,
    PursuitDetail,
    PursuitListResponse,
    PursuitMetrics,
    PursuitStatus,
    PursuitSummary,
    PursuitUpdate,
)

_repo = PursuitRepository()

_TRANSITIONS: dict[str, frozenset[str]] = {
    "identified": frozenset({"qualifying", "withdrawn"}),
    "qualifying": frozenset({"go_no_go", "withdrawn"}),
    "go_no_go": frozenset({"preparing", "withdrawn"}),
    "preparing": frozenset({"submitted", "withdrawn"}),
    "submitted": frozenset({"won", "lost", "withdrawn"}),
    "won": frozenset(),
    "lost": frozenset(),
    "withdrawn": frozenset(),
}
_TERMINAL_OUTCOME = {"won": "won", "lost": "lost", "withdrawn": "cancelled"}


class PursuitNotFoundError(LookupError):
    """La opportunity no existe dentro del scope autorizado."""


class PursuitValidationError(ValueError):
    """Los datos contradicen una regla de negocio."""


class PursuitTransitionError(PursuitValidationError):
    """La transición solicitada no pertenece al workflow canónico."""


class PursuitConflictError(RuntimeError):
    """Conflicto de edición concurrente."""


def create_pursuit(
    user_id: int,
    body: PursuitCreate,
    *,
    idempotency_key: str | None = None,
) -> tuple[PursuitSummary, bool]:
    organization_id, _ = resolve_organization(user_id, body.organization_id, write=True)
    if not _repo.licitacion_exists(body.licitacion_id):
        raise PursuitValidationError("La licitación indicada no existe.")
    responsible_user_id = body.responsible_user_id or user_id
    require_active_member(organization_id, responsible_user_id)
    row, created = _repo.create(
        organization_id=organization_id,
        licitacion_id=body.licitacion_id,
        responsible_user_id=responsible_user_id,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
    )
    return PursuitSummary.model_validate(row), created


def list_pursuits(
    user_id: int,
    *,
    organization_id: int | None = None,
    status: PursuitStatus | None = None,
    responsible_user_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PursuitListResponse:
    resolved_id, _ = resolve_organization(user_id, organization_id)
    rows, total = _repo.list_scoped(
        resolved_id,
        status=status,
        responsible_user_id=responsible_user_id,
        limit=limit,
        offset=offset,
    )
    return PursuitListResponse(
        organization_id=resolved_id,
        items=[PursuitSummary.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_pursuit(
    user_id: int,
    pursuit_id: int,
    *,
    organization_id: int | None = None,
) -> PursuitDetail:
    resolved_id, _ = resolve_organization(user_id, organization_id)
    row = _repo.get(resolved_id, pursuit_id)
    if row is None:
        raise PursuitNotFoundError("Oportunidad no encontrada.")
    return PursuitDetail.model_validate(
        {**row, "events": _repo.list_events(resolved_id, pursuit_id)}
    )


def update_pursuit(
    user_id: int,
    pursuit_id: int,
    body: PursuitUpdate,
    *,
    organization_id: int | None = None,
    idempotency_key: str | None = None,
) -> PursuitDetail:
    resolved_id, _ = resolve_organization(user_id, organization_id, write=True)
    current = _repo.get(resolved_id, pursuit_id)
    if current is None:
        raise PursuitNotFoundError("Oportunidad no encontrada.")

    requested = body.model_dump(exclude_unset=True)
    expected_version = int(requested.pop("expected_version", current["version"]))
    changes = _normalize_and_validate_update(current, requested, resolved_id)
    event_payload = {
        "changes": {
            field: {"from": current.get(field), "to": value}
            for field, value in changes.items()
            if field not in {"decision_at", "submitted_at", "closed_at"}
        },
        "from_version": expected_version,
        "to_version": expected_version + (1 if changes else 0),
    }
    try:
        updated = _repo.update(
            organization_id=resolved_id,
            pursuit_id=pursuit_id,
            actor_user_id=user_id,
            changes=changes,
            expected_version=expected_version,
            event_payload=event_payload,
            idempotency_key=idempotency_key,
        )
    except PursuitConcurrencyError as exc:
        raise PursuitConflictError(str(exc)) from exc
    if updated is None:
        raise PursuitNotFoundError("Oportunidad no encontrada.")
    return PursuitDetail.model_validate(
        {**updated, "events": _repo.list_events(resolved_id, pursuit_id)}
    )


def get_metrics(
    user_id: int,
    *,
    organization_id: int | None = None,
    period_from: datetime | None = None,
    period_to: datetime | None = None,
) -> PursuitMetrics:
    if period_from and period_to and period_to <= period_from:
        raise PursuitValidationError("period_to debe ser posterior a period_from.")
    resolved_id, _ = resolve_organization(user_id, organization_id)
    rows = _repo.metric_rows(
        resolved_id,
        period_from=_as_utc_iso(period_from),
        period_to=_as_utc_iso(period_to),
    )
    won = sum(1 for row in rows if row["outcome"] == "won")
    lost = sum(1 for row in rows if row["outcome"] == "lost")
    resolved = won + lost
    decision_hours = [
        hours
        for row in rows
        if (hours := _elapsed_hours(row.get("identified_at"), row.get("decision_at"))) is not None
    ]
    return PursuitMetrics(
        organization_id=resolved_id,
        period_from=period_from,
        period_to=period_to,
        pursuits_identified=len(rows),
        pursuits_submitted=sum(1 for row in rows if row.get("submitted_at") is not None),
        pursuits_won=won,
        pursuits_lost=lost,
        win_rate=(won / resolved) if resolved else None,
        awarded_amount_eur=sum(
            float(row["awarded_amount_eur"] or 0) for row in rows if row["outcome"] == "won"
        ),
        median_decision_time_hours=median(decision_hours) if decision_hours else None,
    )


def _normalize_and_validate_update(
    current: dict[str, Any],
    requested: dict[str, Any],
    organization_id: int,
) -> dict[str, Any]:
    changes = {field: value for field, value in requested.items() if current.get(field) != value}
    if not changes:
        return {}

    if "responsible_user_id" in changes and changes["responsible_user_id"] is not None:
        require_active_member(organization_id, int(changes["responsible_user_id"]))

    requested_outcome = changes.get("outcome")
    requested_status = changes.get("status")
    if requested_outcome in ("won", "lost") and requested_status is None:
        changes["status"] = requested_outcome
    elif requested_outcome == "cancelled" and requested_status is None:
        changes["status"] = "withdrawn"
    requested_status = changes.get("status")
    if requested_status in _TERMINAL_OUTCOME and "outcome" not in changes:
        changes["outcome"] = _TERMINAL_OUTCOME[str(requested_status)]

    previous_status = str(current["status"])
    next_status = str(changes.get("status", previous_status))
    if next_status != previous_status and next_status not in _TRANSITIONS[previous_status]:
        raise PursuitTransitionError(
            f"Transición no permitida: {previous_status} -> {next_status}."
        )

    now = now_utc_iso()
    next_decision = str(changes.get("decision", current["decision"]))
    next_decision_reason = changes.get("decision_reason", current.get("decision_reason"))
    if next_decision != "pending" and not str(next_decision_reason or "").strip():
        raise PursuitValidationError("Una decisión go/no-go exige motivo.")
    if "decision" in changes:
        changes["decision_at"] = None if next_decision == "pending" else now

    if next_status in {"preparing", "submitted", "won", "lost"} and next_decision != "go":
        raise PursuitValidationError("Preparar o presentar una oferta exige decisión go.")
    if next_decision == "no_go" and next_status not in {"go_no_go", "withdrawn"}:
        raise PursuitValidationError("Una decisión no-go debe cerrar la oportunidad.")

    if next_status == "submitted" and current.get("submitted_at") is None:
        changes["submitted_at"] = now
    if next_status in {"won", "lost"} and current.get("submitted_at") is None:
        raise PursuitValidationError("Ganar o perder exige una oferta presentada.")
    if next_status in _TERMINAL_OUTCOME and current.get("closed_at") is None:
        changes["closed_at"] = now

    next_outcome = str(changes.get("outcome", current["outcome"]))
    expected_outcome = _TERMINAL_OUTCOME.get(next_status)
    if expected_outcome is not None and next_outcome != expected_outcome:
        raise PursuitValidationError("El resultado no coincide con el estado terminal.")
    if next_status not in _TERMINAL_OUTCOME and next_outcome != "pending":
        raise PursuitValidationError("Solo un estado terminal puede tener resultado final.")
    if next_outcome == "won":
        awarded = changes.get("awarded_amount_eur", current.get("awarded_amount_eur"))
        reason = changes.get("outcome_reason", current.get("outcome_reason"))
        if awarded is None and not str(reason or "").strip():
            raise PursuitValidationError(
                "Una oportunidad ganada exige importe adjudicado o justificación."
            )
    return changes


def _as_utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat()


def _elapsed_hours(start: object, end: object) -> float | None:
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=UTC)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=UTC)
    seconds = (end_dt - start_dt).total_seconds()
    return max(0.0, seconds / 3600)
