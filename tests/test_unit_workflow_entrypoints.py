"""Tests de los entrypoints CLI que reemplazan los heredocs de los workflows.

Antes esta lógica vivía como ``python -c "..."`` dentro de
``.github/workflows/{ml-scoring,pliegos,train-model}.yml``, fuera del alcance
de ruff/mypy/pytest. Estos tests cubren el contrato que los workflows
dependen: **el código de salida**, que es lo único que GitHub Actions mira
para decidir si el step falla.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scheduler.jobs import documentos_embeddings as docs_job
from scheduler.jobs import ml_predicciones as ml_job
from scheduler.jobs import ml_training_run as training_job

# ---------------------------------------------------------------------------
# ml_predicciones — scoring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["ok", "sin_abiertas"])
def test_scoring_cli_ok_statuses_exit_zero(status):
    """``sin_abiertas`` no es un fallo: no hay licitaciones que puntuar."""
    resumen = {"baja": {"status": status}, "retencion": {}, "drift": {}, "calibracion": {}}
    with (
        patch.object(ml_job, "run_scoring", return_value=resumen),
        patch("db.database.init_db"),
    ):
        assert ml_job.run_scoring_cli() == 0


@pytest.mark.parametrize("status", ["error", "modelo_ausente", None])
def test_scoring_cli_failure_statuses_exit_nonzero(status):
    resumen = {"baja": {"status": status}, "retencion": {}, "drift": {}, "calibracion": {}}
    with (
        patch.object(ml_job, "run_scoring", return_value=resumen),
        patch("db.database.init_db"),
    ):
        assert ml_job.run_scoring_cli() == 1


# ---------------------------------------------------------------------------
# ml_predicciones — verify
# ---------------------------------------------------------------------------


def test_verify_cli_fails_when_table_empty():
    estado = {"filas": 0, "ultimo_computed_at": None}
    with patch("db.repositories.predicciones.PrediccionesRepository.estado", return_value=estado):
        assert ml_job.verify_predicciones_cli() == 1


def test_verify_cli_ok_when_rows_present():
    estado = {"filas": 42, "ultimo_computed_at": "2026-07-26T00:00:00"}
    with patch("db.repositories.predicciones.PrediccionesRepository.estado", return_value=estado):
        assert ml_job.verify_predicciones_cli() == 0


# ---------------------------------------------------------------------------
# documentos_embeddings — run
# ---------------------------------------------------------------------------


def test_docs_cli_fails_only_when_whole_batch_failed():
    """Lote entero caído (errores y cero extraídos) = fallo sistémico."""
    resumen = {"fetch": {"extracted": 0, "error": 7}, "embed": {}}
    with patch.object(docs_job, "run", return_value=resumen), patch("db.database.init_db"):
        assert docs_job.run_cli() == 1


@pytest.mark.parametrize(
    "fetch",
    [
        {"extracted": 3, "error": 2},  # PDFs corruptos sueltos: normal
        {"extracted": 0, "error": 0},  # nada pendiente
        {"extracted": 5, "error": 0},
    ],
)
def test_docs_cli_tolerates_partial_failures(fetch):
    with (
        patch.object(docs_job, "run", return_value={"fetch": fetch, "embed": {}}),
        patch("db.database.init_db"),
    ):
        assert docs_job.run_cli() == 0


def test_docs_report_cli_exits_zero(tmp_db):
    """El reporting nunca rompe el workflow, solo informa."""
    assert docs_job.report_cli() == 0


# ---------------------------------------------------------------------------
# ml_training_run
# ---------------------------------------------------------------------------


def test_training_run_raises_on_error_metrics():
    with (
        patch("scraper.ml_training.seed_negatives"),
        patch("scraper.ml_training.train_from_db", return_value={"error": "sin datos"}),
        patch("scraper.ml_training.precompute_ml_proba") as precompute,
    ):
        with pytest.raises(RuntimeError, match="Training failed"):
            training_job.run()
        # No debe precomputar ml_proba si el entrenamiento falló.
        precompute.assert_not_called()


def test_training_run_precomputes_on_success():
    with (
        patch("scraper.ml_training.seed_negatives") as seed,
        patch("scraper.ml_training.train_from_db", return_value={"f1": 0.8}),
        patch("scraper.ml_training.precompute_ml_proba") as precompute,
    ):
        assert training_job.run() == {"f1": 0.8}
        seed.assert_called_once()
        precompute.assert_called_once_with(force=False)


# ---------------------------------------------------------------------------
# PrediccionesRepository
# ---------------------------------------------------------------------------


def test_predicciones_repo_rejects_unknown_table(tmp_db):
    from db.repositories.predicciones import PrediccionesRepository

    with pytest.raises(ValueError, match="no permitida"):
        PrediccionesRepository().estado("licitaciones; DROP TABLE users")


def test_predicciones_repo_empty_table(tmp_db):
    from db.repositories.predicciones import PrediccionesRepository

    estado = PrediccionesRepository().estado("predicciones_baja")
    assert estado == {"filas": 0, "ultimo_computed_at": None}
