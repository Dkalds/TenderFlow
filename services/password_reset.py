"""Emisión y entrega de enlaces de recuperación de contraseña, y aviso de cambio."""

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
from services.app_urls import url_absoluta
from services.email_html import CERRAR_DOCUMENTO, ESTILO_ENLACE, abrir_documento
from services.solicitudes_acceso import url_de_login
from shared.audit_events import AUTH_PASSWORD_RESET_REQUESTED

log = get_logger(__name__)

_RESET_TTL_MINUTES = 30
_SUBJECT = "Restablece tu contraseña de TenderFlow"
_ASUNTO_CAMBIADA = "Tu contraseña de TenderFlow ha cambiado"


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
        f'<p><a href="{html.escape(reset_url)}" style="{ESTILO_ENLACE}">'
        "Restablecer contraseña</a></p>"
        if reset_url
        else ""
    )
    html_body = (
        abrir_documento(max_ancho=600)
        + "<p>Se ha solicitado restablecer la contraseña de tu cuenta local de TenderFlow.</p>"
        "<p>El enlace caduca en 30 minutos y sólo puede usarse una vez.</p>"
        f"{link}<p>Si no lo solicitaste, ignora este correo.</p>" + CERRAR_DOCUMENTO
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


def send_password_changed_email(email: str) -> bool:
    """Avisa al titular de que su contraseña ha cambiado.

    Sale tras un reset y tras un cambio desde Ajustes: el único rastro era
    ``auth.password_reset_completed`` en el audit log, que el titular no ve, y
    quien cambia la contraseña de otro cuenta con que no se entere. No lleva
    ningún token —un enlace de reset aquí lo recibiría también quien acaba de
    quitarle la cuenta, si controla el buzón—, sino la pantalla donde se pide
    uno, y la fecha en UTC, sin IP ni navegador.
    """
    cuando = datetime.now(UTC).strftime("%d/%m/%Y a las %H:%M (UTC)")
    enlace = url_absoluta("/restablecer-contrasena")
    parrafos = [
        f"La contraseña de tu cuenta de TenderFlow se cambió el {cuando}.",
        "Si fuiste tú, no tienes que hacer nada. Las demás sesiones abiertas y "
        "tus claves de API han dejado de valer.",
        "Si no fuiste tú, pide ahora un enlace para elegir otra contraseña y "
        "revisa la verificación en dos pasos en Ajustes.",
    ]
    texto = "\n\n".join([*parrafos, *([enlace] if enlace else []), "— TenderFlow"])
    boton = (
        f'<p><a href="{html.escape(enlace)}" style="{ESTILO_ENLACE}">Elegir otra contraseña</a></p>'
        if enlace
        else ""
    )
    html_body = (
        abrir_documento(max_ancho=600)
        + "".join(f"<p>{html.escape(p)}</p>" for p in parrafos)
        + boton
        + CERRAR_DOCUMENTO
    )
    enviado = enviar_email_transaccional(
        to_addr=email,
        subject=_ASUNTO_CAMBIADA,
        texto=texto,
        html=html_body,
        tags=("contrasena-cambiada",),
    )
    domain = email.rpartition("@")[2] or "desconocido"
    if enviado:
        log.info("password_changed_email", sent=True, domain=domain)
    else:
        log.warning("password_changed_email", sent=False, domain=domain)
    return enviado


def notify_password_changed(user_id: int) -> None:
    """Tarea en segundo plano: busca el correo de la cuenta y envía el aviso.

    **Nunca lanza**, como ``process_password_reset_request``: la contraseña ya
    cambió y la respuesta ya salió. Si el aviso no sale queda en el log, sin el
    correo.
    """
    try:
        from db.users import get_user_by_id

        usuario = get_user_by_id(user_id)
        email = str((usuario or {}).get("email") or "")
        if not email:
            log.warning("password_changed_email", sent=False, reason="sin_correo")
            return
        send_password_changed_email(email)
    except Exception:
        log.error("password_changed_email_failed", exc_info=True)
