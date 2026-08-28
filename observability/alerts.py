"""Envío de alertas por email (SMTP) o al log estructurado.

Variables de entorno necesarias para email:

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

import smtplib
import textwrap
from datetime import UTC
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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
) -> bool:
    """Entrega un email por SMTP con STARTTLS. Devuelve si salió de aquí.

    Punto único de transporte del proyecto: lo comparten las alertas de
    operación (:func:`_send_smtp`) y los emails de producto
    (:func:`enviar_email_transaccional`). Tener dos implementaciones de SMTP
    significaba que arreglar el timeout, el STARTTLS o el manejo de error en una
    dejaba la otra atrás.

    **Nunca propaga.** Un buzón mal configurado o un SMTP caído no pueden
    tumbar a quien llama: los dos usos son efectos secundarios de una operación
    que ya salió bien (una alerta que describe algo ya ocurrido, o un correo que
    acompaña a un cambio de estado ya escrito en la base). El valor de retorno
    existe para que el llamante lo registre, no para que reintente aquí.

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
    from config import settings

    user = settings.ALERT_SMTP_USER.strip()
    password = settings.ALERT_SMTP_PASSWORD.get_secret_value().strip()
    host = settings.ALERT_SMTP_HOST.strip()
    port = settings.ALERT_SMTP_PORT
    destino = recipient.strip()

    if not (destino and user and password):
        log.debug(
            "alert_smtp_not_configured",
            missing=[
                k
                for k, v in {
                    etiqueta_destino: destino,
                    "ALERT_SMTP_USER": user,
                    "ALERT_SMTP_PASSWORD": password,
                }.items()
                if not v
            ],
        )
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = destino
    msg.attach(MIMEText(texto, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.sendmail(user, [destino], msg.as_string())
        log.info(
            f"{evento}_sent",
            to=destino if destino_log is None else destino_log,
            subject=subject,
        )
        return True
    except smtplib.SMTPException as e:
        log.warning(f"{evento}_failed", error=str(e))
        return False
    except OSError as e:
        log.warning(f"{evento}_network_error", error=str(e))
        return False


def enviar_email_transaccional(*, to_addr: str, subject: str, texto: str, html: str) -> bool:
    """Envía un email **de producto** a una persona, no una alerta de operación.

    Existe porque :func:`notify` no sirve para esto por tres motivos, y los tres
    se notan en el buzón de quien lo recibe: el asunto sale como
    ``[TenderFlow] [WARN] …``, el cuerpo va envuelto en la plantilla de alerta
    con su franja de color y su pie de "alerta automática", y el envío está
    sujeto a ``ALERT_MIN_LEVEL`` —o sea que un correo dirigido a una persona
    podría no salir según cómo esté configurado el umbral de las alertas de
    infraestructura, que no tiene nada que ver.

    Comparte credenciales SMTP con las alertas a propósito: el proyecto tiene un
    solo buzón remitente y añadir un segundo juego de variables sería
    configuración nueva para un beneficio que hoy no existe. Si algún día el
    correo de producto necesita su propio remitente, este es el punto donde
    cambiarlo.

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
    )


def _send_smtp(
    level: AlertLevel,
    title: str,
    body: str,
    context: dict[str, Any],
    *,
    to_addr: str | None = None,
) -> None:
    """Envía el email usando SMTP con STARTTLS.

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
