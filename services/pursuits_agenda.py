"""Piezas de la agenda del pipeline: filas, bandas, orden y contadores.

Salieron de ``services/pursuits.py`` (2.300 líneas) por la regla de los
módulos-dios del backlog: un bloque cohesivo se extrae entero cuando se toca.
Son funciones sobre filas ya leídas: no consultan la base salvo las
renovaciones del mercado, y no saben de quién es la agenda.

``get_agenda`` —que resuelve la organización, lee los repositorios y las
reglas del usuario y monta la respuesta con estas piezas— y las señales de
reglas siguen en :mod:`services.pursuits`: dependen de la clave de identidad
heredada que D18 está retirando, y su ratchet no deja que un fichero nuevo
herede esa deuda.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, get_args

from db.repositories.base import csv_values
from db.repositories.pursuits import AgendaPursuitRow
from services.cartera import ContratoCartera
from services.competitive.renovaciones import proximas_renovaciones
from shared.dates import a_fecha, hora_local_de_plazo
from shared.dto import (
    AgendaBanda,
    AgendaContador,
    AgendaDueKind,
    AgendaUrgencia,
    PipelineAgendaContadores,
    PipelineAgendaItem,
    PipelineAgendaKpis,
)
from shared.estados import ESTADOS_CERRADOS

# ── Topes de la agenda ──────────────────────────────────────────────────────
# La agenda declara sus truncamientos en la respuesta (ADR-014: nada de
# presentar un corte como si fuera el total). Los topes existen para acotar la
# respuesta, no para ocultar cola.
AGENDA_PURSUITS_MAX = 500
AGENDA_TAREAS_MAX = 500
AGENDA_SENALES_MAX = 50
AGENDA_SENALES_POR_REGLA = 25
AGENDA_REGLAS_MAX = 20
AGENDA_RENOVACIONES_MAX = 15
AGENDA_RENOVACIONES_MESES = 6

# ── Agenda: fusión, bandas y KPIs ───────────────────────────────────────────

#: A igual día, primero lo que tiene plazo externo (pursuit), después lo que
#: alguien tiene que hacer (tarea), después lo propio que vence (contrato) y
#: al final lo que todavía no es compromiso (señal, renovación de mercado).
_KIND_ORDEN = {"pursuit": 0, "tarea": 1, "contrato": 2, "senal": 3, "renovacion": 4}


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
    """Sin fecha al final; por días; a igual día por ``_KIND_ORDEN``; luego expediente."""
    return (
        item.dias_restantes is None,
        item.dias_restantes if item.dias_restantes is not None else 0,
        _KIND_ORDEN[item.kind],
        item.licitacion_id,
    )


#: El orden de los tramos en pantalla es el del ``Literal``: primero lo que aún
#: se puede hacer (vencido, hoy, semana), después lo que hay que cerrar, después
#: el horizonte, y al final lo que solo queda esperar o no tiene fecha.
_BANDA_ORDEN: dict[AgendaBanda, int] = {
    banda: posicion for posicion, banda in enumerate(get_args(AgendaBanda))
}


def _expediente_cerrado(estado: object, adjudicatarios: object) -> bool:
    """El expediente ya no admite ofertas, diga lo que diga su fecha límite.

    Dos evidencias, y basta una: un estado de cierre (el mismo juicio que usa
    el Radar, ``shared.estados``) o una adjudicación publicada. La segunda
    existe porque TED no mueve el estado del anuncio de licitación —la
    adjudicación llega como otro anuncio— y sin ella esos expedientes
    seguirían pareciendo abiertos para siempre.
    """
    return str(estado or "") in ESTADOS_CERRADOS or bool(str(adjudicatarios or "").strip())


def _banda_de_pursuit(status: object, dias: int | None, *, cerrado: bool = False) -> AgendaBanda:
    """Tramo de una oportunidad: su urgencia, salvo que el plazo ya no obligue.

    Con la oferta presentada no queda plazo que cumplir, venza cuando venza:
    lo pendiente es el resultado. Y si ya no se puede presentar —el plazo pasó
    o el expediente está cerrado— no es una urgencia sino una oportunidad que
    nadie cerró. ``cerrado`` manda sobre la fecha: un expediente resuelto sin
    fecha límite caía en «sin fecha» como si le faltara el siguiente paso.
    """
    if status == "submitted":
        return "en_resolucion"
    if cerrado or (dias is not None and dias < 0):
        return "plazo_pasado"
    return _urgencia(dias)


def _banda(item: PipelineAgendaItem) -> AgendaBanda:
    """La banda de la fila, o su urgencia si quien la construyó no la puso."""
    return item.banda or item.urgencia


def _grupo(item: PipelineAgendaItem) -> tuple[str, str]:
    """Con quién va junta la fila: una oportunidad y sus tareas forman grupo."""
    if item.kind in ("pursuit", "tarea") and item.pursuit_id is not None:
        return ("oportunidad", str(item.pursuit_id))
    return (item.kind, item.licitacion_id)


def _ordenar_agenda(items: Sequence[PipelineAgendaItem]) -> list[PipelineAgendaItem]:
    """Orden final de la agenda: por banda y, dentro de ella, por oportunidad.

    Las tareas van **detrás de su oportunidad** cuando caen en la misma banda:
    juntas se leen como un trabajo, y sueltas obligaban a repetir en cada una
    de qué expediente era. El grupo se coloca por su fila más próxima
    (:func:`_agenda_orden`), así que una tarea de mañana sube consigo al plazo
    de dentro de cinco días. Una tarea cuya oportunidad está en otra banda se
    queda en la suya: la de hoy no espera al plazo de dentro de tres semanas.
    """
    ancla: dict[tuple[AgendaBanda, tuple[str, str]], tuple[bool, int, int, str]] = {}
    for item in items:
        clave = (_banda(item), _grupo(item))
        orden = _agenda_orden(item)
        if clave not in ancla or orden < ancla[clave]:
            ancla[clave] = orden

    def posicion(
        item: PipelineAgendaItem,
    ) -> tuple[int, tuple[bool, int, int, str], tuple[str, str], int, bool, int, int]:
        banda = _banda(item)
        grupo = _grupo(item)
        return (
            _BANDA_ORDEN[banda],
            ancla[(banda, grupo)],
            grupo,
            _KIND_ORDEN[item.kind],
            item.dias_restantes is None,
            item.dias_restantes if item.dias_restantes is not None else 0,
            item.tarea_id or 0,
        )

    return sorted(items, key=posicion)


def _campos_pursuit(row: Mapping[str, Any]) -> dict[str, Any]:
    """Los campos que ``pursuit`` y ``tarea`` comparten: la tarea hereda su oportunidad.

    La fila de una tarea (``PursuitTasksRepository.agenda_rows``) trae las
    columnas del pursuit con los mismos alias que ``PursuitRepository.
    agenda_rows``, así que un solo constructor sirve para las dos.
    """
    return {
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
        "next_action_due": _parse_iso_date(row.get("next_action_due")),
        "version": int(row["version"]),
        "rule_id": None,
        "rule_nombre": None,
        "adjudicatario": None,
        "riesgo_cambio": None,
    }


def _pursuit_item(row: AgendaPursuitRow, hoy: date) -> PipelineAgendaItem:
    """Un pursuit abierto: su fecha es **solo** el plazo de presentación.

    ``next_action``/``next_action_due`` siguen viajando como dato, pero ya no
    mueven ``due_date``: la acción interna es otro compromiso, con otra fila
    (``tarea``), y mezclar los dos plazos en uno dejaba al usuario sin saber
    cuál de los dos vencía.

    La fila mira además **el expediente**, no solo la oportunidad: si ya está
    resuelto o adjudicado, lo dice (``expediente_cerrado``, ``adjudicatario``)
    y cambia de tramo. Sin eso la agenda ofrecía planificar el siguiente paso
    de una licitación que llevaba años adjudicada.
    """
    deadline = _parse_iso_date(row.get("tender_deadline"))
    dias = (deadline - hoy).days if deadline is not None else None
    adjudicatarios = str(row.get("adjudicatarios") or "").strip() or None
    cerrado = _expediente_cerrado(row.get("tender_estado"), adjudicatarios)
    return PipelineAgendaItem.model_validate(
        {
            "kind": "pursuit",
            "urgencia": _urgencia(dias),
            "banda": _banda_de_pursuit(row.get("status"), dias, cerrado=cerrado),
            "due_date": deadline,
            "due_hora": hora_local_de_plazo(row.get("tender_deadline")),
            "due_kind": "plazo",
            "dias_restantes": dias,
            **_campos_pursuit(row),
            # Detrás de los campos comunes: ``_campos_pursuit`` deja
            # ``adjudicatario`` a NULL, que es lo que vale para una tarea.
            "adjudicatario": adjudicatarios,
            "expediente_estado": row.get("tender_estado"),
            "expediente_cerrado": cerrado,
        }
    )


def _tarea_item(
    row: Mapping[str, Any],
    hoy: date,
    *,
    tarea_id: int | None,
    tarea_texto: str | None,
    vence: object,
) -> PipelineAgendaItem:
    """Una acción interna sobre un pursuit abierto, con su propio vencimiento.

    ``row`` es la fila del pursuit (o la de la tarea, que la incluye).
    ``tarea_id`` NULL marca la ``next_action`` manual de un pursuit sin tareas:
    existe como compromiso pero no hay fila de ``pursuit_tasks`` que editar.
    Sin ``vence`` cae en ``sin_fecha``, no en «hoy»: una tarea sin fecha no es
    más urgente que una que vence mañana.
    """
    due = _parse_iso_date(vence)
    dias = (due - hoy).days if due is not None else None
    return PipelineAgendaItem.model_validate(
        {
            "kind": "tarea",
            "urgencia": _urgencia(dias),
            "banda": _urgencia(dias),
            "due_date": due,
            "due_kind": "accion",
            "dias_restantes": dias,
            "tarea_id": tarea_id,
            "tarea_texto": tarea_texto,
            **_campos_pursuit(row),
        }
    )


def _agenda_tareas(
    pursuit_rows: Sequence[AgendaPursuitRow],
    tarea_rows: list[dict[str, Any]],
    hoy: date,
) -> list[PipelineAgendaItem]:
    """Las tareas abiertas, más la ``next_action`` manual de quien no tiene ninguna.

    ``next_action`` se deriva de la tarea abierta más urgente (C6.1), así que
    un pursuit con tareas ya está representado por ellas y repetirlo sería
    contar dos veces el mismo compromiso. Un pursuit con ``next_action`` y sin
    tarea abierta la escribió alguien a mano: se emite como ``tarea`` sin
    ``tarea_id`` para que la agenda no la pierda.
    """
    items = [
        _tarea_item(
            row,
            hoy,
            tarea_id=int(row["tarea_id"]),
            tarea_texto=row.get("tarea_texto"),
            vence=row.get("tarea_vence"),
        )
        for row in tarea_rows
    ]
    con_tarea = {int(row["pursuit_id"]) for row in tarea_rows}
    for row in pursuit_rows:
        if int(row["pursuit_id"]) in con_tarea or not row.get("next_action"):
            continue
        items.append(
            _tarea_item(
                row,
                hoy,
                tarea_id=None,
                tarea_texto=str(row["next_action"]),
                vence=row.get("next_action_due"),
            )
        )
    return items


def _contrato_item(contrato: ContratoCartera, hoy: date) -> PipelineAgendaItem:
    """Un contrato de la cartera propia, con la fecha que obliga a moverse.

    Mientras no haya renovación preparada, la fecha es el **inicio de la
    ventana de relicitación** (``relicitacion``): es cuándo hay que empezar,
    no cuándo se acaba. Con la renovación ya creada —o sin ventana, que solo
    existe si hay fecha de fin— la fecha pasa a ser el fin efectivo
    (``fin_contrato``). Sin fecha de fin de ninguna clase, ``sin_fecha``: la
    cartera no inventa una y la agenda tampoco.
    """
    fin = a_fecha(contrato.fecha_fin_efectiva)
    desde = a_fecha(contrato.relicitacion_desde)
    # Anotados los dos: sin el `| None`, mypy infiere `date` de la primera rama
    # y el contrato sin fecha de fin —el que existe de verdad en la cartera—
    # deja de tipar en la segunda.
    due: date | None
    due_kind: AgendaDueKind
    if desde is not None and contrato.renovacion_pursuit_id is None:
        due, due_kind = desde, "relicitacion"
    else:
        due, due_kind = fin, "fin_contrato"
    dias = (due - hoy).days if due is not None else None
    return PipelineAgendaItem.model_validate(
        {
            "kind": "contrato",
            "urgencia": _urgencia(dias),
            "banda": _urgencia(dias),
            "due_date": due,
            "due_kind": due_kind,
            "dias_restantes": dias,
            "licitacion_id": contrato.licitacion_id,
            "titulo": contrato.titulo,
            "organo": contrato.organo_contratacion,
            "importe_eur": contrato.importe_adjudicado,
            "ccaa": contrato.ccaa,
            "tecnologia": contrato.tecnologia,
            "url": contrato.url,
            # La oportunidad ganada de origen: enlaza a su ficha, no a un
            # pursuit abierto (status/decision/next_action van vacíos).
            "pursuit_id": contrato.pursuit_id,
            "status": None,
            "decision": None,
            "responsible_user_id": None,
            "responsible_name": None,
            "next_action": None,
            "next_action_due": None,
            "version": None,
            "rule_id": None,
            "rule_nombre": None,
            "adjudicatario": None,
            "riesgo_cambio": None,
            "fecha_fin_origen": contrato.fecha_fin_origen,
            "cartera_id": contrato.id,
            "fecha_fin_efectiva": fin,
            "relicitacion_desde": desde,
            "relicitacion_hasta": a_fecha(contrato.relicitacion_hasta),
            "renovacion_pursuit_id": contrato.renovacion_pursuit_id,
            "prorrogas_aplicadas": contrato.prorrogas_aplicadas,
        }
    )


def _agenda_contratos(
    contratos: Sequence[ContratoCartera],
    hoy: date,
    *,
    tecnologias: Sequence[str],
    ccaas: Sequence[str],
) -> list[PipelineAgendaItem]:
    """Los contratos **vivos** de la cartera que caen en el ámbito pedido.

    Vivo es lo mismo aquí que en ``CarteraResumen``: sin fecha de fin, o con
    una que todavía no ha pasado. Nadie borra una fila de la cartera, así que
    sin este corte un contrato que acabó en 2019 entraría con su ventana de
    relicitación abierta desde entonces —banda ``vencida``, miles de días de
    retraso y, por el orden de la agenda, por encima de todo lo que sí exige
    acción hoy—. Un contrato terminado ya no es un compromiso; su relicitación,
    si llega, se busca en Mercado → Renovaciones.

    El ámbito se aplica en Python sobre lo que ya devuelve ``listar_cartera``
    (son decenas de filas) con el mismo criterio que el SQL de pursuits y
    señales: la tecnología se busca en el CSV de la fila. Un contrato **sin**
    el dato no se filtra fuera: no saber la CCAA de un contrato propio no es
    motivo para esconder que vence.
    """
    items: list[PipelineAgendaItem] = []
    for contrato in contratos:
        fin = a_fecha(contrato.fecha_fin_efectiva)
        if fin is not None and fin < hoy:
            continue
        if (
            tecnologias
            and contrato.tecnologia
            and not set(csv_values(contrato.tecnologia)) & set(tecnologias)
        ):
            continue
        if ccaas and contrato.ccaa and contrato.ccaa not in ccaas:
            continue
        items.append(_contrato_item(contrato, hoy))
    return items


def _agenda_renovaciones(
    con_pursuit: set[str],
    hoy: date,
    *,
    tecnologias: Sequence[str],
    ccaas: Sequence[str],
) -> list[PipelineAgendaItem]:
    """Contratos **del mercado** que vencen en el horizonte y aún no se anticiparon.

    Solo se fusionan con ``incluir_mercado``: no son un compromiso de la
    organización, sino oportunidad ajena (los contratos propios ya entran
    como ``contrato``). Un mismo contrato con varios adjudicatarios (UTE)
    aparece una sola vez: la fila más próxima al vencimiento gana.

    ``proximas_renovaciones`` filtra por **una** CCAA; con varias se consulta
    una vez por cada una y se reordena la unión por fecha de fin, para que la
    regla «gana la más próxima» siga valiendo sobre el conjunto.
    """
    regiones: list[str | None] = [*ccaas] if ccaas else [None]
    rows: list[dict[str, Any]] = []
    for region in regiones:
        rows.extend(
            proximas_renovaciones(
                months_ahead=AGENDA_RENOVACIONES_MESES,
                ccaa=region,
                tecnologias=[*tecnologias] or None,
                limit=AGENDA_RENOVACIONES_MAX * 4,
            )
        )
    if len(regiones) > 1:
        rows.sort(key=lambda row: _parse_iso_date(row.get("fecha_fin_efectiva")) or date.max)
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
                    "banda": _urgencia(dias),
                    "due_date": due,
                    "due_kind": "fin_contrato",
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

    ``vence_semana`` mide **plazos de presentación** (pursuits) e incluye lo
    vencido: un compromiso pasado de plazo sigue exigiendo acción, no
    desaparece del contador por llegar tarde. ``acciones_hoy`` mide tareas con
    el mismo criterio (vencidas incluidas) y ``relicitaciones_abiertas``,
    contratos cuya ventana de relicitación ya empezó sin renovación preparada.

    ``sin_proxima_accion`` cuenta pursuits sin ``next_action`` **y** sin tarea
    abierta: la agenda emite una ``tarea`` por cada una de las dos cosas, así
    que basta con mirar qué pursuits no tienen ninguna fila de tarea.
    """
    pursuits = [item for item in items if item.kind == "pursuit"]
    tareas = [item for item in items if item.kind == "tarea"]
    contratos = [item for item in items if item.kind == "contrato"]
    en_semana = [
        item for item in pursuits if item.dias_restantes is not None and item.dias_restantes <= 7
    ]
    con_accion = {item.pursuit_id for item in tareas}
    return PipelineAgendaKpis(
        vence_semana=len(en_semana),
        vence_semana_importe_eur=sum(item.importe_eur or 0.0 for item in en_semana),
        go_no_go_pendientes=sum(1 for item in pursuits if item.decision == "pending"),
        sin_proxima_accion=sum(
            1 for item in pursuits if not item.next_action and item.pursuit_id not in con_accion
        ),
        senales_nuevas=sum(1 for item in items if item.kind == "senal"),
        acciones_hoy=sum(
            1 for item in tareas if item.dias_restantes is not None and item.dias_restantes <= 0
        ),
        relicitaciones_abiertas=sum(
            1
            for item in contratos
            if item.due_kind == "relicitacion"
            and item.dias_restantes is not None
            and item.dias_restantes <= 0
        ),
    )


def _marcar(items: Sequence[PipelineAgendaItem]) -> list[PipelineAgendaItem]:
    """Anota en cada fila los contadores en los que cuenta y sus tareas abiertas.

    Los cuatro contadores de oportunidades miran solo las **vivas**: un plazo
    que pasó sin oferta cuenta en ``plazo_pasado`` y en ninguno más —su
    siguiente paso es cerrarla, no decidir ni planificar— y una oferta
    presentada no cuenta en ninguno. Sin ese corte, cinco oportunidades muertas
    hinchaban a la vez «plazos esta semana», «Go/No-Go pendientes» y «sin
    siguiente paso», y la franja dejaba de decir qué había que hacer.

    Devuelve copias: las filas de entrada no se tocan.
    """
    tareas_por_pursuit: dict[int, int] = {}
    for item in items:
        if item.kind == "tarea" and item.pursuit_id is not None:
            tareas_por_pursuit[item.pursuit_id] = tareas_por_pursuit.get(item.pursuit_id, 0) + 1

    marcados: list[PipelineAgendaItem] = []
    for item in items:
        cuenta_en: list[AgendaContador] = []
        tareas_abiertas: int | None = None
        if item.kind == "pursuit":
            banda = _banda(item)
            tareas_abiertas = tareas_por_pursuit.get(item.pursuit_id or 0, 0)
            if banda == "plazo_pasado":
                cuenta_en.append("plazo_pasado")
            elif banda != "en_resolucion":
                if banda in ("hoy", "semana"):
                    cuenta_en.append("plazo_semana")
                if item.decision == "pending":
                    cuenta_en.append("go_no_go")
                if not item.next_action and tareas_abiertas == 0:
                    cuenta_en.append("sin_paso")
        elif item.kind == "tarea":
            if item.dias_restantes is not None and item.dias_restantes <= 0:
                cuenta_en.append("accion_vencida")
        marcados.append(
            item.model_copy(update={"cuenta_en": cuenta_en, "tareas_abiertas": tareas_abiertas})
        )
    return marcados


def _agenda_contadores(items: Sequence[PipelineAgendaItem]) -> PipelineAgendaContadores:
    """Los contadores de la franja: cuántas filas llevan cada uno en ``cuenta_en``.

    No vuelve a aplicar ninguna regla —eso lo hizo :func:`_marcar`—, así que el
    número de un contador y las filas que quedan al filtrar por él no pueden
    separarse.
    """

    def cuantas(contador: AgendaContador) -> int:
        return sum(1 for item in items if contador in item.cuenta_en)

    return PipelineAgendaContadores(
        plazo_semana=cuantas("plazo_semana"),
        plazo_semana_importe_eur=sum(
            item.importe_eur or 0.0 for item in items if "plazo_semana" in item.cuenta_en
        ),
        accion_vencida=cuantas("accion_vencida"),
        go_no_go=cuantas("go_no_go"),
        sin_paso=cuantas("sin_paso"),
        plazo_pasado=cuantas("plazo_pasado"),
    )
