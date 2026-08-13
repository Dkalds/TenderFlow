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


def test_scoring_cli_ok_when_baseline_sin_modelo_activo():
    """Baseline SIN versión activa es el contrato del RFC, no una avería."""
    resumen = {
        "baja": {"status": "ok", "serving": "baseline", "model_version": None, "degradado": None},
        "retencion": {"status": "baseline", "degradado": None},
        "drift": {},
        "calibracion": {},
    }
    with (
        patch.object(ml_job, "run_scoring", return_value=resumen),
        patch("db.database.init_db"),
    ):
        assert ml_job.run_scoring_cli() == 0


@pytest.mark.parametrize("motivo", ["artefacto_irresoluble", "feature_schema_mismatch"])
def test_scoring_cli_fails_when_serving_degradado(motivo):
    """Modelo activo que no llega a servirse: job en rojo + alerta.

    Es el fallo que dejaba el batch en verde sirviendo baseline durante
    semanas: `status` seguía siendo "ok" porque las filas se escribían.
    """
    resumen = {
        "baja": {"status": "ok", "serving": "baseline", "degradado": motivo},
        "retencion": {},
        "drift": {},
        "calibracion": {},
    }
    with (
        patch.object(ml_job, "run_scoring", return_value=resumen),
        patch("db.database.init_db"),
        patch("observability.alerts.notify") as notify,
    ):
        assert ml_job.run_scoring_cli() == 1
    notify.assert_called_once()
    assert notify.call_args.kwargs["baja"] == motivo


def test_scoring_cli_fails_when_only_retencion_degradado():
    resumen = {
        "baja": {"status": "ok", "degradado": None},
        "retencion": {"status": "baseline", "degradado": "artefacto_irresoluble"},
        "drift": {},
        "calibracion": {},
    }
    with (
        patch.object(ml_job, "run_scoring", return_value=resumen),
        patch("db.database.init_db"),
        patch("observability.alerts.notify"),
    ):
        assert ml_job.run_scoring_cli() == 1


# ---------------------------------------------------------------------------
# ml_predicciones — verify
# ---------------------------------------------------------------------------


def _ahora_iso(horas_atras: float = 0.0) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(hours=horas_atras)).isoformat()


def test_verify_cli_fails_when_table_empty():
    estado = {"filas": 0, "ultimo_computed_at": None}
    with patch("db.repositories.predicciones.PrediccionesRepository.estado", return_value=estado):
        assert ml_job.verify_predicciones_cli() == 1


def test_verify_cli_ok_when_rows_are_fresh():
    estado = {"filas": 42, "ultimo_computed_at": _ahora_iso(1)}
    with patch("db.repositories.predicciones.PrediccionesRepository.estado", return_value=estado):
        assert ml_job.verify_predicciones_cli() == 0


def test_verify_cli_fails_when_rows_are_stale():
    """Filas de una corrida vieja: el upsert no purga, así que sobreviven a un
    batch que no escribió ninguna y hacían pasar la verificación."""
    estado = {"filas": 42, "ultimo_computed_at": _ahora_iso(72)}
    with patch("db.repositories.predicciones.PrediccionesRepository.estado", return_value=estado):
        assert ml_job.verify_predicciones_cli() == 1


@pytest.mark.parametrize("valor", [None, "", "no-es-una-fecha"])
def test_verify_cli_fails_when_timestamp_unusable(valor):
    """Con filas pero sin timestamp legible no se puede afirmar frescura."""
    estado = {"filas": 42, "ultimo_computed_at": valor}
    with patch("db.repositories.predicciones.PrediccionesRepository.estado", return_value=estado):
        assert ml_job.verify_predicciones_cli() == 1


def test_verify_cli_accepts_naive_timestamp():
    """Un ``computed_at`` sin tz se interpreta como UTC, no como local."""
    from datetime import UTC, datetime, timedelta

    naive = (datetime.now(UTC) - timedelta(hours=2)).replace(tzinfo=None).isoformat()
    estado = {"filas": 7, "ultimo_computed_at": naive}
    with patch("db.repositories.predicciones.PrediccionesRepository.estado", return_value=estado):
        assert ml_job.verify_predicciones_cli() == 0


# ---------------------------------------------------------------------------
# ml_predicciones — retrain (train-predictivos.yml)
# ---------------------------------------------------------------------------


def test_retrain_cli_publishes_artifacts_to_github_output(tmp_path, monkeypatch):
    """El workflow sube lo que emite este output: sin él el .pkl muere con el
    runner y `model_versions` queda apuntando a una ruta irresoluble."""
    pkl = tmp_path / "baja_model.pkl"
    pkl.write_bytes(b"modelo")
    (tmp_path / "baja_model.sha256").write_text("deadbeef", encoding="utf-8")
    salida = tmp_path / "gh_output"
    salida.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(salida))

    resultados = {
        "baja": {"status": "ok", "version": 3, "path": str(pkl)},
        "retencion": {"status": "datos_insuficientes", "n": 12},
    }
    with (
        patch.object(ml_job, "run_retrain", return_value=resultados),
        patch("db.database.init_db"),
    ):
        assert ml_job.run_retrain_cli() == 0

    escrito = salida.read_text(encoding="utf-8")
    assert escrito.startswith("artefactos=")
    assert str(pkl) in escrito
    # El checksum co-ubicado viaja con el .pkl: verify_model_integrity lo exige
    # en ENV=prod antes de deserializar.
    assert str(tmp_path / "baja_model.sha256") in escrito


def test_retrain_cli_fails_on_unexpected_status(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    resultados = {"baja": {"status": "error"}, "retencion": {"status": "ok", "path": ""}}
    with (
        patch.object(ml_job, "run_retrain", return_value=resultados),
        patch("db.database.init_db"),
    ):
        assert ml_job.run_retrain_cli() == 1


def test_retrain_cli_ok_without_data(monkeypatch):
    """Sin histórico suficiente no hay artefacto ni fallo: se sigue con baseline."""
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    resultados = {
        "baja": {"status": "datos_insuficientes", "n": 3},
        "retencion": {"status": "datos_insuficientes", "n": 5},
    }
    with (
        patch.object(ml_job, "run_retrain", return_value=resultados),
        patch("db.database.init_db"),
    ):
        assert ml_job.run_retrain_cli() == 0


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
