"""Recordatorios de vencimiento para favoritos del usuario (Feature D).

Escribe en el outbox (``domain_events``) un evento por recordatorio de las
licitaciones favoritas cuyo plazo (``fecha_limite``) o fin de contrato
(``fecha_fin``) se aproxima, de la próxima acción de las oportunidades y de los
aplazamientos del Radar que vencen; el despachador los reparte a la campana y a
los webhooks.

Ventanas: 30 dias, 7 dias, 1 dia. El plazo para recurrir los pliegos de un
expediente con indicios (``recurso_<n>``) avisa a 5 y 1 días.
El ``aviso`` de cada evento lleva la ventana y es el ``type`` de la alerta en la
campana, como antes de pasar al outbox. La idempotencia entre pasadas la da la
clave del agregado ``recordatorio`` (:func:`_emitir`), y la campana deduplica
además por ``(user_id, licitacion_id, type)`` (v162).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from db.events import agregados_con_evento, append_domain_event
from db.repositories.pursuits import PursuitRepository
from db.repositories.watchlist import WatchlistRepository
from observability.logging import get_logger
from services.condiciones_oficiales import condiciones_oficiales_de
from shared.dates import instante_utc

log = get_logger(__name__)

#: El SQL de favoritos y plazos vive en el repositorio (ADR-022).
_repo_watchlist = WatchlistRepository()

# Ventanas de alerta en dias
_DEADLINE_WINDOWS = [30, 7, 1]
#: Ventanas de la próxima acción de un pursuit. ``0`` es «hoy»: la acción la
#: fijó el propio equipo y el día señalado merece aviso aunque no falte nada.
_ACCION_WINDOWS = [7, 1, 0]

#: Ventanas del plazo para recurrir los pliegos, en días naturales.
_RECURSO_WINDOWS = [5, 1]
#: Días naturales desde la publicación en los que el plazo de recurso puede
#: seguir abierto: 15 hábiles no pasan de 25 naturales ni con Navidad o Semana
#: Santa por medio. Más atrás no se leen las condiciones del expediente.
_HORIZONTE_RECURSO = 40

#: Agregado de los eventos de este módulo: su id es la clave del recordatorio.
_AGREGADO = "recordatorio"

#: Plazo de recurso por expediente dentro de una pasada: ``None`` si no hay
#: aviso que dar. Un expediente seguido por varios usuarios se lee una vez.
_PlazosRecurso = dict[str, date | None]

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
    user_id: int,
    fecha_fin: str | None = None,
) -> _Candidato:
    """Un recordatorio listo para el outbox.

    La clave es la misma identidad que la alerta: aviso, expediente, persona y
    organización.
    """
    destinatario = str(user_id)
    seguidor: dict[str, Any] = {"user_id": user_id, "organization_id": organization_id}
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
            try:
                append_domain_event(
                    tipo, clave, _AGREGADO, payload, organization_id=organization_id
                )
            except Exception as exc:
                # Van todos los usuarios en el mismo lote: un evento que la base
                # rechaza no puede dejar sin aviso a los que vienen detrás.
                log.warning("recordatorio_emitir_error", clave=clave, error=str(exc)[:200])
                continue
            ya.add(clave)
            emitidos += 1
    return emitidos


def _en_horizonte_recurso(fecha_publicacion: object, hoy: date) -> bool:
    """Si el expediente se publicó hace poco como para seguir siendo recurrible."""
    publicada = _dias_hasta(fecha_publicacion, hoy)
    return publicada is not None and publicada >= -_HORIZONTE_RECURSO


def _precargar_recurso(lic_ids: Iterable[str], plazos: _PlazosRecurso) -> None:
    """Rellena ``plazos`` con el último día para recurrir de los que faltan, en un lote.

    Solo cuenta si hay indicios que lo motiven: recurrir un pliego sin nada que
    revisar no es una acción que el producto deba proponer. Si la lectura falla,
    esos expedientes se quedan sin aviso de recurso en esta pasada y el resto de
    recordatorios sigue saliendo.
    """
    faltan = sorted({lic for lic in lic_ids if lic not in plazos})
    if not faltan:
        return
    try:
        condiciones = condiciones_oficiales_de(faltan)
    except Exception as exc:
        log.warning("recurso_plazo_error", licitaciones=len(faltan), error=str(exc)[:200])
        condiciones = {}
    for lic in faltan:
        leidas = condiciones.get(lic)
        plazo = leidas.plazo_recurso if leidas and leidas.indicios else None
        plazos[lic] = date.fromisoformat(plazo.vence) if plazo else None


def _candidatos_recurso(
    lic_id: str,
    *,
    fecha_publicacion: object,
    organization_id: int,
    titulo: str,
    user_id: int,
    hoy: date,
    plazos: _PlazosRecurso,
) -> list[_Candidato]:
    """Los avisos ``recurso_<n>`` del expediente para esa persona.

    No depende del plazo de presentación: en servicios y suministros suele
    cerrar antes que el de recurso, y el pliego sigue siendo recurrible.
    ``plazos`` ya viene rellenado por :func:`_precargar_recurso`.
    """
    if not _en_horizonte_recurso(fecha_publicacion, hoy):
        return []
    vence = plazos.get(lic_id)
    if vence is None:
        return []
    dias = (vence - hoy).days
    return [
        _candidato(
            aviso=f"recurso_{window}",
            lic_id=lic_id,
            organization_id=organization_id,
            titulo=titulo[:80],
            aviso_titulo=f"Plazo para recurrir los pliegos en {dias} dia(s)",
            detalle=(
                f"La licitacion '{titulo[:80]}' tiene condiciones a revisar y el plazo "
                f"orientativo del recurso especial vence el {vence.isoformat()}."
            ),
            user_id=user_id,
        )
        for window in _RECURSO_WINDOWS
        if 0 <= dias <= window
    ]


def _favoritos_por_usuario(user_ids: list[int]) -> dict[int, dict[str, int]]:
    """``user_id -> {id_externo -> organization_id}`` de los favoritos, en una lectura.

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
    por_usuario: dict[int, dict[str, int]] = {}
    descartados: dict[int, int] = {}
    for user_id, lic, org in _repo_watchlist.favoritos_con_organizacion(user_ids):
        if org is None:
            descartados[user_id] = descartados.get(user_id, 0) + 1
        else:
            por_usuario.setdefault(user_id, {})[lic] = org
    for user_id, n in descartados.items():
        # Silenciarlo dejaría a un usuario sin recordatorios sin que nada lo
        # delate; el aviso nombra cuántos y a quién para poder correr el
        # backfill de tenencia.
        log.warning("watchlist_items_sin_organizacion", user_id=user_id, descartados=n)
    return por_usuario


def _deadline_type(days_left: int, field: str) -> str:
    """Genera el tipo de notificacion segun la ventana y el campo."""
    prefix = "renovacion" if field == "fecha_fin" else "deadline"
    return f"{prefix}_{days_left}"


def check_deadlines_and_notify(user_id: int, plazos: _PlazosRecurso | None = None) -> int:
    """Emite los recordatorios de plazo de los favoritos de un usuario.

    Es :func:`_notificar_favoritos` con un solo usuario. ``plazos`` comparte
    los plazos de recurso ya leídos en la misma pasada.

    Returns:
        Número de eventos nuevos escritos.
    """
    return _notificar_favoritos([user_id], {} if plazos is None else plazos)


def _notificar_favoritos(user_ids: list[int], plazos: _PlazosRecurso) -> int:
    """Emite los recordatorios de plazo de los favoritos de esos usuarios.

    Las lecturas son por lote, no por usuario: los favoritos de todos en una
    sentencia, sus licitaciones en otra, las condiciones de las recurribles en
    un lote (:func:`_precargar_recurso`) y la idempotencia en una por tipo de
    evento (:func:`_emitir`). Cada recordatorio lleva la ``organization_id`` del
    favorito: una alerta sin ella no aparece en ninguna campana. Un fallo al
    preparar los avisos de un usuario no tapa los del resto.

    Returns:
        Número de eventos nuevos escritos.
    """
    favoritos = _favoritos_por_usuario(user_ids)
    if not favoritos:
        return 0

    ids = sorted({lic for del_usuario in favoritos.values() for lic in del_usuario})
    lics = {str(lic.get("id_externo")): lic for lic in _repo_watchlist.plazos_de_licitaciones(ids)}
    now = datetime.now(UTC)
    _precargar_recurso(
        (
            lic_id
            for lic_id, lic in lics.items()
            if _en_horizonte_recurso(lic.get("fecha_publicacion"), now.date())
        ),
        plazos,
    )
    candidatos: list[_Candidato] = []
    for user_id, del_usuario in favoritos.items():
        try:
            candidatos += _candidatos_favoritos(user_id, del_usuario, lics, now, plazos)
        except Exception as exc:
            log.warning("deadline_check_error", user_id=user_id, error=str(exc))

    written = _emitir(candidatos)
    if written:
        log.info("deadline_notifications_written", usuarios=len(favoritos), count=written)
    return written


def _candidatos_favoritos(
    user_id: int,
    favoritos: dict[str, int],
    lics: dict[str, dict[str, Any]],
    now: datetime,
    plazos: _PlazosRecurso,
) -> list[_Candidato]:
    """Los recordatorios de plazo de los favoritos de un usuario."""
    candidatos: list[_Candidato] = []
    for lic_id, organization_id in favoritos.items():
        lic = lics.get(lic_id)
        if lic is None:
            continue
        titulo = str(lic.get("titulo") or lic_id)
        candidatos += _candidatos_recurso(
            lic_id,
            fecha_publicacion=lic.get("fecha_publicacion"),
            organization_id=organization_id,
            titulo=titulo,
            user_id=user_id,
            hoy=now.date(),
            plazos=plazos,
        )

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
    return candidatos


def _dias_hasta(raw: object, hoy: date) -> int | None:
    """Días naturales hasta una fecha ISO (o datetime ISO); ``None`` si no parsea."""
    try:
        return (date.fromisoformat(str(raw)[:10]) - hoy).days
    except (ValueError, TypeError):
        return None


def check_pursuit_deadlines(plazos: _PlazosRecurso | None = None) -> int:
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
    rows = PursuitRepository().deadline_rows(
        desde=hoy.isoformat(),
        hasta=horizonte.isoformat(),
        publicadas_desde=(hoy - timedelta(days=_HORIZONTE_RECURSO)).isoformat(),
    )
    plazos = {} if plazos is None else plazos
    _precargar_recurso(
        (
            str(row["licitacion_id"])
            for row in rows
            if _en_horizonte_recurso(row.get("fecha_publicacion"), hoy)
        ),
        plazos,
    )
    candidatos: list[_Candidato] = []
    for row in rows:
        email = row.get("responsible_email")
        responsable = row.get("responsible_user_id")
        if not email or responsable is None:
            continue
        lic_id = str(row["licitacion_id"])
        titulo = str(row.get("titulo") or lic_id)
        organization_id = int(row["organization_id"])
        candidatos += _candidatos_recurso(
            lic_id,
            fecha_publicacion=row.get("fecha_publicacion"),
            organization_id=organization_id,
            titulo=titulo,
            user_id=int(responsable),
            hoy=hoy,
            plazos=plazos,
        )

        # Las ventanas filtran el resto: lo publicado hace poco entra en la
        # consulta aunque su presentación quede más allá de 30 días.
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
    plazos: _PlazosRecurso = {}
    try:
        total += _notificar_favoritos(usuarios, plazos)
    except Exception as exc:
        log.warning("deadline_check_error", usuarios=len(usuarios), error=str(exc)[:200])
    try:
        total += check_pursuit_deadlines(plazos)
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
            # mismo razonamiento en `_favoritos_por_usuario`.
            sin_organizacion += 1
            continue
        vencimiento = str(fila.get("hasta") or "")[:10]
        candidatos.append(
            _candidato(
                aviso=f"radar_recordatorio_{vencimiento}",
                lic_id=str(fila["id_externo"]),
                organization_id=int(organization_id),
                titulo=str(fila["id_externo"]),
                aviso_titulo="Vuelve a tu Radar la licitación que aplazaste",
                detalle="Pediste que te la recordáramos hoy. Ya está otra vez en la bandeja.",
                user_id=int(fila["user_id"]),
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
