"""Transporte de correo (``observability/mailer.py``) y sus cuatro backends.

Sin red ni SMTP: se parchea el transporte HTTPS fijado (``pinned_https_request``)
y ``smtplib.SMTP``, y se mira lo que cada backend habría enviado. El
``settings`` que lee el mailer se sustituye por un ``SimpleNamespace`` con solo
los campos que usa, igual que hace ``tests/test_solicitudes_acceso_notificacion.py``.
"""

from __future__ import annotations

import email
import json
import warnings
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from pydantic import SecretStr

from observability import mailer
from observability.mailer import Mensaje, ResultadoEnvio, enviar, texto_desde_html

_HTML = (
    "<!DOCTYPE html><html><head><style>p{color:red}</style></head><body>"
    "<p>Hola <strong>Ana</strong>:</p>"
    '<p><a href="https://app.example/entrar?x=1">Entrar en TenderFlow</a></p>'
    "<script>alert(1)</script>"
    "<p>Hasta pronto &amp; gracias.</p></body></html>"
)


def _settings(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "EMAIL_BACKEND": "smtp",
        "EMAIL_FROM": "",
        "EMAIL_FROM_NAME": "TenderFlow",
        "EMAIL_REPLY_TO": "",
        "EMAIL_API_KEY": SecretStr(""),
        "ALERT_SMTP_USER": "bot@tenderflow.example",
        "ALERT_SMTP_PASSWORD": SecretStr("clave-de-app"),
        "ALERT_SMTP_HOST": "smtp.example",
        "ALERT_SMTP_PORT": 587,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture()
def ajustes(monkeypatch):
    """Sustituye ``config.settings`` por un namespace con los campos del mailer."""

    def _aplicar(**overrides: object) -> SimpleNamespace:
        ns = _settings(**overrides)
        monkeypatch.setattr("config.settings", ns)
        return ns

    return _aplicar


class _RespuestaFalsa:
    def __init__(self, status: int, cuerpo: bytes) -> None:
        self.status_code = status
        self._cuerpo = cuerpo

    def iter_content(self, chunk_size: int = 8192):
        yield self._cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


@pytest.fixture()
def transporte(monkeypatch):
    """Parchea ``pinned_https_request`` y devuelve la lista de llamadas capturadas."""
    llamadas: list[dict[str, object]] = []
    respuesta = {"status": 200, "cuerpo": b"{}"}

    def _falso(method, url, *, headers, body, timeout_seconds, allowed_hosts):
        llamadas.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": json.loads(body),
                "timeout": timeout_seconds,
                "allowed_hosts": allowed_hosts,
            }
        )
        return _RespuestaFalsa(int(respuesta["status"]), bytes(respuesta["cuerpo"]))

    monkeypatch.setattr(mailer, "pinned_https_request", _falso)

    def _responder(status: int, cuerpo: dict[str, object]) -> None:
        respuesta["status"] = status
        respuesta["cuerpo"] = json.dumps(cuerpo).encode()

    return SimpleNamespace(llamadas=llamadas, responder=_responder)


def _servidor_smtp() -> MagicMock:
    servidor = MagicMock()
    servidor.__enter__ = lambda s: s
    servidor.__exit__ = MagicMock(return_value=False)
    return servidor


def _mensaje_enviado(servidor: MagicMock) -> email.message.Message:
    _, args, _ = servidor.sendmail.mock_calls[0]
    return email.message_from_string(args[2])


# ── Texto plano desde HTML ───────────────────────────────────────────────────


def test_texto_desde_html_conserva_enlaces_y_separa_bloques() -> None:
    texto = texto_desde_html(_HTML)
    assert "Hola Ana:" in texto
    assert "Entrar en TenderFlow (https://app.example/entrar?x=1)" in texto
    assert "Hasta pronto & gracias." in texto
    # Cada párrafo en su línea; nada del <style> ni del <script>.
    assert texto.count("\n") >= 3
    assert "color:red" not in texto
    assert "alert(1)" not in texto


def test_texto_desde_html_no_repite_el_enlace_si_el_texto_ya_es_la_url() -> None:
    texto = texto_desde_html('<a href="https://x.example/a">https://x.example/a</a>')
    assert texto.strip() == "https://x.example/a"


# ── Normalización común ──────────────────────────────────────────────────────


def test_sin_destinatario_o_sin_cuerpo_es_invalid(ajustes) -> None:
    ajustes()
    with patch("smtplib.SMTP") as smtp:
        vacio = enviar(Mensaje(to="  ", subject="s", text="t"))
        sin_cuerpo = enviar(Mensaje(to="ana@example.com", subject="s"))
    smtp.assert_not_called()
    assert (vacio.ok, vacio.motivo) == (False, "invalid")
    assert (sin_cuerpo.ok, sin_cuerpo.motivo) == (False, "invalid")


# ── Backend SMTP ─────────────────────────────────────────────────────────────


def test_smtp_envia_texto_y_html_con_message_id_y_date(ajustes) -> None:
    ajustes(EMAIL_REPLY_TO="soporte@tenderflow.example")
    servidor = _servidor_smtp()
    with patch("smtplib.SMTP", return_value=servidor) as smtp:
        resultado = enviar(Mensaje(to="ana@example.com", subject="Hola", text="hola", html=_HTML))

    assert resultado.ok and resultado.backend == "smtp"
    smtp.assert_called_once_with("smtp.example", 587, timeout=15)
    servidor.starttls.assert_called_once()
    servidor.login.assert_called_once_with("bot@tenderflow.example", "clave-de-app")

    _, args, _ = servidor.sendmail.mock_calls[0]
    assert args[0] == "bot@tenderflow.example"  # sin EMAIL_FROM, el remitente es la cuenta
    assert args[1] == ["ana@example.com"]
    msg = _mensaje_enviado(servidor)
    assert msg["From"] == "TenderFlow <bot@tenderflow.example>"
    assert msg["To"] == "ana@example.com"
    assert msg["Reply-To"] == "soporte@tenderflow.example"
    assert msg["Message-ID"] and msg["Message-ID"].endswith("@tenderflow.example>")
    assert resultado.provider_id == msg["Message-ID"]
    assert msg["Date"]
    assert msg["List-Unsubscribe"] is None
    assert [p.get_content_type() for p in msg.get_payload()] == ["text/plain", "text/html"]


def test_smtp_deriva_el_texto_si_solo_llega_html(ajustes) -> None:
    ajustes()
    servidor = _servidor_smtp()
    with patch("smtplib.SMTP", return_value=servidor):
        assert enviar(Mensaje(to="ana@example.com", subject="Hola", html=_HTML)).ok
    partes = _mensaje_enviado(servidor).get_payload()
    assert partes[0].get_content_type() == "text/plain"
    assert "Entrar en TenderFlow (https://app.example/entrar?x=1)" in partes[0].get_payload(
        decode=True
    ).decode("utf-8")


def test_smtp_usa_email_from_como_remitente_y_sobre(ajustes) -> None:
    ajustes(EMAIL_FROM="no-reply@tenderflow.es", EMAIL_FROM_NAME="")
    servidor = _servidor_smtp()
    with patch("smtplib.SMTP", return_value=servidor):
        enviar(Mensaje(to="ana@example.com", subject="Hola", text="hola"))
    _, args, _ = servidor.sendmail.mock_calls[0]
    assert args[0] == "no-reply@tenderflow.es"
    assert _mensaje_enviado(servidor)["From"] == "no-reply@tenderflow.es"


def test_list_unsubscribe_cuando_hay_url_de_baja(ajustes) -> None:
    ajustes()
    servidor = _servidor_smtp()
    url = "https://app.example/api/v1/watchlist/rules/baja?k=abc&t=kid.sig"
    with patch("smtplib.SMTP", return_value=servidor):
        enviar(Mensaje(to="ana@example.com", subject="Digest", text="x", unsubscribe_url=url))
    msg = _mensaje_enviado(servidor)
    assert msg["List-Unsubscribe"] == f"<{url}>"
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_smtp_sin_credenciales_no_conecta(ajustes) -> None:
    ajustes(ALERT_SMTP_USER="", ALERT_SMTP_PASSWORD=SecretStr(""))
    with patch("smtplib.SMTP") as smtp:
        resultado = enviar(Mensaje(to="ana@example.com", subject="s", text="t"))
    smtp.assert_not_called()
    assert resultado == ResultadoEnvio(
        ok=False,
        error="faltan ALERT_SMTP_USER, ALERT_SMTP_PASSWORD",
        backend="smtp",
        motivo="not_configured",
    )


def test_smtp_errores_devuelven_resultado_y_no_lanzan(ajustes) -> None:
    import smtplib

    ajustes()
    servidor = _servidor_smtp()
    servidor.login.side_effect = smtplib.SMTPAuthenticationError(535, b"auth failed")
    with patch("smtplib.SMTP", return_value=servidor):
        rechazo = enviar(Mensaje(to="ana@example.com", subject="s", text="t"))
    with patch("smtplib.SMTP", side_effect=OSError("connection refused")):
        red = enviar(Mensaje(to="ana@example.com", subject="s", text="t"))
    assert (rechazo.ok, rechazo.motivo) == (False, "smtp")
    assert "auth failed" in (rechazo.error or "")
    assert (red.ok, red.motivo) == (False, "network")


# ── Backends HTTP (ESP) ──────────────────────────────────────────────────────


def test_resend_construye_la_peticion(ajustes, transporte) -> None:
    ajustes(
        EMAIL_BACKEND="resend",
        EMAIL_FROM="no-reply@tenderflow.es",
        EMAIL_API_KEY=SecretStr("re_secreto"),
        EMAIL_REPLY_TO="soporte@tenderflow.es",
    )
    transporte.responder(200, {"id": "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"})
    url = "https://app.example/api/v1/watchlist/rules/baja?k=abc&t=kid.sig"

    resultado = enviar(
        Mensaje(
            to="ana@example.com",
            subject="Digest",
            text="hola",
            html="<p>hola</p>",
            headers={"X-Entity-Ref-ID": "digest-1"},
            tags=["watchlist digest", "daily"],
            unsubscribe_url=url,
        )
    )

    assert resultado == ResultadoEnvio(
        ok=True, provider_id="49a3999c-0ce1-4ea6-ab68-afcd6dc2e794", backend="resend"
    )
    [llamada] = transporte.llamadas
    assert (llamada["method"], llamada["url"]) == ("POST", "https://api.resend.com/emails")
    assert llamada["allowed_hosts"] == frozenset({"api.resend.com"})
    assert llamada["timeout"] == 15.0
    cabeceras = llamada["headers"]
    assert cabeceras["Authorization"] == "Bearer re_secreto"
    assert cabeceras["Content-Type"] == "application/json"
    assert llamada["body"] == {
        "from": "TenderFlow <no-reply@tenderflow.es>",
        "to": ["ana@example.com"],
        "subject": "Digest",
        "text": "hola",
        "html": "<p>hola</p>",
        "headers": {
            "X-Entity-Ref-ID": "digest-1",
            "List-Unsubscribe": f"<{url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
        "reply_to": "soporte@tenderflow.es",
        # Resend solo admite [A-Za-z0-9_-] en las etiquetas.
        "tags": [
            {"name": "category", "value": "watchlist-digest"},
            {"name": "category", "value": "daily"},
        ],
    }


def test_postmark_construye_la_peticion(ajustes, transporte) -> None:
    ajustes(
        EMAIL_BACKEND="postmark",
        EMAIL_FROM="no-reply@tenderflow.es",
        EMAIL_API_KEY=SecretStr("pm-token"),
    )
    transporte.responder(
        200,
        {"To": "ana@example.com", "MessageID": "b7bc2f4a-e38e", "ErrorCode": 0, "Message": "OK"},
    )
    url = "https://app.example/api/v1/watchlist/rules/baja?k=abc&t=kid.sig"

    resultado = enviar(
        Mensaje(
            to="ana@example.com",
            subject="Digest",
            html="<p>hola <a href='https://x.example'>x</a></p>",
            tags=["watchlist-digest", "daily"],
            reply_to="ana-responde@tenderflow.es",
            unsubscribe_url=url,
        )
    )

    assert resultado == ResultadoEnvio(ok=True, provider_id="b7bc2f4a-e38e", backend="postmark")
    [llamada] = transporte.llamadas
    assert (llamada["method"], llamada["url"]) == ("POST", "https://api.postmarkapp.com/email")
    assert llamada["allowed_hosts"] == frozenset({"api.postmarkapp.com"})
    assert llamada["headers"]["X-Postmark-Server-Token"] == "pm-token"
    assert "Authorization" not in llamada["headers"]
    cuerpo = llamada["body"]
    assert cuerpo["From"] == "TenderFlow <no-reply@tenderflow.es>"
    assert cuerpo["To"] == "ana@example.com"
    assert cuerpo["Subject"] == "Digest"
    assert cuerpo["HtmlBody"] == "<p>hola <a href='https://x.example'>x</a></p>"
    assert cuerpo["TextBody"].strip() == "hola x (https://x.example)"  # derivado del HTML
    assert cuerpo["ReplyTo"] == "ana-responde@tenderflow.es"  # el del mensaje gana al global
    assert cuerpo["Tag"] == "watchlist-digest"  # Postmark admite una sola
    assert cuerpo["Headers"] == [
        {"Name": "List-Unsubscribe", "Value": f"<{url}>"},
        {"Name": "List-Unsubscribe-Post", "Value": "List-Unsubscribe=One-Click"},
    ]


@pytest.mark.parametrize("backend", ["resend", "postmark"])
def test_esp_sin_clave_ni_remitente_no_llama_al_transporte(ajustes, transporte, backend) -> None:
    ajustes(EMAIL_BACKEND=backend, EMAIL_FROM="", ALERT_SMTP_USER="", EMAIL_API_KEY=SecretStr(""))
    resultado = enviar(Mensaje(to="ana@example.com", subject="s", text="t"))
    assert transporte.llamadas == []
    assert (resultado.ok, resultado.backend, resultado.motivo) == (False, backend, "not_configured")
    assert resultado.error == "faltan EMAIL_API_KEY, EMAIL_FROM"


def test_resend_error_http_es_provider_con_el_mensaje_del_esp(ajustes, transporte) -> None:
    ajustes(EMAIL_BACKEND="resend", EMAIL_FROM="x@tenderflow.es", EMAIL_API_KEY=SecretStr("k"))
    transporte.responder(
        422, {"statusCode": 422, "name": "validation_error", "message": "Invalid `from` field"}
    )
    resultado = enviar(Mensaje(to="ana@example.com", subject="s", text="t"))
    assert (resultado.ok, resultado.motivo, resultado.provider_id) == (False, "provider", None)
    assert resultado.error == "resend HTTP 422: Invalid `from` field"


def test_postmark_errorcode_distinto_de_cero_es_fallo_aunque_responda_200(
    ajustes, transporte
) -> None:
    ajustes(EMAIL_BACKEND="postmark", EMAIL_FROM="x@tenderflow.es", EMAIL_API_KEY=SecretStr("k"))
    transporte.responder(200, {"ErrorCode": 300, "Message": "Invalid 'From' address"})
    resultado = enviar(Mensaje(to="ana@example.com", subject="s", text="t"))
    assert (resultado.ok, resultado.motivo) == (False, "provider")
    assert resultado.error == "postmark HTTP 200: Invalid 'From' address"


@pytest.mark.parametrize(
    "excepcion",
    [requests.RequestException("Pinned HTTPS request failed"), ValueError("DNS resolution failed")],
)
def test_esp_fallo_de_transporte_es_network_y_no_lanza(ajustes, monkeypatch, excepcion) -> None:
    ajustes(EMAIL_BACKEND="resend", EMAIL_FROM="x@tenderflow.es", EMAIL_API_KEY=SecretStr("k"))

    def _rompe(*_a: object, **_k: object):
        raise excepcion

    monkeypatch.setattr(mailer, "pinned_https_request", _rompe)
    resultado = enviar(Mensaje(to="ana@example.com", subject="s", text="t"))
    assert (resultado.ok, resultado.motivo) == (False, "network")
    assert str(excepcion) in (resultado.error or "")


def test_la_clave_del_esp_no_llega_al_resultado_ni_al_log(ajustes, transporte) -> None:
    clave = "re_super_secreta_1234"
    ajustes(EMAIL_BACKEND="resend", EMAIL_FROM="x@tenderflow.es", EMAIL_API_KEY=SecretStr(clave))
    transporte.responder(401, {"message": "API key is invalid"})
    with patch("observability.mailer.log") as log:
        resultado = enviar(Mensaje(to="ana@example.com", subject="s", text="t"))
    assert resultado.ok is False
    assert clave not in str(resultado)
    for llamada in log.method_calls:
        assert clave not in str(llamada)


# ── Backend consola ──────────────────────────────────────────────────────────


def test_console_escribe_al_log_sin_la_direccion_completa(ajustes) -> None:
    ajustes(EMAIL_BACKEND="console")
    with patch("observability.mailer.log") as log, patch("smtplib.SMTP") as smtp:
        resultado = enviar(
            Mensaje(
                to="ana@example.com",
                subject="Hola",
                text="cuerpo",
                unsubscribe_url="https://app.example/baja?k=1&t=2",
            )
        )
    smtp.assert_not_called()
    assert resultado.ok and resultado.backend == "console"
    assert resultado.provider_id and resultado.provider_id.startswith("<")
    evento, kwargs = log.info.call_args.args[0], log.info.call_args.kwargs
    assert evento == "mailer_console"
    assert kwargs["to_dominio"] == "example.com"
    assert kwargs["subject"] == "Hola"
    assert kwargs["texto"] == "cuerpo"
    assert kwargs["headers"]["List-Unsubscribe"] == "<https://app.example/baja?k=1&t=2>"
    assert "ana@example.com" not in str(kwargs)


# ── Settings: obligatoriedad condicional en producción ───────────────────────


def _settings_prod(**kwargs: object):
    from config.settings import Settings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Settings(
            ENV="prod",
            # Perfil sin HTTP: los validadores de SIGNING_KEY/HMAC/Redis no
            # aplican y el test mira solo la regla del correo, que es de todos
            # los perfiles. DATABASE_URL vacío para no heredar el de un .env.
            APP_PROFILE="worker",
            DATABASE_URL="",
            ALERT_EMAIL_TO="",
            **kwargs,
        )


@pytest.mark.parametrize("backend", ["resend", "postmark"])
def test_prod_con_esp_exige_clave_y_remitente(backend) -> None:
    with pytest.raises(ValueError, match="EMAIL_API_KEY y EMAIL_FROM"):
        _settings_prod(EMAIL_BACKEND=backend, EMAIL_API_KEY="", EMAIL_FROM="")
    with pytest.raises(ValueError, match="EMAIL_FROM: obligatorio"):
        _settings_prod(EMAIL_BACKEND=backend, EMAIL_API_KEY="k", EMAIL_FROM="")
    with pytest.raises(ValueError, match="EMAIL_API_KEY: obligatorio"):
        _settings_prod(EMAIL_BACKEND=backend, EMAIL_API_KEY="", EMAIL_FROM="x@tenderflow.es")
    s = _settings_prod(EMAIL_BACKEND=backend, EMAIL_API_KEY="k", EMAIL_FROM="x@tenderflow.es")
    assert backend == s.EMAIL_BACKEND


def test_prod_con_smtp_o_console_no_exige_la_clave_del_esp() -> None:
    assert _settings_prod(EMAIL_BACKEND="smtp", EMAIL_API_KEY="", EMAIL_FROM="").EMAIL_FROM == ""
    assert _settings_prod(EMAIL_BACKEND="console", EMAIL_API_KEY="").EMAIL_BACKEND == "console"


def test_dev_con_esp_sin_clave_arranca() -> None:
    from config.settings import Settings

    s = Settings(ENV="dev", EMAIL_BACKEND="resend", EMAIL_API_KEY="", EMAIL_FROM="")
    assert s.EMAIL_BACKEND == "resend"


def test_email_backend_solo_admite_los_cuatro_valores() -> None:
    from config.settings import Settings

    with pytest.raises(ValueError):
        Settings(ENV="dev", EMAIL_BACKEND="sendgrid")


# ── Integración con observability/alerts.py ──────────────────────────────────


def test_enviar_email_transaccional_propaga_la_url_de_baja_y_las_etiquetas() -> None:
    from observability.alerts import enviar_email_transaccional

    with patch(
        "observability.mailer.enviar",
        return_value=ResultadoEnvio(ok=True, provider_id="id-1", backend="console"),
    ) as envio:
        assert enviar_email_transaccional(
            to_addr="ana@example.com",
            subject="Digest",
            texto="t",
            html="<p>t</p>",
            unsubscribe_url="https://app.example/baja?k=1&t=2",
            tags=["watchlist-digest"],
        )
    [mensaje] = envio.call_args.args
    assert mensaje == Mensaje(
        to="ana@example.com",
        subject="Digest",
        text="t",
        html="<p>t</p>",
        tags=["watchlist-digest"],
        unsubscribe_url="https://app.example/baja?k=1&t=2",
    )


def test_entregar_email_cuenta_el_motivo_del_fallo_del_proveedor() -> None:
    from observability.alerts import _entregar_email

    with (
        patch(
            "observability.mailer.enviar",
            return_value=ResultadoEnvio(
                ok=False, error="resend HTTP 422", backend="resend", motivo="provider"
            ),
        ),
        patch("observability.alerts._contar_fallo_entrega") as contador,
        patch("observability.alerts.log") as log,
    ):
        assert (
            _entregar_email(recipient="ops@x.example", subject="s", texto="t", html="<p>t</p>")
            is False
        )
    contador.assert_called_once_with("provider")
    assert log.warning.call_args.args[0] == "alert_email_failed"
    assert log.warning.call_args.kwargs["motivo"] == "provider"


def test_el_digest_sale_con_su_url_de_baja_en_list_unsubscribe(tmp_db, monkeypatch) -> None:
    """La URL del pie del digest es la misma que va en el encabezado RFC 8058."""
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO watchlist_cpv (user_key, cpv_prefix, keyword, min_importe, ccaa, email, "
            "frequency, created_at) VALUES ('uk-baja-1', '48', NULL, NULL, NULL, "
            "'dest@example.com', 'daily', '2024-01-01')"
        )
        entry_id = c.execute("SELECT MAX(id) FROM watchlist_cpv").fetchone()[0]
        c.execute(
            "INSERT INTO pending_digests "
            "(user_key, recipient_email, entry_id, licitacion_id, frequency, matched_at) "
            "VALUES ('uk-baja-1', 'dest@example.com', %s, 'LIC-BAJA-01', 'daily', '2024-01-01')",
            (entry_id,),
        )

    monkeypatch.setattr("services.app_urls.frontend_base_url", lambda: "https://app.example")
    from scheduler.watchlist_alerts import send_pending_digests

    with patch("scheduler.watchlist_alerts.enviar_email_transaccional", return_value=True) as envio:
        assert send_pending_digests("daily") == 1

    kwargs = envio.call_args.kwargs
    url = kwargs["unsubscribe_url"]
    assert url is not None
    assert url.startswith("https://app.example/api/v1/watchlist/rules/baja?k=uk-baja-1&t=")
    assert url in kwargs["texto"]
    assert kwargs["tags"] == ["watchlist-digest"]
