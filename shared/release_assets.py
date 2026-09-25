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

En qué Release buscar (2026-09)
-------------------------------
Hasta 2026-09 solo se miraba la Release *latest*, y *latest* no es un sitio
estable: ``release.yml`` crea una Release nueva —que pasa a ser *latest*, sin
un solo asset de modelo— con cada tag ``v*``, así que publicar una versión de
software dejaba a ``ml-scoring`` sin artefactos. :func:`locate_release_asset`
busca por nombre exacto en la Release de tag fijo :data:`ML_MODELS_RELEASE_TAG`,
después en *latest* y por último en las más recientes. Todas esas lecturas van
a ``api.github.com`` con su allowlist; el único salto al CDN sigue siendo el de
:func:`download_asset`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

from observability.logging import get_logger
from shared.outbound_http import pinned_https_request

log = get_logger(__name__)

REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
# El tag viaja en la RUTA de la URL de la API: sin ``/``, ``?``, ``#`` ni ``%``,
# y empezando por alfanumérico para que no pueda ser ``.`` ni ``..``. Mismo
# criterio que ``REPO_RE``: lo que no encaja no sale a la red.
_TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")

#: Tag de la Release **fija** donde ``train-predictivos.yml`` publica los
#: artefactos de modelo. El workflow la crea con ``--latest=false``: una
#: release de software no la desplaza y ella no desplaza a ninguna. El YAML
#: repite el literal (``TAG``) y ``tests/test_unit_train_predictivos_workflow.py``
#: los mantiene iguales: si divergen, se publica donde nadie busca.
ML_MODELS_RELEASE_TAG = "ml-models"

# Una página de la API: las 30 Releases más recientes por fecha de creación
# (el ``per_page`` por defecto de GitHub). Es el último recurso, para assets
# subidos a una *latest* que dejó de serlo —las filas de ``model_versions`` con
# nombre fijo, anteriores al tag fijo—; más atrás no compensa paginar en cada
# resolución.
_RELEASES_RECIENTES = 30
# Máximo de ``per_page`` que acepta la API de GitHub.
_MAX_POR_PAGINA = 100

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

    Es donde siguen subiendo ``train-model.yml`` y ``train-tech.yml``, y la
    que consultan directamente ``SAPClassifier.ensure_downloaded`` y
    ``TechnologyClassifier.ensure_downloaded``. Para los artefactos de
    ``model_versions`` ya no es el primer sitio: ver
    :func:`locate_release_asset`.
    """
    if not REPO_RE.fullmatch(repo):
        log.warning("release_assets.invalid_repository", repository=repo)
        return None
    datos = _get_api_json(f"https://api.github.com/repos/{repo}/releases/latest", repo, token=token)
    return _como_release(datos, repo)


def fetch_release_by_tag(repo: str, tag: str, *, token: str = "") -> dict[str, Any] | None:
    """Metadata de la Release del tag ``tag``, o ``None`` si no existe o no se pudo."""
    if not REPO_RE.fullmatch(repo):
        log.warning("release_assets.invalid_repository", repository=repo)
        return None
    if not _TAG_RE.fullmatch(tag):
        log.warning("release_assets.invalid_tag", tag=tag)
        return None
    datos = _get_api_json(
        f"https://api.github.com/repos/{repo}/releases/tags/{tag}", repo, token=token
    )
    return _como_release(datos, repo)


def fetch_recent_releases(
    repo: str, *, token: str = "", limit: int = _RELEASES_RECIENTES
) -> list[dict[str, Any]]:
    """Las ``limit`` Releases más recientes por fecha de creación, o ``[]``.

    Una sola página, sin seguir la paginación: es el último recurso de
    :func:`locate_release_asset`, no un inventario del repositorio.
    """
    if not REPO_RE.fullmatch(repo):
        log.warning("release_assets.invalid_repository", repository=repo)
        return []
    por_pagina = max(1, min(limit, _MAX_POR_PAGINA))
    datos = _get_api_json(
        f"https://api.github.com/repos/{repo}/releases?per_page={por_pagina}", repo, token=token
    )
    if datos is None:
        return []
    if not isinstance(datos, list):
        log.warning("release_assets.invalid_release_response", repo=repo)
        return []
    return [release for release in datos if isinstance(release, dict)]


def find_asset_id(release: dict[str, Any], asset_name: str) -> int | None:
    """``id`` del asset llamado ``asset_name``, o ``None`` si no está."""
    asset_id = _asset_id(release, asset_name)
    if asset_id is None:
        log.warning(
            "release_assets.asset_not_found",
            asset=asset_name,
            release=release.get("tag_name"),
        )
    return asset_id


class AssetLocalizado(NamedTuple):
    """Dónde está un asset: la Release que lo publica y su ``id`` de descarga.

    Se devuelve la Release entera porque el ``.sha256`` co-ubicado tiene que
    salir de la MISMA (:func:`download_checksum_sidecar`), no de otra que
    tenga un sidecar con el mismo nombre.
    """

    release: dict[str, Any]
    asset_id: int


def locate_release_asset(
    repo: str,
    asset_name: str,
    *,
    token: str = "",
    tag_fijo: str | None = ML_MODELS_RELEASE_TAG,
    recientes: int = _RELEASES_RECIENTES,
) -> AssetLocalizado | None:
    """Primera Release que publica un asset llamado exactamente ``asset_name``.

    Orden: la Release de ``tag_fijo`` (donde publica ``train-predictivos.yml``),
    *latest* (donde siguen subiendo ``train-model.yml`` y ``train-tech.yml``) y
    las ``recientes`` más recientes, que es donde quedaron los assets subidos a
    una *latest* que dejó de serlo: las filas de ``model_versions`` con nombre
    fijo (``baja_model.pkl``), anteriores al tag fijo, se resuelven por aquí.
    Gana la primera que lo tenga. Las lecturas se piden bajo demanda: si el
    asset está en la Release fija no se toca ni *latest* ni el listado.

    No verifica contenido: el sha256 lo coteja el llamante contra
    ``model_versions`` (``shared.model_artifacts``), venga de la Release que
    venga. Los borradores se saltan: un draft no está publicado.
    """
    if not REPO_RE.fullmatch(repo):
        log.warning("release_assets.invalid_repository", repository=repo)
        return None
    vistas: set[int] = set()
    revisadas = 0
    for release in _releases_candidatas(repo, token=token, tag_fijo=tag_fijo, recientes=recientes):
        # La Release fija y *latest* reaparecen en el listado de recientes: se
        # revisan una vez.
        release_id = release.get("id")
        if isinstance(release_id, int):
            if release_id in vistas:
                continue
            vistas.add(release_id)
        if release.get("draft") is True:
            continue
        revisadas += 1
        asset_id = _asset_id(release, asset_name)
        if asset_id is not None:
            log.info(
                "release_assets.asset_located",
                asset=asset_name,
                release=release.get("tag_name"),
                releases_revisadas=revisadas,
            )
            return AssetLocalizado(release, asset_id)
    # Un solo aviso por búsqueda, no uno por Release revisada.
    log.warning(
        "release_assets.asset_not_found",
        asset=asset_name,
        repo=repo,
        releases_revisadas=revisadas,
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


def _releases_candidatas(
    repo: str, *, token: str, tag_fijo: str | None, recientes: int
) -> Iterator[dict[str, Any]]:
    """Releases en el orden de :func:`locate_release_asset`, pedidas bajo demanda."""
    if tag_fijo:
        fija = fetch_release_by_tag(repo, tag_fijo, token=token)
        if fija is not None:
            yield fija
    latest = fetch_latest_release(repo, token=token)
    if latest is not None:
        yield latest
    if recientes > 0:
        yield from fetch_recent_releases(repo, token=token, limit=recientes)


def _get_api_json(url: str, repo: str, *, token: str) -> object | None:
    """GET a ``api.github.com`` y JSON decodificado, o ``None`` si falla.

    Un 404 no es una avería sino una Release que no existe —la de tag fijo
    antes de su primera publicación, o un repositorio sin ninguna—, y la
    búsqueda sigue con la siguiente candidata. Va a ``info`` para que el camino
    normal de :func:`locate_release_asset` no llene el log de avisos.
    """
    try:
        with pinned_https_request(
            "GET",
            url,
            headers=_headers("application/vnd.github+json", token=token),
            timeout_seconds=_TIMEOUT_API_SEGUNDOS,
            allowed_hosts=_API_HOSTS,
        ) as response:
            if response.status_code == 404:
                log.info("release_assets.release_not_found", repo=repo, url=url)
                return None
            response.raise_for_status()
            datos: object = json.loads(b"".join(response.iter_content()))
    except Exception as exc:
        log.warning("release_assets.release_fetch_failed", repo=repo, error=str(exc))
        return None
    return datos


def _como_release(datos: object, repo: str) -> dict[str, Any] | None:
    """``datos`` si tiene forma de Release (un objeto JSON); si no, ``None``."""
    if datos is None:
        return None
    if not isinstance(datos, dict):
        log.warning("release_assets.invalid_release_response", repo=repo)
        return None
    return datos


def _asset_id(release: dict[str, Any], asset_name: str) -> int | None:
    """Como :func:`find_asset_id` pero sin avisar cuando no está.

    :func:`locate_release_asset` recorre hasta una treintena de Releases y en
    casi todas el asset no está, que es lo esperado: un aviso por cada una
    enterraría el único que importa, el de no haberlo encontrado en ninguna.
    """
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
    return None


def _volcar(response: Any, dest: Path) -> None:
    with dest.open("wb") as out:
        for chunk in response.iter_content(_CHUNK):
            out.write(chunk)


def _headers(accept: str, *, token: str) -> dict[str, str]:
    headers = {"Accept": accept, "User-Agent": "tenderflow"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
