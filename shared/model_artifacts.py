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

    path = resolve_active_artifact("baja")   # Path verificado, o None
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from pathlib import Path
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

_RELEASES_URL = "https://api.github.com/repos/Dkalds/TenderFlow/releases/latest"
_CHUNK = 1 << 20


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
        req = urllib.request.Request(_RELEASES_URL, headers=headers)  # noqa: S310 — HTTPS fijo
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            release: dict[str, Any] = json.loads(resp.read())
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
        req = urllib.request.Request(url, headers=headers)  # noqa: S310 — HTTPS validado
        with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as out:  # noqa: S310
            while chunk := resp.read(_CHUNK):
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
    - Fichero ausente + sha256 registrado → intento de descarga desde la
      Release (runners efímeros) y verificación posterior.
    - Sin versión activa, o irresoluble sin hash → ``None`` (el caller decide
      su fallback — p. ej. el baseline histórico).
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
        return path

    if not expected:
        log.warning("model_artifact_missing_sin_sha256", model=name, path=str(path))
        return None

    if not _download_release_asset(path.name, path):
        log.warning("model_artifact_unresolvable", model=name, path=str(path))
        return None
    actual = _sha256(path)
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
    return path
