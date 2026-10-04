"""Tests de ``shared/github_actions.py`` — lanzar un workflow por dispatch.

Lo usa el paso semanal de active learning para pedir ``train-model.yml`` en
vez de entrenar dentro de un runner que no puede publicar el artefacto.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from shared import github_actions

_URL = "https://api.github.com/repos/Dkalds/TenderFlow/actions/workflows/train-model.yml/dispatches"


class _Respuesta:
    """Doble mínimo de ``PinnedHttpsResponse``."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 300:
            raise RuntimeError(f"Pinned HTTPS response status {self.status_code}")

    def __enter__(self) -> _Respuesta:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _lanzar(respuesta: Any, **kwargs: Any) -> tuple[bool, Any]:
    argumentos = {"ref": "master", "token": "t0k3n", **kwargs}
    with patch.object(github_actions, "pinned_https_request", side_effect=respuesta) as request:
        aceptado = github_actions.dispatch_workflow(
            argumentos.pop("repo", "Dkalds/TenderFlow"),
            argumentos.pop("workflow", "train-model.yml"),
            **argumentos,
        )
    return aceptado, request


def test_un_204_es_un_workflow_encolado() -> None:
    aceptado, request = _lanzar([_Respuesta(204)])

    assert aceptado is True
    request.assert_called_once()
    metodo, url = request.call_args.args
    assert (metodo, url) == ("POST", _URL)
    enviado = request.call_args.kwargs
    assert json.loads(enviado["body"]) == {"ref": "master"}
    assert enviado["headers"]["Authorization"] == "Bearer t0k3n"
    # El token solo puede salir hacia la API de GitHub.
    assert enviado["allowed_hosts"] == frozenset({"api.github.com"})


def test_sin_permiso_devuelve_false_y_no_lanza() -> None:
    """El caso de un token sin ``actions: write``: 403, y quien llama avisa."""
    aceptado, _request = _lanzar([_Respuesta(403)])

    assert aceptado is False


def test_un_fallo_de_red_devuelve_false() -> None:
    aceptado, _request = _lanzar(OSError("DNS caído"))

    assert aceptado is False


def test_sin_token_no_sale_a_la_red() -> None:
    aceptado, request = _lanzar([_Respuesta(204)], token="")

    assert aceptado is False
    request.assert_not_called()


@pytest.mark.parametrize(
    "argumento",
    [
        {"repo": "no-es-un-repo"},
        {"repo": "Dkalds/TenderFlow/../otro"},
        {"workflow": "../../releases/latest"},
        {"workflow": "train-model"},
        {"workflow": "a/b.yml"},
        {"ref": "rama con espacios"},
        {"ref": "../master"},
        {"ref": "feature/../master"},
        {"ref": ""},
    ],
)
def test_lo_que_no_encaja_no_sale_a_la_red(argumento: dict[str, str]) -> None:
    """Repo y workflow van en la ruta de la URL: nada que cambie de recurso."""
    aceptado, request = _lanzar([_Respuesta(204)], **argumento)

    assert aceptado is False
    request.assert_not_called()


def test_una_rama_con_barra_es_un_ref_valido() -> None:
    aceptado, request = _lanzar([_Respuesta(204)], ref="claude/una-rama")

    assert aceptado is True
    assert json.loads(request.call_args.kwargs["body"]) == {"ref": "claude/una-rama"}
