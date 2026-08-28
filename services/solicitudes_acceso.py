"""Avisos del embudo de acceso: al operador cuando llega, a la persona cuando entra.

El embudo de captación estaba construido entero salvo su último tramo. El
formulario de la landing persiste la petición (``db/solicitudes_acceso.py``), el
panel de administración la lista y la mueve de estado
(``api/routes/admin_solicitudes.py``) — y ahí se acababa:

- **Al operador** sólo se le avisaba por webhook
  (``api/routes/publico_solicitudes.py::_avisar_operador``). El webhook es un
  buen canal, pero exige que exista una suscripción configurada con su
  ``WEBHOOK_ALLOWED_HOSTS``; si no la hay —y no consta que la haya— el aviso no
  sale y la cola sólo se descubre abriendo el panel. Un canal opcional no puede
  ser el único.
- **A quien pedía acceso** no se le escribía nunca, pese a que la página de
  gracias le promete literalmente que "la respuesta llega por correo"
  (``web/src/app/(publico)/solicitud-recibida/page.tsx``). Prometer un correo
  que el sistema no sabe enviar es la clase de incumplimiento que se paga en
  confianza justo con quien acaba de dar su dirección.

**Lo que este módulo NO hace: conceder el acceso.** La allowlist sigue viviendo
en ``OAUTH_ALLOWED_EMAILS``/``OAUTH_ALLOWED_DOMAINS`` (``shared/auth_core.py``),
así que habilitar a alguien sigue siendo editar variables de entorno. Moverla a
base de datos cambia un mecanismo de autenticación, y eso exige RFC
(AGENTS.md §5) además de migración: queda en el backlog, no aquí. Por eso el
correo de bienvenida **no se envía solo** al cambiar de estado: lo dispara el
operador explícitamente cuando ya ha habilitado el acceso, y el nombre del campo
que lo activa lo dice (ver ``EstadoBody.notificar``). Si se enviara automático,
la persona recibiría un "ya puedes entrar" y se encontraría un 403.
"""

from __future__ import annotations

import html
from urllib.parse import urlparse

from config.settings import settings
from observability.alerts import AlertLevel, enviar_email_transaccional, notify
from observability.logging import get_logger

log = get_logger(__name__)

__all__ = ["avisar_operador_de_solicitud", "notificar_acceso_concedido", "url_de_login"]

_ASUNTO_ACCESO = "Tu acceso a TenderFlow ya está activo"

#: Ventana de agrupación del aviso al operador. Un correo cada 15 minutos como
#: mucho, con la cuenta de pendientes dentro.
#:
#: No es una comodidad, es contención de un vector de amplificación de correo.
#: El formulario que dispara este aviso es público, anónimo y sin captcha
#: (``api/routes/publico_solicitudes.py`` explica por qué), y ``notify`` no tiene
#: deduplicación ni throttling: valida el nivel y llama a ``_send_smtp``. Sin
#: ventana, una IP podía provocar 120 correos por minuto —el tope del bucket
#: global del middleware— y varias IPs no tenían tope ninguno. Y el buzón
#: remitente es el mismo que usan las alertas de infraestructura: si el proveedor
#: lo bloquea por volumen, se pierden también las alertas reales.
_VENTANA_AVISO_SEGUNDOS = 900

#: Clave **global**, no por IP. El recurso que se protege es el buzón del
#: operador, que es uno solo; una clave por IP dejaría el ataque intacto sin más
#: que rotar de origen. Es el mismo limiter que usan ``csp-report`` y
#: ``client-error``, con un bucket propio.
_CLAVE_AVISO = "aviso_solicitudes"


def url_de_login() -> str | None:
    """URL de la pantalla de acceso, deducida de la configuración existente.

    No se introduce una variable de entorno nueva para esto a propósito:
    ``FRONTEND_URL`` existe en ``render.yaml`` pero **no** en
    ``config/settings.py`` ni en ``.env.example`` (está anotada como deuda de
    documentación en el backlog), y tocar ``.env*`` requiere OK humano
    (AGENTS.md §6). Así que se deduce de lo que ya está declarado y validado:
    el primer origen de ``CORS_ALLOWED_ORIGINS`` —que es el sitio que puede
    hablar con esta API— y, si está vacío, el origen del callback de OAuth.

    Devuelve ``None`` cuando no hay forma honesta de saberlo. El correo se envía
    igual, sin enlace: mejor un correo sin botón que un botón a ninguna parte.
    """
    origenes = [o.strip().rstrip("/") for o in (settings.CORS_ALLOWED_ORIGINS or "").split(",")]
    for origen in origenes:
        if origen.startswith("http"):
            return f"{origen}/login"

    partes = urlparse(settings.OAUTH_REDIRECT_URI or "")
    if partes.scheme and partes.netloc:
        return f"{partes.scheme}://{partes.netloc}/login"
    return None


def _cuerpo_acceso(empresa: str | None, enlace: str | None) -> tuple[str, str]:
    """Texto plano y HTML del correo de acceso concedido.

    Se escribe entero aquí y no con la plantilla de alertas porque el
    destinatario es una persona que no conoce el producto, no un operador
    leyendo una incidencia. Dice tres cosas y ninguna más: que ya puede entrar,
    cómo entra, y qué hacer si no funciona.
    """
    saludo = "Hola" if not empresa else f"Hola, equipo de {empresa}"
    pasos = (
        "Entra con el botón «Continuar con Google», usando esta misma dirección "
        "de correo (o la de tu empresa, si habilitamos el dominio entero)."
    )
    cierre = (
        "Si al entrar te dice que tu cuenta no tiene acceso, respóndenos a este "
        "correo y lo revisamos."
    )

    lineas = [f"{saludo}:", "", "Ya tienes acceso a TenderFlow.", "", pasos]
    if enlace:
        lineas += ["", enlace]
    lineas += ["", cierre, "", "— TenderFlow"]
    texto = "\n".join(lineas)

    # `empresa` es texto que escribió el visitante en un formulario público: se
    # escapa antes de entrar en el HTML. Es la misma regla que el resto del
    # proyecto aplica al HTML dinámico.
    saludo_html = html.escape(saludo)
    boton = (
        f'<p style="margin:20px 0"><a href="{html.escape(enlace)}" '
        'style="background:#0e7490;color:#fff;padding:10px 18px;border-radius:6px;'
        'text-decoration:none;display:inline-block">Entrar en TenderFlow</a></p>'
        if enlace
        else ""
    )
    cuerpo_html = (
        '<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;'
        'max-width:600px;margin:0 auto;color:#1f2733;line-height:1.55">'
        f"<p>{saludo_html}:</p>"
        "<p><strong>Ya tienes acceso a TenderFlow.</strong></p>"
        f"<p>{html.escape(pasos)}</p>"
        f"{boton}"
        f'<p style="color:#55606e;font-size:14px">{html.escape(cierre)}</p>'
        '<p style="color:#8a93a0;font-size:12px;margin-top:24px">TenderFlow · '
        "inteligencia de licitaciones públicas de tecnología</p>"
        "</body></html>"
    )
    return texto, cuerpo_html


def notificar_acceso_concedido(*, email: str, empresa: str | None = None) -> bool:
    """Escribe a quien pidió acceso para decirle que ya puede entrar.

    Devuelve si el correo salió. **No lanza**: el cambio de estado de la
    solicitud ya está escrito cuando esto se ejecuta, así que un SMTP caído no
    puede convertir una aprobación buena en un error 500 para el operador. Lo
    que sí hace es dejar constancia en el log, porque un correo que no sale es
    justamente el fallo que este módulo existe para evitar.
    """
    enlace = url_de_login()
    texto, cuerpo_html = _cuerpo_acceso(empresa, enlace)
    enviado = enviar_email_transaccional(
        to_addr=email, subject=_ASUNTO_ACCESO, texto=texto, html=cuerpo_html
    )
    # El email es un dato personal: se registra si salió y a qué dominio, nunca
    # la dirección completa. Basta para diagnosticar un buzón corporativo que
    # rebota sin dejar un rastro que no hace falta.
    dominio = email.rpartition("@")[2] or "desconocido"
    log.info("solicitud_acceso_aviso_persona", enviado=enviado, dominio=dominio)
    return enviado


def _dentro_de_la_ventana_de_aviso() -> bool:
    """``True`` si toca emitir el aviso; ``False`` si se agrupa con el anterior.

    Consume una unidad del bucket cuando devuelve ``True``, igual que cualquier
    otro uso del limiter. Fail-open a propósito: ver el docstring de
    :func:`avisar_operador_de_solicitud`.
    """
    from services.rate_limiting import get_rate_limiter

    try:
        return get_rate_limiter().check(
            _CLAVE_AVISO, max_calls=1, window_seconds=_VENTANA_AVISO_SEGUNDOS
        )
    except Exception:
        log.warning("solicitud_acceso_aviso_sin_limiter")
        return True


def avisar_operador_de_solicitud(
    *, solicitud_id: int, empresa: str | None, origen: str | None, pendientes: int
) -> bool:
    """Avisa por email de que hay una solicitud esperando.

    Segundo canal junto al webhook que ya existía, no sustituto: el webhook es
    mejor cuando está configurado, y esto cubre el caso —hoy el probable— de que
    no lo esté.

    **Sin el email ni el mensaje de quien escribe**, igual que el webhook: el
    aviso dice que hay algo que atender y cuántas cosas hay, y el dato de
    contacto se lee en el panel, que ya exige ser administrador. ``empresa`` sí
    viaja porque es dato de negocio y es lo que hace accionable el aviso.

    Va como ``WARN`` y no como ``INFO`` por una razón práctica y no semántica:
    ``ALERT_MIN_LEVEL`` vale ``warn`` por defecto, así que un ``INFO`` se
    descartaría en silencio en la configuración más común — que es exactamente
    el fallo que este aviso viene a corregir. No es una avería del sistema, pero
    sí es algo con una persona esperando al otro lado.

    **Agrupado, no por solicitud.** Ver :data:`_VENTANA_AVISO_SEGUNDOS`: como
    mucho un correo cada 15 minutos, y el cuerpo dice cuántas esperan, así que
    agrupar no pierde información — el operador abre el panel igual. Devuelve
    ``False`` cuando el aviso se agrupa, que **no** es un fallo: la solicitud
    está guardada y el pendiente lo recogerá el siguiente correo o el panel.

    Si el limiter no está disponible se envía igual. Un backend de rate limit
    caído no puede convertirse en la razón por la que nadie se entera de que hay
    gente esperando: el fallo que se acepta es el ruido, no el silencio.
    """
    if not _dentro_de_la_ventana_de_aviso():
        log.info("solicitud_acceso_aviso_operador_agrupado", solicitud_id=solicitud_id)
        return False
    try:
        notify(
            AlertLevel.WARN,
            "Solicitud de acceso pendiente",
            f"Hay {pendientes} solicitud(es) esperando revisión en el panel.",
            solicitud_id=solicitud_id,
            empresa=empresa or "—",
            origen=origen or "—",
        )
        return True
    except Exception:
        # Un aviso que falla no puede tumbar el alta: la solicitud ya está
        # guardada y esto corre después de responderle al visitante.
        log.exception("solicitud_acceso_aviso_operador_fallido", solicitud_id=solicitud_id)
        return False
