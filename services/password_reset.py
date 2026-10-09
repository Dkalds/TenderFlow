"""Emisión y entrega de enlaces de recuperación de contraseña."""

from __future__ import annotations

import hashlib
import html
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from db.audit import log_event
from db.password_reset import create_reset_token_for_email
from observability.alerts import enviar_email_transaccional
from observability.logging import get_logger
from services.solicitudes_acceso import url_de_login
from shared.audit_events import AUTH_PASSWORD_RESET_REQUESTED

log = get_logger(__name__)

_RESET_TTL_MINUTES = 30
_SUBJECT = "Restablece tu contraseña de TenderFlow"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_password_reset(email: str) -> tuple[bool, str | None]:
    """Crea un token para una cuenta local; devuelve existencia y token bruto."""
    raw = secrets.token_urlsafe(32)
    expires_at = (datetime.now(UTC) + timedelta(minutes=_RESET_TTL_MINUTES)).isoformat()
    created = create_reset_token_for_email(email, token_hash(raw), expires_at)
    return created, raw if created else None


def process_password_reset_request(email: str) -> None:
    """Atiende una solicitud ya respondida: emite el token, deja rastro y envía.

    Corre como tarea en segundo plano de ``POST /auth/password-reset/request``.
    Aquí vive **todo** lo que depende de si la cuenta existe, y por eso va
    después de responder: hecho en línea, una cuenta local activa costaba dos
    escrituras más que una inexistente (invalidar los tokens anteriores e
    insertar el nuevo) y la latencia de la respuesta las distinguía aunque el
    cuerpo fuera idéntico. Lo que la ruta hace en línea —validar y contar las
    cuotas— pesa lo mismo con cuenta que sin ella.

    **Nunca lanza.** La respuesta ya salió y no hay a quién devolver el error:
    queda en el log, sin el correo ni el token.
    """
    try:
        created, token = issue_password_reset(email)
        # La respuesta es indistinguible; el rastro no: dice si se emitió un
        # enlace, sin el correo ni el id (para una cuenta que no existe no hay).
        log_event(
            event_type=AUTH_PASSWORD_RESET_REQUESTED,
            outcome="success" if created else "failure",
            detail={"issued": bool(created)},
        )
        if created and token is not None:
            send_password_reset_email(email, token)
    except Exception:
        # `error(..., exc_info=True)` y no `exception(...)`: con las dos la
        # traza sale en el evento, ya pasada por el redactor; `exception`
        # además se la entrega a `logging`, que la imprime otra vez tal cual
        # —con lo que el mensaje de la excepción traiga— debajo de la línea.
        log.error("password_reset_request_failed", exc_info=True)


def send_password_reset_email(email: str, token: str) -> bool:
    """Envía el token sin escribirlo en logs ni persistencia."""
    login_url = url_de_login()
    reset_url = None
    if login_url:
        base = login_url.removesuffix("/login")
        reset_url = f"{base}/restablecer-contrasena#token={quote(token)}"
    if reset_url is None:
        log.error("password_reset_frontend_url_unavailable")
        return False

    text_lines = [
        "Se ha solicitado restablecer la contraseña de tu cuenta local de TenderFlow.",
        "",
        "El enlace caduca en 30 minutos y sólo puede usarse una vez.",
    ]
    if reset_url:
        text_lines += ["", reset_url]
    text_lines += ["", "Si no lo solicitaste, ignora este correo."]
    text = "\n".join(text_lines)
    link = (
        f'<p><a href="{html.escape(reset_url)}">Restablecer contraseña</a></p>' if reset_url else ""
    )
    html_body = (
        "<!DOCTYPE html><html><body>"
        "<p>Se ha solicitado restablecer la contraseña de tu cuenta local de TenderFlow.</p>"
        "<p>El enlace caduca en 30 minutos y sólo puede usarse una vez.</p>"
        f"{link}<p>Si no lo solicitaste, ignora este correo.</p>"
        "</body></html>"
    )
    sent = enviar_email_transaccional(
        to_addr=email,
        subject=_SUBJECT,
        texto=text,
        html=html_body,
    )
    domain = email.rpartition("@")[2] or "desconocido"
    if sent:
        log.info("password_reset_email", sent=True, domain=domain)
    else:
        # Quien lo pidió ya leyó «te llegará un enlace». Si el correo no sale
        # —sin credenciales SMTP el transporte lo anota en `debug`— este es el
        # único rastro visible, y en `info` no lo miraba nadie. El dominio y
        # no la dirección, como en el resto del correo de producto.
        log.warning("password_reset_email", sent=False, domain=domain)
    return sent
