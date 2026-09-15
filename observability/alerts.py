"""Envío de alertas por email o al log estructurado.

El transporte vive en :mod:`observability.mailer` (``EMAIL_BACKEND``: ``smtp``,
``resend``, ``postmark`` o ``console``; ver
``docs/runbooks/correo-transaccional.md``). Este módulo conserva la API que
usan los llamantes —:func:`notify`, :func:`enviar_email_transaccional`,
:func:`_send_smtp`— y el contrato de fallo, el log y la métrica de entrega.

Variables de entorno necesarias para el backend ``smtp`` (el default):

- ``ALERT_EMAIL_TO``       : destinatario, p.ej. dkalitovicsd@gmail.com
- ``ALERT_SMTP_USER``      : cuenta remitente, p.ej. dkalitovicsd@gmail.com
- ``ALERT_SMTP_PASSWORD``  : contraseña de aplicación de Google (16 chars)
- ``ALERT_SMTP_HOST``      : servidor SMTP  (default: smtp.gmail.com)
- ``ALERT_SMTP_PORT``      : puerto STARTTLS (default: 587)
- ``ALERT_MIN_LEVEL``      : ``info`` | ``warn`` | ``error`` (default: ``warn``)

Si las variables no están definidas las alertas solo se escriben al log.

Cómo obtener la contraseña de aplicación de Gmail
--------------------------------------------------
1. Activa la verificación en 2 pasos en tu cuenta Google.
2. Ve a https://myaccount.google.com/apppasswords
3. Crea una nueva contraseña para "Correo" / "Otro (nombre personalizado)".
4. Copia los 16 caracteres y ponlos en ALERT_SMTP_PASSWORD.
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from datetime import UTC
from enum import IntEnum
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)


class AlertLevel(IntEnum):
    INFO = 10
    WARN = 20
    ERROR = 30
    CRITICAL = 40


_LEVEL_NAMES = {
    "info": AlertLevel.INFO,
    "warn": AlertLevel.WARN,
    "warning": AlertLevel.WARN,
    "error": AlertLevel.ERROR,
    # "crit" lo emite scheduler/drift_monitor.py; sin esta entrada caía al
    # default WARN y un drift crítico se degradaba a aviso en silencio.
    "crit": AlertLevel.CRITICAL,
    "critical": AlertLevel.CRITICAL,
}

_LEVEL_COLORS = {
    AlertLevel.INFO: "#36a64f",
    AlertLevel.WARN: "#e6a817",
    AlertLevel.ERROR: "#e04e4e",
    AlertLevel.CRITICAL: "#8b0000",
}

_LEVEL_EMOJI = {
    AlertLevel.INFO: "\u2139\ufe0f",
    AlertLevel.WARN: "\u26a0\ufe0f",
    AlertLevel.ERROR: "\u274c",
    AlertLevel.CRITICAL: "\U0001f6a8",
}


def _min_level() -> AlertLevel:
    from config import settings

    raw = settings.ALERT_MIN_LEVEL.lower()
    return _LEVEL_NAMES.get(raw, AlertLevel.WARN)


def _contar_fallo_entrega(motivo: str) -> None:
    """Suma uno a ``alert_delivery_failed_total`` sin poder fallar.

    Va envuelto en su propio ``try`` porque este módulo no puede propagar nada
    (ver :func:`_entregar_email`): sería absurdo que el contador que existe para
    hacer visible un canal roto fuese, él mismo, capaz de romper al llamante.
    """
    try:
        from observability.runtime_metrics import alert_delivery_failed_total

        alert_delivery_failed_total.labels(canal="email", motivo=motivo).inc()
    except Exception:  # pragma: no cover — métrica best-effort
        log.debug("alert_delivery_metric_unavailable", motivo=motivo)


def _build_html(level: AlertLevel, title: str, body: str, context: dict[str, Any]) -> str:
    color = _LEVEL_COLORS[level]
    emoji = _LEVEL_EMOJI[level]
    ctx_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#555;font-weight:bold'>{k}</td>"
        f"<td style='padding:4px 0'>{v}</td></tr>"
        for k, v in context.items()
    )
    ctx_table = (
        f"<table style='margin-top:12px;border-collapse:collapse'>{ctx_rows}</table>"
        if ctx_rows
        else ""
    )
    return textwrap.dedent(f"""\
        <!DOCTYPE html>
        <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
          <div style="border-left:4px solid {color};padding:12px 16px;
                      background:#fafafa;border-radius:4px">
            <h2 style="margin:0 0 8px;color:{color}">{emoji} {title}</h2>
            <p style="margin:0;color:#333;white-space:pre-wrap">{body}</p>
            {ctx_table}
          </div>
          <p style="font-size:11px;color:#aaa;margin-top:16px">
            TenderFlow · alerta automática · nivel {level.name}
          </p>
        </body></html>
    """)


def _entregar_email(
    *,
    recipient: str,
    subject: str,
    texto: str,
    html: str,
    evento: str = "alert_email",
    etiqueta_destino: str = "ALERT_EMAIL_TO",
    destino_log: str | None = None,
    unsubscribe_url: str | None = None,
    tags: Sequence[str] = (),
) -> bool:
    """Entrega un email por el backend configurado. Devuelve si salió de aquí.

    Punto único de entrada al correo del proyecto: lo comparten las alertas de
    operación (:func:`_send_smtp`) y los emails de producto
    (:func:`enviar_email_transaccional`). El transporte —SMTP, Resend, Postmark
    o consola, según ``EMAIL_BACKEND``— vive en :mod:`observability.mailer`;
    aquí quedan el contrato de fallo, el log y la métrica, que es lo que los
    llamantes y sus tests conocen. ``unsubscribe_url`` pone los encabezados
    ``List-Unsubscribe`` (RFC 8058) y ``tags`` etiqueta el envío en el ESP.

    **Nunca propaga.** Un buzón mal configurado o un SMTP caído no pueden
    tumbar a quien llama: los dos usos son efectos secundarios de una operación
    que ya salió bien (una alerta que describe algo ya ocurrido, o un correo que
    acompaña a un cambio de estado ya escrito en la base). El valor de retorno
    existe para que el llamante lo registre, no para que reintente aquí.

    Lo que cambia con S6.3: no propagar no puede significar *no dejar rastro
    agregable*. Cada camino de fallo incrementa ``alert_delivery_failed_total``
    antes de devolver ``False``. Sin ese contador, un ``ALERT_SMTP_PASSWORD``
    caducado dejaba de enviar alertas en silencio — los llamantes descartan el
    booleano, así que el único rastro era un ``log.warning`` que nadie agrega. El
    canal que avisa de todo lo demás era el único del que no avisaba nadie.

    ``evento`` prefija los eventos de log —``alert_email`` mantiene los nombres
    que ya existían (``alert_email_sent``…) para no romper lo que los busque— y
    ``etiqueta_destino`` nombra de dónde salió el destinatario, que no es el
    mismo sitio en los dos usos.

    ``destino_log`` es **lo que se escribe en el log** en lugar de la dirección.
    Existe porque los dos usos tienen destinatarios de naturaleza distinta: el de
    las alertas es ``ALERT_EMAIL_TO``, una constante de configuración que sí
    puede registrarse entera, mientras que el del correo de producto es una
    persona física y su dirección es un dato personal. Sin este parámetro, este
    ``log.info`` contradecía en el log del transporte la promesa que
    ``services/solicitudes_acceso.py::notificar_acceso_concedido`` cumple en el
    suyo ("se registra si salió y a qué dominio, NUNCA la dirección completa"),
    y ningún test lo veía porque el del servicio mockea el transporte entero.
    """
    from observability.mailer import Mensaje, enviar

    destino = recipient.strip()
    if not destino:
        log.debug("alert_smtp_not_configured", missing=[etiqueta_destino])
        _contar_fallo_entrega("not_configured")
        return False

    resultado = enviar(
        Mensaje(
            to=destino,
            subject=subject,
            text=texto,
            html=html,
            tags=list(tags),
            unsubscribe_url=unsubscribe_url,
        )
    )
    if resultado.ok:
        log.info(
            f"{evento}_sent",
            to=destino if destino_log is None else destino_log,
            subject=subject,
            backend=resultado.backend,
            provider_id=resultado.provider_id,
        )
        return True

    # Los nombres de evento (`*_failed`, `*_network_error`) y las etiquetas de
    # la métrica (`smtp`, `network`, `not_configured`) son los que ya existían;
    # `provider` e `invalid` son nuevos y solo aparecen con los backends HTTP.
    motivo = resultado.motivo or "unknown"
    if motivo == "not_configured":
        log.debug("alert_smtp_not_configured", backend=resultado.backend, error=resultado.error)
    elif motivo == "network":
        log.warning(f"{evento}_network_error", backend=resultado.backend, error=resultado.error)
    else:
        log.warning(
            f"{evento}_failed", backend=resultado.backend, motivo=motivo, error=resultado.error
        )
    _contar_fallo_entrega(motivo)
    return False


def enviar_email_transaccional(
    *,
    to_addr: str,
    subject: str,
    texto: str,
    html: str,
    unsubscribe_url: str | None = None,
    tags: Sequence[str] = (),
) -> bool:
    """Envía un email **de producto** a una persona, no una alerta de operación.

    ``unsubscribe_url`` es la URL de baja del correo (la del pie del digest):
    cuando viene, el mensaje sale con ``List-Unsubscribe`` y
    ``List-Unsubscribe-Post`` para que el cliente de correo ofrezca «Cancelar
    suscripción» en vez de «Marcar como spam». ``tags`` etiqueta el envío en
    el proveedor cuando ``EMAIL_BACKEND`` es un ESP.

    Existe porque :func:`notify` no sirve para esto por tres motivos, y los tres
    se notan en el buzón de quien lo recibe: el asunto sale como
    ``[TenderFlow] [WARN] …``, el cuerpo va envuelto en la plantilla de alerta
    con su franja de color y su pie de "alerta automática", y el envío está
    sujeto a ``ALERT_MIN_LEVEL`` —o sea que un correo dirigido a una persona
    podría no salir según cómo esté configurado el umbral de las alertas de
    infraestructura, que no tiene nada que ver.

    Comparte backend y remitente con las alertas a propósito: el proyecto tiene
    un solo remitente (``EMAIL_FROM``, o la cuenta SMTP si está vacío) y un
    segundo juego de variables sería configuración nueva para un beneficio que
    hoy no existe. Si algún día el correo de producto necesita su propio
    remitente, este es el punto donde cambiarlo.

    Al log va **el dominio y no la dirección**: aquí el destinatario es una
    persona, no un buzón de operación, y el dominio basta para diagnosticar un
    correo corporativo que rebota.
    """
    return _entregar_email(
        recipient=to_addr,
        subject=subject,
        texto=texto,
        html=html,
        evento="email_producto",
        etiqueta_destino="destinatario",
        destino_log=to_addr.rpartition("@")[2] or "desconocido",
        unsubscribe_url=unsubscribe_url,
        tags=tags,
    )


def _send_smtp(
    level: AlertLevel,
    title: str,
    body: str,
    context: dict[str, Any],
    *,
    to_addr: str | None = None,
) -> None:
    """Envía la alerta por el backend de correo configurado (``EMAIL_BACKEND``).

    Conserva el nombre histórico: es lo que parchean los tests y lo que buscan
    los llamantes, y con ``EMAIL_BACKEND=smtp`` (el default) sigue siendo
    literalmente cierto.

    ``to_addr`` sobreescribe la variable de entorno ``ALERT_EMAIL_TO``
    cuando se especifica (útil para notificaciones por destinatario).
    """
    from config import settings

    _entregar_email(
        recipient=(to_addr or settings.ALERT_EMAIL_TO or ""),
        subject=f"[TenderFlow] [{level.name}] {title}",
        texto=body,
        html=_build_html(level, title, body, context),
    )


def notify(
    level: AlertLevel | str,
    title: str,
    body: str = "",
    *,
    to_addr: str | None = None,
    **context: Any,
) -> None:
    """Envía una alerta. Seguro de llamar sin configuración (solo loguea).

    ``level`` puede ser un enum ``AlertLevel`` o cadena (``info``/``warn``/
    ``error``/``critical``).

    ``to_addr`` sobreescribe el destinatario de ``ALERT_EMAIL_TO`` del entorno.
    """
    if isinstance(level, str):
        level = _LEVEL_NAMES.get(level.lower(), AlertLevel.WARN)

    if level < _min_level():
        return

    log.log(
        {
            AlertLevel.INFO: 20,
            AlertLevel.WARN: 30,
            AlertLevel.ERROR: 40,
            AlertLevel.CRITICAL: 50,
        }[level],
        "alert",
        alert_title=title,
        alert_body=body,
        **context,
    )

    _send_smtp(level, title, body, context, to_addr=to_addr)


# ---------------------------------------------------------------------------
# Alerta de lag del feed diario
# ---------------------------------------------------------------------------

_DAILY_LAG_THRESHOLD_HOURS = 8
_DAILY_MAX_CONSECUTIVE_FAILURES = 3


def check_daily_lag() -> None:
    """Alerta si el cursor del feed diario tiene un lag excesivo.

    Consulta ``ingestion_cursors`` para ``place_live_atom`` y compara
    ``last_seen_updated`` con la hora actual.
    """
    from datetime import datetime

    from db.database import get_cursor

    cursor = get_cursor("place_live_atom")
    if cursor is None:
        # No se ha ejecutado nunca — no alertar
        return

    last_updated = cursor.get("last_seen_updated")
    if not last_updated:
        return

    try:
        # Parsear timestamp ISO
        last_dt = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
        now = datetime.now(UTC)
        # Normalizar a aware UTC para comparar
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=UTC)
        lag = now - last_dt
        lag_hours = lag.total_seconds() / 3600
    except (ValueError, TypeError):
        log.warning("daily_lag_check_parse_error", raw=last_updated)
        return

    if lag_hours > _DAILY_LAG_THRESHOLD_HOURS:
        notify(
            AlertLevel.WARN,
            f"Feed diario con lag de {lag_hours:.1f}h",
            body=(
                f"El último registro del feed ATOM en vivo tiene {lag_hours:.1f} horas "
                f"de antigüedad (umbral: {_DAILY_LAG_THRESHOLD_HOURS}h)."
            ),
            lag_hours=round(lag_hours, 1),
            last_seen_updated=last_updated,
        )


def check_daily_consecutive_failures() -> None:
    """Alerta si los últimos N runs del carril diario fallaron todos."""
    from services.extraction_runs import load_recent_daily_statuses

    statuses = load_recent_daily_statuses(_DAILY_MAX_CONSECUTIVE_FAILURES)

    if len(statuses) < _DAILY_MAX_CONSECUTIVE_FAILURES:
        return

    if all(s == "error" for s in statuses):
        notify(
            AlertLevel.ERROR,
            f"Feed diario: {_DAILY_MAX_CONSECUTIVE_FAILURES} fallos consecutivos",
            body="Los últimos runs del carril diario han fallado todos.",
        )


# ---------------------------------------------------------------------------
# Alerta de modelo ML obsoleto (D2)
# ---------------------------------------------------------------------------

_MODEL_STALENESS_DAYS = 30


def check_ml_model_staleness() -> None:
    """Alerta si el modelo ML SAP tiene más de ``_MODEL_STALENESS_DAYS`` días.

    Lee ``metadata["trained_at"]`` del clasificador. Si el fichero no existe
    o no tiene metadatos, registra un warning sin alertar.
    """
    from datetime import datetime
    from pathlib import Path

    model_path = Path("models/sap_classifier.pkl")
    if not model_path.exists():
        log.debug("ml_staleness_check_no_model", path=str(model_path))
        return

    try:
        import joblib

        clf = joblib.load(model_path)
        trained_at_raw = getattr(clf, "metadata", {}).get("trained_at")
        if not trained_at_raw:
            log.debug("ml_staleness_check_no_trained_at")
            return

        trained_dt = datetime.fromisoformat(str(trained_at_raw).replace("Z", "+00:00"))
        now = datetime.now(UTC)
        if trained_dt.tzinfo is None:
            trained_dt = trained_dt.replace(tzinfo=UTC)
        age_days = (now - trained_dt).total_seconds() / 86400
    except Exception as exc:
        log.warning("ml_staleness_check_error", error=str(exc))
        return

    if age_days > _MODEL_STALENESS_DAYS:
        notify(
            AlertLevel.WARN,
            f"Modelo ML SAP obsoleto ({age_days:.0f} días)",
            body=(
                f"El clasificador SAP fue entrenado hace {age_days:.0f} días "
                f"(umbral: {_MODEL_STALENESS_DAYS}d). Considera re-entrenar "
                f"con datos recientes."
            ),
            model_age_days=round(age_days, 1),
            trained_at=trained_at_raw,
        )
