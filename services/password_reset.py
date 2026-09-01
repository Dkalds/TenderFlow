"""Emisión y entrega de enlaces de recuperación de contraseña."""

from __future__ import annotations

import hashlib
import html
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from db.password_reset import create_reset_token_for_email
from observability.alerts import enviar_email_transaccional
from observability.logging import get_logger
from services.solicitudes_acceso import url_de_login

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
    log.info("password_reset_email", sent=sent, domain=domain)
    return sent
