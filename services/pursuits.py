"""Dominio de oportunidades: permisos, transiciones, métricas y agenda."""

from __future__ import annotations

from datetime import UTC, date, datetime
from statistics import median
from typing import Any

from db.database import now_utc_iso
from db.repositories.agenda import SignalCriteria, signal_rows
from db.repositories.pursuits import PursuitConcurrencyError, PursuitRepository
from services.competitive.renovaciones import proximas_renovaciones
from services.organizations import require_active_member, resolve_organization
from services.watchlist_rules import list_rules
from shared.dto import (
    AgendaUrgencia,
    PipelineAgendaItem,
    PipelineAgendaKpis,
    PipelineAgendaResponse,
    PursuitCreate,
    PursuitDetail,
    PursuitListResponse,
    PursuitMetrics,
    PursuitStatus,
    PursuitSummary,
    PursuitUpdate,
)

_repo = PursuitRepository()

# ── Topes de la agenda ──────────────────────────────────────────────────────
# La agenda declara sus truncamientos en la respuesta (ADR-014: nada de
# presentar un corte como si fuera el total). Los topes existen para acotar la
# respuesta, no para ocultar cola.
AGENDA_PURSUITS_MAX = 500
AGENDA_SENALES_MAX = 50
AGENDA_SENALES_POR_REGLA = 25
AGENDA_REGLAS_MAX = 20
AGENDA_RENOVACIONES_MAX = 15
AGENDA_RENOVACIONES_MESES = 6

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


def get_agenda(
    user_id: int,
    *,
    user_key: str,
    organization_id: int | None = None,
    solo_mios: bool = False,
    tecnologia: str | None = None,
    ccaa: str | None = None,
) -> PipelineAgendaResponse:
    """Agenda de compromisos: pursuits abiertos, señales sin triar y renovaciones.

    La fusión, el orden y las bandas de urgencia se calculan aquí; el frontend
    solo agrupa por la banda que ya viene puesta. Las señales reutilizan el
    triaje del Radar: seguir = crear pursuit, descartar = ``radar_dismissals``.
    """
    resolved_id, _ = resolve_organization(user_id, organization_id)
    hoy = datetime.now(UTC).date()

    pursuit_rows, pursuits_truncados = _repo.agenda_rows(
        resolved_id,
        responsible_user_id=user_id if solo_mios else None,
        tecnologia=tecnologia,
        ccaa=ccaa,
        limit=AGENDA_PURSUITS_MAX,
    )
    items = [_pursuit_item(row, hoy) for row in pursuit_rows]

    senal_items, senales_truncadas = _agenda_senales(
        user_key,
        resolved_id,
        hoy,
        tecnologia=tecnologia,
        ccaa=ccaa,
    )
    items.extend(senal_items)
    items.extend(
        _agenda_renovaciones(
            _repo.licitacion_ids(resolved_id),
            hoy,
            tecnologia=tecnologia,
            ccaa=ccaa,
        )
    )

    items.sort(key=_agenda_orden)
    return PipelineAgendaResponse(
        organization_id=resolved_id,
        solo_mios=solo_mios,
        items=items,
        kpis=_agenda_kpis(items),
        pursuits_total=len(pursuit_rows),
        pursuits_truncados=pursuits_truncados,
        senales_truncadas=senales_truncadas,
        renovaciones_horizonte_meses=AGENDA_RENOVACIONES_MESES,
    )


def _normalize_and_validate_update(
    current: dict[str, Any],
    requested: dict[str, Any],
    organization_id: int,
) -> dict[str, Any]:
    if "next_action" in requested:
        texto = str(requested["next_action"] or "").strip()
        requested["next_action"] = texto or None
    if isinstance(requested.get("next_action_due"), date):
        # La columna es TEXT ISO (v83); serializar aquí mantiene comparable el
        # diff contra ``current`` y el payload del evento JSON-serializable.
        requested["next_action_due"] = requested["next_action_due"].isoformat()
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


# ── Agenda: fusión, bandas y KPIs ───────────────────────────────────────────

_KIND_ORDEN = {"pursuit": 0, "senal": 1, "renovacion": 2}


def _urgencia(dias: int | None) -> AgendaUrgencia:
    """Banda de urgencia de un compromiso a ``dias`` vista. Pura y testeable."""
    if dias is None:
        return "sin_fecha"
    if dias < 0:
        return "vencida"
    if dias == 0:
        return "hoy"
    if dias <= 7:
        return "semana"
    if dias <= 30:
        return "mes"
    return "despues"


def _parse_iso_date(value: object) -> date | None:
    """Fecha de un TEXT ISO (``YYYY-MM-DD`` o timestamp completo), o ``None``."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _agenda_orden(item: PipelineAgendaItem) -> tuple[bool, int, int, str]:
    """Sin fecha al final; a igual día, pursuit antes que señal y renovación."""
    return (
        item.dias_restantes is None,
        item.dias_restantes if item.dias_restantes is not None else 0,
        _KIND_ORDEN[item.kind],
        item.licitacion_id,
    )


def _pursuit_item(row: dict[str, Any], hoy: date) -> PipelineAgendaItem:
    deadline = _parse_iso_date(row.get("tender_deadline"))
    next_due = _parse_iso_date(row.get("next_action_due"))
    fechas = [valor for valor in (deadline, next_due) if valor is not None]
    due = min(fechas) if fechas else None
    dias = (due - hoy).days if due is not None else None
    return PipelineAgendaItem.model_validate(
        {
            "kind": "pursuit",
            "urgencia": _urgencia(dias),
            "due_date": due,
            "dias_restantes": dias,
            "licitacion_id": str(row["licitacion_id"]),
            "titulo": row.get("titulo"),
            "organo": row.get("organo"),
            "importe_eur": row.get("importe_eur"),
            "ccaa": row.get("ccaa"),
            "tecnologia": row.get("tecnologia"),
            "url": row.get("url"),
            "pursuit_id": int(row["pursuit_id"]),
            "status": row.get("status"),
            "decision": row.get("decision"),
            "responsible_user_id": row.get("responsible_user_id"),
            "responsible_name": row.get("responsible_name"),
            "next_action": row.get("next_action"),
            "next_action_due": next_due,
            "version": int(row["version"]),
            "rule_id": None,
            "rule_nombre": None,
            "adjudicatario": None,
            "riesgo_cambio": None,
        }
    )


def _agenda_senales(
    user_key: str,
    organization_id: int,
    hoy: date,
    *,
    tecnologia: str | None,
    ccaa: str | None,
) -> tuple[list[PipelineAgendaItem], bool]:
    """Matches vivos y sin triar de las reglas activas del usuario, deduplicados."""
    reglas = [regla for regla in list_rules(user_key, organization_id) if regla.active]
    recogidas: dict[str, PipelineAgendaItem] = {}
    for regla in reglas[:AGENDA_REGLAS_MAX]:
        if regla.id is None:
            continue
        criterios = SignalCriteria(
            rule_id=regla.id,
            nombre=regla.nombre,
            keyword=regla.keyword,
            cpv=regla.cpv,
            min_importe=regla.min_importe,
            ccaa=regla.ccaa,
        )
        etiqueta = regla.nombre or regla.keyword or regla.cpv or f"Regla {regla.id}"
        for row in signal_rows(
            criterios,
            user_key=user_key,
            organization_id=organization_id,
            tecnologia=tecnologia,
            ccaa=ccaa,
            limit=AGENDA_SENALES_POR_REGLA,
        ):
            licitacion_id = str(row["id_externo"])
            if licitacion_id in recogidas:
                continue
            deadline = _parse_iso_date(row.get("fecha_limite"))
            dias = (deadline - hoy).days if deadline is not None else None
            recogidas[licitacion_id] = PipelineAgendaItem.model_validate(
                {
                    "kind": "senal",
                    "urgencia": _urgencia(dias),
                    "due_date": deadline,
                    "dias_restantes": dias,
                    "licitacion_id": licitacion_id,
                    "titulo": row.get("titulo"),
                    "organo": row.get("organo"),
                    "importe_eur": row.get("importe_eur"),
                    "ccaa": row.get("ccaa"),
                    "tecnologia": row.get("tecnologia"),
                    "url": row.get("url"),
                    "pursuit_id": None,
                    "status": None,
                    "decision": None,
                    "responsible_user_id": None,
                    "responsible_name": None,
                    "next_action": None,
                    "next_action_due": None,
                    "version": None,
                    "rule_id": regla.id,
                    "rule_nombre": etiqueta,
                    "adjudicatario": None,
                    "riesgo_cambio": None,
                }
            )
    senales = list(recogidas.values())
    senales.sort(key=_agenda_orden)
    return senales[:AGENDA_SENALES_MAX], len(senales) > AGENDA_SENALES_MAX


def _agenda_renovaciones(
    con_pursuit: set[str],
    hoy: date,
    *,
    tecnologia: str | None,
    ccaa: str | None,
) -> list[PipelineAgendaItem]:
    """Contratos que vencen en el horizonte y aún no se anticiparon.

    Un mismo contrato con varios adjudicatarios (UTE) aparece una sola vez:
    la fila más próxima al vencimiento gana, que es la primera del orden SQL.
    """
    rows = proximas_renovaciones(
        months_ahead=AGENDA_RENOVACIONES_MESES,
        ccaa=ccaa,
        tecnologias=[tecnologia] if tecnologia else None,
        limit=AGENDA_RENOVACIONES_MAX * 4,
    )
    items: list[PipelineAgendaItem] = []
    vistos: set[str] = set()
    for row in rows:
        licitacion_id = str(row["licitacion_id"])
        if licitacion_id in con_pursuit or licitacion_id in vistos:
            continue
        vistos.add(licitacion_id)
        due = _parse_iso_date(row.get("fecha_fin_efectiva"))
        dias = (due - hoy).days if due is not None else None
        items.append(
            PipelineAgendaItem.model_validate(
                {
                    "kind": "renovacion",
                    "urgencia": _urgencia(dias),
                    "due_date": due,
                    "dias_restantes": dias,
                    "licitacion_id": licitacion_id,
                    "titulo": row.get("titulo"),
                    "organo": row.get("organo_contratacion"),
                    "importe_eur": row.get("importe_adjudicado"),
                    "ccaa": row.get("ccaa"),
                    "tecnologia": None,
                    "url": row.get("url"),
                    "pursuit_id": None,
                    "status": None,
                    "decision": None,
                    "responsible_user_id": None,
                    "responsible_name": None,
                    "next_action": None,
                    "next_action_due": None,
                    "version": None,
                    "rule_id": None,
                    "rule_nombre": None,
                    "adjudicatario": row.get("empresa"),
                    "riesgo_cambio": row.get("riesgo_cambio"),
                }
            )
        )
        if len(items) >= AGENDA_RENOVACIONES_MAX:
            break
    return items


def _agenda_kpis(items: list[PipelineAgendaItem]) -> PipelineAgendaKpis:
    """KPIs sobre los items ya fusionados del scope pedido.

    ``vence_semana`` incluye lo vencido: un compromiso pasado de plazo sigue
    exigiendo acción, no desaparece del contador por llegar tarde.
    """
    pursuits = [item for item in items if item.kind == "pursuit"]
    en_semana = [
        item
        for item in pursuits
        if item.dias_restantes is not None and item.dias_restantes <= 7
    ]
    return PipelineAgendaKpis(
        vence_semana=len(en_semana),
        vence_semana_importe_eur=sum(item.importe_eur or 0.0 for item in en_semana),
        go_no_go_pendientes=sum(1 for item in pursuits if item.decision == "pending"),
        sin_proxima_accion=sum(1 for item in pursuits if not item.next_action),
        senales_nuevas=sum(1 for item in items if item.kind == "senal"),
    )
