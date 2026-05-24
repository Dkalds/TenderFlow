"""Abstracción de secretos con backends intercambiables.

Backends soportados (variable SECRETS_BACKEND):
  - ``env``              — leer de variables de entorno / .env (por defecto)
  - ``azure_keyvault``   — Azure KeyVault via azure-keyvault-secrets
  - ``aws_secretsmanager`` — AWS Secrets Manager via boto3

Uso::

    from config.secrets import get_secret

    db_password = get_secret("DATABASE_PASSWORD")
    api_key = get_secret("OPENAI_API_KEY")
"""

from __future__ import annotations

import os

from observability.logging import get_logger

log = get_logger(__name__)

_BACKEND = os.environ.get("SECRETS_BACKEND", "env").lower()
_AZURE_VAULT_URL = os.environ.get("AZURE_KEYVAULT_URL", "")
_AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")
_AWS_SECRET_PREFIX = os.environ.get("AWS_SECRET_PREFIX", "licitaciones-sap/")

# In-process cache to avoid repeated external calls
_cache: dict[str, str | None] = {}


def _get_from_env(name: str) -> str | None:
    """Lee el secreto desde entorno/env file."""
    return os.environ.get(name)


def _get_from_azure(name: str) -> str | None:
    """Lee el secreto desde Azure KeyVault."""
    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found]
        from azure.keyvault.secrets import SecretClient  # type: ignore[import-not-found]

        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=_AZURE_VAULT_URL, credential=credential)
        # KeyVault names use hyphens, not underscores
        kv_name = name.replace("_", "-").lower()
        secret = client.get_secret(kv_name)
        return secret.value  # type: ignore[no-any-return]
    except ImportError:
        log.warning("azure_keyvault_not_installed", secret_name=name)
        return _get_from_env(name)
    except Exception as exc:
        log.warning("azure_keyvault_error", secret_name=name, error=str(exc))
        return _get_from_env(name)


def _get_from_aws(name: str) -> str | None:
    """Lee el secreto desde AWS Secrets Manager."""
    try:
        import boto3  # type: ignore[import-not-found]

        client = boto3.client("secretsmanager", region_name=_AWS_REGION)
        secret_id = f"{_AWS_SECRET_PREFIX}{name}"
        response = client.get_secret_value(SecretId=secret_id)
        return response.get("SecretString")  # type: ignore[no-any-return]
    except ImportError:
        log.warning("boto3_not_installed", secret_name=name)
        return _get_from_env(name)
    except Exception as exc:
        log.warning("aws_secretsmanager_error", secret_name=name, error=str(exc))
        return _get_from_env(name)


def get_secret(name: str, default: str | None = None) -> str | None:
    """Obtiene un secreto del backend configurado.

    Args:
        name:    Nombre del secreto (convención UPPER_SNAKE_CASE).
        default: Valor por defecto si el secreto no existe.

    Returns:
        El valor del secreto o ``default``.
    """
    if name in _cache:
        return _cache[name]

    value: str | None = None
    if _BACKEND == "azure_keyvault":
        value = _get_from_azure(name)
    elif _BACKEND == "aws_secretsmanager":
        value = _get_from_aws(name)
    else:
        value = _get_from_env(name)

    result = value if value is not None else default
    if result is not None:
        _cache[name] = result
    else:
        log.debug("secret_not_cached", secret_name=name, reason="resolved_to_none")
    return result


def clear_cache() -> None:
    """Limpia la cache de secretos (útil en tests o tras rotación)."""
    _cache.clear()


def rotate_secret(name: str, new_value: str) -> None:
    """Actualiza un secreto en el backend y limpia la cache local.

    Solo implementado para el backend ``env`` (actualiza os.environ).
    Para vault real, usar la CLI/SDK del proveedor.
    """
    if _BACKEND == "env":
        os.environ[name] = new_value
    _cache.pop(name, None)
    log.info("secret_rotated", name=name, backend=_BACKEND)
