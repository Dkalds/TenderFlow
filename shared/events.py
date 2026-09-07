"""Catálogo de eventos de dominio y plantillas de salida (plan 2026-09 v2, S4).

Hasta aquí el sistema tenía **siete** almacenes con forma de evento
(``pursuit_events``, ``contrato_eventos``, ``licitaciones_history``,
``user_notifications``, ``pending_digests``, ``webhook_deliveries`` y
``domain_events``) y ninguno era el backbone: cada productor escribía a mano en
el almacén que le venía bien, así que «¿qué pasó con esta oportunidad?» no
tenía una sola respuesta y añadir un canal de salida obligaba a tocar todos los
productores.

Este módulo es la **mitad declarativa** del outbox: qué eventos existen, qué
lleva cada uno, por qué canales sale y cómo se serializa a cada formato de
webhook. No toca la base de datos a propósito —eso vive en ``db/events.py``
(ADR-022)— y por eso lo pueden importar tanto la API como el scheduler sin
arrastrar persistencia.

Dos reglas que conviene no perder de vista:

- **El catálogo es cerrado.** ``validar_tipo`` rechaza cualquier tipo que no
  esté aquí: un evento con el nombre mal escrito no se pierde en silencio en
  una tabla append-only, falla en el sitio donde se escribe.
- **Las plantillas son puras.** ``renderizar`` recibe el evento ya cargado y
  devuelve el cuerpo; así se prueban contra el esquema de Adaptive Cards y la
  forma de Block Kit sin red ni base de datos (D13: plantillas sobre el webhook
  genérico, no integraciones OAuth por plataforma).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# ── Vocabulario ──────────────────────────────────────────────────────────────

#: Canales a los que el despachador abanica un evento.
#:
#: ``in_app``  → ``user_notifications`` (la campana de la consola).
#: ``digest``  → ``pending_digests`` (el correo agrupado).
#: ``webhook`` → ``webhook_deliveries`` (las integraciones de la organización).
#: ``cache``   → la señal de invalidación compartida entre procesos.
Canal = Literal["in_app", "digest", "webhook", "cache"]

CANALES: tuple[Canal, ...] = ("in_app", "digest", "webhook", "cache")

#: Formato del cuerpo que recibe un webhook. D13 del plan: se resuelve con
#: plantillas sobre el webhook genérico que ya existía, no con una integración
#: OAuth por plataforma (que habría añadido dos proveedores de identidad para
#: entregar el mismo JSON).
Formato = Literal["json", "slack_blocks", "teams_adaptive_card"]

FORMATOS: tuple[Formato, ...] = ("json", "slack_blocks", "teams_adaptive_card")

FORMATO_POR_DEFECTO: Formato = "json"

#: Familias del catálogo. Un webhook puede suscribirse a la familia entera con
#: el comodín ``pursuit.*`` en vez de enumerar sus tipos uno a uno.
FAMILIAS: tuple[str, ...] = (
    "pursuit",
    "licitacion",
    "adjudicacion",
    "renovacion",
    "ficha",
    "watchlist_rule",
    "solicitud_acceso",
)


class TipoDeEventoDesconocido(ValueError):
    """El tipo de evento no está en el catálogo."""


class PayloadIncompleto(ValueError):
    """El payload no trae los campos que el catálogo declara obligatorios."""


@dataclass(frozen=True)
class EspecificacionEvento:
    """Qué es un evento, qué lleva y por dónde sale.

    Attributes:
        tipo: Nombre canónico, ``familia.hecho``.
        titulo: Etiqueta legible; encabeza la notificación y la tarjeta.
        campos: Claves que el payload **debe** traer. No es validación de
            tipos: es el contrato mínimo para que los consumidores (plantilla,
            notificación in-app, digest) no tengan que adivinar.
        canales: Salidas a las que el despachador abanica este evento.
        tipo_notificacion: Valor de ``user_notifications.type`` cuando el
            evento sale por ``in_app``; ``None`` si no sale por ahí.
        preferencia_email: El usuario decide por preferencia
            (``immediate``/``daily``/``off``) si este evento le llega por
            correo. Solo lo tienen los eventos personales (S4.6).
    """

    tipo: str
    titulo: str
    campos: tuple[str, ...]
    canales: tuple[Canal, ...]
    tipo_notificacion: str | None = None
    preferencia_email: bool = False

    @property
    def familia(self) -> str:
        return self.tipo.split(".", 1)[0]


def _spec(
    tipo: str,
    titulo: str,
    campos: tuple[str, ...],
    canales: tuple[Canal, ...],
    *,
    tipo_notificacion: str | None = None,
    preferencia_email: bool = False,
) -> tuple[str, EspecificacionEvento]:
    return tipo, EspecificacionEvento(
        tipo=tipo,
        titulo=titulo,
        campos=campos,
        canales=canales,
        tipo_notificacion=tipo_notificacion,
        preferencia_email=preferencia_email,
    )


#: El catálogo. Añadir un tipo aquí es lo único que hace falta para que el
#: despachador lo reparta y para que un webhook pueda suscribirse a él.
CATALOGO: dict[str, EspecificacionEvento] = dict(
    (
        _spec(
            "pursuit.created",
            "Nueva oportunidad",
            ("pursuit_id", "licitacion_id", "organization_id"),
            ("webhook", "cache"),
        ),
        _spec(
            "pursuit.state_changed",
            "Cambio de estado de una oportunidad",
            ("pursuit_id", "licitacion_id", "estado_anterior", "estado_nuevo"),
            ("webhook", "cache"),
        ),
        _spec(
            "pursuit.decided",
            "Decisión sobre una oportunidad",
            ("pursuit_id", "licitacion_id", "decision"),
            ("webhook", "cache"),
        ),
        _spec(
            "pursuit.assigned",
            "Te han asignado una oportunidad",
            ("pursuit_id", "licitacion_id", "responsible_user_id", "actor_user_id"),
            ("in_app", "digest", "webhook"),
            tipo_notificacion="pursuit_asignada",
            preferencia_email=True,
        ),
        _spec(
            "pursuit.commented",
            "Comentario en una oportunidad",
            ("pursuit_id", "licitacion_id", "actor_user_id", "destinatarios"),
            ("in_app", "digest", "webhook"),
            tipo_notificacion="pursuit_comentada",
            preferencia_email=True,
        ),
        _spec(
            "licitacion.cambiada",
            "Cambio en un expediente que sigues",
            ("id_externo", "changed_fields"),
            ("in_app", "webhook"),
            tipo_notificacion="licitacion_cambiada",
        ),
        _spec(
            "adjudicacion.detectada",
            "Adjudicación detectada",
            ("id_externo",),
            ("in_app", "webhook"),
            tipo_notificacion="adjudicacion_detectada",
        ),
        _spec(
            "renovacion.en_ventana",
            "Renovación en ventana",
            ("id_externo", "fecha_fin"),
            ("in_app", "webhook"),
            tipo_notificacion="renovacion_en_ventana",
        ),
        _spec(
            "ficha.extraida",
            "Ficha del pliego extraída",
            ("id_externo",),
            ("webhook", "cache"),
        ),
        _spec(
            "watchlist_rule.matched",
            "Coincidencias de una regla de seguimiento",
            ("rule_id", "user_key", "total_matches"),
            ("webhook",),
        ),
        # Ya existía como suscripción de webhook antes de S4 (la emite
        # `api/routes/publico_solicitudes.py`). Entra al catálogo para que el
        # vocabulario sea uno solo y no dos listas que se contradicen.
        _spec(
            "solicitud_acceso.creada",
            "Nueva solicitud de acceso",
            ("email",),
            ("webhook",),
        ),
    )
)

TIPOS: frozenset[str] = frozenset(CATALOGO)


def validar_tipo(tipo: str) -> str:
    """Devuelve ``tipo`` si está en el catálogo; si no, lanza.

    Es el punto donde un evento mal escrito deja de ser una fila huérfana en
    una tabla append-only y pasa a ser un error en el sitio que lo escribe.
    """
    if tipo not in CATALOGO:
        raise TipoDeEventoDesconocido(
            f"Tipo de evento fuera del catálogo: {tipo!r}. Permitidos: {', '.join(sorted(TIPOS))}"
        )
    return tipo


def especificacion(tipo: str) -> EspecificacionEvento:
    """Especificación de un tipo del catálogo."""
    validar_tipo(tipo)
    return CATALOGO[tipo]


def validar_payload(tipo: str, payload: dict[str, Any]) -> None:
    """Comprueba que el payload trae los campos obligatorios del tipo."""
    faltan = [campo for campo in especificacion(tipo).campos if campo not in payload]
    if faltan:
        raise PayloadIncompleto(f"El evento {tipo!r} exige {faltan} en su payload.")


def tipos_de_canal(canal: Canal) -> list[str]:
    """Tipos del catálogo que salen por un canal, en orden estable."""
    return sorted(t for t, spec in CATALOGO.items() if canal in spec.canales)


def suscripciones_validas() -> list[str]:
    """Vocabulario que acepta un webhook: comodines + tipos del catálogo.

    Es la lista que sirve ``GET /webhooks/event-types``: la UI no la duplica,
    así que no puede divergir de lo que valida el alta.
    """
    return sorted({"*", *(f"{familia}.*" for familia in FAMILIAS), *TIPOS})


def suscripcion_cubre(suscripciones: set[str] | frozenset[str], tipo: str) -> bool:
    """¿Alguna de las suscripciones del webhook cubre este tipo?

    Cubre el comodín global (``*``), el de familia (``pursuit.*``) y el tipo
    exacto. Se compara contra el catálogo y no contra una lista propia para que
    ampliar el catálogo no obligue a tocar el enrutado.
    """
    if "*" in suscripciones or tipo in suscripciones:
        return True
    familia = tipo.split(".", 1)[0]
    return f"{familia}.*" in suscripciones


# ── Plantillas de salida (D13) ───────────────────────────────────────────────
#
# Un renderer por familia, no por tipo: lo que cambia entre `pursuit.created` y
# `pursuit.decided` es el texto, no la estructura de la tarjeta. `renderizar`
# cae al formato `json` para cualquier evento sin plantilla específica, que es
# el criterio de aceptación del plan y además la degradación correcta: un
# receptor que espera JSON firmado lo sigue recibiendo.


def _resumen(tipo: str, payload: dict[str, Any]) -> str:
    """Una línea legible del evento, común a Slack y Teams."""
    spec = CATALOGO.get(tipo)
    titulo = spec.titulo if spec else tipo
    referencia = str(
        payload.get("titulo")
        or payload.get("licitacion_id")
        or payload.get("id_externo")
        or payload.get("rule_id")
        or ""
    )
    return f"{titulo}: {referencia}".strip().rstrip(":")


def _hechos(payload: dict[str, Any], *, maximo: int = 8) -> list[tuple[str, str]]:
    """Pares (clave, valor) presentables del payload, en orden estable.

    Se aplanan a texto porque las dos plantillas los pintan como una lista de
    hechos, y ni Block Kit ni Adaptive Cards admiten un objeto anidado ahí.
    """
    hechos: list[tuple[str, str]] = []
    for clave in sorted(payload):
        valor = payload[clave]
        if valor is None or valor == "" or valor == [] or valor == {}:
            continue
        if isinstance(valor, list | tuple):
            texto = ", ".join(str(v) for v in valor)
        elif isinstance(valor, dict):
            texto = ", ".join(f"{k}={v}" for k, v in sorted(valor.items()))
        else:
            texto = str(valor)
        hechos.append((clave, texto[:300]))
        if len(hechos) >= maximo:
            break
    return hechos


def _cuerpo_json(tipo: str, payload: dict[str, Any], timestamp: str) -> dict[str, Any]:
    """Formato histórico del webhook. Se conserva byte a byte: hay receptores
    en producción que ya parsean ``{event, data, timestamp}``."""
    return {"event": tipo, "data": payload, "timestamp": timestamp}


def _cuerpo_slack(tipo: str, payload: dict[str, Any], timestamp: str) -> dict[str, Any]:
    """Block Kit: ``text`` de respaldo + bloques de sección.

    ``text`` no es decorativo — es lo que Slack usa en la notificación push y
    en los clientes que no renderizan bloques; un mensaje sin él llega vacío al
    móvil.
    """
    campos = [
        {"type": "mrkdwn", "text": f"*{clave}*\n{valor}"} for clave, valor in _hechos(payload)
    ]
    bloques: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": _resumen(tipo, payload)[:150]},
        }
    ]
    # Block Kit admite como mucho 10 campos por sección.
    for inicio in range(0, len(campos), 10):
        bloques.append({"type": "section", "fields": campos[inicio : inicio + 10]})
    bloques.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"TenderFlow · {tipo} · {timestamp}"}],
        }
    )
    return {"text": _resumen(tipo, payload), "blocks": bloques}


def _cuerpo_teams(tipo: str, payload: dict[str, Any], timestamp: str) -> dict[str, Any]:
    """Adaptive Card 1.5 envuelta en el sobre de adjunto que espera Teams."""
    tarjeta: dict[str, Any] = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": _resumen(tipo, payload),
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [{"title": clave, "value": valor} for clave, valor in _hechos(payload)],
            },
            {
                "type": "TextBlock",
                "text": f"TenderFlow · {tipo} · {timestamp}",
                "isSubtle": True,
                "spacing": "Small",
                "wrap": True,
            },
        ],
    }
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": tarjeta,
            }
        ],
    }


def renderizar(
    tipo: str,
    payload: dict[str, Any],
    *,
    formato: str | None,
    timestamp: str,
) -> dict[str, Any]:
    """Cuerpo del webhook para este evento en el formato pedido.

    Un formato desconocido —o ausente, que es lo que traen los webhooks
    anteriores a la revisión ``v108``— cae a ``json``: la entrega no se pierde
    por no reconocer una plantilla.
    """
    if formato == "slack_blocks":
        return _cuerpo_slack(tipo, payload, timestamp)
    if formato == "teams_adaptive_card":
        return _cuerpo_teams(tipo, payload, timestamp)
    return _cuerpo_json(tipo, payload, timestamp)


def normalizar_formato(valor: str | None) -> Formato:
    """Formato válido a partir de lo que traiga la columna (o ``json``).

    Se comparan literales uno a uno en vez de ``valor in FORMATOS`` porque la
    pertenencia a una tupla no estrecha el tipo para mypy, y estrecharlo a mano
    con un ``cast`` sería afirmar lo que aquí se está comprobando.
    """
    if valor == "slack_blocks":
        return "slack_blocks"
    if valor == "teams_adaptive_card":
        return "teams_adaptive_card"
    return FORMATO_POR_DEFECTO


__all__ = [
    "CANALES",
    "CATALOGO",
    "FAMILIAS",
    "FORMATOS",
    "FORMATO_POR_DEFECTO",
    "TIPOS",
    "Canal",
    "EspecificacionEvento",
    "Formato",
    "PayloadIncompleto",
    "TipoDeEventoDesconocido",
    "especificacion",
    "normalizar_formato",
    "renderizar",
    "suscripcion_cubre",
    "suscripciones_validas",
    "tipos_de_canal",
    "validar_payload",
    "validar_tipo",
]
