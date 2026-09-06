"""Dominio de oportunidades: permisos, transiciones, métricas y agenda."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any, get_args

from db.database import now_utc_iso
from db.notifications import insert_user_notification
from db.repositories.adjudicaciones import (
    LEAD_TIME_MESES,
    AdjudicacionRepository,
    lead_time_por_organo,
)
from db.repositories.agenda import SignalCriteria, signal_rows
from db.repositories.licitaciones import LicitacionRepository
from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuits import PursuitConcurrencyError, PursuitRepository
from db.users import get_user_by_id
from observability.logging import get_logger
from services.analytics.lead_time import estimar_adjudicacion
from services.competitive.renovaciones import proximas_renovaciones
from services.ficha_pdf import BloqueFicha, FichaOportunidad, construir_pdf
from services.kit_presentacion import KitPresentacion, construir_kit, marcar_item
from services.organizations import require_active_member, resolve_organization
from services.watchlist_rules import list_rules
from shared.dto import (
    AgendaUrgencia,
    OrganizationSettings,
    PerdidaPorMotivo,
    PipelineAgendaItem,
    PipelineAgendaKpis,
    PipelineAgendaResponse,
    PursuitAdjudicacionDetectada,
    PursuitAdjudicatario,
    PursuitCreate,
    PursuitDetail,
    PursuitListResponse,
    PursuitMetrics,
    PursuitOutcomeReasonCode,
    PursuitStatus,
    PursuitSummary,
    PursuitUpdate,
)
from shared.identity import user_key_from_email
from shared.tender_facts import RequiredDocumentFact

_repo = PursuitRepository()
_adj_repo = AdjudicacionRepository()
_lic_repo = LicitacionRepository()
log = get_logger(__name__)

TIPO_NOTIFICACION_ASIGNACION = "pursuit_asignada"
_ESTADOS_TERMINALES = frozenset({"won", "lost", "withdrawn"})

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
        score_al_abrir=body.score_al_abrir,
        banda_al_abrir=body.banda_al_abrir,
    )
    if created:
        _notificar_asignacion(row, actor_user_id=user_id)
    return PursuitSummary.model_validate(row), created


def _notificar_asignacion(row: dict[str, Any], *, actor_user_id: int) -> None:
    """Alerta in-app a quien acaba de recibir la oportunidad.

    Asignar a alguien no le decía nada hasta 2026-09: la fila cambiaba de
    responsable y la persona se enteraba al abrir Mi Pipeline, si lo abría.
    Nunca lanza —la asignación ya está escrita— y no avisa a quien se asigna a
    sí mismo. La clave única de ``user_notifications`` hace que reasignar el
    mismo expediente a la misma persona no repita el aviso.
    """
    responsable = row.get("responsible_user_id")
    if responsable is None or int(responsable) == actor_user_id:
        return
    try:
        usuario = get_user_by_id(int(responsable))
        if usuario is None:
            return
        actor = get_user_by_id(actor_user_id) or {}
        quien = str(actor.get("display_name") or actor.get("email") or "Alguien de tu equipo")
        titulo = str(row.get("tender_title") or row.get("licitacion_id") or "")[:80]
        insert_user_notification(
            user_key=user_key_from_email(usuario.get("email"), int(responsable)),
            type_=TIPO_NOTIFICACION_ASIGNACION,
            title=f"Te han asignado: {titulo}",
            body=f"{quien} te asignó esta oportunidad. Ábrela para ver la decisión pendiente "
            "y la próxima acción.",
            licitacion_id=str(row["licitacion_id"]),
            organization_id=int(row["organization_id"]),
        )
    except Exception as exc:
        log.warning(
            "pursuit_assignment_notification_failed",
            pursuit_id=row.get("id"),
            error=str(exc)[:200],
        )


def _adjudicacion_detectada(row: dict[str, Any]) -> PursuitAdjudicacionDetectada | None:
    """Lo que la ingesta ya sabe del resultado del expediente, o ``None``.

    Se calcula en lectura y no se persiste: la adjudicación vive en su tabla y
    puede corregirse con la siguiente pasada; copiarla al pursuit congelaría un
    dato que no es suyo. Las filas se agregan lo justo para la ficha —importe
    total y máximo de ofertas— sin resolver a empresa canónica.
    """
    licitacion_id = str(row["licitacion_id"])
    filas = _adj_repo.list_for_licitacion(licitacion_id)
    if not filas:
        return None
    licitacion = _lic_repo.get_by_id(licitacion_id) or {}
    importes = [float(f["importe_adjudicado"]) for f in filas if f.get("importe_adjudicado")]
    ofertas = [int(f["n_ofertas_recibidas"]) for f in filas if f.get("n_ofertas_recibidas")]
    return PursuitAdjudicacionDetectada(
        estado_licitacion=licitacion.get("estado"),
        adjudicatarios=[
            PursuitAdjudicatario(
                nombre=str(f.get("nombre") or "Adjudicatario sin nombre publicado"),
                nif=f.get("nif"),
                importe_adjudicado=f.get("importe_adjudicado"),
                fecha_adjudicacion=(
                    str(f["fecha_adjudicacion"])[:10] if f.get("fecha_adjudicacion") else None
                ),
                n_ofertas_recibidas=f.get("n_ofertas_recibidas"),
                lote_id=f.get("lote_id"),
            )
            for f in filas
        ],
        importe_total=sum(importes) if importes else None,
        n_ofertas=max(ofertas) if ofertas else None,
        cierre_pendiente=str(row.get("status")) not in _ESTADOS_TERMINALES,
    )


def _detalle(row: dict[str, Any], organization_id: int, pursuit_id: int) -> PursuitDetail:
    return PursuitDetail.model_validate(
        {
            **row,
            "events": _repo.list_events(organization_id, pursuit_id),
            "adjudicacion": _adjudicacion_detectada(row),
        }
    )


def _con_fecha_prevista(rows: list[dict[str, Any]]) -> list[PursuitSummary]:
    """Añade `expected_award` (F4.4) a las filas ya leídas.

    Una sola consulta para toda la página, no una por oportunidad: el tablero
    pinta cincuenta tarjetas y el lead-time es por órgano, no por expediente,
    así que los órganos repetidos —lo normal en una cartera— se resuelven una
    vez.

    Un fallo aquí **no** tumba el listado: la fecha prevista es información
    añadida, y quedarse sin tablero de pipeline porque una consulta de
    percentiles falló sería un mal negocio. Sin ella, cada tarjeta enseña «sin
    estimación», que es exactamente lo que enseñará también un órgano sin
    histórico suficiente.
    """
    organos = sorted({str(r["tender_organo"]) for r in rows if r.get("tender_organo")})
    stats: dict[str, dict[str, Any]] = {}
    if organos:
        desde = (datetime.now(UTC) - timedelta(days=30 * LEAD_TIME_MESES)).date().isoformat()
        try:
            stats = lead_time_por_organo(organos, desde_iso=desde)
        except Exception as exc:
            log.warning("pursuit_lead_time_error", error=str(exc)[:200])

    items: list[PursuitSummary] = []
    for row in rows:
        resumen = PursuitSummary.model_validate(row)
        organo = row.get("tender_organo")
        if organo:
            resumen.expected_award = estimar_adjudicacion(
                row.get("tender_deadline"), stats.get(str(organo))
            )
        items.append(resumen)
    return items


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
        items=_con_fecha_prevista(rows),
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
    return _detalle(row, resolved_id, pursuit_id)


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
    if changes.get("responsible_user_id") is not None:
        _notificar_asignacion(updated, actor_user_id=user_id)
    return _detalle(updated, resolved_id, pursuit_id)


#: Los motivos de D37, como tupla, para el mensaje de error de la ruta.
#: Se derivan del `Literal` del contrato en vez de reescribirse: una lista
#: paralela sería lo primero en quedarse vieja el día que D37 se revise.
MOTIVOS_PERDIDA: tuple[str, ...] = get_args(PursuitOutcomeReasonCode)

#: Pérdidas mínimas para publicar el reparto por motivo.
#:
#: Cinco es el mismo umbral que el plan pide para el corte de la UI, y vive
#: aquí —no en la pantalla— porque el juicio es el mismo en el cuadro de mando,
#: en el informe semanal y en el PDF. Un «60 % por precio» sobre tres casos es
#: ruido con aspecto de conclusión.
MINIMO_PERDIDAS_POR_MOTIVO = 5

#: Etiqueta de los cierres anteriores a F3.1. No es un motivo de D37: es la
#: ausencia de uno, y se cuenta aparte para que no se reparta entre los demás
#: y los infle.
SIN_CODIFICAR = "sin_codificar"


def _perdidas_por_motivo(rows: list[dict[str, Any]]) -> list[PerdidaPorMotivo]:
    """Reparto de las pérdidas por motivo, o lista vacía si no hay base.

    Por debajo de `MINIMO_PERDIDAS_POR_MOTIVO` devuelve **vacío**, no los
    conteos crudos: si los devolviera, cada consumidor tendría que acordarse
    de aplicar el mínimo y el primero que se olvidara publicaría un porcentaje
    sobre dos casos.
    """
    perdidas = [row for row in rows if row.get("outcome") == "lost"]
    if len(perdidas) < MINIMO_PERDIDAS_POR_MOTIVO:
        return []
    conteo: dict[str, int] = {}
    for row in perdidas:
        motivo = str(row.get("outcome_reason_code") or "").strip() or SIN_CODIFICAR
        conteo[motivo] = conteo.get(motivo, 0) + 1
    total = len(perdidas)
    return [
        PerdidaPorMotivo(motivo=motivo, n=n, pct=n / total)
        # Por frecuencia y, a igualdad, por nombre: dos consultas idénticas no
        # pueden devolver el reparto en distinto orden.
        for motivo, n in sorted(conteo.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _trimestre(iso: Any) -> str | None:
    """``2026-Q4`` a partir de una fecha ISO; ``None`` si no se entiende."""
    fecha = _a_fecha_simple(iso)
    return f"{fecha.year}-Q{(fecha.month - 1) // 3 + 1}" if fecha is not None else None


def _a_fecha_simple(valor: Any) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()[:10]
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


def _valor_ponderado(
    rows: list[dict[str, Any]],
    ajustes: OrganizationSettings,
) -> tuple[float, dict[str, float], int, dict[str, int]]:
    """``(valor, previsión por trimestre, sin importe, probabilidades usadas)``.

    Sólo cuenta oportunidades **abiertas**: una ganada ya está contada en
    `awarded_amount_eur` y sumarla aquí la contaría dos veces; una perdida no
    es pipeline. Las probabilidades salen de la configuración de la
    organización, con los defaults de D34 detrás, y viajan con el resultado
    porque son supuestos: sin ellos, la cifra no es reproducible (ADR-014).

    Un expediente sin importe publicado **no** se cuenta como cero, se cuenta
    aparte. Tratarlo como cero baja el pipeline en silencio y hace que la
    cifra dependa de la cobertura del corpus sin que nadie lo vea.
    """
    valor = 0.0
    prevision: dict[str, float] = {}
    sin_importe = 0
    usadas: dict[str, int] = {}

    for row in rows:
        etapa = str(row.get("status") or "")
        probabilidad = ajustes.probabilidad_de(etapa)
        if probabilidad == 0:
            continue  # etapa terminal o desconocida: fuera del pipeline
        usadas[etapa] = probabilidad
        importe = row.get("tender_importe")
        if importe is None:
            sin_importe += 1
            continue
        aporte = float(importe) * probabilidad / 100
        valor += aporte
        trimestre = _trimestre(row.get("tender_deadline"))
        if trimestre is not None:
            prevision[trimestre] = round(prevision.get(trimestre, 0.0) + aporte, 2)

    return round(valor, 2), dict(sorted(prevision.items())), sin_importe, usadas


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
    # Ajustes de la organización para el valor ponderado (F4.1). Una lectura
    # que falle deja los defaults de D34: la cifra sigue siendo correcta y
    # declarada, sólo que sin la personalización.
    try:
        ajustes = OrganizationSettings.model_validate(
            OrganizationRepository().get_settings(resolved_id)
        )
    except Exception as exc:
        log.warning("pursuit_metrics_settings_error", error=str(exc)[:200])
        ajustes = OrganizationSettings()
    valor, prevision, sin_importe, probabilidades = _valor_ponderado(rows, ajustes)

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
        perdidas_por_motivo=_perdidas_por_motivo(rows),
        perdidas_n_minimo=MINIMO_PERDIDAS_POR_MOTIVO,
        pipeline_value_eur=valor,
        probabilidades_etapa_usadas=probabilidades,
        prevision_trimestral=prevision,
        pipeline_sin_importe=sin_importe,
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
    # F3.1 — cerrar en `lost` exige motivo codificado (D37).
    #
    # Es obligatorio en el momento del cierre y no después porque después no
    # se hace: el histórico de motivos que este producto quiere explotar sólo
    # existe si se captura cuando la persona todavía recuerda por qué perdió.
    # Los cierres anteriores a v104 quedan sin código y se completan aparte;
    # esta regla mira `next_outcome`, así que no bloquea editar otra cosa de
    # una oportunidad ya cerrada.
    if next_outcome == "lost" and "outcome" in changes:
        codigo = changes.get("outcome_reason_code", current.get("outcome_reason_code"))
        if not str(codigo or "").strip():
            raise PursuitValidationError(
                "Cerrar una oportunidad como perdida exige un motivo codificado: "
                + ", ".join(MOTIVOS_PERDIDA)
                + "."
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
                    "fecha_fin_origen": row.get("fecha_fin_origen"),
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
        item for item in pursuits if item.dias_restantes is not None and item.dias_restantes <= 7
    ]
    return PipelineAgendaKpis(
        vence_semana=len(en_semana),
        vence_semana_importe_eur=sum(item.importe_eur or 0.0 for item in en_semana),
        go_no_go_pendientes=sum(1 for item in pursuits if item.decision == "pending"),
        sin_proxima_accion=sum(1 for item in pursuits if not item.next_action),
        senales_nuevas=sum(1 for item in items if item.kind == "senal"),
    )


def ficha_pdf(user_id: int, pursuit_id: int, *, organization_id: int | None = None) -> bytes:
    """F2.7 — el one-pager de una oportunidad, en PDF.

    Reutiliza :func:`get_pursuit`, que ya resuelve la organización y comprueba
    la pertenencia: el PDF **no** puede tener su propia ruta de lectura, porque
    entonces habría dos sitios donde olvidarse del ámbito y sólo uno con test
    de aislamiento.

    Los bloques sin dato no se rellenan: se omiten con la nota de por qué. Un
    one-pager con guiones en la mitad de las filas se lee como que el producto
    no sabe nada; la nota se lee como trazabilidad, que es lo que sí sabe.
    """
    detalle = get_pursuit(user_id, pursuit_id, organization_id=organization_id)

    bloques: list[BloqueFicha] = [
        BloqueFicha(
            titulo="Expediente",
            filas=[
                ("Órgano", detalle.tender_organo or "—"),
                ("Identificador", detalle.licitacion_id),
                (
                    "Fecha límite",
                    detalle.tender_deadline.date().isoformat()
                    if detalle.tender_deadline
                    else "sin publicar",
                ),
            ],
        ),
        BloqueFicha(
            titulo="Decisión",
            filas=[
                ("Etapa", detalle.status),
                ("Decisión", detalle.decision),
                *([("Motivo", detalle.decision_reason)] if detalle.decision_reason else []),
                ("Responsable", detalle.responsible_name or "sin asignar"),
                ("Próxima acción", detalle.next_action or "sin definir"),
                *(
                    [("Vence", detalle.next_action_due.isoformat())]
                    if detalle.next_action_due
                    else []
                ),
            ],
        ),
    ]

    if detalle.offer_price_eur is not None:
        bloques.append(
            BloqueFicha(
                titulo="Oferta",
                filas=[("Precio ofertado", f"{detalle.offer_price_eur:,.2f} €")],
                procedencia="Precio registrado por el equipo, no publicado por la fuente.",
            )
        )
    else:
        bloques.append(
            BloqueFicha(
                titulo="Oferta",
                nota_vacio="Todavía no se ha registrado precio ofertado.",
            )
        )

    if detalle.expected_award is not None:
        prevista = detalle.expected_award
        bloques.append(
            BloqueFicha(
                titulo="Fecha prevista de adjudicación",
                filas=[
                    ("Estimación", prevista.fecha.isoformat()),
                    ("Rango p25-p75", f"{prevista.p25.isoformat()} — {prevista.p75.isoformat()}"),
                ],
                procedencia=(
                    f"Estimada sumando el lead-time mediano del órgano a la fecha límite, "
                    f"sobre {prevista.n} adjudicaciones de los últimos 24 meses."
                ),
            )
        )
    else:
        bloques.append(
            BloqueFicha(
                titulo="Fecha prevista de adjudicación",
                nota_vacio=(
                    "Sin estimación: el órgano no tiene adjudicaciones suficientes en los "
                    "últimos 24 meses para calcular un lead-time fiable."
                ),
            )
        )

    if detalle.adjudicacion is not None:
        adj = detalle.adjudicacion
        bloques.append(
            BloqueFicha(
                titulo="Adjudicación observada",
                filas=[
                    ("Adjudicatario", adj.adjudicatarios[0].nombre if adj.adjudicatarios else "—"),
                    (
                        "Fecha",
                        (adj.adjudicatarios[0].fecha_adjudicacion or "—")
                        if adj.adjudicatarios
                        else "—",
                    ),
                    (
                        "Importe adjudicado",
                        f"{adj.importe_total:,.2f} €" if adj.importe_total is not None else "—",
                    ),
                    ("Ofertas recibidas", str(adj.n_ofertas) if adj.n_ofertas is not None else "—"),
                ],
                procedencia="Publicado por la fuente; no es el resultado que registró el equipo.",
            )
        )

    return construir_pdf(
        FichaOportunidad(
            titulo=detalle.tender_title or detalle.licitacion_id,
            subtitulo=f"Oportunidad #{detalle.id} · organización {detalle.organization_id}",
            bloques=bloques,
        )
    )


def _documentos_del_pliego(licitacion_id: str) -> list[RequiredDocumentFact]:
    """Los documentos exigidos de la ficha, o lista vacía si no hay ficha."""
    from services.rag.fact_sheet import get_fact_sheet

    record = get_fact_sheet(licitacion_id)
    return list(record.facts.required_documents) if record and record.facts else []


def kit_de_pursuit(
    user_id: int, pursuit_id: int, *, organization_id: int | None = None
) -> KitPresentacion:
    """F2.3 — el kit de una oportunidad, con su estado.

    Pasa por :func:`get_pursuit`, que ya resuelve la organización y comprueba
    la pertenencia: el kit no puede tener su propia ruta de lectura, porque
    entonces habría dos sitios donde olvidarse del ámbito.
    """
    detalle = get_pursuit(user_id, pursuit_id, organization_id=organization_id)
    return construir_kit(
        detalle.licitacion_id,
        _documentos_del_pliego(detalle.licitacion_id),
        organization_id=detalle.organization_id,
        pursuit_id=pursuit_id,
    )


def marcar_kit_de_pursuit(
    user_id: int,
    pursuit_id: int,
    *,
    clave: str,
    listo: bool,
    organization_id: int | None = None,
) -> KitPresentacion:
    """Marca un ítem y devuelve el kit actualizado.

    Se resuelve la organización **con permiso de escritura**: marcar es una
    modificación del trabajo del equipo, y un `viewer` no debe poder decir que
    la garantía está lista.
    """
    resolved_id, _ = resolve_organization(user_id, organization_id, write=True)
    detalle = get_pursuit(user_id, pursuit_id, organization_id=resolved_id)
    marcar_item(
        organization_id=resolved_id,
        pursuit_id=pursuit_id,
        actor_user_id=user_id,
        clave=clave,
        listo=listo,
    )
    return construir_kit(
        detalle.licitacion_id,
        _documentos_del_pliego(detalle.licitacion_id),
        organization_id=resolved_id,
        pursuit_id=pursuit_id,
    )
