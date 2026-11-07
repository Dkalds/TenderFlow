"""Settings de identidad y seguridad: OAuth, sesiones, MFA, API keys y claves de firma.

Módulo hermano de ``config/settings.py`` (P3 «Los dos módulos-dios»): ``Settings``
hereda de esta clase, así que los nombres de las variables de entorno y el
acceso (``settings.SIGNING_KEY``) son los de siempre. Las variables de Microsoft
Entra ID son funciones y no campos (ver ``oauth_microsoft_*``).

Sin ``model_config`` propio, por lo mismo que ``config/settings_resumen.py``.
"""

from __future__ import annotations

import os
from typing import Self

from pydantic import SecretStr, model_validator

from config.settings_entorno import EntornoSettings

# Longitud mínima de las claves que firman cosas en producción (``SIGNING_KEY``,
# ``AUDIT_HMAC_KEY``) y del secreto de origen (``API_ORIGIN_SECRET``). La usan los validators de ``Settings`` y, para el
# servidor MCP, ``mcp_server.servidor.validar_configuracion``: una sola cifra.
LONGITUD_MINIMA_CLAVE = 32


class AuthSettings(EntornoSettings):
    """OAuth, API keys, sesiones, MFA, secretos y claves que firman tokens y auditoría."""

    # ── Secrets ───────────────────────────────────────────────────────────
    # TTL (segundos) para el cache in-process de secretos. Tras expirar, el
    # próximo get_secret() re-consulta el backend (vault/env). Permite que la
    # rotación de secretos en vault se propague sin reiniciar el proceso.
    # 0 = sin cache (re-fetch siempre). Default 300s (5 min).
    SECRETS_CACHE_TTL_SECONDS: int = 300

    # ── OAuth ────────────────────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: SecretStr = SecretStr("")
    OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/oauth/google/callback"
    OAUTH_ALLOWED_EMAILS: str = ""
    OAUTH_ALLOWED_DOMAINS: str = ""
    OAUTH_ADMIN_EMAILS: str = ""

    # Secreto HMAC para hashear API keys (32+ chars). Si vacío usa SHA-256 plain.
    # Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"
    API_HMAC_SECRET: SecretStr = SecretStr("")
    # Las API keys nuevas son de mínimo privilegio y tienen caducidad. La
    # creación de una key con ``*`` debe ser una decisión explícita de un admin.
    API_KEY_DEFAULT_SCOPES: str = "data:read"
    API_KEY_DEFAULT_TTL_DAYS: int = 90
    API_KEY_MAX_TTL_DAYS: int = 365
    # Operaciones irreversibles requieren autenticación reciente; si la cuenta
    # usa MFA también se exige una elevación reciente de segundo factor.
    SENSITIVE_ACTION_MAX_AGE_SECONDS: int = 900
    MFA_STEP_UP_MAX_AGE_SECONDS: int = 900
    MFA_MAX_FAILURES: int = 5
    MFA_FAILURE_WINDOW_SECONDS: int = 300
    # Sesiones de navegador deslizantes (Ola 1). ``expires_at`` es el plazo de
    # inactividad: cada petición validada lo vuelve a poner en ``now + IDLE``,
    # nunca más allá del techo ``created_at + ABSOLUTE_DAYS``, pasado el cual la
    # sesión se rechaza aunque esté fresca. La tabla ``sessions`` no tiene
    # columna para «recordar este equipo»: ese login solo alarga la ventana de
    # inactividad a ``REMEMBER_DAYS``; el techo es el mismo (ver db/sessions.py).
    SESSION_IDLE_HOURS: int = 24
    SESSION_ABSOLUTE_DAYS: int = 30
    SESSION_REMEMBER_DAYS: int = 90
    # Las claves de idempotencia son datos de corta vida: no deben convertirse
    # en una caché permanente de respuestas ni secretos de integración.
    IDEMPOTENCY_TTL_SECONDS: int = 86_400

    # Clave independiente para firmar tokens CSRF/OAuth state (HMAC-SHA256).
    # Si no se configura, se deriva de GOOGLE_CLIENT_SECRET como fallback.
    # En producción configura un valor aleatorio de 32+ caracteres:
    #   python -c "import secrets; print(secrets.token_hex(32))"
    SIGNING_KEY: SecretStr = SecretStr("")
    # Firma independiente de la cadena de auditoría. No compartir con tokens.
    AUDIT_HMAC_KEY: SecretStr = SecretStr("")

    # Clave maestra para derivar secretos de webhook (HMAC-SHA256).
    # Si vacío, se deriva de SIGNING_KEY como fallback.
    # Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"
    WEBHOOK_SIGNING_KEY: SecretStr = SecretStr("")

    # Clave Fernet para cifrar secretos TOTP at-rest. Obligatoria en prod.
    # Genera una con: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    TOTP_ENCRYPTION_KEY: SecretStr = SecretStr("")

    # Alta ABIERTA a cualquier correo, sin verificar el buzón (el modo de dev y
    # de tests). Apagada, que es lo de producción, `POST /auth/register` solo
    # admite correos con el acceso concedido y la cuenta se activa con un enlace
    # al correo (RFC 2026-10-21-alta-con-contrasena-tras-concesion). En
    # prod/staging activarlo impide arrancar (`_validate_prod_closed_registration`).
    ALLOW_SELF_REGISTRATION: bool = False

    @model_validator(mode="after")
    def _validate_prod_signing_key(self) -> Self:
        if self._is_prod_data and self._firma_y_audita and not self.SIGNING_KEY.get_secret_value():
            raise ValueError(
                "SIGNING_KEY es obligatorio en ENV=prod con APP_PROFILE=api o mcp para firmar tokens CSRF/OAuth. "
                'Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        return self

    @model_validator(mode="after")
    def _validate_prod_webhook_signing_key(self) -> Self:
        """En producción, exigir WEBHOOK_SIGNING_KEY o SIGNING_KEY como fallback."""
        if self._is_prod_data and self._serves_http:
            wk = self.WEBHOOK_SIGNING_KEY.get_secret_value()
            sk = self.SIGNING_KEY.get_secret_value()
            if not wk and not sk:
                raise ValueError(
                    "WEBHOOK_SIGNING_KEY (o SIGNING_KEY como fallback) es obligatorio "
                    "en ENV=prod con APP_PROFILE=api para derivar secretos de webhook. "
                    'Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"'
                )
        return self

    @model_validator(mode="after")
    def _validate_prod_api_hmac_secret(self) -> Self:
        """En producción, exigir HMAC secret robusto para API keys."""
        if self._is_prod_data and self._serves_http:
            secret = self.API_HMAC_SECRET.get_secret_value()
            if not secret:
                raise ValueError(
                    "API_HMAC_SECRET es obligatorio en ENV=prod con APP_PROFILE=api para hashear API keys con HMAC. "
                    'Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"'
                )
            if len(secret) < 32:
                raise ValueError(
                    "API_HMAC_SECRET demasiado corto. Usa al menos 32 caracteres "
                    "(recomendado: secrets.token_hex(32))."
                )
        return self

    @model_validator(mode="after")
    def _validate_prod_audit_hmac_secret(self) -> Self:
        """db/audit.py solo lo usa el proceso API (login, exports, acciones admin) —
        el scraper/scheduler nunca llama a log_action/log_event, así que este
        validator sigue el gating de ``_firma_y_audita`` (``api`` y ``mcp``, que
        también escribe auditoría). Sin esto, el job diario de scraping
        (APP_PROFILE=scraper) no arranca."""
        if (
            self._is_prod_data
            and self._firma_y_audita
            and len(self.AUDIT_HMAC_KEY.get_secret_value()) < LONGITUD_MINIMA_CLAVE
        ):
            raise ValueError(
                f"AUDIT_HMAC_KEY ({LONGITUD_MINIMA_CLAVE}+ caracteres) es obligatorio en producción"
            )
        return self

    @model_validator(mode="after")
    def _validate_prod_signing_key_strength(self) -> Self:
        """En producción, exigir SIGNING_KEY con longitud mínima de 32 chars."""
        if self._is_prod_data and self._firma_y_audita:
            key = self.SIGNING_KEY.get_secret_value()
            if key and len(key) < LONGITUD_MINIMA_CLAVE:
                raise ValueError(
                    f"SIGNING_KEY demasiado corto. Usa al menos {LONGITUD_MINIMA_CLAVE} caracteres "
                    '(recomendado: python -c "import secrets; print(secrets.token_hex(32))").'
                )
        return self

    @model_validator(mode="after")
    def _validate_prod_oauth_domains(self) -> Self:
        """La allowlist estática puede quedar vacía cuando gobierna Postgres.

        ``oauth_email_allowed`` sólo permite el vacío en desarrollo. En
        producción/staging, el callback consulta ``access_grants`` y cualquier
        fallo de BD deniega el acceso. El comodín explícito sigue siendo la
        única forma de abrir OAuth a cualquier dominio.
        """
        return self

    @model_validator(mode="after")
    def _validate_prod_closed_registration(self) -> Self:
        """El alta abierta no existe fuera de dev: ``ALLOW_SELF_REGISTRATION`` falla el arranque.

        El modo abierto crea la cuenta verificada sin probar el buzón: quien
        registra primero la dirección de otro conserva contraseña y sesión
        cuando el titular entra después por Google, y recibe sus invitaciones.
        """
        if self.ALLOW_SELF_REGISTRATION and self.ENV in ("prod", "staging"):
            raise ValueError(
                "ALLOW_SELF_REGISTRATION no puede estar activo en ENV=prod/staging: "
                "el alta abierta no verifica el correo. Quítalo del entorno (el alta "
                "de producción es la cerrada, con concesión y enlace al buzón)."
            )
        return self


# ── ANCLA S1 — identidad y equipo (OIDC genérico, invitaciones) ───────────
#
# Microsoft Entra ID (D17: multi-tenant + allowlist por dominio). Van como
# variables de entorno leídas aquí y no como campos de `Settings` porque
# `Settings` es un modelo con ~200 campos que se instancia al importar
# `config`, y estas tres solo las mira el flujo de login: declararlas arriba
# obligaría a tocar la sección de OAuth que comparten otros streams.
#
# Vacío significa «Microsoft no está configurado»: `GET /auth/oauth/microsoft/
# authorize` responde 501 y la página de login no ofrece el botón, igual que
# hace Google con `GOOGLE_CLIENT_ID` vacío.


def oauth_microsoft_client_id() -> str:
    """``OAUTH_MICROSOFT_CLIENT_ID`` — id de aplicación registrado en Entra ID."""
    return os.environ.get("OAUTH_MICROSOFT_CLIENT_ID", "").strip()


def oauth_microsoft_client_secret() -> str:
    """``OAUTH_MICROSOFT_CLIENT_SECRET`` — secreto de cliente de esa aplicación."""
    return os.environ.get("OAUTH_MICROSOFT_CLIENT_SECRET", "").strip()


def oauth_microsoft_tenant() -> str:
    """``OAUTH_MICROSOFT_TENANT`` — tenant del documento de descubrimiento.

    Default ``common`` por D17: registro multi-tenant, y quién entra lo decide
    ``OAUTH_ALLOWED_DOMAINS`` + ``access_grants``, que ya existen y ya gobiernan
    el acceso por Google. Un valor concreto (GUID o dominio) restringe el login
    a un solo tenant, que es lo que querría un despliegue de un único cliente.
    """
    return os.environ.get("OAUTH_MICROSOFT_TENANT", "").strip() or "common"
