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

    recipient = (to_addr or settings.ALERT_EMAIL_TO or "").strip()
    user = settings.ALERT_SMTP_USER.strip()
    password = settings.ALERT_SMTP_PASSWORD.get_secret_value().strip()
    host = settings.ALERT_SMTP_HOST.strip()
    port = settings.ALERT_SMTP_PORT

    if not (recipient and user and password):
        log.debug(
            "alert_smtp_not_configured",
            missing=[
                k
                for k, v in {
                    "ALERT_EMAIL_TO": recipient,
                    "ALERT_SMTP_USER": user,
                    "ALERT_SMTP_PASSWORD": password,
                }.items()
                if not v
            ],
        )
        return

    subject = f"[TenderFlow] [{level.name}] {title}"
    html = _build_html(level, title, body, context)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = recipient
    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.sendmail(user, [recipient], msg.as_string())
        log.info("alert_email_sent", to=recipient, subject=subject)
    except smtplib.SMTPException as e:
        log.warning("alert_email_failed", error=str(e))
    except OSError as e:
        log.warning("alert_email_network_error", error=str(e))


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
