"""Recordatorios de vencimiento para favoritos del usuario (Feature D).

Escribe en el outbox (``domain_events``) un evento por recordatorio de las
licitaciones favoritas cuyo plazo (``fecha_limite``) o fin de contrato
(``fecha_fin``) se aproxima, de la próxima acción de las oportunidades y de los
aplazamientos del Radar que vencen; el despachador los reparte a la campana y a
los webhooks.

Ventanas: 30 dias, 7 dias, 1 dia.
El ``aviso`` de cada evento lleva la ventana y es el ``type`` de la alerta en la
campana, como antes de pasar al outbox. La idempotencia entre pasadas la da la
clave del agregado ``recordatorio`` (:func:`_emitir`), y la campana deduplica
además por ``(user_id, licitacion_id, type)`` (v162).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from db.events import agregados_con_evento, append_domain_event
from db.repositories.pursuits import PursuitRepository
from db.repositories.watchlist import WatchlistRepository
from observability.logging import get_logger
from shared.dates import instante_utc

log = get_logger(__name__)

#: El SQL de favoritos y plazos vive en el repositorio (ADR-022).
_repo_watchlist = WatchlistRepository()

# Ventanas de alerta en dias
_DEADLINE_WINDOWS = [30, 7, 1]
#: Ventanas de la próxima acción de un pursuit. ``0`` es «hoy»: la acción la
#: fijó el propio equipo y el día señalado merece aviso aunque no falte nada.
_ACCION_WINDOWS = [7, 1, 0]

#: Agregado de los eventos de este módulo: su id es la clave del recordatorio.
_AGREGADO = "recordatorio"

#: ``(tipo de evento, clave, payload, organization_id)`` de un recordatorio.
_Candidato = tuple[str, str, dict[str, Any], int]


def _candidato(
    *,
    aviso: str,
    lic_id: str,
    organization_id: int,
    titulo: str,
    aviso_titulo: str,
    detalle: str,
    user_id: int | None,
    user_key: str | None = None,
    fecha_fin: str | None = None,
) -> _Candidato:
    """Un recordatorio listo para el outbox.

    La clave es la misma identidad que la alerta: aviso, expediente, persona y
    organización. ``user_key`` solo viaja cuando no hay ``user_id`` (aplazamientos
    del Radar que el backfill no resolvió).
    """
    destinatario = str(user_id) if user_id is not None else f"k:{user_key}"
    seguidor: dict[str, Any] = {"user_id": user_id, "organization_id": organization_id}
    if user_id is None:
        seguidor["user_key"] = user_key
    payload: dict[str, Any] = {
        "id_externo": lic_id,
        "licitacion_id": lic_id,
        "aviso": aviso,
        "titulo": titulo,
        "aviso_titulo": aviso_titulo,
        "detalle": detalle,
        "organization_id": organization_id,
        "seguidores": [seguidor],
    }
    tipo = "plazo.recordatorio"
    if fecha_fin is not None:
        tipo = "renovacion.en_ventana"
        payload["fecha_fin"] = fecha_fin
    return tipo, f"{aviso}:{lic_id}:{destinatario}:{organization_id}", payload, organization_id


def _emitir(candidatos: list[_Candidato]) -> int:
    """Escribe los recordatorios que aún no tienen evento. Devuelve cuántos."""
    emitidos = 0
    for tipo in sorted({c[0] for c in candidatos}):
        del_tipo = [c for c in candidatos if c[0] == tipo]
        ya = agregados_con_evento(tipo, _AGREGADO, {c[1] for c in del_tipo})
        for _tipo, clave, payload, organization_id in del_tipo:
            if clave in ya:
                continue
            ya.add(clave)
            append_domain_event(tipo, clave, _AGREGADO, payload, organization_id=organization_id)
            emitidos += 1
    return emitidos


def _get_watchlist_items(user_id: int) -> dict[str, int]:
    """``id_externo -> organization_id`` de los favoritos del usuario.

    Incluye los guardados bajo la clave de un correo anterior que el backfill
    no resolvió: sin ellos no tendrían recordatorio.

    Devuelve un mapa y no una lista porque el recordatorio **hereda la
    organización del favorito que lo origina**. La campana lee
    ``user_notifications`` con ámbito (``services/notifications.get_user_alerts``
    y sus vecinas reciben siempre un ``organization_id`` ya resuelto desde
    ``api/tenancy.py``, nunca ``None``), así que una alerta escrita sin
    organización no aparece en ninguna parte: es la misma clase de fila
    invisible que S4.3 cerró en los repositorios de tenencia, y este job la
    seguía escribiendo con su ``INSERT`` crudo.

    Las filas legacy con ``organization_id IS NULL`` —las que se escribieron
    cuando la columna era opcional— se descartan aquí en vez de propagar el
    ``None`` hasta la escritura. Crear la alerta huérfana sería peor que no
    crearla: gasta la identidad única de la alerta con una fila que el usuario
    no ve. Descartarlas se cura solo: en cuanto
    el favorito pasa a la organización personal de su dueño (lo hizo el
    backfill de tenencia, ya ejecutado), la siguiente pasada del job lo avisa.
    """
    filas = _repo_watchlist.favoritos_con_organizacion(user_id)
    items = {lic: org for lic, org in filas if org is not None}
    descartados = len(filas) - len(items)
    if descartados:
        # Silenciarlo dejaría a un usuario sin recordatorios sin que nada lo
        # delate; el aviso nombra cuántos y a quién para poder correr el
        # backfill de tenencia.
        log.warning(
            "watchlist_items_sin_organizacion",
            user_id=user_id,
            descartados=descartados,
        )
    return items


def _get_licitaciones_for_deadlines(
    ids: list[str],
) -> list[dict[str, Any]]:
    """Carga titulo, fecha_limite y fecha_fin de las licitaciones favoritas."""
    return _repo_watchlist.plazos_de_licitaciones(ids)


def _deadline_type(days_left: int, field: str) -> str:
    """Genera el tipo de notificacion segun la ventana y el campo."""
    prefix = "renovacion" if field == "fecha_fin" else "deadline"
    return f"{prefix}_{days_left}"


def check_deadlines_and_notify(user_id: int) -> int:
    """Emite los recordatorios de plazo de los favoritos del usuario.

    Cada recordatorio lleva la ``organization_id`` del favorito: una alerta sin
    ella no aparece en ninguna campana.

    Returns:
        Número de eventos nuevos escritos.
    """
    favoritos = _get_watchlist_items(user_id)
    if not favoritos:
        return 0

    lics = _get_licitaciones_for_deadlines(list(favoritos))
    now = datetime.now(UTC)
    candidatos: list[_Candidato] = []

    for lic in lics:
        lic_id = str(lic.get("id_externo") or "")
        organization_id = favoritos.get(lic_id)
        if organization_id is None:
            # No debería ocurrir: las licitaciones salen de la propia consulta
            # de favoritos. Si ocurriera, escribir con ``None`` es justo lo que
            # este camino evita, así que se salta.
            continue
        titulo = str(lic.get("titulo") or lic_id)

        for field in ("fecha_limite", "fecha_fin"):
            raw_date = lic.get(field)
            if not raw_date:
                continue
            dt = instante_utc(raw_date)
            if dt is None:
                continue

            days_left = (dt - now).days
            if days_left < 0:
                continue  # ya vencida

            for window in _DEADLINE_WINDOWS:
                if days_left > window:
                    continue
                label = "presentacion" if field == "fecha_limite" else "fin de contrato"
                candidatos.append(
                    _candidato(
                        aviso=_deadline_type(window, field),
                        lic_id=lic_id,
                        organization_id=organization_id,
                        titulo=titulo[:80],
                        aviso_titulo=f"Plazo de {label} en {days_left} dia(s)",
                        detalle=f"La licitacion '{titulo}' vence el "
                        f"{dt.date().isoformat()} ({days_left} dias).",
                        user_id=user_id,
                        fecha_fin=dt.date().isoformat() if field == "fecha_fin" else None,
                    )
                )

    written = _emitir(candidatos)
    if written:
        log.info("deadline_notifications_written", user_id=user_id, count=written)
    return written


def _dias_hasta(raw: object, hoy: date) -> int | None:
    """Días naturales hasta una fecha ISO (o datetime ISO); ``None`` si no parsea."""
    try:
        return (date.fromisoformat(str(raw)[:10]) - hoy).days
    except (ValueError, TypeError):
        return None


def check_pursuit_deadlines() -> int:
    """Recordatorios para los pursuits abiertos con responsable.

    Dos fechas por pursuit: el plazo de presentación del expediente, con las
    mismas ventanas y el mismo ``type`` que los favoritos (``deadline_<n>``,
    así quien además lo tiene en favoritos no recibe el aviso dos veces), y la
    próxima acción que el equipo se fijó (``accion_<n>``, con ventana «hoy»).

    Hasta 2026-09 el pursuit —el objeto con compromisos de verdad— no generaba
    ningún recordatorio: sólo la watchlist lo hacía, y ni siquiera ella corría
    en producción porque nada llamaba a :func:`check_all_users_deadlines`.
    """
    hoy = datetime.now(UTC).date()
    # El horizonte es la mayor de sus ventanas: más allá no hay aviso que
    # mandar, y pedirlo en SQL es lo que impide que el `LIMIT` corte un plazo
    # de mañana por ser de un pursuit creado ayer.
    horizonte = hoy + timedelta(days=max([*_DEADLINE_WINDOWS, *_ACCION_WINDOWS]))
    rows = PursuitRepository().deadline_rows(desde=hoy.isoformat(), hasta=horizonte.isoformat())
    candidatos: list[_Candidato] = []
    for row in rows:
        email = row.get("responsible_email")
        responsable = row.get("responsible_user_id")
        if not email or responsable is None:
            continue
        lic_id = str(row["licitacion_id"])
        titulo = str(row.get("titulo") or lic_id)
        organization_id = int(row["organization_id"])

        dias = _dias_hasta(row.get("fecha_limite"), hoy)
        if dias is not None and dias >= 0:
            for window in _DEADLINE_WINDOWS:
                if dias > window:
                    continue
                candidatos.append(
                    _candidato(
                        aviso=_deadline_type(window, "fecha_limite"),
                        lic_id=lic_id,
                        organization_id=organization_id,
                        titulo=titulo[:80],
                        aviso_titulo=f"Plazo de presentacion en {dias} dia(s)",
                        detalle=f"La oportunidad '{titulo}' vence el "
                        f"{str(row.get('fecha_limite'))[:10]} ({dias} dias).",
                        user_id=int(responsable),
                    )
                )

        accion_dias = _dias_hasta(row.get("next_action_due"), hoy)
        if accion_dias is not None and accion_dias >= 0:
            accion = str(row.get("next_action") or "Próxima acción")[:80]
            cuando = "hoy" if accion_dias == 0 else f"en {accion_dias} dia(s)"
            for window in _ACCION_WINDOWS:
                if accion_dias > window:
                    continue
                candidatos.append(
                    _candidato(
                        aviso=f"accion_{window}",
                        lic_id=lic_id,
                        organization_id=organization_id,
                        titulo=accion,
                        aviso_titulo=f"Proxima accion {cuando}",
                        detalle=f"Oportunidad '{titulo[:80]}'.",
                        user_id=int(responsable),
                    )
                )
    written = _emitir(candidatos)
    if written:
        log.info("pursuit_deadline_notifications_written", count=written)
    return written


def check_all_users_deadlines() -> int:
    """Corre el check de deadlines para todos los usuarios con favoritos y
    para los pursuits abiertos.

    Llamado desde ``_run_watchlist_notify`` (pipeline canónica, cada pasada).
    Returns: total de eventos escritos.
    """
    usuarios = _repo_watchlist.usuarios_con_favoritos()

    total = 0
    for user_id in usuarios:
        try:
            total += check_deadlines_and_notify(user_id)
        except Exception as exc:
            log.warning("deadline_check_error", user_id=user_id, error=str(exc))
    try:
        total += check_pursuit_deadlines()
    except Exception as exc:
        log.warning("pursuit_deadline_check_error", error=str(exc)[:200])
    try:
        total += check_radar_postponements()
    except Exception as exc:
        log.warning("radar_postponement_check_error", error=str(exc)[:200])
    return total


def check_radar_postponements() -> int:
    """F5.6 — avisa de los aplazamientos del Radar que vencen.

    «Recuérdamelo en N días» sólo es una promesa si alguien la cumple. Este
    check convierte cada aplazamiento vencido en un recordatorio, con la
    misma idempotencia que el resto: el ``aviso`` lleva la fecha del
    vencimiento, así que no se repite aunque el job pase cada hora, y un
    segundo aplazamiento del mismo expediente —con otra fecha— sí genera su
    propio aviso.

    Ventana de dos días hacia atrás: cubre de sobra la cadencia del pipeline
    (varias pasadas al día) y evita recorrer el histórico entero en cada
    ejecución. Un aplazamiento cuyo vencimiento caiga en una caída del
    scheduler de más de 48 h se pierde; a cambio, no se avisa en masa de
    recordatorios de hace meses el día que el job vuelva a arrancar, que es el
    fallo más ruidoso de los dos.

    Devuelve cuántos eventos escribió.
    """
    from db import radar_dismissals

    desde = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    try:
        vencidos = radar_dismissals.pospuestos_vencidos(desde_iso=desde)
    except Exception as exc:
        log.warning("radar_postponement_query_error", error=str(exc)[:200])
        return 0

    candidatos: list[_Candidato] = []
    sin_organizacion = 0
    for fila in vencidos:
        organization_id = fila.get("organization_id")
        if organization_id is None:
            # Alerta sin ámbito = alerta que no aparece en ninguna campana y
            # que además gasta la clave única. Se cuenta y se descarta; ver el
            # mismo razonamiento en `_get_watchlist_items`.
            sin_organizacion += 1
            continue
        vencimiento = str(fila.get("hasta") or "")[:10]
        user_id = fila.get("user_id")
        candidatos.append(
            _candidato(
                aviso=f"radar_recordatorio_{vencimiento}",
                lic_id=str(fila["id_externo"]),
                organization_id=int(organization_id),
                titulo=str(fila["id_externo"]),
                aviso_titulo="Vuelve a tu Radar la licitación que aplazaste",
                detalle="Pediste que te la recordáramos hoy. Ya está otra vez en la bandeja.",
                user_id=int(user_id) if user_id is not None else None,
                user_key=str(fila["user_key"]),
            )
        )
    escritas = _emitir(candidatos)
    if escritas or sin_organizacion:
        log.info(
            "radar_postponement_notifications_written",
            count=escritas,
            sin_organizacion=sin_organizacion,
        )
    return escritas
