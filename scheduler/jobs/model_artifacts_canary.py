"""Canary de los artefactos de modelo: lo registrado frente a lo publicado.

``model_versions`` dice qué versión de cada modelo está activa y con qué
sha256; las Releases de GitHub guardan los ficheros. Son dos sitios que se
escriben por separado, y cuando dejan de coincidir nadie puede servir el
modelo: ``shared.model_artifacts.resolve_active_artifact`` baja el asset, ve
que el hash no es el registrado y lanza ``ModelArtifactMismatch``.

Pasó el 2026-09-29. El paso semanal ``sap_active_learning`` reentrenó dentro
de un runner de ``scrape-daily`` y dejó activa una versión cuyo ``.pkl`` solo
existió en el disco de ese runner. La Release seguía publicando el
``sap_classifier.pkl`` de mayo, y ``ml_scoring`` cayó en cada pasada durante
cuatro días con un mensaje que decía qué hashes no cuadraban pero no por qué
ni qué hacer.

Este canary hace la misma comparación sin descargar nada —la API de Releases
ya trae el sha256 de cada asset— y sobre **todos** los modelos con versión
activa, no solo el que la pipeline diaria carga. Job ligero: una lectura de
BD y, si hay algo que comparar, tres peticiones a ``api.github.com``.
"""

from __future__ import annotations

from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

# Caracteres del sha256 que se enseñan en el resumen: el cuerpo de la alerta
# se corta a 500 caracteres (``_notify_step_failure``) y dos hashes enteros
# por modelo se lo comen. Los completos van en el log.
_SHA_CORTO = 12


def run() -> dict[str, Any]:
    """Coteja cada versión activa con el asset que publica la Release.

    Devuelve ``{"checked": n, "divergentes": [...], "sin_publicar": [...],
    "error": str | None}``. Las dos listas llevan un dict por versión:
    ``{name, version, asset, registrado, publicado, release}``.

    Un fallo leyendo las Releases no es un hallazgo: se reporta como ``error``
    y no marca ninguna versión (fail-open, igual que ``llm_models_canary``).
    """
    from db.model_registry import list_active
    from shared.model_artifacts import check_published_artifact, fetch_model_releases

    result: dict[str, Any] = {"checked": 0, "divergentes": [], "sin_publicar": [], "error": None}
    activas = list_active()
    if not activas:
        return result

    releases = fetch_model_releases()
    if not releases:
        log.warning("model_artifacts_canary_fetch_failed")
        result["error"] = "no se pudo leer ninguna Release del repositorio de modelos"
        return result

    for activa in activas:
        estado = check_published_artifact(activa, releases)
        result["checked"] += 1
        if estado.estado not in ("divergente", "sin_publicar"):
            continue
        hallazgo = {
            "name": activa["name"],
            "version": activa["version"],
            "asset": estado.asset,
            "registrado": estado.registrado,
            "publicado": estado.publicado,
            "release": estado.release,
        }
        # Nivel error a propósito: mientras dure, ningún proceso puede servir
        # la versión que el registro da por activa.
        if estado.estado == "divergente":
            result["divergentes"].append(hallazgo)
            log.error("model_artifacts_canary_divergente", **hallazgo)
        else:
            result["sin_publicar"].append(hallazgo)
            log.error("model_artifacts_canary_sin_publicar", **hallazgo)

    if not result["divergentes"] and not result["sin_publicar"]:
        log.info("model_artifacts_canary_ok", checked=result["checked"])
    return result


def resumen(result: dict[str, Any]) -> str:
    """Los hallazgos en una frase por modelo, o cadena vacía si no hay ninguno."""
    lineas = [
        f"{h['name']} v{h['version']}: registrado {h['registrado'][:_SHA_CORTO]}, "
        f"publicado {h['publicado'][:_SHA_CORTO]} ({h['asset']} en la Release {h['release']})"
        for h in result["divergentes"]
    ]
    lineas += [
        f"{h['name']} v{h['version']}: {h['asset']} no está en ninguna Release"
        for h in result["sin_publicar"]
    ]
    return "; ".join(lineas)
