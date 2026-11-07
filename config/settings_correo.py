"""Settings del correo: alertas por SMTP y correo transaccional (``observability/mailer.py``).

Módulo hermano de ``config/settings.py`` (P3 «Los dos módulos-dios»): ``Settings``
hereda de esta clase, así que los nombres de las variables de entorno y el
acceso (``settings.EMAIL_BACKEND``) son los de siempre.

Sin ``model_config`` propio, por lo mismo que ``config/settings_resumen.py``.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import SecretStr, field_validator, model_validator

from config.settings_entorno import EntornoSettings


class CorreoSettings(EntornoSettings):
    """Destinatarios y cuenta SMTP de alertas, backend del ESP y remitente."""

    # ── Correo de alertas ─────────────────────────────────────────────────
    ALERT_EMAIL_TO: str = ""
    ALERT_SMTP_USER: str = ""
    ALERT_SMTP_PASSWORD: SecretStr = SecretStr("")
    ALERT_SMTP_HOST: str = "smtp.gmail.com"
    ALERT_SMTP_PORT: int = 587

    # ── Correo transaccional (observability/mailer.py) ───────────────────
    # Backend por el que sale TODO el correo (alertas, invitaciones, reset de
    # contraseña, digests). `smtp` reutiliza ALERT_SMTP_*; `resend` y
    # `postmark` hablan con el ESP por HTTPS con EMAIL_API_KEY; `console` solo
    # escribe al log (desarrollo y tests). Ver docs/runbooks/correo-transaccional.md.
    EMAIL_BACKEND: Literal["smtp", "resend", "postmark", "console"] = "smtp"
    # Remitente. Vacío → la cuenta SMTP (ALERT_SMTP_USER). Con un ESP tiene que
    # ser una dirección de un dominio verificado en el proveedor (SPF/DKIM).
    EMAIL_FROM: str = ""
    EMAIL_FROM_NAME: str = "TenderFlow"
    # Clave del ESP (Resend: API key; Postmark: Server API token). Solo se usa
    # con esos backends; observability/logging.py redacta su valor en los logs.
    EMAIL_API_KEY: SecretStr = SecretStr("")
    # Reply-To opcional para todo el correo (p. ej. un buzón de soporte).
    EMAIL_REPLY_TO: str = ""

    @field_validator("ALERT_SMTP_PORT", mode="before")
    @classmethod
    def _validate_smtp_port(cls, v: object) -> int:
        val = int(str(v))
        if not (1 <= val <= 65535):
            raise ValueError("ALERT_SMTP_PORT debe estar entre 1 y 65535")
        return val

    @model_validator(mode="after")
    def _validate_prod_smtp_password(self) -> Self:
        """En producción, exigir SMTP password si hay destinatarios de alertas.

        Aplica a todos los perfiles: el scraper y los workers también notifican.
        """
        if (
            self._is_prod_data
            and self.ALERT_EMAIL_TO
            and not self.ALERT_SMTP_PASSWORD.get_secret_value()
        ):
            raise ValueError(
                "ALERT_SMTP_PASSWORD es obligatorio cuando ALERT_EMAIL_TO está "
                "configurado en ENV=prod. Configura un app password de Gmail."
            )
        return self

    @model_validator(mode="after")
    def _validate_prod_email_backend(self) -> Self:
        """Con un ESP elegido en producción, la clave y el remitente no pueden faltar.

        Condicional al backend a propósito: con el default ``smtp`` el proceso
        arranca exactamente igual que antes, así que esta regla no convierte
        ninguna variable en obligatoria para el despliegue actual —y por eso
        ``scripts/check_env_parity.py``, que solo ve obligatoriedad
        incondicional, no la cuenta entre las que exige ``render.yaml``—. Quien
        cambie ``EMAIL_BACKEND`` a ``resend`` o ``postmark`` sí tiene que
        declarar las dos: un ESP sin clave no envía nada y un ESP con remitente
        vacío rechaza cada mensaje con un 4xx, y ambos fallos serían silenciosos
        porque el transporte nunca propaga. Aplica a todos los perfiles: el
        scraper y los workers también escriben correo.

        ``console`` no se admite en producción ni en staging: no envía nada y
        escribe el cuerpo de cada correo en el log. La recuperación de
        contraseña, la verificación del alta y los avisos dejaban de funcionar
        sin que nada fallara, y el log se llenaba de direcciones y enlaces que
        solo el redactor separaba de quien lo leyera. Es un backend de
        desarrollo, y desde 2026-10 el arranque lo dice.
        """
        if self._is_prod_data and self.EMAIL_BACKEND == "console":
            raise ValueError(
                f"EMAIL_BACKEND=console no se admite en ENV={self.ENV}: no envía ningún "
                "correo y escribe su cuerpo en el log. Usa smtp, resend o postmark "
                "(ver docs/runbooks/correo-transaccional.md)."
            )
        if self._is_prod_data and self.EMAIL_BACKEND in ("resend", "postmark"):
            faltan = [
                nombre
                for nombre, valor in (
                    ("EMAIL_API_KEY", self.EMAIL_API_KEY.get_secret_value()),
                    ("EMAIL_FROM", self.EMAIL_FROM),
                )
                if not valor.strip()
            ]
            if faltan:
                raise ValueError(
                    f"{' y '.join(faltan)}: obligatorio con EMAIL_BACKEND="
                    f"{self.EMAIL_BACKEND} en ENV={self.ENV}. El remitente debe ser una "
                    "dirección de un dominio verificado en el proveedor "
                    "(ver docs/runbooks/correo-transaccional.md)."
                )
        return self
