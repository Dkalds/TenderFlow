"""Despachador del outbox: reparte ``domain_events`` a sus canales de salida.

Plan de arquitectura 2026-09 v2, S4.1. La mutación escribe **un** evento en su
propia transacción (``db.events.append_domain_event``) y este job lo abanica
después hacia los cuatro sitios donde el producto se entera de algo:

    domain_events ──┬─→ user_notifications   (la campana de la consola)
                    ├─→ pending_digests      (el correo agrupado)
                    ├─→ webhook_deliveries   (Slack, Teams, integraciones)
                    └─→ señal de caché       (invalidación entre procesos)

Por qué un despachador y no cuatro escrituras en el productor: hasta aquí cada
productor escribía directo en el almacén que le convenía, así que añadir un
canal obligaba a tocarlos todos, una entrega fallida no dejaba rastro de qué la
había originado, y no había forma de contestar «¿qué pasó con esta
oportunidad?» sin unir siete tablas.

**Idempotencia.** Antes de entregar por un canal, el despachador *reclama* el
par ``(event_id, canal)`` en ``domain_event_dispatches``, que tiene un único.
Si el proceso muere a mitad —o Render lo reinicia durante un despliegue— el
reintento vuelve a coger el evento entero y solo salen los canales que aún no
estaban reclamados. Un canal que falla libera su reclamo, así que el fallo se
reintenta en la pasada siguiente en vez de perderse: la idempotencia no se
paga con mensajes perdidos.

**Plano ``pipeline``** (ADR-012): corre dentro del cierre canónico, así que no
necesita workflow propio y funciona igual en Actions y en APScheduler. El
worker de S5 puede invocarlo a demanda con el mismo ``run()``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from db.database import now_utc, now_utc_iso
from db.events import (
    claim_channel,
    mark_dispatched,
    pending_events,
    release_channel,
)
from observability.logging import get_logger
from shared.crypto import cabeceras_de_firma, segundos_unix
from shared.events import CATALOGO, Canal, EspecificacionEvento, renderizar, suscripcion_cubre

log = get_logger(__name__)

#: Cuántos eventos procesa una pasada. La cola en régimen permanente son
#: decenas de filas; el techo protege del backfill (una re-ingesta grande puede
#: dejar miles de ``licitacion.cambiada`` de golpe) para que una pasada no se
#: coma la ventana del cierre entero.
LOTE_POR_PASADA = 200

_TIMEOUT_ENTREGA_S = 5.0


@dataclass(frozen=True)
class Destinatario:
    """Persona a la que va una salida personal del evento."""

    user_key: str
    organization_id: int
    user_id: int | None = None
    email: str | None = None


@dataclass
class ResultadoDespacho:
    """Qué hizo una pasada. Se loguea entero: es el diagnóstico del backbone."""

    procesados: int = 0
    ignorados: int = 0
    in_app: int = 0
    digest: int = 0
    correos: int = 0
    webhooks: int = 0
    fallidos: int = 0
    #: Pendientes más viejos que ``EVENT_DISPATCH_MAX_AGE_HOURS``: se dieron
    #: por despachados sin entregarse (ver :func:`caducar_viejos`).
    caducados: int = 0


# ── Resolución de destinatarios ──────────────────────────────────────────────


def _usuario_a_destinatario(user_id: int, organization_id: int) -> Destinatario | None:
    """Convierte un id de usuario en destinatario, o ``None`` si no sirve.

    Los eventos de ``pursuit.*`` viajan con ids de usuario porque es lo que
    tiene a mano quien los emite. La traducción a ``user_key`` (la clave opaca
    con la que se indexan las notificaciones) y al email de entrega se hace
    aquí, en un solo sitio, y no en cada productor.
    """
    from db.users import get_user_by_id
    from shared.identity import user_key_from_email

    usuario = get_user_by_id(int(user_id))
    if usuario is None:
        return None
    email = usuario.get("email")
    return Destinatario(
        user_key=user_key_from_email(email, int(user_id)),
        organization_id=organization_id,
        user_id=int(user_id),
        email=str(email) if email else None,
    )


def _destinatarios(evento: dict[str, Any]) -> list[Destinatario]:
    """A quién va la salida personal de este evento.

    Dos formas, según la familia, y las dos deliberadas:

    - ``pursuit.*`` trae ids de usuario (``responsible_user_id``,
      ``destinatarios``): quien emite el evento está dentro de una organización
      y conoce a las personas por su id.
    - El resto (``licitacion.cambiada``, ``adjudicacion.detectada``,
      ``renovacion.en_ventana``) trae ``seguidores``: pares
      ``(user_key, organization_id)`` que el productor ya resolvió en SQL,
      porque «quién sigue este expediente» es una consulta y no un dato del
      cambio.

    **Quien origina el evento nunca es destinatario**: asignarse a uno mismo o
    comentar en la propia oportunidad no genera aviso ni correo.
    """
    payload = evento.get("payload") or {}
    tipo = str(evento.get("event_type") or "")
    organization_id = int(evento.get("organization_id") or payload.get("organization_id") or 0)
    actor = payload.get("actor_user_id")
    actor_id = int(actor) if actor is not None else None

    if tipo.startswith("pursuit."):
        if not organization_id:
            log.warning("event_dispatch_sin_organizacion", event_id=evento.get("id"), tipo=tipo)
            return []
        ids: list[int] = []
        responsable = payload.get("responsible_user_id")
        if responsable is not None:
            ids.append(int(responsable))
        for candidato in payload.get("destinatarios") or []:
            try:
                ids.append(int(candidato))
            except (TypeError, ValueError):
                continue
        vistos: set[int] = set()
        destinatarios: list[Destinatario] = []
        for user_id in ids:
            if user_id in vistos or user_id == actor_id:
                continue
            vistos.add(user_id)
            resuelto = _usuario_a_destinatario(user_id, organization_id)
            if resuelto is not None:
                destinatarios.append(resuelto)
        return destinatarios

    seguidores: list[Destinatario] = []
    for fila in payload.get("seguidores") or []:
        if not isinstance(fila, dict):
            continue
        user_key = str(fila.get("user_key") or "")
        # ``user_id`` llega desde v129 (``services/contract_events``); los
        # eventos anteriores en cola no lo traen y la alerta sale sólo con clave.
        bruto = fila.get("user_id")
        if not user_key:
            # Los productores nuevos (F1.5, F3.4, F5.1, F5.2) mandan sólo el
            # ``user_id`` (ADR-030): la traducción a la clave de la bandeja
            # vive aquí, en el único sitio que ya la hacía para ``pursuit.*``.
            if bruto is None:
                continue
            org_fila = int(fila.get("organization_id") or organization_id or 0)
            if not org_fila:
                continue
            resuelto = _usuario_a_destinatario(int(bruto), org_fila)
            if resuelto is not None and resuelto.user_id != actor_id:
                seguidores.append(resuelto)
            continue
        seguidores.append(
            Destinatario(
                user_key=user_key,
                organization_id=int(fila.get("organization_id") or organization_id or 0),
                user_id=int(bruto) if bruto is not None else None,
                email=str(fila["email"]) if fila.get("email") else None,
            )
        )
    # La misma persona puede llegar dos veces —favorito y responsable de la
    # oportunidad sobre el mismo expediente—; un solo aviso y una sola línea
    # de digest por persona y organización.
    unicos: list[Destinatario] = []
    vistas: set[tuple[str, int]] = set()
    for destinatario in seguidores:
        clave = (destinatario.user_key, destinatario.organization_id)
        if clave in vistas:
            continue
        vistas.add(clave)
        unicos.append(destinatario)
    return unicos


# ── Canales ──────────────────────────────────────────────────────────────────


def _titulo_y_cuerpo(evento: dict[str, Any], spec: EspecificacionEvento) -> tuple[str, str]:
    """Texto de la notificación in-app: el título del catálogo y el detalle."""
    payload = evento.get("payload") or {}
    referencia = str(
        payload.get("titulo") or payload.get("licitacion_id") or payload.get("id_externo") or ""
    )
    # F5.3: el aviso con nombre («Plazo ampliado al 12/10») sustituye al
    # título genérico de la familia. Los eventos anteriores a F5.3 que sigan en
    # cola no lo traen y salen con el título del catálogo, como siempre.
    encabezado = str(payload.get("aviso_titulo") or spec.titulo)
    titulo = f"{encabezado}: {referencia}".strip().rstrip(":")[:200]
    partes: list[str] = []
    if payload.get("aviso_detalle"):
        partes.append(str(payload["aviso_detalle"]))
    cambios = payload.get("valores")
    if isinstance(cambios, dict) and cambios:
        partes.append(
            " · ".join(
                f"{campo}: {(valor or {}).get('antes', '—')} → {(valor or {}).get('despues', '—')}"
                for campo, valor in sorted(cambios.items())
                if isinstance(valor, dict)
            )
        )
    elif payload.get("detalle"):
        partes.append(str(payload["detalle"]))
    cuerpo = " — ".join(p for p in partes if p) or referencia
    return titulo, cuerpo[:1000]


def _tipo_notificacion(evento: dict[str, Any], spec: EspecificacionEvento) -> str:
    """Valor de ``user_notifications.type`` para este evento concreto.

    El único de ``user_notifications`` es ``(user_key, licitacion_id, type)``,
    así que un ``type`` fijo por familia haría que el **segundo** cambio del
    mismo expediente no llegara nunca: la fila ya existiría. Añadir el id del
    evento hace que cada cambio real sea una alerta distinta y que reintentar
    el mismo evento siga siendo un no-op, que es justo la idempotencia que se
    quiere.
    """
    base = spec.tipo_notificacion or spec.tipo
    if spec.tipo == "licitacion.cambiada":
        # El discriminante es la fila de historial y no el id del evento: un
        # backfill que vuelva a derivar el historial escribe eventos nuevos
        # para cambios viejos, y con el id del evento cada backfill repetiría
        # todas las alertas de la bandeja.
        payload = evento.get("payload") or {}
        return f"{base}:{payload.get('history_id') or evento.get('id')}"
    if spec.tipo == "pursuit.task_due":
        # Una tarea que se re-fecha vuelve a vencer otro día y eso es otro
        # aviso; con el tipo fijo, el segundo vencimiento chocaría con el único
        # de la oportunidad y no llegaría.
        payload = evento.get("payload") or {}
        return f"{base}:{payload.get('task_id')}:{payload.get('vence')}"
    if spec.tipo == "pursuit.mentioned":
        # Una mención por comentario: dos comentarios que te mencionan en la
        # misma oportunidad son dos avisos.
        payload = evento.get("payload") or {}
        return f"{base}:{payload.get('comment_id')}"
    # F1.5, F3.4, F5.1, F5.2: el discriminante es el hecho, no el evento, por
    # la misma razón que en `licitacion.cambiada` — un segundo documento o un
    # segundo competidor sobre el mismo expediente es otro aviso, y el mismo
    # hecho reemitido no debe duplicar la bandeja.
    payload = evento.get("payload") or {}
    if spec.tipo == "licitacion.documento_nuevo":
        return f"{base}:{payload.get('documento_id')}"
    if spec.tipo == "licitacion.recurso":
        return f"{base}:{payload.get('resolucion_id')}"
    if spec.tipo == "competidor.adjudicacion_en_mi_segmento":
        return f"{base}:{payload.get('empresa_id')}"
    if spec.tipo == "cuenta.vencimiento_proximo":
        return f"{base}:{payload.get('fecha_fin')}"
    if spec.tipo == "pursuit.cartera_vence":
        # F4.3: el mismo contrato avisa a seis, tres y un mes. Con el tipo
        # fijo, el segundo aviso chocaría con el único del expediente.
        return (
            f"{base}:{payload.get('cartera_id')}:{payload.get('meses')}:{payload.get('fecha_fin')}"
        )
    return base


def _frecuencia_en_ajustes(
    destinatario: Destinatario, spec: EspecificacionEvento, canal: str
) -> str | None:
    """Frecuencia del canal en Ajustes (``notification_preferences``), o ``None``.

    Solo para los eventos cuyo interruptor vive en Ajustes (``clave_ajustes``)
    y destinatarios con ``user_id``: esa tabla se indexa por id. ``None``
    significa «este evento no se gobierna desde Ajustes» y deja la decisión al
    camino de siempre.

    Fail-safe hacia el defecto del canal y no hacia ``off``, por lo mismo que
    ``services.notifications.modo_email_de``: silenciar por un fallo de lectura
    es el modo de fallo que nadie detecta.

    Es la lectura de los canales **personales** (``in_app``, ``email``). El
    canal ``webhook`` no puede usarla porque su defecto es ``off`` y el
    destino es de la organización: usa :func:`_frecuencia_explicita_en_ajustes`.
    """
    if spec.clave_ajustes is None or destinatario.user_id is None:
        return None
    from db.repositories import notification_preferences as prefs

    try:
        return prefs.resolver(
            destinatario.user_id,
            tipo=spec.clave_ajustes,
            canal=canal,
            organization_id=destinatario.organization_id or None,
        )
    except Exception:
        log.warning("event_dispatch_prefs_ilegibles", tipo=spec.tipo, canal=canal, exc_info=True)
        return prefs.frecuencia_por_defecto(canal)


def _frecuencia_explicita_en_ajustes(
    destinatario: Destinatario, spec: EspecificacionEvento, canal: str
) -> str | None:
    """Frecuencia que el destinatario **fijó** en Ajustes, o ``None`` si no dijo nada.

    Mismas condiciones que :func:`_frecuencia_en_ajustes` (evento con
    ``clave_ajustes`` y destinatario con ``user_id``), pero sin rellenar con el
    defecto del canal: ``None`` es «sin opinión» y el llamador decide qué hacer
    con ello.

    El fail-safe también es «sin opinión»: un fallo de lectura no puede
    convertirse en un ``off`` que silencie el webhook de toda la organización.
    """
    if spec.clave_ajustes is None or destinatario.user_id is None:
        return None
    from db.repositories import notification_preferences as prefs

    try:
        return prefs.resolver_explicita(
            destinatario.user_id,
            tipo=spec.clave_ajustes,
            canal=canal,
            organization_id=destinatario.organization_id or None,
        )
    except Exception:
        log.warning("event_dispatch_prefs_ilegibles", tipo=spec.tipo, canal=canal, exc_info=True)
        return None


def _webhook_apagado_por_todos(evento: dict[str, Any], spec: EspecificacionEvento) -> bool:
    """¿Todos los destinatarios apagaron el canal ``webhook`` de este aviso en Ajustes?

    Es la regla con la que la preferencia personal gobierna una suscripción de
    organización (ver :func:`_canal_webhook`). Devuelve ``False`` —el webhook
    sale— cuando el evento no se gobierna desde Ajustes, cuando no tiene
    destinatarios a quienes preguntar, o cuando al menos uno no lo apagó
    explícitamente (fila ``immediate``/``daily`` o ninguna fila).
    """
    if spec.clave_ajustes is None:
        return False
    destinatarios = _destinatarios(evento)
    if not destinatarios:
        return False
    return all(
        _frecuencia_explicita_en_ajustes(destinatario, spec, "webhook") == "off"
        for destinatario in destinatarios
    )


def _canal_in_app(evento: dict[str, Any], spec: EspecificacionEvento) -> int:
    from db.notifications import insert_user_notification

    payload = evento.get("payload") or {}
    licitacion_id = payload.get("licitacion_id") or payload.get("id_externo")
    titulo, cuerpo = _titulo_y_cuerpo(evento, spec)
    tipo = _tipo_notificacion(evento, spec)
    escritas = 0
    for destinatario in _destinatarios(evento):
        if not destinatario.organization_id:
            continue
        if _frecuencia_en_ajustes(destinatario, spec, "in_app") == "off":
            continue
        if insert_user_notification(
            user_key=destinatario.user_key,
            user_id=destinatario.user_id,
            type_=tipo,
            title=titulo,
            body=cuerpo,
            licitacion_id=str(licitacion_id) if licitacion_id else None,
            organization_id=destinatario.organization_id,
        ):
            escritas += 1
    return escritas


def _canal_digest(evento: dict[str, Any], spec: EspecificacionEvento) -> tuple[int, int]:
    """Correo del evento según la preferencia de cada destinatario (S4.6).

    Devuelve ``(filas_encoladas, correos_enviados)``.

    - ``immediate`` sale en esta misma pasada.
    - ``daily`` se encola en ``pending_digests`` y lo agrupa el digest diario.
    - ``off`` no escribe nada: es la única forma de que «desactivado» signifique
      lo que dice, porque una fila encolada acaba entregándose.

    Los eventos con ``clave_ajustes`` (C6.1, C6.2) leen el modo del canal
    ``email`` de Ajustes; el resto, de ``user_event_prefs`` (S4.6).
    """
    if not spec.preferencia_email and spec.clave_ajustes is None:
        return 0, 0

    from services.email_digest import asunto_evento, render_evento
    from services.notifications import modo_email_de

    payload = evento.get("payload") or {}
    licitacion_id = str(payload.get("licitacion_id") or payload.get("id_externo") or "")
    encoladas = 0
    enviados = 0
    for posicion, destinatario in enumerate(_destinatarios(evento)):
        modo = _frecuencia_en_ajustes(destinatario, spec, "email") or modo_email_de(
            destinatario.user_key, spec.tipo, user_id=destinatario.user_id
        )
        if modo == "off":
            continue
        email = destinatario.email or _email_de(destinatario)
        if not email:
            continue
        if modo == "daily":
            from services.watchlist import store_pending_digest

            entry_id = entry_id_de_digest(int(evento["id"]), posicion)
            if entry_id is None:
                continue
            store_pending_digest(
                destinatario.user_key,
                email,
                entry_id,
                licitacion_id,
                "daily",
                now_utc_iso(),
                user_id=destinatario.user_id,
            )
            encoladas += 1
            continue
        titulo, cuerpo = _titulo_y_cuerpo(evento, spec)
        texto, html = render_evento(titulo=titulo, cuerpo=cuerpo, licitacion_id=licitacion_id)
        from observability.alerts import enviar_email_transaccional

        if enviar_email_transaccional(
            to_addr=email,
            subject=asunto_evento(str(payload.get("aviso_titulo") or spec.titulo), licitacion_id),
            texto=texto,
            html=html,
        ):
            enviados += 1
    return encoladas, enviados


#: Huecos por evento en el ``entry_id`` negativo de ``pending_digests``.
DIGEST_HUECOS_POR_EVENTO = 100


def entry_id_de_digest(event_id: int, posicion: int) -> int | None:
    """``entry_id`` con el que un evento se encola en ``pending_digests``.

    Negativo, y codifica el evento y la posición del destinatario:
    ``-(event_id * 100 + posicion)``. Dos restricciones de la tabla obligan a
    esta forma, y las dos se resolverían con una columna que hoy no existe:

    - ``entry_id`` apuntaba a una regla (``watchlist_rules``) o a una entrada
      legada (``watchlist_cpv``) sin discriminador. Con el id del evento en
      positivo, un evento cuyo id coincidiera con el de una regla del mismo
      usuario salía en el digest con los criterios de esa regla. El signo
      negativo es el discriminador: ninguna secuencia de esas tablas es
      negativa, y ``load_pending_digests`` sólo cruza con ``domain_events`` las
      filas con ``entry_id < 0``.
    - El único es ``(entry_id, licitacion_id)``, sin destinatario. Con un
      ``entry_id`` por evento, el segundo seguidor del mismo expediente chocaba
      con el primero y su fila se descartaba en silencio (``DO NOTHING``).

    La posición es la del destinatario en :func:`_destinatarios`, que es
    determinista: reintentar el mismo evento reproduce los mismos ``entry_id``
    y el ``ON CONFLICT`` lo hace idempotente.

    Devuelve ``None`` cuando no hay hueco —más de 99 destinatarios para un
    evento, o un ``event_id`` por encima de ~21 millones, donde el producto ya
    no cabe en el ``integer`` de la columna—: ese destinatario se queda sin la
    línea del digest (la campana sí le llega) y el log lo dice. Una columna
    propia para el evento en ``pending_digests`` retiraría este límite; hasta
    entonces, la cola lleva miles de eventos, no millones.
    """
    maximo_int4 = 2**31 - 1
    codificado = event_id * DIGEST_HUECOS_POR_EVENTO + posicion
    if posicion >= DIGEST_HUECOS_POR_EVENTO or codificado > maximo_int4:
        log.warning("event_dispatch_digest_sin_hueco", event_id=event_id, posicion=posicion)
        return None
    return -codificado


def event_id_de_entry(entry_id: int) -> int | None:
    """Inversa de :func:`entry_id_de_digest`: el evento de una fila del digest.

    ``None`` para las filas de reglas (``entry_id`` positivo).
    """
    if entry_id >= 0:
        return None
    return (-entry_id) // DIGEST_HUECOS_POR_EVENTO


def _email_de(destinatario: Destinatario) -> str | None:
    """Correo del destinatario cuando el productor no lo trajo en el payload.

    Los seguidores de un expediente viajan con clave e id, no con correo: el
    correo es dato personal y el evento se guarda para siempre en una tabla
    append-only. Se resuelve aquí, en el momento de entregar, y sólo para el
    canal que lo necesita.
    """
    if destinatario.user_id is None:
        return None
    from db.users import get_user_by_id

    usuario = get_user_by_id(int(destinatario.user_id))
    email = (usuario or {}).get("email")
    return str(email) if email else None


def _sello_unix(marca: str) -> int:
    """Segundos Unix del ``created_at`` del evento, que es lo que lleva el cuerpo.

    Sellar la cabecera con el mismo instante que el cuerpo es lo que hace que
    ``X-Webhook-Timestamp`` describa el evento y no la pasada del despachador.
    Si la marca no parsea (no debería: la escribe ``append_domain_event``) se
    sella con «ahora» antes que no entregar.
    """
    try:
        return segundos_unix(marca)
    except ValueError:
        return segundos_unix(now_utc())


def _canal_webhook(evento: dict[str, Any], spec: EspecificacionEvento) -> int:
    """Entrega el evento a los webhooks suscritos. Devuelve entregas con 2xx.

    Las firmas HMAC (``shared.crypto.cabeceras_de_firma``), la allowlist y el
    pinning de DNS son **los mismos** que ya usaban el ping manual y
    ``db/webhooks.py``: lo único nuevo es de dónde sale el cuerpo (la plantilla
    del formato del webhook) y qué filas se consultan (las de la organización
    del evento, más las globales sin dueño).

    **Preferencia personal sobre una suscripción de organización (R7.2).** El
    webhook es de la organización (``webhooks`` no tiene ``user_id``) y la
    preferencia de Ajustes es de cada persona, así que el canal no puede
    filtrar destinatario a destinatario como ``in_app`` o ``email``: el aviso
    sale entero o no sale. La regla es la del opt-out unánime: para los
    eventos con ``clave_ajustes``, el webhook **no** recibe el aviso solo si
    **todos** sus destinatarios lo apagaron explícitamente para el canal
    ``webhook``; basta uno que lo tenga en ``immediate``/``daily`` o que no
    haya dicho nada para que salga. Los eventos sin ``clave_ajustes`` no
    cambian.

    Por qué «sin fila» cuenta como «que salga» y no como el defecto ``off`` del
    canal: aplicar el defecto habría cortado de golpe los ``pursuit.*`` de
    todos los webhooks ya dados de alta (Slack, Teams) hasta que cada
    destinatario entrara en Ajustes a encenderlo, y ninguno de ellos habría
    pedido silencio. Lo que la persona no dijo lo decide la suscripción de la
    organización, que sí lo pidió. ``daily`` equivale a ``immediate``: un
    webhook no tiene digest.

    Un aviso bloqueado no deja fila en ``webhook_deliveries``: no hubo intento
    de entrega que registrar. Documentado en ``docs/integraciones/webhooks.md``.
    """
    import requests

    from config.settings import settings
    from db.repositories.webhooks import WebhookRepository, resolve_stored_secret
    from shared.outbound_http import pinned_https_request
    from shared.ssrf import validate_outbound_url

    repo = WebhookRepository()
    organization_id = evento.get("organization_id")
    suscriptores = repo.list_active_subscribers(
        organization_id=int(organization_id) if organization_id is not None else None
    )
    candidatos = [
        fila
        for fila in suscriptores
        if suscripcion_cubre(frozenset(fila.get("event_types") or []), spec.tipo)
    ]
    if not candidatos:
        return 0
    # Las preferencias se leen solo cuando hay a quién entregar: la mayoría de
    # las organizaciones no tiene webhooks y no hay por qué pagar la consulta.
    if _webhook_apagado_por_todos(evento, spec):
        log.info(
            "event_dispatch_webhook_apagado_en_ajustes",
            tipo=spec.tipo,
            organization_id=organization_id,
            webhooks=len(candidatos),
        )
        return 0

    permitidos = frozenset(
        host.strip() for host in settings.WEBHOOK_ALLOWED_HOSTS.split(",") if host.strip()
    )
    entregados = 0
    for fila in candidatos:
        webhook_id = int(fila["id"])
        url = str(fila["url"])
        marca = str(evento.get("created_at") or now_utc_iso())
        cuerpo = json.dumps(
            renderizar(
                spec.tipo,
                dict(evento.get("payload") or {}),
                formato=str(fila.get("formato") or ""),
                timestamp=marca,
            ),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            if settings.ENV in ("prod", "staging") and not permitidos:
                raise ValueError("WEBHOOK_ALLOWED_HOSTS no está configurado")
            validate_outbound_url(url, allowed_hosts=permitidos or None)
        except ValueError as exc:
            log.warning("event_dispatch_webhook_ssrf", webhook_id=webhook_id, error=str(exc))
            repo.record_delivery(
                webhook_id,
                status_code=0,
                success=False,
                event_type=spec.tipo,
                payload_size=len(cuerpo),
            )
            continue

        secret = resolve_stored_secret(webhook_id, str(fila["secret"]))
        cabeceras = {
            "Content-Type": "application/json",
            **cabeceras_de_firma(secret=secret, body=cuerpo, timestamp=_sello_unix(marca)),
            "X-Webhook-Event": spec.tipo,
            "User-Agent": "licitaciones-sap-webhook/1.0",
        }
        try:
            with pinned_https_request(
                "POST",
                url,
                headers=cabeceras,
                body=cuerpo,
                timeout_seconds=_TIMEOUT_ENTREGA_S,
                allowed_hosts=permitidos or None,
            ) as respuesta:
                ok = 200 <= respuesta.status_code < 300
                repo.record_delivery(
                    webhook_id,
                    status_code=respuesta.status_code,
                    success=ok,
                    event_type=spec.tipo,
                    payload_size=len(cuerpo),
                )
                entregados += int(ok)
        except (requests.RequestException, ValueError) as exc:
            log.warning("event_dispatch_webhook_failed", webhook_id=webhook_id, error=str(exc))
            repo.record_delivery(
                webhook_id,
                status_code=0,
                success=False,
                event_type=spec.tipo,
                payload_size=len(cuerpo),
            )
    return entregados


def _canal_cache() -> None:
    """Invalida la caché compartida entre el scraper y la API.

    No mira el evento: la señal es global (un timestamp que todos los procesos
    comparan), así que el «qué» cambió no la afina. Es el mismo mecanismo que
    ya usaba el scraper, no uno nuevo.
    """
    from shared.cache_signal import signal_cache_invalidation

    signal_cache_invalidation()


# ── Pasada ───────────────────────────────────────────────────────────────────


def _despachar_canal(
    canal: Canal, evento: dict[str, Any], spec: EspecificacionEvento, resultado: ResultadoDespacho
) -> None:
    if canal == "in_app":
        resultado.in_app += _canal_in_app(evento, spec)
    elif canal == "digest":
        encoladas, enviados = _canal_digest(evento, spec)
        resultado.digest += encoladas
        resultado.correos += enviados
    elif canal == "webhook":
        resultado.webhooks += _canal_webhook(evento, spec)
    elif canal == "cache":
        _canal_cache()


def caducar_viejos(max_age_hours: int | None = None) -> int:
    """Da por despachados, sin entregarlos, los pendientes más viejos que el tope.

    **Decisión sobre la cola acumulada** (2026-09-19, S4.1): el despachador
    estuvo escrito y sin cablear, así que al enchufarlo la cola trae semanas de
    eventos. No se entregan: un «te han asignado» de hace diez días, o un
    webhook que anuncia un cambio de plazo ya vencido, es ruido que enseña a
    ignorar el canal. Lo que supera ``EVENT_DISPATCH_MAX_AGE_HOURS`` (48 h por
    defecto) sale de la cola marcado como despachado, con el conteo por tipo en
    el log (``event_dispatch_caducados``) y en ``ops_events``
    (``domain_events_caducados``), que es la métrica que sobrevive a los
    runners efímeros de Actions.

    La misma regla vale después del arranque: un evento que se queda atascado
    —un canal que falla pasada tras pasada, o el despachador apagado con
    ``EVENT_DISPATCH_ENABLED=0`` más de dos días— caduca igual en vez de salir
    tarde. El evento no se borra: sigue en ``domain_events`` para la
    cronología y la auditoría, sólo deja de estar pendiente.
    """
    from datetime import timedelta

    from config.settings import event_dispatch_max_age_hours
    from db.events import caducar_pendientes

    horas = max_age_hours if max_age_hours is not None else event_dispatch_max_age_hours()
    limite = (now_utc() - timedelta(hours=max(1, int(horas)))).isoformat()
    conteo = caducar_pendientes(limite)
    total = sum(conteo.values())
    if total:
        log.warning("event_dispatch_caducados", total=total, horas=horas, por_tipo=conteo)
        try:
            from observability.ops_events import record_event

            record_event(
                "domain_events_caducados",
                value=float(total),
                detail=json.dumps(conteo, ensure_ascii=False, sort_keys=True)[:500],
            )
        except Exception:  # pragma: no cover - la métrica nunca tumba el reparto
            log.debug("event_dispatch_caducados_sin_ops_event", exc_info=True)
    return total


def dispatch_pending(
    limit: int = LOTE_POR_PASADA, *, max_age_hours: int | None = None
) -> ResultadoDespacho:
    """Reparte los eventos pendientes. Devuelve el desglose de la pasada.

    Antes de repartir caduca lo que supera la antigüedad máxima
    (:func:`caducar_viejos`): así el lote de la pasada nunca se gasta en
    eventos que no se van a entregar.
    """
    resultado = ResultadoDespacho()
    resultado.caducados = caducar_viejos(max_age_hours)
    for evento in pending_events(limit):
        event_id = int(evento["id"])
        spec = CATALOGO.get(str(evento.get("event_type") or ""))
        if spec is None:
            # Eventos de log (``cache.invalidated``, la señal de tecnología, lo
            # que escriban los tests): no tienen canal, así que se marcan y
            # salen de la cola. Sin esto, `domain_events_pending` crecería para
            # siempre por filas que nadie va a repartir nunca.
            mark_dispatched(event_id)
            resultado.ignorados += 1
            continue

        fallo = False
        for canal in spec.canales:
            if not claim_channel(event_id, canal):
                continue
            try:
                _despachar_canal(canal, evento, spec, resultado)
            except Exception:
                # El reclamo se libera para que la pasada siguiente reintente
                # SOLO este canal: los que ya salieron siguen reclamados.
                release_channel(event_id, canal)
                fallo = True
                log.warning(
                    "event_dispatch_canal_failed",
                    event_id=event_id,
                    canal=canal,
                    tipo=spec.tipo,
                    exc_info=True,
                )
        if fallo:
            resultado.fallidos += 1
            continue
        mark_dispatched(event_id)
        resultado.procesados += 1
    return resultado


def run() -> int:
    """Entry point del scheduler. Devuelve cuántos eventos quedaron despachados.

    Antes de vaciar la cola, escribe los ``pursuit.task_due`` del día (C6.1):
    el vencimiento no es una mutación que alguien haga, así que no tiene un
    productor en el camino de escritura y su sitio natural es la pasada que ya
    corre periódicamente. Es idempotente por ``(tarea, fecha)``, así que da
    igual cuántas pasadas haya en un día. Un fallo aquí no puede impedir el
    despacho del resto de la cola.
    """
    from config.settings import event_dispatch_enabled

    if not event_dispatch_enabled():
        # Los eventos se siguen escribiendo; esperan en la cola y, al volver a
        # encenderlo, lo que supere la antigüedad máxima caduca sin salir.
        log.info("event_dispatch_desactivado")
        return 0

    from services.avisos_outbox import emitir_avisos
    from services.pursuit_tasks import emitir_tareas_que_vencen

    try:
        emitidos = emitir_tareas_que_vencen()
        if emitidos:
            log.info("event_dispatch_tareas_que_vencen", emitidos=emitidos)
    except Exception:
        log.warning("event_dispatch_tareas_que_vencen_failed", exc_info=True)
    # F1.5, F5.1 y F5.2: tampoco son mutaciones de nadie —un documento nuevo
    # lo trae la ingesta, un contrato entra solo en su ventana de vencimiento—
    # así que se derivan aquí, con cursor, igual que las tareas que vencen.
    # `emitir_avisos` aísla cada productor: uno roto no para a los demás.
    emitir_avisos()
    resultado = dispatch_pending()
    if resultado.procesados or resultado.fallidos or resultado.ignorados or resultado.caducados:
        log.info(
            "event_dispatch_done",
            procesados=resultado.procesados,
            ignorados=resultado.ignorados,
            caducados=resultado.caducados,
            in_app=resultado.in_app,
            digest=resultado.digest,
            correos=resultado.correos,
            webhooks=resultado.webhooks,
            fallidos=resultado.fallidos,
        )
    return resultado.procesados
