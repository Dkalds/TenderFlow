"""Dominio de oportunidades: permisos, transiciones, métricas y agenda."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

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
from shared.dates import a_fecha
from shared.dto import (
    AgendaUrgencia,
    BajaPropiaResult,
    BajaPropiaSegmento,
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
    RadarBanda,
    RadarBandaCalidad,
    RadarQuality,
)
from shared.identity import user_key_from_email
from shared.scoring_weights import KNOWN_WEIGHT_KEYS, WEIGHTS_TOTAL, validate_scoring_weights
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

# ── Calidad del Radar (S3.2) ────────────────────────────────────────────────
#: Denominador mínimo para publicar un porcentaje por banda. Diez es el suelo
#: por debajo del cual un win rate es anécdota: con cinco cierres, una sola
#: oportunidad mueve el número veinte puntos. El cliente no lo reinventa — la
#: respuesta lo lleva dentro (``RadarQuality.minimo_por_banda``).
RADAR_QUALITY_MINIMO = 10

#: Orden de presentación de las bandas: de más prioritaria a menos, que es
#: como el Radar las pinta.
_ORDEN_BANDAS: tuple[RadarBanda, ...] = ("Caliente", "Atractiva", "Tibia", "Descarte")

# ── Propuesta de pesos (S3.3) ───────────────────────────────────────────────
#: Cierres con desglose sellado que hacen falta para proponer nada. Veinte no
#: es un número redondo por gusto: con seis dimensiones y menos de veinte
#: cierres, la diferencia de medias entre ganadas y perdidas es ruido.
PESOS_MINIMO_CIERRES = 20

#: Cuánto puede moverse una dimensión de una sola vez, en puntos de peso. El
#: ajuste es una sugerencia sobre evidencia parcial, no un reentrenamiento:
#: cinco puntos reordenan la bandeja sin volverla irreconocible.
PESOS_PASO_MAX = 5

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
    lote_numero = _resolver_lote(body.licitacion_id, body.lote_id)
    row, created = _repo.create(
        organization_id=organization_id,
        licitacion_id=body.licitacion_id,
        responsible_user_id=responsible_user_id,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        score_al_abrir=body.score_al_abrir,
        banda_al_abrir=body.banda_al_abrir,
        lote_numero=lote_numero,
        desglose_al_abrir=_serializar_desglose(body.desglose_al_abrir),
    )
    if created:
        _notificar_asignacion(row, actor_user_id=user_id)
    return PursuitSummary.model_validate(row), created


def _resolver_lote(licitacion_id: str, lote_id: int | None) -> str | None:
    """``lote_id`` de la API → ``lote_numero`` persistible, o ``None``.

    ``None`` significa «el expediente completo», que es el caso por defecto y
    el único que existía antes de la revisión ``v110``. Se traduce a número
    porque los ids de ``lotes`` se renumeran en cada re-ingesta
    (``db/upsert.py::replace_lotes``) y una oportunidad tiene que sobrevivir a
    eso; la comprobación de pertenencia impide abrir un expediente apuntando al
    lote de otro.
    """
    if lote_id is None:
        return None
    lote = _repo.lote_by_id(licitacion_id, lote_id)
    if lote is None:
        raise PursuitValidationError("El lote indicado no pertenece a esa licitación.")
    return str(lote["numero"])


def _serializar_desglose(desglose: dict[str, float] | None) -> str | None:
    """El desglose del score, listo para la columna TEXT de ``v110``."""
    if not desglose:
        return None
    return json.dumps(desglose, ensure_ascii=False, sort_keys=True)


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
    detalle = PursuitDetail.model_validate(
        {
            **row,
            "events": _repo.list_events(organization_id, pursuit_id),
            "adjudicacion": _adjudicacion_detectada(row),
        }
    )
    # La fecha prevista (F4.4) también en el detalle: la fila del repositorio no
    # trae la columna, así que sin esto `expected_award` era siempre `None` y la
    # ficha PDF afirmaba «el órgano no tiene adjudicaciones suficientes» junto a
    # una tarjeta del listado que sí enseñaba la fecha, sobre el mismo
    # expediente. Una consulta para un órgano: es una vista de detalle.
    organo = row.get("tender_organo")
    if organo:
        stats = _lead_time_por_organo([str(organo)])
        detalle.expected_award = estimar_adjudicacion(
            row.get("tender_deadline"), stats.get(str(organo))
        )
    return detalle


def _lead_time_por_organo(organos: list[str]) -> dict[str, dict[str, Any]]:
    """Percentiles de lead-time de esos órganos, o ``{}`` si la consulta falla.

    Un fallo aquí **no** tumba a quien llama: la fecha prevista es información
    añadida, y quedarse sin tablero de pipeline —o sin ficha— porque una
    consulta de percentiles falló sería un mal negocio. Sin ella se enseña «sin
    estimación», que es exactamente lo que enseña también un órgano sin
    histórico suficiente.
    """
    if not organos:
        return {}
    desde = (datetime.now(UTC) - timedelta(days=30 * LEAD_TIME_MESES)).date().isoformat()
    try:
        return lead_time_por_organo(organos, desde_iso=desde)
    except Exception as exc:
        log.warning("pursuit_lead_time_error", error=str(exc)[:200])
        return {}


def _con_fecha_prevista(rows: list[dict[str, Any]]) -> list[PursuitSummary]:
    """Añade `expected_award` (F4.4) a las filas ya leídas.

    Una sola consulta para toda la página, no una por oportunidad: el tablero
    pinta cincuenta tarjetas y el lead-time es por órgano, no por expediente,
    así que los órganos repetidos —lo normal en una cartera— se resuelven una
    vez.

    El fallback ante un fallo de la consulta lo pone
    :func:`_lead_time_por_organo`, que comparte con el detalle.
    """
    stats = _lead_time_por_organo(
        sorted({str(r["tender_organo"]) for r in rows if r.get("tender_organo")})
    )

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
    fecha = a_fecha(iso)
    return f"{fecha.year}-Q{(fecha.month - 1) // 3 + 1}" if fecha is not None else None


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

    El trimestre lo fija la **fecha prevista de adjudicación** (F4.4) y sólo
    cae a la fecha límite cuando el órgano no tiene histórico suficiente, que
    es lo que el contrato dice desde el principio. Repartir por la fecha límite
    adelantaba la previsión entera uno o dos trimestres: entre presentar y
    adjudicar hay una mediana de dos o tres meses, así que una oferta que cierra
    el 20 de diciembre se cobraba en Q4 cuando el ingreso llega en Q1.
    """
    valor = 0.0
    prevision: dict[str, float] = {}
    sin_importe = 0
    usadas: dict[str, int] = {}

    # Una consulta de percentiles para todos los órganos de la página, no una
    # por oportunidad: el lead-time es por órgano y una cartera repite órganos.
    stats = _lead_time_por_organo(
        sorted({str(r["tender_organo"]) for r in rows if r.get("tender_organo")})
    )

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
        prevista = estimar_adjudicacion(
            row.get("tender_deadline"), stats.get(str(row.get("tender_organo") or ""))
        )
        trimestre = _trimestre(prevista.fecha if prevista else row.get("tender_deadline"))
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
        radar_quality=calcular_radar_quality(
            rows,
            period_from=period_from,
            period_to=period_to,
        ),
        perdidas_por_motivo=_perdidas_por_motivo(rows),
        perdidas_n_minimo=MINIMO_PERDIDAS_POR_MOTIVO,
        pipeline_value_eur=valor,
        probabilidades_etapa_usadas=probabilidades,
        prevision_trimestral=prevision,
        pipeline_sin_importe=sin_importe,
    )


# ── Calidad del Radar: el bucle que v93 dejó abierto ────────────────────────


def calcular_radar_quality(
    rows: Sequence[Mapping[str, Any]],
    *,
    period_from: datetime | None = None,
    period_to: datetime | None = None,
    minimo: int = RADAR_QUALITY_MINIMO,
) -> RadarQuality | None:
    """Precisión y tasa de cierre por banda de entrada del Radar.

    Función pura sobre las filas que ya trae ``metric_rows``: no abre otra
    consulta a propósito, para que la calidad del Radar y el embudo de la misma
    respuesta no puedan hablar de universos distintos.

    Devuelve ``None`` cuando ninguna fila lleva banda sellada: es el estado
    normal para las oportunidades anteriores a la revisión ``v93``, y publicar
    un objeto con todo a cero diría «el Radar acierta el 0 %» cuando lo cierto
    es que no se midió.
    """
    con_banda = [row for row in rows if row.get("banda_al_abrir") in _ORDEN_BANDAS]
    if not con_banda:
        return None

    bandas: list[RadarBandaCalidad] = []
    for banda in _ORDEN_BANDAS:
        propias = [row for row in con_banda if row.get("banda_al_abrir") == banda]
        if not propias:
            # Una banda sin ninguna oportunidad no se inventa con ceros: no hay
            # nada que decir de ella (ADR-014).
            continue
        ganadas = sum(1 for row in propias if row.get("outcome") == "won")
        perdidas = sum(1 for row in propias if row.get("outcome") == "lost")
        resueltas = ganadas + perdidas
        # "Cerrada" incluye la retirada: dejó de consumir trabajo del equipo.
        # No entra en la precisión —una retirada no dice quién habría ganado—
        # pero sí en la tasa de cierre, que mide cuánto de lo priorizado acabó.
        cerradas = sum(1 for row in propias if row.get("outcome") in ("won", "lost", "cancelled"))
        abiertas = len(propias)
        bandas.append(
            RadarBandaCalidad(
                banda=banda,
                abiertas=abiertas,
                cerradas=cerradas,
                ganadas=ganadas,
                perdidas=perdidas,
                resueltas=resueltas,
                precision=(ganadas / resueltas) if resueltas >= minimo else None,
                tasa_cierre=(cerradas / abiertas) if abiertas >= minimo else None,
                suficiente=resueltas >= minimo,
            )
        )

    observadas = [
        momento
        for row in con_banda
        if (momento := _parse_iso_datetime(row.get("identified_at"))) is not None
    ]
    pedido = period_from is not None or period_to is not None
    return RadarQuality(
        minimo_por_banda=minimo,
        ventana_desde=period_from or (min(observadas) if observadas else None),
        ventana_hasta=period_to or (max(observadas) if observadas else None),
        # Con periodo pedido a medias (solo ``from`` o solo ``to``) el otro
        # extremo se completa con lo observado, pero el origen sigue siendo el
        # periodo: es lo que acota la ventana de la que habla la métrica.
        ventana_origen="periodo_solicitado" if pedido else "historico_observado",
        bandas=bandas,
        pursuits_con_banda=len(con_banda),
        pursuits_total=len(rows),
        cobertura_pct=(100.0 * len(con_banda) / len(rows)) if rows else None,
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


def _parse_iso_datetime(value: object) -> datetime | None:
    """``datetime`` UTC de un TEXT ISO de la base, o ``None`` si no lo es.

    Las columnas de fecha son TEXT (ADR-016/021) y pueden venir sin offset;
    asumir UTC en ese caso es la convención del módulo (``_elapsed_hours``).
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


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


def baja_propia(
    user_id: int,
    *,
    organization_id: int | None = None,
    segmento: str = "cpv",
    limite: int = 50,
) -> BajaPropiaResult:
    """Mi baja media por segmento, para compararla con la del mercado (C6.5).

    El mercado lo da `/competitive/bajas/referencia`; esto es la otra mitad, y
    hasta ahora no existía: el producto sabía cuánto baja el mercado y no cuánto
    baja el equipo que lo usa.

    Sólo entra lo **presentado** y con base sin IVA declarada, y cada segmento
    declara su `n`. Los segmentos con menos de cinco ofertas no salen: con
    menos, un expediente al que se fue muy agresivo convierte «bajamos un 4 %»
    en «bajamos un 22 %», y alguien planifica la siguiente oferta con eso.
    """
    from db.repositories.pursuits import PursuitRepository

    resolved_id, _role = resolve_organization(user_id, organization_id)
    repo = PursuitRepository()
    filas = repo.baja_propia_por_segmento(
        resolved_id,
        segmento="organo" if segmento == "organo" else "cpv",
        limite=limite,
    )
    return BajaPropiaResult(
        organization_id=resolved_id,
        segmento="organo" if segmento == "organo" else "cpv",
        min_ofertas=repo.MIN_OFERTAS_POR_SEGMENTO,
        items=[
            BajaPropiaSegmento(
                segmento=str(f.get("segmento") or "(sin dato)"),
                n=int(f.get("n") or 0),
                baja_propia_pct=_a_float(f.get("baja_propia_pct")),
                baja_min_pct=_a_float(f.get("baja_min_pct")),
                baja_max_pct=_a_float(f.get("baja_max_pct")),
            )
            for f in filas
        ],
    )


def _a_float(valor: object) -> float | None:
    """`Decimal` de Postgres a float, o `None`. Un `0.0` por error sería una baja nula."""
    if valor is None:
        return None
    try:
        return float(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# ── Pesos propuestos, nunca aplicados solos (S3.3) ──────────────────────────
#
# El Radar puntúa con seis dimensiones ponderadas, y hasta ahora esos pesos
# sólo podían moverse a ojo: nadie tenía delante la evidencia de qué dimensión
# separa de verdad lo que la organización gana de lo que pierde.
#
# Lo que sigue construye esa evidencia a partir de los cierres con desglose
# sellado (``v110``) y la deja como **propuesta**. No hay camino automático que
# la aplique: cambiar los pesos reordena la bandeja diaria del equipo, y esa es
# una decisión de quien la firma, no un efecto secundario de haber perdido tres
# licitaciones. Aplicarla es una llamada aparte que además queda en ``audit_log``.


class PesoPropuestoDimension(BaseModel):
    """Una dimensión del score, con la evidencia que sostiene su ajuste.

    ``media_ganadas``/``media_perdidas`` son la media de esa dimensión en el
    desglose sellado de las oportunidades ganadas y de las perdidas. ``delta``
    es su diferencia: positivo significa que la dimensión valía más en lo que se
    ganó, y por eso su peso sube.
    """

    model_config = ConfigDict(extra="forbid")

    dimension: str
    peso_actual: int = Field(ge=0, le=WEIGHTS_TOTAL)
    peso_propuesto: int = Field(ge=0, le=WEIGHTS_TOTAL)
    media_ganadas: float
    media_perdidas: float
    delta: float


class PesosPropuestos(BaseModel):
    """Propuesta de ajuste de pesos con su base declarada (ADR-014).

    ``estado`` es ``insuficiente`` mientras la organización no acumule
    ``minimo_cierres`` oportunidades cerradas **con desglose sellado**. En ese
    estado ``pesos_propuestos`` viaja en ``None`` y ``dimensiones`` vacío: una
    propuesta que no se sostiene no se enseña con una advertencia al lado, no se
    enseña.
    """

    model_config = ConfigDict(extra="forbid")

    organization_id: int = Field(ge=1)
    estado: Literal["propuesta", "insuficiente"]
    #: Cierres con desglose que hacen falta para proponer. Viaja con el dato
    #: para que la pantalla no reinvente el umbral.
    minimo_cierres: int = Field(ge=1)
    n_ganadas: int = Field(ge=0)
    n_perdidas: int = Field(ge=0)
    #: ``n_ganadas + n_perdidas``: la base real de la propuesta.
    n_cierres: int = Field(ge=0)
    #: De dónde salen los pesos vigentes: del perfil de scoring visible en la
    #: organización, o de la configuración global cuando no hay perfil.
    origen_pesos_actuales: Literal["perfil", "global"]
    pesos_actuales: dict[str, int] = Field(default_factory=dict)
    pesos_propuestos: dict[str, int] | None = None
    dimensiones: list[PesoPropuestoDimension] = Field(default_factory=list)


class PesosPropuestosAplicados(BaseModel):
    """Resultado de aplicar la propuesta: qué quedó escrito y sobre qué base."""

    model_config = ConfigDict(extra="forbid")

    organization_id: int = Field(ge=1)
    pesos: dict[str, int]
    #: Visibilidad con la que quedó el perfil de scoring. Se conserva la que
    #: tuviera; sólo cuando no había perfil se crea ``organization``, porque la
    #: propuesta se calcula con los cierres de todo el equipo.
    visibility: Literal["private", "organization"]
    n_cierres: int = Field(ge=0)


def _media(desgloses: Sequence[Mapping[str, float]], dimension: str) -> float:
    """Media de una dimensión tratando su ausencia como 0.

    Ausente no es «desconocido»: el desglose omite la dimensión cuando no
    aportó nada al score (``afinidad`` sin portfolio, ``senal_tecnica`` sin
    señal técnica), y ese cero es justamente su contribución.
    """
    if not desgloses:
        return 0.0
    return sum(float(d.get(dimension, 0.0)) for d in desgloses) / len(desgloses)


def proponer_pesos(
    pesos_actuales: Mapping[str, int],
    ganadas: Sequence[Mapping[str, float]],
    perdidas: Sequence[Mapping[str, float]],
    *,
    paso_max: int = PESOS_PASO_MAX,
) -> tuple[dict[str, int], list[PesoPropuestoDimension]]:
    """Pesos propuestos y su evidencia. Pura: sin BD, sin perfil, sin reloj.

    El ajuste es una redistribución, no una subida: los deltas se centran en su
    media antes de escalarse, así que lo que una dimensión gana lo pierde otra y
    la suma sigue siendo ``WEIGHTS_TOTAL``. Sin centrar, un periodo en que todas
    las dimensiones puntuaron más alto en las ganadas subiría todos los pesos a
    la vez, que en una suma constante no significa nada.

    ``paso_max`` acota el movimiento de la dimensión más separada; el resto se
    mueve en proporción. Los pesos se recortan a ``[0, WEIGHTS_TOTAL - 1]``: el
    tope de arriba es lo que impide que ``afinidad`` llegue a 100, que
    ``validate_scoring_weights`` prohíbe porque deja el resto del score en cero.
    """
    dimensiones = sorted(k for k in pesos_actuales if k in KNOWN_WEIGHT_KEYS)
    deltas = {dim: _media(ganadas, dim) - _media(perdidas, dim) for dim in dimensiones}
    escala = max((abs(valor) for valor in deltas.values()), default=0.0)
    ajustes: dict[str, float] = dict.fromkeys(dimensiones, 0.0)
    if escala == 0.0:
        # Ninguna dimensión separa ganadas de perdidas: la propuesta honesta es
        # no mover nada.
        propuestos = {dim: int(pesos_actuales[dim]) for dim in dimensiones}
    else:
        centro = sum(deltas.values()) / len(dimensiones)
        ajustes = {dim: paso_max * (valor - centro) / escala for dim, valor in deltas.items()}
        propuestos = _reequilibrar(
            {
                dim: max(0, min(WEIGHTS_TOTAL - 1, round(int(pesos_actuales[dim]) + ajustes[dim])))
                for dim in dimensiones
            },
            ajustes,
        )

    evidencia = [
        PesoPropuestoDimension(
            dimension=dim,
            peso_actual=int(pesos_actuales[dim]),
            peso_propuesto=propuestos[dim],
            media_ganadas=round(_media(ganadas, dim), 4),
            media_perdidas=round(_media(perdidas, dim), 4),
            delta=round(deltas[dim], 4),
        )
        for dim in dimensiones
    ]
    return propuestos, evidencia


def _reequilibrar(pesos: dict[str, int], ajustes: Mapping[str, float]) -> dict[str, int]:
    """Corrige el desvío de redondeo para que la suma vuelva a ``WEIGHTS_TOTAL``.

    Reparte la diferencia de uno en uno empezando por la dimensión cuyo ajuste
    apuntaba más fuerte en esa dirección: así el punto suelto cae donde la
    evidencia lo pedía y no en la primera clave alfabética. El desempate es el
    nombre, para que la propuesta sea reproducible.
    """
    resultado = dict(pesos)
    diferencia = WEIGHTS_TOTAL - sum(resultado.values())
    if diferencia == 0 or not resultado:
        return resultado
    paso = 1 if diferencia > 0 else -1
    candidatos = sorted(resultado, key=lambda dim: (-paso * ajustes.get(dim, 0.0), dim))
    # Tope de vueltas: con todas las dimensiones en su límite la diferencia no
    # se puede repartir, y el bucle tiene que terminar igual.
    intentos = 0
    tope = (abs(diferencia) + 1) * len(candidatos)
    while diferencia != 0 and intentos < tope:
        dim = candidatos[intentos % len(candidatos)]
        siguiente = resultado[dim] + paso
        if 0 <= siguiente <= WEIGHTS_TOTAL - 1:
            resultado[dim] = siguiente
            diferencia -= paso
        intentos += 1
    return resultado


def _pesos_vigentes(
    user_key: str, organization_id: int
) -> tuple[dict[str, int], Literal["perfil", "global"]]:
    """Pesos con los que el Radar puntúa hoy, y de dónde salen.

    Mismo orden de precedencia que ``services/analytics/scoring.py``: el perfil
    visible en la organización manda sobre la configuración global. Si no
    coincidieran, la propuesta partiría de unos pesos que nadie está usando.
    """
    from config import settings
    from db.repositories.user_profiles import get_user_profile

    perfil = get_user_profile(user_key, organization_id)
    weights = (perfil or {}).get("weights")
    if isinstance(weights, dict) and weights:
        return {str(k): int(v) for k, v in weights.items()}, "perfil"
    return dict(settings.SCORING_WEIGHTS), "global"


def _desgloses_cerrados(
    organization_id: int,
) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    """Desgloses sellados de las oportunidades ganadas y de las perdidas."""
    ganadas: list[dict[str, float]] = []
    perdidas: list[dict[str, float]] = []
    for row in _repo.closed_scored_rows(organization_id):
        try:
            crudo = json.loads(str(row["desglose_al_abrir"]))
        except (TypeError, ValueError):
            # Un desglose ilegible no puede sostener nada: se descarta del
            # numerador Y del denominador, que es lo que evita que la base
            # declarada mienta.
            log.warning("pursuit_desglose_ilegible", pursuit_id=row.get("id"))
            continue
        if not isinstance(crudo, dict):
            continue
        desglose = {str(k): float(v) for k, v in crudo.items() if isinstance(v, int | float)}
        (ganadas if row.get("outcome") == "won" else perdidas).append(desglose)
    return ganadas, perdidas


def get_weights_proposal(
    user_id: int,
    *,
    user_key: str,
    organization_id: int | None = None,
) -> PesosPropuestos:
    """Propuesta de ajuste de pesos a partir de los cierres de la organización."""
    resolved_id, _ = resolve_organization(user_id, organization_id)
    pesos_actuales, origen = _pesos_vigentes(user_key, resolved_id)
    ganadas, perdidas = _desgloses_cerrados(resolved_id)
    n_cierres = len(ganadas) + len(perdidas)
    if n_cierres < PESOS_MINIMO_CIERRES:
        return PesosPropuestos(
            organization_id=resolved_id,
            estado="insuficiente",
            minimo_cierres=PESOS_MINIMO_CIERRES,
            n_ganadas=len(ganadas),
            n_perdidas=len(perdidas),
            n_cierres=n_cierres,
            origen_pesos_actuales=origen,
            pesos_actuales=pesos_actuales,
            pesos_propuestos=None,
            dimensiones=[],
        )
    propuestos, evidencia = proponer_pesos(pesos_actuales, ganadas, perdidas)
    return PesosPropuestos(
        organization_id=resolved_id,
        estado="propuesta",
        minimo_cierres=PESOS_MINIMO_CIERRES,
        n_ganadas=len(ganadas),
        n_perdidas=len(perdidas),
        n_cierres=n_cierres,
        origen_pesos_actuales=origen,
        pesos_actuales=pesos_actuales,
        pesos_propuestos=propuestos,
        dimensiones=evidencia,
    )


def apply_weights_proposal(
    user_id: int,
    *,
    user_key: str,
    organization_id: int | None = None,
) -> PesosPropuestosAplicados:
    """Escribe la propuesta vigente en el perfil de scoring. Un clic explícito.

    No acepta pesos por parámetro a propósito: si el cliente pudiera mandar los
    suyos, esto sería un ``PUT /me/profile`` con otro nombre y el registro de
    auditoría diría «aplicó la propuesta» sobre unos números que la propuesta
    nunca hizo. Recalcula, aplica lo que acaba de calcular y lo deja escrito.
    """
    from db.audit import log_event
    from db.repositories.user_profiles import get_own_user_profile, upsert_user_profile
    from shared.cache import invalidate_organization_scoped, invalidate_user_scoped

    resolved_id, _ = resolve_organization(user_id, organization_id, write=True)
    propuesta = get_weights_proposal(user_id, user_key=user_key, organization_id=resolved_id)
    if propuesta.estado != "propuesta" or propuesta.pesos_propuestos is None:
        raise PursuitValidationError(
            "Todavía no hay propuesta que aplicar: hacen falta "
            f"{PESOS_MINIMO_CIERRES} oportunidades cerradas con desglose y hay "
            f"{propuesta.n_cierres}."
        )
    pesos = propuesta.pesos_propuestos
    # La propuesta se construye para cumplir la invariante, pero quien escribe
    # el perfil es este llamador: si un cambio futuro la rompiera, el perfil
    # quedaría con pesos que el Radar no sabe usar y nadie se enteraría hasta
    # ver el corpus entero en banda Descarte.
    validate_scoring_weights(pesos)

    previo = get_own_user_profile(user_key)
    visibility: Literal["private", "organization"] = (
        "private" if str((previo or {}).get("visibility") or "") == "private" else "organization"
    )
    # El upsert reemplaza el perfil entero (ver su docstring), así que el resto
    # de los campos se reenvían tal cual: aplicar los pesos no puede borrar de
    # paso las keywords de afinidad ni los CPV de quien lo aplica.
    upsert_user_profile(
        user_key,
        {
            "weights": pesos,
            "afinidad_keywords": (previo or {}).get("afinidad_keywords"),
            "cpvs": (previo or {}).get("cpvs"),
            "importe_min": (previo or {}).get("importe_min"),
            "importe_max": (previo or {}).get("importe_max"),
        },
        resolved_id,
        visibility,
    )
    # El ranking cacheado se calculó con los pesos viejos, en el scope propio y
    # en el de la organización que tuviera antes el perfil.
    invalidate_user_scoped("analytics", "scoring", user_key)
    anterior = (previo or {}).get("organization_id")
    for afectada in {resolved_id, int(anterior) if anterior is not None else None}:
        if afectada is not None:
            invalidate_organization_scoped("analytics", "scoring", afectada)
    log_event(
        event_type="pursuit.weights_proposal_applied",
        user_key=user_key,
        resource=f"organization:{resolved_id}",
        detail={
            "pesos_anteriores": propuesta.pesos_actuales,
            "pesos_aplicados": pesos,
            "n_ganadas": propuesta.n_ganadas,
            "n_perdidas": propuesta.n_perdidas,
        },
    )
    return PesosPropuestosAplicados(
        organization_id=resolved_id,
        pesos=pesos,
        visibility=visibility,
        n_cierres=propuesta.n_cierres,
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
