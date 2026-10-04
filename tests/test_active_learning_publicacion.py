"""El reentrenamiento automático no activa lo que no puede publicar.

El 2026-09-29 ``maybe_retrain_classifier`` corrió dentro de un runner de
``scrape-daily``: entrenó, pasó el gate y dejó la versión nueva **activa** en
``model_versions``. El ``.pkl`` se escribió en ``data/models/`` de ese runner y
desapareció con él; nadie lo subió a la Release. Desde entonces el registro
pedía un sha256 que ningún artefacto publicado tenía, y ``ml_scoring`` cayó
por ``ModelArtifactMismatch`` en cada pasada.

Con un plano de orquestación declarado el job ya no entrena: lanza
``train-model.yml``, que es el único camino que entrena **y** publica, y si no
puede lanzarlo avisa de que toca hacerlo a mano.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _sin_entorno_de_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ningún test de este módulo puede lanzar un workflow de verdad.

    La suite corre dentro de GitHub Actions, donde ``GITHUB_REPOSITORY`` y
    ``GITHUB_REF_NAME`` existen. Se quitan las tres variables, y los tests que
    prueban el lanzamiento las ponen ellos y parchean la petición.
    """
    for nombre in ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "GITHUB_REF_NAME"):
        monkeypatch.delenv(nombre, raising=False)


def _en_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    """El entorno del cierre de ``scrape-daily`` tras darle ``actions: write``."""
    monkeypatch.setenv("SCHEDULER_PLANE", "actions")
    monkeypatch.setenv("GITHUB_TOKEN", "token-de-prueba")
    monkeypatch.setenv("GITHUB_REPOSITORY", "Dkalds/TenderFlow")
    monkeypatch.setenv("GITHUB_REF_NAME", "master")


def _correr(
    n_feedbacks: int, *, dispatch: bool = False, **kwargs: Any
) -> tuple[dict[str, Any], dict[str, MagicMock]]:
    from scheduler.concept_drift import maybe_retrain_classifier

    with (
        patch(
            "db.model_registry.feedbacks_since_last_train", return_value=n_feedbacks
        ) as feedbacks,
        patch("db.model_registry.get_active", return_value=None),
        patch("scheduler.concept_drift._fetch_training_dataframe") as fetch,
        patch("scraper.ml_classifier.SAPClassifier") as clf,
        patch("scraper.ml_training.precompute_ml_proba") as precompute,
        patch("services.ml.promotion.promote_if_better") as promote,
        patch("shared.github_actions.dispatch_workflow", return_value=dispatch) as lanzar,
        patch("scheduler.concept_drift.notify") as notificar,
    ):
        result = maybe_retrain_classifier(**kwargs)
    return result, {
        "feedbacks": feedbacks,
        "fetch": fetch,
        "clf": clf,
        "precompute": precompute,
        "promote": promote,
        "dispatch": lanzar,
        "notify": notificar,
    }


# ---------------------------------------------------------------------------
# Con plano declarado: ni entrena ni activa
# ---------------------------------------------------------------------------


def test_en_el_plano_actions_ni_entrena_ni_activa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Los 59 feedbacks del incidente: no se toca el registro."""
    _en_actions(monkeypatch)

    result, mocks = _correr(59, dispatch=True)

    assert result["triggered"] is False
    assert "new_version" not in result
    mocks["fetch"].assert_not_called()
    mocks["clf"].assert_not_called()
    mocks["promote"].assert_not_called()
    # El `precompute(force=True)` de después del reentrenamiento fue además lo
    # que agotó los 20 minutos del cierre en el primer run rojo.
    mocks["precompute"].assert_not_called()


def test_lanza_el_workflow_que_entrena_y_publica(monkeypatch: pytest.MonkeyPatch) -> None:
    _en_actions(monkeypatch)

    result, mocks = _correr(59, dispatch=True)

    mocks["dispatch"].assert_called_once_with(
        "Dkalds/TenderFlow", "train-model.yml", ref="master", token="token-de-prueba"
    )
    assert result["retrain_lanzado"] is True
    assert "retrain_pendiente" not in result
    mocks["notify"].assert_called_once()
    _nivel, titulo, cuerpo = mocks["notify"].call_args[0]
    assert "lanzado" in titulo
    assert "59" in cuerpo


def test_si_github_rechaza_el_lanzamiento_avisa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token sin ``actions: write``, API caída: alguien tiene que enterarse."""
    _en_actions(monkeypatch)

    result, mocks = _correr(59, dispatch=False)

    mocks["dispatch"].assert_called_once()
    assert result["retrain_pendiente"] is True
    assert "retrain_lanzado" not in result
    _nivel, titulo, cuerpo = mocks["notify"].call_args[0]
    assert "reentrenar" in titulo
    assert "59" in cuerpo
    assert "gh workflow run train-model.yml" in cuerpo


@pytest.mark.parametrize("plano", ["docker", "worker"])
def test_fuera_de_actions_avisa_sin_intentar_lanzar(
    monkeypatch: pytest.MonkeyPatch, plano: str
) -> None:
    """Ni el scheduler de Compose ni el worker de Render comparten disco con la
    API, y ninguno tiene un token de Actions con el que lanzar nada."""
    monkeypatch.setenv("SCHEDULER_PLANE", plano)

    result, mocks = _correr(59, dispatch=True)

    mocks["dispatch"].assert_not_called()
    mocks["promote"].assert_not_called()
    assert result["retrain_pendiente"] is True


def test_sin_token_en_actions_avisa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un step que no exporta ``GITHUB_TOKEN`` no puede lanzar nada."""
    _en_actions(monkeypatch)
    monkeypatch.delenv("GITHUB_TOKEN")

    result, mocks = _correr(59, dispatch=True)

    mocks["dispatch"].assert_not_called()
    assert result["retrain_pendiente"] is True


# ---------------------------------------------------------------------------
# Cuándo toca
# ---------------------------------------------------------------------------


def test_cuenta_desde_la_ultima_version_registrada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un candidato rechazado ya gastó las etiquetas: no se relanza cada semana."""
    _en_actions(monkeypatch)

    _result, mocks = _correr(59, dispatch=True)

    mocks["feedbacks"].assert_called_once_with("sap_classifier", desde_ultimo_registro=True)


def test_por_debajo_del_umbral_no_hace_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    _en_actions(monkeypatch)

    result, mocks = _correr(10, dispatch=True)

    assert result["triggered"] is False
    assert "retrain_pendiente" not in result
    assert "retrain_lanzado" not in result
    mocks["dispatch"].assert_not_called()
    mocks["notify"].assert_not_called()


def test_el_dry_run_no_lanza_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    _en_actions(monkeypatch)

    result, mocks = _correr(59, dispatch=True, dry_run=True)

    assert result["triggered"] is True
    assert result["dry_run"] is True
    mocks["dispatch"].assert_not_called()
    mocks["notify"].assert_not_called()


# ---------------------------------------------------------------------------
# Sin plano declarado: como antes
# ---------------------------------------------------------------------------


def test_sin_plano_declarado_reentrena_como_antes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mano en un checkout, quien entrena y quien sirve comparten ``data/models/``."""
    import pandas as pd

    monkeypatch.delenv("SCHEDULER_PLANE", raising=False)
    promocion = MagicMock(activada=True, version=3, motivos_rechazo=[], golden={})
    promocion.as_dict.return_value = {"activada": True, "version": 3}

    from scheduler.concept_drift import maybe_retrain_classifier

    with (
        patch("db.model_registry.feedbacks_since_last_train", return_value=59),
        patch("db.model_registry.get_active", return_value=None),
        patch(
            "scheduler.concept_drift._fetch_training_dataframe",
            return_value=pd.DataFrame({"col": [1]}),
        ),
        patch("scraper.ml_classifier.SAPClassifier") as clf,
        patch("scraper.ml_training.precompute_ml_proba"),
        patch("services.ml.promotion.promote_if_better", return_value=promocion) as promote,
        patch("shared.github_actions.dispatch_workflow") as lanzar,
        patch("scheduler.concept_drift.notify"),
    ):
        clf.return_value.train.return_value = {"f1": 0.8, "n_train": 50, "n_test": 10}
        result = maybe_retrain_classifier()

    promote.assert_called_once()
    lanzar.assert_not_called()
    assert result["new_version"] == 3
    assert "retrain_pendiente" not in result
