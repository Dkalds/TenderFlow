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

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from db.database import now_utc_iso
from db.events import (
    claim_channel,
    mark_dispatched,
    pending_events,
    release_channel,
)
from observability.logging import get_logger
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
        if not user_key:
            continue
        seguidores.append(
            Destinatario(
                user_key=user_key,
                organization_id=int(fila.get("organization_id") or organization_id or 0),
                email=str(fila["email"]) if fila.get("email") else None,
            )
        )
    return seguidores


# ── Canales ──────────────────────────────────────────────────────────────────


def _titulo_y_cuerpo(evento: dict[str, Any], spec: EspecificacionEvento) -> tuple[str, str]:
    """Texto de la notificación in-app: el título del catálogo y el detalle."""
    payload = evento.get("payload") or {}
    referencia = str(
        payload.get("titulo") or payload.get("licitacion_id") or payload.get("id_externo") or ""
    )
    titulo = f"{spec.titulo}: {referencia}".strip().rstrip(":")[:200]
    cambios = payload.get("valores")
    if isinstance(cambios, dict) and cambios:
        cuerpo = " · ".join(
            f"{campo}: {(valor or {}).get('antes', '—')} → {(valor or {}).get('despues', '—')}"
            for campo, valor in sorted(cambios.items())
            if isinstance(valor, dict)
        )
    else:
        cuerpo = str(payload.get("detalle") or referencia)
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
    return base


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
        if insert_user_notification(
            user_key=destinatario.user_key,
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
    """
    if not spec.preferencia_email:
        return 0, 0

    from services.email_digest import asunto_evento, render_evento
    from services.notifications import modo_email_de

    payload = evento.get("payload") or {}
    licitacion_id = str(payload.get("licitacion_id") or payload.get("id_externo") or "")
    encoladas = 0
    enviados = 0
    for destinatario in _destinatarios(evento):
        modo = modo_email_de(destinatario.user_key, spec.tipo)
        if modo == "off" or not destinatario.email:
            continue
        if modo == "daily":
            from services.watchlist import store_pending_digest

            # `entry_id` es el id del evento y no el del pursuit: dos eventos
            # sobre la misma oportunidad son dos avisos distintos, y el único
            # de `pending_digests` es (entry_id, licitacion_id).
            store_pending_digest(
                destinatario.user_key,
                destinatario.email,
                int(evento["id"]),
                licitacion_id,
                "daily",
                now_utc_iso(),
            )
            encoladas += 1
            continue
        titulo, cuerpo = _titulo_y_cuerpo(evento, spec)
        texto, html = render_evento(titulo=titulo, cuerpo=cuerpo, licitacion_id=licitacion_id)
        from observability.alerts import enviar_email_transaccional

        if enviar_email_transaccional(
            to_addr=destinatario.email,
            subject=asunto_evento(spec.titulo, licitacion_id),
            texto=texto,
            html=html,
        ):
            enviados += 1
    return encoladas, enviados


def _firmar(secret: str, cuerpo: bytes) -> str:
    return hmac.new(secret.encode(), cuerpo, hashlib.sha256).hexdigest()


def _canal_webhook(evento: dict[str, Any], spec: EspecificacionEvento) -> int:
    """Entrega el evento a los webhooks suscritos. Devuelve entregas con 2xx.

    La firma HMAC, la allowlist y el pinning de DNS son **los mismos** que ya
    usaban el ping manual y ``db/webhooks.py``: lo único nuevo es de dónde sale
    el cuerpo (la plantilla del formato del webhook) y qué filas se consultan
    (las de la organización del evento, más las globales sin dueño).
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
    if not suscriptores:
        return 0

    permitidos = frozenset(
        host.strip() for host in settings.WEBHOOK_ALLOWED_HOSTS.split(",") if host.strip()
    )
    entregados = 0
    for fila in suscriptores:
        suscripciones = frozenset(fila.get("event_types") or [])
        if not suscripcion_cubre(suscripciones, spec.tipo):
            continue
        webhook_id = int(fila["id"])
        url = str(fila["url"])
        cuerpo = json.dumps(
            renderizar(
                spec.tipo,
                dict(evento.get("payload") or {}),
                formato=str(fila.get("formato") or ""),
                timestamp=str(evento.get("created_at") or now_utc_iso()),
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
            "X-Webhook-Signature": f"sha256={_firmar(secret, cuerpo)}",
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


def dispatch_pending(limit: int = LOTE_POR_PASADA) -> ResultadoDespacho:
    """Reparte los eventos pendientes. Devuelve el desglose de la pasada."""
    resultado = ResultadoDespacho()
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
    """Entry point del scheduler. Devuelve cuántos eventos quedaron despachados."""
    resultado = dispatch_pending()
    if resultado.procesados or resultado.fallidos or resultado.ignorados:
        log.info(
            "event_dispatch_done",
            procesados=resultado.procesados,
            ignorados=resultado.ignorados,
            in_app=resultado.in_app,
            digest=resultado.digest,
            correos=resultado.correos,
            webhooks=resultado.webhooks,
            fallidos=resultado.fallidos,
        )
    return resultado.procesados
