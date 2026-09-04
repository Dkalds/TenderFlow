"""Resolución verificada de artefactos de modelo (revisión arquitectura 2026-08).

Cierra dos huecos del subsistema ML:

1. **El registry guardaba el sha256 pero nadie lo verificaba al cargar**
   (ítem P2 del backlog «db/model_registry.py no verifica el sha256»): un
   artefacto sustituido o desactualizado en disco se servía igual.
2. **`data/models/` es efímero en los runners de Actions**: una fila de
   ``model_versions`` puede apuntar a un path que no existe en el runner
   siguiente. Si la fila tiene sha256, se intenta descargar el asset homónimo
   de la última Release de GitHub — el mismo canal de distribución que ya usa
   ``sap_classifier`` (``scraper/ml_classifier.py::ensure_downloaded``) — y se
   verifica contra el hash registrado antes de servirlo.

Uso::

    from shared.model_artifacts import resolve_active_artifact

    path = resolve_active_artifact("baja_model")   # Path verificado, o None
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

import requests

from observability.logging import get_logger

log = get_logger(__name__)

_RELEASES_URL = "https://api.github.com/repos/Dkalds/TenderFlow/releases/latest"
_CHUNK = 1 << 20
# Subcarpeta propia dentro del temp: los artefactos se nombran por el basename
# del path registrado (``baja_model.pkl``), demasiado genérico para soltarlo en
# la raíz de un directorio compartido.
_CACHE_SUBDIR = "tenderflow-models"


def artifact_cache_dir() -> Path:
    """Directorio **escribible** donde materializar artefactos descargados.

    El ``path`` de ``model_versions`` es la ruta del sistema de ficheros de la
    máquina que ENTRENÓ el modelo (un runner de Actions efímero). Descargar ahí
    funciona en otro runner —comparten layout— pero no en el contenedor de la
    API en Render, que no tiene disco propio, no lleva ``data/`` en la imagen y
    puede no poder crear el directorio del path registrado. El resultado era
    que la API no podía obtener **ningún** artefacto y ``/explain`` degradaba a
    503 de forma permanente.

    Se prefiere ``settings.DATA_DIR/models`` —la variable que el proyecto ya usa
    para todo lo que escribe (``DOWNLOADS_DIR``, backups, parquet) y que en
    despliegues gestionados ya apunta sola a un temp escribible— y se cae a
    ``tempfile.gettempdir()`` si ese directorio no se puede crear. No se inventa
    una variable de entorno nueva: la que hace este trabajo ya existe.
    """
    candidatos: list[Path] = []
    try:
        from config import settings

        data_dir = getattr(settings, "DATA_DIR", None)
        if data_dir:
            candidatos.append(Path(str(data_dir)) / "models")
    except Exception:  # pragma: no cover — settings siempre carga en runtime
        log.debug("model_artifact_settings_unavailable", exc_info=True)
    candidatos.append(Path(tempfile.gettempdir()) / _CACHE_SUBDIR)

    for candidato in candidatos:
        try:
            candidato.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.info("model_artifact_cache_dir_no_escribible", dir=str(candidato))
            continue
        return candidato
    # El temp es el último recurso y ya se intentó crear; devolverlo deja que
    # el fallo salga en la escritura, con su ruta en el mensaje.
    return candidatos[-1]


class ModelArtifactError(RuntimeError):
    """Error de resolución de un artefacto de modelo."""


class ModelArtifactMismatch(ModelArtifactError):
    """El sha256 del artefacto en disco no coincide con el registrado."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _download_release_asset(asset_name: str, dest: Path) -> bool:
    """Descarga ``asset_name`` de la última Release a ``dest``. True si lo logró."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.get(_RELEASES_URL, headers=headers, timeout=30)
        resp.raise_for_status()
        release: dict[str, Any] = resp.json()
        asset = next(
            (a for a in release.get("assets", []) if a.get("name") == asset_name),
            None,
        )
        if asset is None:
            log.warning("model_artifact_asset_not_in_release", asset=asset_name)
            return False
        url = str(asset["browser_download_url"])
        if not url.startswith("https://"):
            log.warning("model_artifact_download_url_no_https", asset=asset_name)
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        # `stream=True`: los artefactos de modelo pesan cientos de MB y el runner
        # de Actions no tiene RAM para materializarlos antes de escribirlos.
        with (
            requests.get(url, headers=headers, timeout=120, stream=True) as asset_resp,
            dest.open("wb") as out,
        ):
            asset_resp.raise_for_status()
            for chunk in asset_resp.iter_content(chunk_size=_CHUNK):
                out.write(chunk)
        log.info("model_artifact_downloaded", asset=asset_name, dest=str(dest))
        return True
    except Exception as exc:
        log.warning("model_artifact_download_failed", asset=asset_name, error=str(exc))
        return False


def resolve_active_artifact(name: str) -> Path | None:
    """Path del artefacto de la versión activa de ``name``, verificado por sha256.

    - Fichero presente + sha256 registrado → se verifica; discrepancia lanza
      :class:`ModelArtifactMismatch` (un artefacto equivocado sirviendo
      predicciones es peor que no servirlas).
    - Fichero ausente + sha256 registrado → se busca en la caché local
      (:func:`artifact_cache_dir`) y, si no está o no cuadra, se descarga de la
      Release **a esa caché** y se verifica.
    - Sin versión activa, o irresoluble sin hash → ``None`` (el caller decide
      su fallback — p. ej. el baseline histórico).

    Es el **único** resolvedor de ``model_versions`` del proyecto: hasta 2026-09
    coexistía con el de ``api/model_cache.py``, que llamaba a
    ``SAPClassifier.load()`` sobre una ruta local inexistente en Render y hacía
    que ``POST /models/{name}/activate/{version}`` invalidase una caché que
    recargaba el mismo fichero ausente — el runbook de rollback no cambiaba lo
    que servía la API.
    """
    from db.model_registry import get_active

    activa = get_active(name)
    if not activa:
        return None
    path = Path(str(activa["path"]))
    expected = str(activa.get("sha256") or "")

    if path.exists():
        if not expected:
            log.warning("model_artifact_sin_sha256_registrado", model=name, path=str(path))
            return path
        actual = _sha256(path)
        if actual != expected:
            log.error(
                "model_artifact_sha256_mismatch",
                model=name,
                path=str(path),
                expected=expected,
                actual=actual,
            )
            raise ModelArtifactMismatch(
                f"El artefacto de '{name}' en {path} no coincide con el sha256 registrado"
            )
        _ensure_sidecar_checksum(path, actual)
        return path

    # El fichero no está donde dice el registro. Antes de bajarlo otra vez, la
    # caché local escribible: es el mismo asset y su sha256 lo dice.
    local = artifact_cache_dir() / path.name
    if local.exists():
        actual = _sha256(local)
        if expected and actual == expected:
            _ensure_sidecar_checksum(local, actual)
            return local
        # Quedó de una versión anterior: se borra en vez de servirla. Un
        # artefacto viejo sirviendo predicciones bajo el número de versión
        # nuevo es exactamente lo que este módulo existe para impedir.
        log.info("model_artifact_cache_obsoleta", model=name, path=str(local))
        local.unlink(missing_ok=True)

    if not expected:
        log.warning("model_artifact_missing_sin_sha256", model=name, path=str(path))
        return None

    if not _download_release_asset(path.name, local):
        log.warning("model_artifact_unresolvable", model=name, path=str(path))
        return None
    actual = _sha256(local)
    if actual != expected:
        log.error(
            "model_artifact_sha256_mismatch_post_download",
            model=name,
            expected=expected,
            actual=actual,
        )
        raise ModelArtifactMismatch(
            f"El asset descargado para '{name}' no coincide con el sha256 registrado"
        )
    _ensure_sidecar_checksum(local, actual)
    return local


def _ensure_sidecar_checksum(path: Path, verified_sha256: str) -> None:
    """Escribe ``<path>.sha256`` si falta, con el hash ya verificado.

    ``shared.model_integrity.verify_model_integrity`` —el paso previo a
    ``joblib.load``— **rechaza la carga en ``ENV=prod``** cuando no hay ni pin
    out-of-band ni checksum co-ubicado. El asset de la Release se descarga
    solo (``_download_release_asset`` pide ``path.name``), así que sin esto
    resolver un artefacto en un runner efímero cambiaría el fallback silencioso
    a baseline por un ``RuntimeError`` a mitad del batch.

    El hash que se persiste es el que acaba de cotejarse contra
    ``model_versions``, no uno leído del propio release: es la misma fuente
    out-of-band que el pin ``ML_*_SHA256``, no una verificación circular.
    """
    sidecar = path.with_suffix(".sha256")
    if sidecar.exists():
        return
    from shared.model_integrity import write_checksum

    write_checksum(path, verified_sha256)
    log.info("model_artifact_sidecar_written", path=str(sidecar))


def resolve_servable_artifact(name: str, fallback: Path) -> Path | None:
    """Artefacto servible de ``name``, o ``None`` si no hay ninguno.

    Prefiere el de la versión activa del registro -- descargándolo de la
    Release si este runner no lo tiene, y verificando su sha256 -- y cae al
    artefacto local de ``fallback`` cuando no hay versión activa registrada.

    Existe porque los clasificadores de ``scraper/`` decidían si había modelo
    con un ``Path.exists()`` sobre ``data/models/*.pkl``, que está en
    ``.gitignore`` y no viene en el checkout: en un runner efímero eso es
    **siempre** False, así que ``precompute_ml_proba`` y
    ``precompute_ml_tecnologias`` salían en ``no_model`` por construcción,
    pasada tras pasada, con el artefacto publicado en la Release y nadie
    bajándolo. El canal ya existía (``resolve_active_artifact``) pero solo
    estaba cableado en ``services/ml/scoring.py``.

    Un ``ModelArtifactMismatch`` se propaga, igual que en el camino de
    scoring: servir el artefacto equivocado es peor que no servir ninguno. Un
    fallo **leyendo** el registro (BD caída, proceso sin ``DATABASE_URL``) no
    es lo mismo y no debe dejar sin modelo a quien tiene uno local: se avisa y
    se cae al fallback, que es el criterio que ya aplica
    ``scraper/ml_classifier.py::load`` con su ``registry_lookup_failed``.
    """
    try:
        artefacto = resolve_active_artifact(name)
    except ModelArtifactMismatch:
        raise
    except Exception as exc:
        log.warning("model_artifact_registry_lookup_failed", model=name, error=str(exc))
        artefacto = None
    if artefacto is not None:
        return artefacto
    if fallback.exists():
        log.info("model_artifact_fallback_local", model=name, path=str(fallback))
        return fallback
    log.warning("model_artifact_sin_artefacto_servible", model=name, fallback=str(fallback))
    return None
