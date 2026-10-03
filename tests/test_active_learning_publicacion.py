"""El reentrenamiento automático no activa lo que no puede publicar.

El 2026-09-29 ``maybe_retrain_classifier`` corrió dentro de un runner de
``scrape-daily``: entrenó, pasó el gate y dejó la versión nueva **activa** en
``model_versions``. El ``.pkl`` se escribió en ``data/models/`` de ese runner y
desapareció con él; nadie lo subió a la Release. Desde entonces el registro
pedía un sha256 que ningún artefacto publicado tenía, y ``ml_scoring`` cayó
por ``ModelArtifactMismatch`` en cada pasada.

Con un plano de orquestación declarado el job ya no entrena: avisa de que toca
lanzar ``train-model.yml``, que es el único camino que entrena **y** publica.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _correr(n_feedbacks: int, **kwargs: Any) -> tuple[dict[str, Any], dict[str, MagicMock]]:
    from scheduler.concept_drift import maybe_retrain_classifier

    with (
        patch("db.model_registry.feedbacks_since_last_train", return_value=n_feedbacks),
        patch("db.model_registry.get_active", return_value=None),
        patch("scheduler.concept_drift._fetch_training_dataframe") as fetch,
        patch("scraper.ml_classifier.SAPClassifier") as clf,
        patch("scraper.ml_training.precompute_ml_proba") as precompute,
        patch("services.ml.promotion.promote_if_better") as promote,
        patch("scheduler.concept_drift.notify") as notificar,
    ):
        result = maybe_retrain_classifier(**kwargs)
    return result, {
        "fetch": fetch,
        "clf": clf,
        "precompute": precompute,
        "promote": promote,
        "notify": notificar,
    }


def test_en_el_plano_actions_ni_entrena_ni_activa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Los 59 feedbacks del incidente: se avisa, no se toca el registro."""
    monkeypatch.setenv("SCHEDULER_PLANE", "actions")

    result, mocks = _correr(59)

    assert result["triggered"] is False
    assert result["retrain_pendiente"] is True
    assert "new_version" not in result
    mocks["fetch"].assert_not_called()
    mocks["clf"].assert_not_called()
    mocks["promote"].assert_not_called()
    # El `precompute(force=True)` de después del reentrenamiento fue además lo
    # que agotó los 20 minutos del cierre en el primer run rojo.
    mocks["precompute"].assert_not_called()


def test_el_aviso_dice_como_reentrenar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHEDULER_PLANE", "actions")

    _result, mocks = _correr(59)

    mocks["notify"].assert_called_once()
    _nivel, titulo, cuerpo = mocks["notify"].call_args[0]
    assert "reentrenar" in titulo
    assert "59" in cuerpo
    assert "train-model.yml" in cuerpo


def test_por_debajo_del_umbral_no_avisa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHEDULER_PLANE", "actions")

    result, mocks = _correr(10)

    assert result["triggered"] is False
    assert "retrain_pendiente" not in result
    mocks["notify"].assert_not_called()


def test_el_dry_run_sigue_informando_igual(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHEDULER_PLANE", "actions")

    result, mocks = _correr(59, dry_run=True)

    assert result["triggered"] is True
    assert result["dry_run"] is True
    mocks["notify"].assert_not_called()


@pytest.mark.parametrize("plano", ["docker", "worker"])
def test_ningun_plano_declarado_reentrena_en_proceso(
    monkeypatch: pytest.MonkeyPatch, plano: str
) -> None:
    """Ni el scheduler de Compose ni el worker de Render comparten disco con la API."""
    monkeypatch.setenv("SCHEDULER_PLANE", plano)

    result, mocks = _correr(59)

    assert result["retrain_pendiente"] is True
    mocks["promote"].assert_not_called()


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
        patch("scheduler.concept_drift.notify"),
    ):
        clf.return_value.train.return_value = {"f1": 0.8, "n_train": 50, "n_test": 10}
        result = maybe_retrain_classifier()

    promote.assert_called_once()
    assert result["new_version"] == 3
    assert "retrain_pendiente" not in result
