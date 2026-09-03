"""Descarga de assets de una Release de GitHub sobre HTTPS con DNS pinning.

``shared.outbound_http.pinned_https_request`` resuelve el destino una vez y
rechaza cualquier redirección, porque «un salto nuevo necesita su propia
decisión de allowlist y su propio pinning» (docstring de
``PinnedHttpsResponse.raise_for_status``). El endpoint de descarga de assets de
GitHub —``api.github.com/repos/{repo}/releases/assets/{id}`` con
``Accept: application/octet-stream``— responde **siempre** ``302`` hacia
``release-assets.githubusercontent.com``. Con la regla general, y sin nadie que
tomara esa decisión, el artefacto no se podía bajar nunca.

Este módulo la toma explícitamente: lee el ``Location``, lo valida contra la
allowlist del CDN de assets y emite un **segundo** request pinned. Un solo
salto, hacia hosts nombrados, y **sin reenviar el ``Authorization``** — la URL
firmada ya lleva su propia credencial en la query, y mandar el token del repo a
otro host sería filtrarlo.

Historia: entre 2026-07-27 (commit ``7023864``, que sustituyó
``urllib.request.urlopen`` —que sí seguía redirects— por el transporte pinned)
y este cambio, ``SAPClassifier.ensure_downloaded`` falló con ``Pinned HTTPS
response status 302`` en todos los runners. Con él caían ``ml_scoring`` y
``ml_tecnologias`` de la pipeline canónica, que solo saben mirar si el fichero
está en disco.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from observability.logging import get_logger
from shared.outbound_http import pinned_https_request

log = get_logger(__name__)

REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")

_API_HOSTS = frozenset({"api.github.com"})
# Hosts a los que GitHub redirige la descarga de un asset. El primero es el
# vigente (verificado 2026-09-03); el segundo es el histórico, que sigue
# apareciendo en releases antiguas y en GitHub Enterprise.
_ASSET_CDN_HOSTS = frozenset(
    {
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    }
)
_CHUNK = 1 << 20
_TIMEOUT_API_SEGUNDOS = 15.0
_TIMEOUT_DESCARGA_SEGUNDOS = 120.0


def fetch_latest_release(repo: str, *, token: str = "") -> dict[str, Any] | None:
    """Metadata de la Release marcada como *latest*, o ``None`` si no se pudo.

    Es la MISMA release que resuelve ``shared.model_artifacts`` y la que
    publica ``train-predictivos.yml`` vía ``gh release view``: si un workflow
    subiera los assets a otro tag, nadie los encontraría.
    """
    if not REPO_RE.fullmatch(repo):
        log.warning("release_assets.invalid_repository", repository=repo)
        return None
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        with pinned_https_request(
            "GET",
            url,
            headers=_headers("application/vnd.github+json", token=token),
            timeout_seconds=_TIMEOUT_API_SEGUNDOS,
            allowed_hosts=_API_HOSTS,
        ) as response:
            response.raise_for_status()
            release = json.loads(b"".join(response.iter_content()))
    except Exception as exc:
        log.warning("release_assets.release_fetch_failed", repo=repo, error=str(exc))
        return None
    if not isinstance(release, dict):
        log.warning("release_assets.invalid_release_response", repo=repo)
        return None
    return release


def find_asset_id(release: dict[str, Any], asset_name: str) -> int | None:
    """``id`` del asset llamado ``asset_name``, o ``None`` si no está."""
    assets = release.get("assets", [])
    if not isinstance(assets, list):
        log.warning("release_assets.invalid_release_assets")
        return None
    for asset in assets:
        if isinstance(asset, dict) and asset.get("name") == asset_name:
            candidate = asset.get("id")
            if isinstance(candidate, int) and candidate > 0:
                return candidate
            break
    log.warning(
        "release_assets.asset_not_found",
        asset=asset_name,
        release=release.get("tag_name"),
    )
    return None


def download_asset(
    repo: str,
    asset_id: int,
    dest: Path,
    *,
    token: str = "",
) -> bool:
    """Descarga el asset ``asset_id`` a ``dest``. ``True`` si el fichero quedó.

    El cuerpo se escribe en streaming: los artefactos de modelo pesan cientos
    de MB y el runner de Actions no tiene RAM para materializarlos antes.
    Si algo falla a mitad se borra el fichero parcial — dejarlo sería peor que
    no tenerlo, porque ``is_available()`` es un ``Path.exists()`` y lo daría
    por bueno.
    """
    if not REPO_RE.fullmatch(repo):
        log.warning("release_assets.invalid_repository", repository=repo)
        return False
    url = f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with pinned_https_request(
            "GET",
            url,
            headers=_headers("application/octet-stream", token=token),
            timeout_seconds=_TIMEOUT_DESCARGA_SEGUNDOS,
            allowed_hosts=_API_HOSTS,
        ) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location", "")
                _descargar_desde_cdn(location, dest)
            else:
                response.raise_for_status()
                _volcar(response, dest)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        log.warning(
            "release_assets.download_failed", asset_id=asset_id, dest=str(dest), error=str(exc)
        )
        return False
    log.info("release_assets.downloaded", asset_id=asset_id, dest=str(dest))
    return True


def download_checksum_sidecar(
    repo: str,
    release: dict[str, Any],
    target: Path,
    *,
    token: str = "",
) -> bool:
    """Descarga ``<target>.sha256`` de la misma Release, junto al artefacto.

    No es cosmético: con ``ENV=prod``,
    ``shared.model_integrity.verify_model_integrity`` **rechaza** deserializar
    un artefacto que no traiga ni checksum co-ubicado ni pin out-of-band. Bajar
    el ``.pkl`` a secas cambia un ``no_model`` silencioso por un
    ``load_failed``, que tampoco puntúa nada.
    """
    sidecar = target.with_suffix(".sha256")
    asset_id = find_asset_id(release, sidecar.name)
    if asset_id is None:
        return False
    return download_asset(repo, asset_id, sidecar, token=token)


def _descargar_desde_cdn(location: str, dest: Path) -> None:
    """Segundo (y último) salto: el CDN de assets, con su propia allowlist.

    Sin ``Authorization``: ``location`` es una URL prefirmada y reenviar el
    token del repo a un host distinto sería filtrarlo. ``allowed_hosts`` hace
    que un ``Location`` inesperado —un redirect abierto en el lado de GitHub,
    o una respuesta manipulada— muera aquí en vez de convertirse en un GET
    ciego a donde diga el atacante.
    """
    if not location:
        raise ValueError("Redirect del asset sin cabecera Location")
    with pinned_https_request(
        "GET",
        location,
        headers={"Accept": "application/octet-stream", "User-Agent": "tenderflow"},
        timeout_seconds=_TIMEOUT_DESCARGA_SEGUNDOS,
        allowed_hosts=_ASSET_CDN_HOSTS,
    ) as cdn_response:
        # Un segundo redirect no se sigue: `raise_for_status` lo rechaza y el
        # caller degrada. Encadenar saltos es justo lo que este módulo evita.
        cdn_response.raise_for_status()
        _volcar(cdn_response, dest)


def _volcar(response: Any, dest: Path) -> None:
    with dest.open("wb") as out:
        for chunk in response.iter_content(_CHUNK):
            out.write(chunk)


def _headers(accept: str, *, token: str) -> dict[str, str]:
    headers = {"Accept": accept, "User-Agent": "tenderflow"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
