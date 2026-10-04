"""Lanzar un workflow de GitHub Actions por ``workflow_dispatch``.

Hay trabajo que un job programado puede **decidir** pero no debe **hacer**: el
paso semanal de active learning sabe cuándo toca reentrenar el clasificador,
pero corre en un runner con ``contents: read`` y sin dónde publicar el
artefacto. Quien entrena y publica es ``train-model.yml``. Este módulo es el
puente: una petición a la API de GitHub que encola ese workflow.

Requiere un token con ``actions: write``. El de ``github.token`` vale: los
eventos que provoca ese token no encadenan workflows, con dos excepciones
documentadas, y ``workflow_dispatch`` es una de ellas.

El transporte es el de ``shared.outbound_http`` —HTTPS con DNS pinning y
allowlist de host—, el mismo que usa ``shared.release_assets``.
"""

from __future__ import annotations

import json
import re

from observability.logging import get_logger
from shared.outbound_http import pinned_https_request

log = get_logger(__name__)

_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
# El nombre del fichero viaja en la RUTA de la URL: sin ``/`` ni nada que
# pueda cambiar de recurso. Mismo criterio que ``release_assets._TAG_RE``.
_WORKFLOW_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.ya?ml")
# Rama o tag sobre el que se lanza. Va en el cuerpo JSON, no en la URL, pero
# se acota igual: un ref con espacios o comodines no es un ref.
_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./-]*")

_API_HOSTS = frozenset({"api.github.com"})
_TIMEOUT_SEGUNDOS = 15.0


def dispatch_workflow(repo: str, workflow: str, *, ref: str, token: str) -> bool:
    """Encola ``workflow`` sobre ``ref``. ``True`` si GitHub aceptó la petición.

    Aceptar no es terminar: la API responde ``204`` en cuanto encola el run, y
    lo que pase dentro se ve en el propio workflow. Nunca lanza: sin token,
    con argumentos que no encajan o con cualquier fallo de red devuelve
    ``False``, para que quien llama pueda caer a su alternativa (avisar a una
    persona) en vez de romper el paso que lo invocó.

    Args:
        repo: ``owner/nombre``.
        workflow: Nombre del fichero dentro de ``.github/workflows/``.
        ref: Rama o tag cuyo YAML se ejecuta.
        token: Token con ``actions: write`` sobre ``repo``.
    """
    if not token:
        log.info("github_actions.dispatch_sin_token", workflow=workflow)
        return False
    if not _REPO_RE.fullmatch(repo):
        log.warning("github_actions.invalid_repository", repository=repo)
        return False
    if not _WORKFLOW_RE.fullmatch(workflow):
        log.warning("github_actions.invalid_workflow", workflow=workflow)
        return False
    if not _REF_RE.fullmatch(ref) or ".." in ref:
        log.warning("github_actions.invalid_ref", ref=ref)
        return False

    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
    try:
        with pinned_https_request(
            "POST",
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "tenderflow",
            },
            body=json.dumps({"ref": ref}).encode(),
            timeout_seconds=_TIMEOUT_SEGUNDOS,
            allowed_hosts=_API_HOSTS,
        ) as response:
            response.raise_for_status()
    except Exception as exc:
        log.warning("github_actions.dispatch_failed", workflow=workflow, ref=ref, error=str(exc))
        return False
    log.info("github_actions.dispatched", workflow=workflow, ref=ref, repo=repo)
    return True
