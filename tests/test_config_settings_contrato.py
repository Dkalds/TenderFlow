"""Contrato de ``Settings``: campos, defaults, tipos, validadores y exports.

``config/settings.py`` se partió en módulos por dominio (P3 «Los dos
módulos-dios»). La partición es un movimiento: cada variable de entorno sigue
llamándose igual, con el mismo tipo, el mismo default y los mismos validadores.
Este test lo fija contra ``tests/fixtures/settings_contrato.json``, una
instantánea tomada con el fichero único **antes** de partirlo.

Los nombres de las variables de entorno se derivan del nombre del campo, del
``model_config`` (prefijo y sensibilidad a mayúsculas) y de los alias; los tres
están en la instantánea, así que un cambio de nombre de variable la rompe.

Si cambias un setting a propósito, regenera la instantánea y revisa el diff::

    python -m tests.test_config_settings_contrato
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from pydantic import SecretStr

_INSTANTANEA = Path(__file__).parent / "fixtures" / "settings_contrato.json"

# Nombres que el repo importa de `config.settings` (grep de `from config.settings
# import` en todo el árbol, incluidos los privados que usa la suite).
_EXPORTS = (
    "JOBS_LOCK_TTL_SEGUNDOS_DEFAULT",
    "LONGITUD_MINIMA_CLAVE",
    "Settings",
    "_ADMIN_DB_URL_ENV",
    "_PERFILES_CON_CREDENCIAL_ADMIN",
    "_PERFIL_POR_DEFECTO",
    "_ROOT",
    "_origen_cors_seguro",
    "_redis_publico_sin_tls",
    "_settings",
    "database_admin_url",
    "ensure_data_dirs",
    "event_dispatch_enabled",
    "event_dispatch_max_age_hours",
    "jobs_backoff_base_segundos",
    "jobs_cierre_por_cola",
    "jobs_consumidor_en_api",
    "jobs_export_umbral_filas",
    "jobs_lock_ttl_segundos",
    "jobs_max_intentos",
    "jobs_worker_poll_segundos",
    "mcp_database_ssl_problema",
    "mcp_database_url",
    "mcp_google_redirect_uri",
    "mcp_public_url",
    "mcp_redirect_uris_extra",
    "oauth_microsoft_client_id",
    "oauth_microsoft_client_secret",
    "oauth_microsoft_tenant",
    "settings",
)


def _default(valor: object, raiz: Path) -> str:
    """Default legible y estable entre máquinas (las rutas, relativas al repo)."""
    if isinstance(valor, SecretStr):
        return f"SecretStr({valor.get_secret_value()!r})"
    if isinstance(valor, Path):
        try:
            return f"Path({valor.relative_to(raiz).as_posix()!r})"
        except ValueError:
            return f"Path({valor.as_posix()!r})"
    return repr(valor)


def _contrato() -> dict[str, object]:
    from config.settings import _ROOT, Settings

    decoradores = Settings.__pydantic_decorators__
    config = Settings.model_config
    return {
        "model_config": {
            clave: repr(config.get(clave))
            for clave in (
                "case_sensitive",
                "env_file",
                "env_file_encoding",
                "env_nested_delimiter",
                "env_prefix",
                "extra",
            )
        },
        "campos": {
            nombre: {
                "tipo": repr(campo.annotation),
                "default": _default(campo.default, _ROOT),
                "default_factory": repr(campo.default_factory),
                "alias": repr(campo.alias),
                "validation_alias": repr(campo.validation_alias),
                "metadata": repr(campo.metadata),
            }
            for nombre, campo in Settings.model_fields.items()
        },
        "field_validators": {
            nombre: {"campos": list(dec.info.fields), "mode": dec.info.mode}
            for nombre, dec in decoradores.field_validators.items()
        },
        "model_validators": {
            nombre: dec.info.mode for nombre, dec in decoradores.model_validators.items()
        },
    }


def test_contrato_de_settings_igual_a_la_instantanea() -> None:
    esperado = json.loads(_INSTANTANEA.read_text(encoding="utf-8"))
    actual = json.loads(json.dumps(_contrato()))
    assert actual["model_config"] == esperado["model_config"]
    assert set(actual["campos"]) == set(esperado["campos"]), "campos añadidos o retirados"
    for nombre, campo in esperado["campos"].items():
        assert actual["campos"][nombre] == campo, nombre
    assert actual["field_validators"] == esperado["field_validators"]
    assert actual["model_validators"] == esperado["model_validators"]


def test_config_settings_sigue_exportando_lo_que_importa_el_repo() -> None:
    # `import config.settings as m` daría el singleton: `config/__init__.py`
    # reexporta `settings` y tapa el submódulo como atributo del paquete.
    modulo = importlib.import_module("config.settings")
    faltan = [nombre for nombre in _EXPORTS if not hasattr(modulo, nombre)]
    assert not faltan


if __name__ == "__main__":
    _INSTANTANEA.write_text(
        json.dumps(_contrato(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    sys.stdout.write(f"instantánea escrita en {_INSTANTANEA}\n")
