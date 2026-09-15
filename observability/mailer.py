"""Transporte de correo del proyecto: un mensaje, varios backends.

Hasta 2026-09 todo el correo —alertas de operación, invitaciones, recuperación
de contraseña, digests de watchlist, avisos de acceso— salía por
``observability/alerts.py::_entregar_email`` con SMTP de Gmail y una
contraseña de aplicación. No había abstracción de proveedor, ningún mensaje
llevaba ``List-Unsubscribe`` y no existía forma de usar un ESP transaccional
con un remitente autenticado por dominio (SPF/DKIM/DMARC). Este módulo es esa
abstracción; ``alerts.py`` conserva su API pública y delega aquí.

Backends (``EMAIL_BACKEND``):

- ``smtp``     — el código SMTP que ya existía (STARTTLS, ``ALERT_SMTP_*``).
- ``resend``   — ``POST https://api.resend.com/emails`` con ``Bearer``.
- ``postmark`` — ``POST https://api.postmarkapp.com/email`` con
  ``X-Postmark-Server-Token``.
- ``console``  — escribe el correo al log estructurado; para desarrollo y tests.

Lo que hace por cada mensaje, sea cual sea el backend:

- Garantiza un par texto + HTML: si el llamante solo pasa HTML, deriva el
  texto plano (:func:`texto_desde_html`) conservando los enlaces. Ningún
  correo sale solo en HTML: es la señal de spam más barata de evitar.
- Con ``adjuntos`` monta un ``multipart/mixed`` por SMTP y manda el contenido
  en base64 por los dos ESP. Sin adjuntos el correo conserva la forma de
  siempre (``multipart/alternative``): cambiarla para todo el mundo por una
  funcionalidad que la mayoría de los correos no usa sería riesgo gratis.
- Con ``unsubscribe_url`` añade ``List-Unsubscribe: <url>`` y
  ``List-Unsubscribe-Post: List-Unsubscribe=One-Click`` (RFC 8058), que es lo
  que Gmail y Yahoo exigen a quien envía correo masivo desde 2024.
- Por SMTP fija ``Message-ID`` y ``Date``, que un relay no siempre añade. Por
  HTTP los pone el proveedor —son su identificador para rebotes y quejas— y
  por eso no se envían: un ESP que rechazara un ``Message-ID`` ajeno con un 422
  tumbaría todos los envíos por un encabezado que él mismo iba a poner.

Contrato de fallo: **nunca propaga**. Igual que ``_entregar_email`` antes,
devuelve un :class:`ResultadoEnvio` y quien llama decide qué registrar. No hay
reintentos aquí: los digests y los webhooks tienen los suyos.

El secreto del proveedor viaja en un encabezado y nunca en la URL ni en los
logs; ``observability/logging.py`` redacta además el valor de
``EMAIL_API_KEY`` allá donde aparezca.
"""

from __future__ import annotations

import base64
import json
import re
import smtplib
from collections.abc import Mapping
from dataclasses import dataclass, field
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from html.parser import HTMLParser
from typing import Any

import requests

from observability.logging import get_logger
from shared.outbound_http import pinned_https_request

log = get_logger(__name__)

_TIMEOUT_SEGUNDOS = 15.0
_RESEND_URL = "https://api.resend.com/emails"
_RESEND_HOST = "api.resend.com"
_POSTMARK_URL = "https://api.postmarkapp.com/email"
_POSTMARK_HOST = "api.postmarkapp.com"
_USER_AGENT = "TenderFlow-mailer/1.0"
#: Cuánto del cuerpo de error de un proveedor se conserva en ``ResultadoEnvio``.
_MAX_ERROR_PROVEEDOR = 300
#: Resend solo admite ASCII alfanumérico, guion y guion bajo en las etiquetas.
_TAG_RESEND_RE = re.compile(r"[^A-Za-z0-9_-]+")


#: Tope del conjunto de adjuntos de un mensaje, antes de base64.
#:
#: Existe porque los dos backends HTTP meten el contenido **dentro del JSON**
#: de la petición, codificado en base64 —que infla un tercio—, y el límite del
#: proveedor es sobre la petición entera. Sin tope, un informe de una
#: organización grande hace que el ESP rechace la llamada con un 4xx y el
#: destinatario pierde **también el cuerpo**, no sólo el adjunto.
#:
#: 8 MiB deja el JSON en ~11 MiB, por debajo de los límites de Resend y
#: Postmark con margen. Al pasarse se manda el correo **sin** adjuntos en vez
#: de no mandarlo: el informe tiene las mismas tablas en HTML.
_MAX_ADJUNTOS_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class Adjunto:
    """Un fichero que viaja con el correo.

    Existe desde 2026-09-15 porque los informes programados (T6) lo necesitan:
    hasta entonces el transporte montaba un ``MIMEMultipart("alternative")`` y
    no había forma de adjuntar nada, ni por SMTP ni por los dos ESP. Se dejó
    sin hacer a propósito mientras no hubo consumidor
    (`docs/plans/2026-09-ola2-migraciones-propuestas.md` §T6); ahora lo hay.

    ``contenido`` son bytes y no una ruta: quien genera el PDF lo tiene en
    memoria, y hacerle escribir un fichero temporal sólo para que el mailer lo
    vuelva a leer añadiría un modo de fallo (disco lleno, permisos) a un camino
    que no lo tenía.
    """

    filename: str
    contenido: bytes
    content_type: str = "application/pdf"

    @property
    def tamano(self) -> int:
        return len(self.contenido)


@dataclass(frozen=True)
class Mensaje:
    """Un correo tal y como lo describe el llamante, sin decisiones de transporte.

    ``text`` y ``html`` son opcionales por separado pero no a la vez; si falta
    ``text`` se deriva del HTML. ``headers`` son encabezados adicionales del
    llamante (se envían tal cual); ``tags`` son etiquetas para la analítica del
    proveedor (Resend admite varias, Postmark una). ``unsubscribe_url`` es la
    URL de baja: si viene, el correo lleva los encabezados de RFC 8058.
    """

    to: str
    subject: str
    text: str | None = None
    html: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    reply_to: str | None = None
    unsubscribe_url: str | None = None
    adjuntos: list[Adjunto] = field(default_factory=list)


@dataclass(frozen=True)
class ResultadoEnvio:
    """Qué pasó con un envío. ``motivo`` es la categoría corta para métricas.

    Valores de ``motivo``: ``not_configured`` (faltan credenciales o remitente),
    ``invalid`` (el mensaje no es enviable: sin destinatario o sin cuerpo),
    ``smtp`` (el servidor SMTP rechazó algo), ``network`` (no se pudo hablar
    con el transporte), ``provider`` (el ESP respondió con error). ``None``
    cuando ``ok``.
    """

    ok: bool
    provider_id: str | None = None
    error: str | None = None
    backend: str = ""
    motivo: str | None = None


@dataclass(frozen=True)
class _Preparado:
    """El mensaje ya normalizado: remitente resuelto, texto garantizado, encabezados."""

    to: str
    subject: str
    text: str
    html: str | None
    from_addr: str
    from_header: str
    reply_to: str | None
    headers: dict[str, str]
    tags: list[str]
    message_id: str
    adjuntos: list[Adjunto]


# ── Texto plano a partir de HTML ─────────────────────────────────────────────

_ETIQUETAS_BLOQUE = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "ul",
        "ol",
        "blockquote",
        "section",
        "article",
        "header",
        "footer",
        "hr",
        "pre",
    }
)
_ETIQUETAS_OMITIDAS = frozenset({"style", "script", "head", "title"})


class _ExtractorTexto(HTMLParser):
    """Convierte HTML en texto legible: bloques → saltos, enlaces → «texto (url)»."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._partes: list[str] = []
        self._omitiendo = 0
        self._href: str | None = None
        self._texto_enlace: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _ETIQUETAS_OMITIDAS:
            self._omitiendo += 1
            return
        if self._omitiendo:
            return
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._texto_enlace = []
        if tag in _ETIQUETAS_BLOQUE:
            self._partes.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _ETIQUETAS_OMITIDAS:
            self._omitiendo = max(0, self._omitiendo - 1)
            return
        if self._omitiendo:
            return
        if tag == "a" and self._href is not None:
            etiqueta = " ".join("".join(self._texto_enlace).split())
            href = self._href.strip()
            if href and etiqueta and etiqueta != href and not href.startswith("#"):
                self._partes.append(f"{etiqueta} ({href})")
            else:
                self._partes.append(etiqueta or href)
            self._href = None
            self._texto_enlace = []
        if tag in _ETIQUETAS_BLOQUE:
            self._partes.append("\n")

    def handle_data(self, data: str) -> None:
        if self._omitiendo:
            return
        if self._href is not None:
            self._texto_enlace.append(data)
        else:
            self._partes.append(data)

    def texto(self) -> str:
        crudo = "".join(self._partes)
        lineas = [" ".join(linea.split()) for linea in crudo.splitlines()]
        # Colapsa las líneas en blanco consecutivas a una sola.
        salida: list[str] = []
        for linea in lineas:
            if not linea and salida and not salida[-1]:
                continue
            salida.append(linea)
        return "\n".join(salida).strip() + "\n"


def texto_desde_html(html: str) -> str:
    """Alternativa en texto plano de un cuerpo HTML, conservando los enlaces.

    No pretende ser una conversión fiel: sirve para que ningún correo salga
    solo en HTML y para que quien lea en texto pueda seguir los enlaces.
    """
    extractor = _ExtractorTexto()
    extractor.feed(html)
    extractor.close()
    return extractor.texto()


# ── Normalización ────────────────────────────────────────────────────────────


def _remitente(settings: Any) -> tuple[str, str]:
    """``(dirección, encabezado From)``. ``EMAIL_FROM`` cae al usuario SMTP."""
    direccion = (settings.EMAIL_FROM or "").strip() or (settings.ALERT_SMTP_USER or "").strip()
    nombre = (settings.EMAIL_FROM_NAME or "").strip()
    if not direccion:
        return "", ""
    return direccion, (formataddr((nombre, direccion)) if nombre else direccion)


def _normalizar(mensaje: Mensaje, settings: Any) -> _Preparado | ResultadoEnvio:
    """Aplica las garantías comunes a todos los backends o explica por qué no puede."""
    destino = mensaje.to.strip()
    backend = str(settings.EMAIL_BACKEND)
    if not destino:
        return ResultadoEnvio(ok=False, error="sin destinatario", backend=backend, motivo="invalid")
    html = mensaje.html if mensaje.html and mensaje.html.strip() else None
    texto = mensaje.text if mensaje.text and mensaje.text.strip() else None
    if texto is None and html is not None:
        texto = texto_desde_html(html)
    if texto is None:
        return ResultadoEnvio(ok=False, error="sin cuerpo", backend=backend, motivo="invalid")

    from_addr, from_header = _remitente(settings)
    dominio = from_addr.rpartition("@")[2] or None
    message_id = make_msgid(domain=dominio)

    headers = dict(mensaje.headers)
    if mensaje.unsubscribe_url:
        headers["List-Unsubscribe"] = f"<{mensaje.unsubscribe_url}>"
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    reply_to = (mensaje.reply_to or settings.EMAIL_REPLY_TO or "").strip() or None

    # Un adjunto sin bytes o sin nombre no es un adjunto: por SMTP sale como
    # una parte vacía y por HTTP lo rechaza el ESP con un 422 que tumbaría el
    # correo entero por algo que no aporta nada.
    adjuntos = [a for a in mensaje.adjuntos if a.contenido and a.filename.strip()]
    if sum(a.tamano for a in adjuntos) > _MAX_ADJUNTOS_BYTES:
        # Se manda sin adjuntos, no se deja de mandar: el cuerpo lleva la misma
        # información y perderlo entero por el peso del PDF sería cambiar un
        # problema pequeño por uno grande. Queda en el log porque «el informe
        # llegó sin PDF» es una pregunta que alguien hará.
        log.warning(
            "correo_adjuntos_demasiado_grandes",
            to=destino[:64],
            bytes=sum(a.tamano for a in adjuntos),
            tope=_MAX_ADJUNTOS_BYTES,
        )
        adjuntos = []

    return _Preparado(
        to=destino,
        subject=mensaje.subject,
        text=texto,
        html=html,
        from_addr=from_addr,
        from_header=from_header,
        reply_to=reply_to,
        headers=headers,
        tags=[t for t in mensaje.tags if t],
        message_id=message_id,
        adjuntos=adjuntos,
    )


def _no_configurado(backend: str, faltan: list[str]) -> ResultadoEnvio:
    log.debug("mailer_not_configured", backend=backend, missing=faltan)
    return ResultadoEnvio(
        ok=False,
        error=f"faltan {', '.join(faltan)}",
        backend=backend,
        motivo="not_configured",
    )


# ── Backend SMTP ─────────────────────────────────────────────────────────────


def _construir_mime(prep: _Preparado) -> MIMEMultipart:
    """El árbol MIME: ``alternative`` a secas, o ``mixed`` envolviéndolo.

    Sin adjuntos se conserva el mensaje de siempre —``multipart/alternative``
    con texto y HTML— porque cambiar la forma del correo que ya sale a
    producción por una funcionalidad que ese correo no usa es riesgo gratis.

    Con adjuntos, el `alternative` pasa a ser la **primera parte** de un
    ``multipart/mixed``. El orden importa y es la trampa clásica: colgar el
    texto, el HTML y el PDF como tres hermanos de un `mixed` hace que el
    cliente enseñe el texto plano *y* el HTML uno detrás de otro, en vez de
    elegir. Las alternativas van juntas dentro de su propio contenedor.
    """
    cuerpo = MIMEMultipart("alternative")
    cuerpo.attach(MIMEText(prep.text, "plain", "utf-8"))
    if prep.html is not None:
        cuerpo.attach(MIMEText(prep.html, "html", "utf-8"))

    if prep.adjuntos:
        msg = MIMEMultipart("mixed")
        msg.attach(cuerpo)
        for adjunto in prep.adjuntos:
            # `MIMEBase` y no `MIMEApplication`: aquél sólo acepta el subtipo y
            # clava `application/` como maintype, así que un `text/csv` salía
            # por SMTP como `application/csv` mientras los dos ESP lo mandaban
            # bien. El mismo correo con dos formas según el backend es
            # exactamente lo que este módulo existe para no tener.
            maintype, _, subtipo = adjunto.content_type.partition("/")
            parte = MIMEBase(maintype or "application", subtipo or "octet-stream")
            parte.set_payload(adjunto.contenido)
            encoders.encode_base64(parte)
            parte.add_header("Content-Disposition", "attachment", filename=adjunto.filename)
            msg.attach(parte)
    else:
        msg = cuerpo

    msg["Subject"] = prep.subject
    msg["From"] = prep.from_header
    msg["To"] = prep.to
    msg["Date"] = formatdate(usegmt=True)
    msg["Message-ID"] = prep.message_id
    if prep.reply_to:
        msg["Reply-To"] = prep.reply_to
    for nombre, valor in prep.headers.items():
        msg[nombre] = valor
    return msg


def _enviar_smtp(prep: _Preparado, settings: Any) -> ResultadoEnvio:
    """SMTP con STARTTLS: el transporte que ya existía, movido aquí sin cambios."""
    user = (settings.ALERT_SMTP_USER or "").strip()
    password = settings.ALERT_SMTP_PASSWORD.get_secret_value().strip()
    host = (settings.ALERT_SMTP_HOST or "").strip()
    port = int(settings.ALERT_SMTP_PORT)

    faltan = [k for k, v in (("ALERT_SMTP_USER", user), ("ALERT_SMTP_PASSWORD", password)) if not v]
    if faltan:
        return _no_configurado("smtp", faltan)

    # Sin EMAIL_FROM el remitente es la cuenta SMTP, como siempre fue. Gmail
    # reescribe el From a la cuenta autenticada salvo que sea un alias
    # verificado: por eso EMAIL_FROM solo tiene sentido pleno con un ESP.
    envelope_from = prep.from_addr or user
    msg = _construir_mime(prep)
    try:
        with smtplib.SMTP(host, port, timeout=int(_TIMEOUT_SEGUNDOS)) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.sendmail(envelope_from, [prep.to], msg.as_string())
    except smtplib.SMTPException as exc:
        return ResultadoEnvio(ok=False, error=str(exc), backend="smtp", motivo="smtp")
    except OSError as exc:
        return ResultadoEnvio(ok=False, error=str(exc), backend="smtp", motivo="network")
    return ResultadoEnvio(ok=True, provider_id=prep.message_id, backend="smtp")


# ── Backends HTTP (ESP) ──────────────────────────────────────────────────────


def _post_json(
    url: str,
    *,
    host: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
) -> tuple[int, bytes]:
    """Un POST JSON con DNS fijado, TLS verificado y sin redirecciones.

    Reutiliza :func:`shared.outbound_http.pinned_https_request` con una
    allowlist de un solo host: el mismo camino que ya recorren los webhooks y
    la descarga de pliegos, para no tener una tercera implementación de HTTP
    saliente con sus propias reglas.
    """
    cuerpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
        **headers,
    }
    with pinned_https_request(
        "POST",
        url,
        headers=request_headers,
        body=cuerpo,
        timeout_seconds=_TIMEOUT_SEGUNDOS,
        allowed_hosts=frozenset({host}),
    ) as respuesta:
        datos = b"".join(respuesta.iter_content())
        return respuesta.status_code, datos


def _json_o_vacio(datos: bytes) -> dict[str, Any]:
    try:
        decodificado = json.loads(datos.decode("utf-8", errors="replace"))
    except ValueError:
        return {}
    return decodificado if isinstance(decodificado, dict) else {}


def _error_proveedor(backend: str, status: int, cuerpo: dict[str, Any], campo: str) -> str:
    detalle = str(cuerpo.get(campo) or "")[:_MAX_ERROR_PROVEEDOR]
    return f"{backend} HTTP {status}" + (f": {detalle}" if detalle else "")


def _clave_api(settings: Any) -> str:
    return str(settings.EMAIL_API_KEY.get_secret_value()).strip()


def _faltan_para_esp(prep: _Preparado, settings: Any) -> list[str]:
    faltan: list[str] = []
    if not _clave_api(settings):
        faltan.append("EMAIL_API_KEY")
    if not prep.from_addr:
        faltan.append("EMAIL_FROM")
    return faltan


def _enviar_resend(prep: _Preparado, settings: Any) -> ResultadoEnvio:
    """https://resend.com/docs/api-reference/emails/send-email"""
    faltan = _faltan_para_esp(prep, settings)
    if faltan:
        return _no_configurado("resend", faltan)

    payload: dict[str, Any] = {
        "from": prep.from_header,
        "to": [prep.to],
        "subject": prep.subject,
        "text": prep.text,
    }
    if prep.html is not None:
        payload["html"] = prep.html
    if prep.headers:
        payload["headers"] = dict(prep.headers)
    if prep.reply_to:
        payload["reply_to"] = prep.reply_to
    if prep.tags:
        payload["tags"] = [
            {"name": "category", "value": _TAG_RESEND_RE.sub("-", tag)} for tag in prep.tags
        ]
    if prep.adjuntos:
        # Resend quiere el contenido en base64 dentro del JSON; no hay subida
        # aparte. Ése es el motivo de `_MAX_ADJUNTOS_BYTES`: base64 infla un
        # tercio y el límite del proveedor es sobre la petición entera.
        payload["attachments"] = [
            {
                "filename": a.filename,
                "content": base64.b64encode(a.contenido).decode("ascii"),
                "content_type": a.content_type,
            }
            for a in prep.adjuntos
        ]

    try:
        status, datos = _post_json(
            _RESEND_URL,
            host=_RESEND_HOST,
            headers={"Authorization": f"Bearer {_clave_api(settings)}"},
            payload=payload,
        )
    except (requests.RequestException, ValueError, OSError) as exc:
        return ResultadoEnvio(ok=False, error=str(exc), backend="resend", motivo="network")

    cuerpo = _json_o_vacio(datos)
    if not 200 <= status < 300:
        return ResultadoEnvio(
            ok=False,
            error=_error_proveedor("resend", status, cuerpo, "message"),
            backend="resend",
            motivo="provider",
        )
    return ResultadoEnvio(
        ok=True, provider_id=str(cuerpo.get("id") or "") or None, backend="resend"
    )


def _enviar_postmark(prep: _Preparado, settings: Any) -> ResultadoEnvio:
    """https://postmarkapp.com/developer/api/email-api"""
    faltan = _faltan_para_esp(prep, settings)
    if faltan:
        return _no_configurado("postmark", faltan)

    payload: dict[str, Any] = {
        "From": prep.from_header,
        "To": prep.to,
        "Subject": prep.subject,
        "TextBody": prep.text,
    }
    if prep.html is not None:
        payload["HtmlBody"] = prep.html
    if prep.headers:
        payload["Headers"] = [{"Name": k, "Value": v} for k, v in prep.headers.items()]
    if prep.reply_to:
        payload["ReplyTo"] = prep.reply_to
    if prep.tags:
        payload["Tag"] = prep.tags[0]
    if prep.adjuntos:
        payload["Attachments"] = [
            {
                "Name": a.filename,
                "Content": base64.b64encode(a.contenido).decode("ascii"),
                "ContentType": a.content_type,
            }
            for a in prep.adjuntos
        ]

    try:
        status, datos = _post_json(
            _POSTMARK_URL,
            host=_POSTMARK_HOST,
            headers={"X-Postmark-Server-Token": _clave_api(settings)},
            payload=payload,
        )
    except (requests.RequestException, ValueError, OSError) as exc:
        return ResultadoEnvio(ok=False, error=str(exc), backend="postmark", motivo="network")

    cuerpo = _json_o_vacio(datos)
    # Postmark responde 200 con ErrorCode 0; cualquier otro código es un rechazo.
    if not 200 <= status < 300 or int(cuerpo.get("ErrorCode") or 0) != 0:
        return ResultadoEnvio(
            ok=False,
            error=_error_proveedor("postmark", status, cuerpo, "Message"),
            backend="postmark",
            motivo="provider",
        )
    return ResultadoEnvio(
        ok=True, provider_id=str(cuerpo.get("MessageID") or "") or None, backend="postmark"
    )


# ── Backend consola ──────────────────────────────────────────────────────────


def _enviar_console(prep: _Preparado) -> ResultadoEnvio:
    """No envía nada: deja el correo entero en el log. Para desarrollo y tests.

    Al log va el dominio del destinatario y no la dirección, igual que en el
    resto del proyecto; el cuerpo en texto sí, porque ver el enlace de un reset
    o de una invitación es justamente para lo que sirve este backend.
    """
    log.info(
        "mailer_console",
        to_dominio=prep.to.rpartition("@")[2] or "desconocido",
        subject=prep.subject,
        from_header=prep.from_header,
        reply_to=prep.reply_to,
        message_id=prep.message_id,
        headers=dict(prep.headers),
        tags=list(prep.tags),
        # Nombre y tamaño, no el contenido: un PDF en base64 en el log no lo
        # lee nadie y sí llena el disco de quien desarrolla.
        adjuntos=[f"{a.filename} ({a.tamano} B)" for a in prep.adjuntos],
        texto=prep.text,
    )
    return ResultadoEnvio(ok=True, provider_id=prep.message_id, backend="console")


# ── Punto de entrada ─────────────────────────────────────────────────────────


def enviar(mensaje: Mensaje) -> ResultadoEnvio:
    """Envía ``mensaje`` por el backend configurado. **Nunca lanza.**"""
    from config import settings

    preparado = _normalizar(mensaje, settings)
    if isinstance(preparado, ResultadoEnvio):
        log.warning("mailer_invalid_message", error=preparado.error)
        return preparado

    backend = str(settings.EMAIL_BACKEND)
    if backend == "smtp":
        resultado = _enviar_smtp(preparado, settings)
    elif backend == "resend":
        resultado = _enviar_resend(preparado, settings)
    elif backend == "postmark":
        resultado = _enviar_postmark(preparado, settings)
    elif backend == "console":
        resultado = _enviar_console(preparado)
    else:  # `Settings` ya lo impide con Literal; queda por si alguien parchea el singleton.
        resultado = ResultadoEnvio(
            ok=False,
            error=f"EMAIL_BACKEND desconocido: {backend!r}",
            backend=backend,
            motivo="not_configured",
        )

    if resultado.ok:
        log.debug(
            "mailer_sent",
            backend=resultado.backend,
            provider_id=resultado.provider_id,
            list_unsubscribe="List-Unsubscribe" in preparado.headers,
        )
    elif resultado.motivo != "not_configured":
        log.warning(
            "mailer_failed",
            backend=resultado.backend,
            motivo=resultado.motivo,
            error=resultado.error,
        )
    return resultado
