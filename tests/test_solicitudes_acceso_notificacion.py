"""Tests del cierre del embudo de acceso: a quién se avisa, cuándo y con qué.

Lo que fijan estos tests es el contrato que hacía falta arreglar: que la persona
que pide acceso recibe un correo **cuando el operador lo pide y no antes**, que
pulsar dos veces no le escribe dos veces, que un SMTP caído no convierte una
aprobación buena en un error, y que el aviso al operador no depende de que
exista un webhook configurado.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from api.app import app
from api.routes.dual_auth import require_any_auth
from observability.alerts import enviar_email_transaccional
from services.solicitudes_acceso import (
    avisar_operador_de_solicitud,
    notificar_acceso_concedido,
    url_de_login,
)

RUTA = "/api/v1/admin/solicitudes-acceso"


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    return TestClient(app)


def _admin():
    return {"user_id": 1, "email": "admin@test.com", "is_admin": True, "auth_method": "session"}


def _solicitud(**extra):
    base = {
        "id": 7,
        "email": "ana@empresa.example",
        "empresa": "Empresa SL",
        "mensaje": None,
        "origen": "landing",
        "estado": "pendiente",
        "created_at": None,
    }
    base.update(extra)
    return base


class TestUrlDeLogin:
    """De dónde sale el enlace del correo, sin inventar una variable nueva."""

    def test_usa_el_primer_origen_cors(self):
        fake = SimpleNamespace(
            CORS_ALLOWED_ORIGINS="https://app.tenderflow.example, https://otro.example",
            OAUTH_REDIRECT_URI="",
        )
        with patch("services.solicitudes_acceso.settings", fake):
            assert url_de_login() == "https://app.tenderflow.example/login"

    def test_cae_al_origen_del_callback_oauth(self):
        fake = SimpleNamespace(
            CORS_ALLOWED_ORIGINS="",
            OAUTH_REDIRECT_URI="https://app.example/api/v1/auth/oauth/google/callback",
        )
        with patch("services.solicitudes_acceso.settings", fake):
            assert url_de_login() == "https://app.example/login"

    def test_sin_configuracion_no_inventa_una_url(self):
        """Mejor un correo sin botón que un botón a ninguna parte."""
        fake = SimpleNamespace(CORS_ALLOWED_ORIGINS="", OAUTH_REDIRECT_URI="")
        with patch("services.solicitudes_acceso.settings", fake):
            assert url_de_login() is None


class TestCorreoDeAcceso:
    def test_envia_con_asunto_y_destinatario_correctos(self):
        with (
            patch(
                "services.solicitudes_acceso.url_de_login", return_value="https://x.example/login"
            ),
            patch(
                "services.solicitudes_acceso.enviar_email_transaccional", return_value=True
            ) as enviar,
        ):
            assert notificar_acceso_concedido(email="ana@empresa.example", empresa="Empresa SL")

        kwargs = enviar.call_args.kwargs
        assert kwargs["to_addr"] == "ana@empresa.example"
        assert "acceso" in kwargs["subject"].lower()
        # El enlace tiene que llegar en las dos partes del multipart: quien lee
        # en texto plano también necesita poder entrar.
        assert "https://x.example/login" in kwargs["texto"]
        assert "https://x.example/login" in kwargs["html"]

    def test_escapa_el_nombre_de_empresa_en_el_html(self):
        """`empresa` es texto que escribió un desconocido en un formulario público."""
        with (
            patch("services.solicitudes_acceso.url_de_login", return_value=None),
            patch(
                "services.solicitudes_acceso.enviar_email_transaccional", return_value=True
            ) as enviar,
        ):
            notificar_acceso_concedido(
                email="ana@empresa.example", empresa="<script>alert(1)</script>"
            )

        html_generado = enviar.call_args.kwargs["html"]
        assert "<script>" not in html_generado
        assert "&lt;script&gt;" in html_generado

    def test_un_smtp_caido_no_lanza(self):
        """La solicitud ya está marcada cuando esto corre: no puede reventar."""
        with (
            patch("services.solicitudes_acceso.url_de_login", return_value=None),
            patch("services.solicitudes_acceso.enviar_email_transaccional", return_value=False),
        ):
            assert notificar_acceso_concedido(email="ana@empresa.example") is False

    def test_no_registra_la_direccion_completa(self):
        """El email es dato personal: al log va el dominio, no la dirección."""
        with (
            patch("services.solicitudes_acceso.url_de_login", return_value=None),
            patch("services.solicitudes_acceso.enviar_email_transaccional", return_value=True),
            patch("services.solicitudes_acceso.log") as log,
        ):
            notificar_acceso_concedido(email="ana@empresa.example")

        registrado = log.info.call_args.kwargs
        assert registrado["dominio"] == "empresa.example"
        assert "ana@empresa.example" not in str(registrado)


class TestElTransporteTampocoRegistraLaDireccion:
    """La misma promesa, un nivel más abajo: en ``observability/alerts.py``.

    ``test_no_registra_la_direccion_completa`` mockea el transporte entero y solo
    mira el logger del servicio, así que no veía que ``_entregar_email``
    escribiera ``to=<dirección completa>`` en el log de producción. Para las
    alertas de operación eso es aceptable —el destinatario es ``ALERT_EMAIL_TO``,
    configuración— pero el mismo transporte escribe a personas físicas.
    """

    @staticmethod
    def _settings_smtp():
        return SimpleNamespace(
            ALERT_SMTP_USER="bot@tenderflow.example",
            ALERT_SMTP_PASSWORD=SimpleNamespace(get_secret_value=lambda: "clave-de-app"),
            ALERT_SMTP_HOST="smtp.example",
            ALERT_SMTP_PORT=587,
        )

    def test_el_correo_de_producto_registra_el_dominio(self):
        with (
            patch("config.settings", self._settings_smtp()),
            patch("smtplib.SMTP"),
            patch("observability.alerts.log") as log,
        ):
            enviado = enviar_email_transaccional(
                to_addr="ana@empresa.example",
                subject="Tu acceso ya está activo",
                texto="hola",
                html="<p>hola</p>",
            )

        assert enviado is True
        assert log.info.call_args.kwargs["to"] == "empresa.example"
        assert "ana@empresa.example" not in str(log.info.call_args)

    def test_las_alertas_de_operacion_siguen_registrando_su_buzon(self):
        """No es una regresión encubierta: el destinatario de una alerta es
        configuración del propio despliegue y saber a qué buzón salió es lo que
        hace diagnosticable un correo que no llega."""
        from observability.alerts import _entregar_email

        with (
            patch("config.settings", self._settings_smtp()),
            patch("smtplib.SMTP"),
            patch("observability.alerts.log") as log,
        ):
            _entregar_email(
                recipient="ops@tenderflow.example",
                subject="[TenderFlow] [WARN] algo",
                texto="x",
                html="<p>x</p>",
            )

        assert log.info.call_args.kwargs["to"] == "ops@tenderflow.example"


@pytest.fixture()
def _ventana_abierta():
    """Deja pasar la ventana de agrupación del aviso al operador.

    Sin esto los tests de este bloque compartirían el bucket global del limiter
    y el segundo en ejecutarse se agruparía: el resultado dependería del orden.
    """
    with patch("services.solicitudes_acceso._dentro_de_la_ventana_de_aviso", return_value=True):
        yield


class TestAvisoAlOperador:
    def test_no_propaga_si_el_canal_falla(self, _ventana_abierta):
        """Corre después de responderle al visitante: su alta ya está hecha."""
        with patch("services.solicitudes_acceso.notify", side_effect=RuntimeError("smtp")):
            assert (
                avisar_operador_de_solicitud(
                    solicitud_id=7, empresa="Empresa SL", origen="landing", pendientes=3
                )
                is False
            )

    def test_no_incluye_datos_de_contacto(self, _ventana_abierta):
        """El aviso dice que hay algo que atender, no quién lo pide."""
        with patch("services.solicitudes_acceso.notify") as notify:
            avisar_operador_de_solicitud(
                solicitud_id=7, empresa="Empresa SL", origen="landing", pendientes=3
            )

        enviado = str(notify.call_args)
        assert "@" not in enviado
        assert "Empresa SL" in enviado


class TestAgrupacionDelAviso:
    """El formulario que dispara esto es público, anónimo y sin captcha.

    ``notify`` no agrupa ni deduplica nada: valida el nivel y llama a SMTP. Un
    aviso por solicitud convertía el embudo en un amplificador de correo contra
    el único buzón remitente del proyecto —el mismo que envía las alertas de
    infraestructura—, con el único tope del bucket global del middleware (120/min
    por IP, y varias IPs sin tope).
    """

    @staticmethod
    def _avisar():
        return avisar_operador_de_solicitud(
            solicitud_id=7, empresa="Empresa SL", origen="landing", pendientes=3
        )

    def test_el_segundo_aviso_de_la_ventana_no_escribe(self):
        limiter = MagicMock()
        limiter.check.side_effect = [True, False]

        with (
            patch("services.rate_limiting.get_rate_limiter", return_value=limiter),
            patch("services.solicitudes_acceso.notify") as notify,
        ):
            primero = self._avisar()
            segundo = self._avisar()

        assert primero is True
        assert segundo is False
        assert notify.call_count == 1

    def test_la_clave_del_bucket_es_global_y_no_por_ip(self):
        """Con clave por IP el ataque queda intacto: basta rotar de origen.

        El recurso que se protege es el buzón del operador, que es uno solo.
        """
        limiter = MagicMock()
        limiter.check.return_value = True

        with (
            patch("services.rate_limiting.get_rate_limiter", return_value=limiter),
            patch("services.solicitudes_acceso.notify"),
        ):
            self._avisar()

        assert limiter.check.call_args.args[0] == "aviso_solicitudes"
        assert limiter.check.call_args.kwargs["max_calls"] == 1
        assert limiter.check.call_args.kwargs["window_seconds"] >= 600

    def test_un_limiter_caido_no_silencia_el_aviso(self):
        """El fallo que se acepta al degradar es el ruido, nunca el silencio."""
        limiter = MagicMock()
        limiter.check.side_effect = RuntimeError("backend caído")

        with (
            patch("services.rate_limiting.get_rate_limiter", return_value=limiter),
            patch("services.solicitudes_acceso.notify") as notify,
        ):
            assert self._avisar() is True

        notify.assert_called_once()


class TestPatchNotifica:
    def test_sin_notificar_no_lee_ni_escribe_a_nadie(self, client):
        """El comportamiento por defecto no cambia: nadie recibe un correo."""
        app.dependency_overrides[require_any_auth] = _admin
        try:
            with (
                patch("api.routes.admin_solicitudes.actualizar_estado", return_value=True),
                patch("api.routes.admin_solicitudes.log_event"),
                patch("api.routes.admin_solicitudes.obtener_solicitud") as obtener,
                patch("api.routes.admin_solicitudes.notificar_acceso_concedido") as avisar,
            ):
                resp = client.patch(f"{RUTA}/7", json={"estado": "atendida"})
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "notificado": None, "grant_id": None}
        obtener.assert_not_called()
        avisar.assert_not_called()

    def test_notifica_al_marcar_atendida(self, client):
        app.dependency_overrides[require_any_auth] = _admin
        try:
            with (
                patch("api.routes.admin_solicitudes.actualizar_estado", return_value=True),
                patch("api.routes.admin_solicitudes.log_event"),
                patch("api.routes.admin_solicitudes.obtener_solicitud", return_value=_solicitud()),
                patch(
                    "api.routes.admin_solicitudes.notificar_acceso_concedido", return_value=True
                ) as avisar,
            ):
                resp = client.patch(f"{RUTA}/7", json={"estado": "atendida", "notificar": True})
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["notificado"] is True
        assert avisar.call_args.kwargs == {
            "email": "ana@empresa.example",
            "empresa": "Empresa SL",
        }

    def test_no_reenvia_a_quien_ya_estaba_atendido(self, client):
        """Pulsar dos veces no puede escribirle dos veces a la misma persona."""
        app.dependency_overrides[require_any_auth] = _admin
        try:
            with (
                patch("api.routes.admin_solicitudes.actualizar_estado", return_value=True),
                patch("api.routes.admin_solicitudes.log_event"),
                patch(
                    "api.routes.admin_solicitudes.obtener_solicitud",
                    return_value=_solicitud(estado="atendida"),
                ),
                patch("api.routes.admin_solicitudes.notificar_acceso_concedido") as avisar,
            ):
                resp = client.patch(f"{RUTA}/7", json={"estado": "atendida", "notificar": True})
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["notificado"] is False
        avisar.assert_not_called()

    def test_descartar_nunca_escribe_aunque_se_pida(self, client):
        """Un descarte con `notificar` no puede felicitar a quien se rechaza."""
        app.dependency_overrides[require_any_auth] = _admin
        try:
            with (
                patch("api.routes.admin_solicitudes.actualizar_estado", return_value=True),
                patch("api.routes.admin_solicitudes.log_event"),
                patch("api.routes.admin_solicitudes.obtener_solicitud") as obtener,
                patch("api.routes.admin_solicitudes.notificar_acceso_concedido") as avisar,
            ):
                resp = client.patch(f"{RUTA}/7", json={"estado": "descartada", "notificar": True})
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["notificado"] is None
        obtener.assert_not_called()
        avisar.assert_not_called()

    def test_un_correo_que_no_sale_se_reporta(self, client):
        """El operador tiene que saber que no ha avisado a nadie."""
        app.dependency_overrides[require_any_auth] = _admin
        try:
            with (
                patch("api.routes.admin_solicitudes.actualizar_estado", return_value=True),
                patch("api.routes.admin_solicitudes.log_event"),
                patch("api.routes.admin_solicitudes.obtener_solicitud", return_value=_solicitud()),
                patch(
                    "api.routes.admin_solicitudes.notificar_acceso_concedido", return_value=False
                ),
            ):
                resp = client.patch(f"{RUTA}/7", json={"estado": "atendida", "notificar": True})
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["notificado"] is False
