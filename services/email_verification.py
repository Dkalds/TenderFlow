"""Alta con correo y contraseña para quien tiene el acceso concedido.

RFC 2026-10-21-alta-con-contrasena-tras-concesion. ``POST /auth/register`` en
modo cerrado responde siempre lo mismo y deja aquí, en segundo plano, todo lo
que depende de si la cuenta existe: crearla o reemplazarla sin verificar, y
mandar el correo que toca.

Dos correos:

- **Verificar**: a una cuenta nueva o aún sin verificar. Lleva el enlace a
  ``/verificar-correo#token=…`` (24 h, un uso).
- **Ya tienes cuenta**: a una cuenta verificada. No cambia nada; lleva un enlace
  de restablecer contraseña (el de RFC 243, 30 min), que para quien entró solo
  por Google sirve para crear su primera contraseña.

El token va en el fragmento de la URL, como el del reset: el navegador no lo
manda al servidor ni lo deja en un ``Referer``, y el redactor de
``observability/logging.py`` lo tapa si el backend es ``console``.
"""

from __future__ import annotations

import html
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from db.audit import log_event
from db.email_verification import register_unverified
from db.password_reset import create_reset_token_for_user
from observability.alerts import enviar_email_transaccional
from observability.logging import get_logger
from services.app_urls import url_absoluta
from services.email_html import (
    BLANCO,
    CERRAR_DOCUMENTO,
    ESTILO_PIE,
    OXIDO,
    SECUNDARIO,
    abrir_documento,
)
from services.password_reset import token_hash
from shared.audit_events import AUTH_SIGNUP_REQUESTED
from shared.auth_core import hash_password

log = get_logger(__name__)

__all__ = [
    "VERIFICACION_TTL_HORAS",
    "issue_verification_token",
    "process_registration",
]

#: Vida del enlace de verificación. Más que los 30 minutos del reset: quien se
#: da de alta puede no abrir el correo hasta el día siguiente, y lo peor que
#: hace un enlace robado aquí es activar una cuenta cuya contraseña eligió el
#: propio dueño del buzón.
VERIFICACION_TTL_HORAS = 24
_RESET_TTL_MINUTOS = 30

_ASUNTO_VERIFICAR = "Activa tu cuenta de TenderFlow"
_ASUNTO_YA_TIENES = "Ya tienes una cuenta en TenderFlow"


def issue_verification_token() -> tuple[str, str, str]:
    """``(token bruto, su hash, caducidad ISO)`` de un enlace de verificación nuevo."""
    raw = secrets.token_urlsafe(32)
    expires_at = (datetime.now(UTC) + timedelta(hours=VERIFICACION_TTL_HORAS)).isoformat()
    return raw, token_hash(raw), expires_at


def _boton(enlace: str, texto: str) -> str:
    return (
        f'<p style="margin:20px 0"><a href="{html.escape(enlace)}" '
        f'style="background:{OXIDO};color:{BLANCO};padding:10px 18px;border-radius:6px;'
        f'text-decoration:none;display:inline-block">{html.escape(texto)}</a></p>'
    )


def _documento(parrafos: list[str], boton: str, pie: str) -> str:
    cuerpo = "".join(f"<p>{html.escape(p)}</p>" for p in parrafos)
    return (
        abrir_documento(max_ancho=600)
        + cuerpo
        + boton
        + f'<p style="color:{SECUNDARIO}">{html.escape(pie)}</p>'
        + f'<p style="{ESTILO_PIE};margin-top:24px">TenderFlow · '
        "inteligencia de licitaciones públicas de tecnología</p>" + CERRAR_DOCUMENTO
    )


def send_verification_email(email: str, token: str) -> bool:
    """Envía el enlace de activación. Nunca escribe el token en el log."""
    enlace = url_absoluta(f"/verificar-correo#token={quote(token)}")
    if enlace is None:
        # Sin origen del frontend no hay enlace que mandar, y un correo de
        # activación sin enlace no activa nada.
        log.error("email_verification_frontend_url_unavailable")
        return False
    parrafos = [
        "Hola:",
        "Para terminar de crear tu cuenta de TenderFlow, confirma que esta "
        "dirección de correo es tuya.",
        f"El enlace caduca en {VERIFICACION_TTL_HORAS} horas y sólo puede usarse una vez.",
    ]
    pie = "Si no has creado una cuenta, ignora este correo: sin confirmarla no se activa."
    texto = "\n\n".join([*parrafos, enlace, pie, "— TenderFlow"])
    enviado = enviar_email_transaccional(
        to_addr=email,
        subject=_ASUNTO_VERIFICAR,
        texto=texto,
        html=_documento(parrafos, _boton(enlace, "Activar mi cuenta"), pie),
        tags=("verificacion-alta",),
    )
    _registrar_envio("email_verification_email", email, enviado)
    return enviado


def send_existing_account_email(email: str, reset_token: str) -> bool:
    """«Ya tienes cuenta», con un enlace para (re)establecer la contraseña."""
    enlace = url_absoluta(f"/restablecer-contrasena#token={quote(reset_token)}")
    if enlace is None:
        log.error("email_verification_frontend_url_unavailable")
        return False
    parrafos = [
        "Hola:",
        "Alguien ha intentado crear una cuenta de TenderFlow con esta dirección, "
        "pero ya tienes una.",
        "Puedes entrar con Google o con tu contraseña. Si no la recuerdas, o si "
        "hasta ahora entrabas solo con Google, elige una nueva con este enlace. "
        f"Caduca en {_RESET_TTL_MINUTOS} minutos y sólo puede usarse una vez.",
    ]
    pie = "Si no has sido tú, ignora este correo: tu cuenta no ha cambiado."
    texto = "\n\n".join([*parrafos, enlace, pie, "— TenderFlow"])
    enviado = enviar_email_transaccional(
        to_addr=email,
        subject=_ASUNTO_YA_TIENES,
        texto=texto,
        html=_documento(parrafos, _boton(enlace, "Elegir contraseña"), pie),
        tags=("verificacion-alta",),
    )
    _registrar_envio("email_verification_existing_email", email, enviado)
    return enviado


def _registrar_envio(evento: str, email: str, enviado: bool) -> None:
    # El dominio y no la dirección, como en el resto del correo de producto.
    # `warning` si no salió: la persona ya leyó «revisa tu correo».
    dominio = email.rpartition("@")[2] or "desconocido"
    if enviado:
        log.info(evento, sent=True, domain=dominio)
    else:
        log.warning(evento, sent=False, domain=dominio)


def process_registration(email: str, password: str, display_name: str | None) -> None:
    """Atiende un alta cerrada ya respondida: escribe lo que toque y envía.

    Corre como tarea en segundo plano de ``POST /auth/register``, por el mismo
    motivo que el reset: la respuesta no puede distinguir por su latencia una
    cuenta nueva de una existente. El hash de la contraseña también va aquí:
    cuesta lo mismo en todas las ramas, pero hacerlo en línea alargaría la
    respuesta sin necesidad.

    **Nunca lanza.** La respuesta ya salió y no hay a quién devolver el error.
    """
    try:
        raw, digest, expires_at = issue_verification_token()
        estado, user_id = register_unverified(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name,
            token_hash=digest,
            expires_at=expires_at,
        )
        # Sin correo ni id, como el reset: el rastro dice qué pasó, no a quién.
        log_event(
            event_type=AUTH_SIGNUP_REQUESTED,
            outcome="success" if estado != "deactivated" else "failure",
            detail={"estado": estado},
        )
        log.info("register_closed_processed", estado=estado, user_id=user_id)
        if estado in ("created", "replaced"):
            send_verification_email(email, raw)
        elif estado == "verified" and user_id is not None:
            reset_raw = secrets.token_urlsafe(32)
            reset_expires = (datetime.now(UTC) + timedelta(minutes=_RESET_TTL_MINUTOS)).isoformat()
            if create_reset_token_for_user(user_id, token_hash(reset_raw), reset_expires):
                send_existing_account_email(email, reset_raw)
    except Exception:
        log.error("register_closed_failed", exc_info=True)
