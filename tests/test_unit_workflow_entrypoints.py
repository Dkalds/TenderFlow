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


@pytest.fixture
def sin_entorno_actions(monkeypatch):
    """Quita del entorno lo que el CLI de ml_predicciones lee o escribe.

    La suite corre dentro de GitHub Actions, donde ``GITHUB_OUTPUT`` y
    ``GITHUB_STEP_SUMMARY`` existen: sin esto, cada test del CLI de scoring
    escribiría sus outputs y su resumen en el step de CI que ejecuta pytest.
    """
    for nombre in (
        "GITHUB_OUTPUT",
        "GITHUB_STEP_SUMMARY",
        "ML_VERIFY_COMPUTED_AT",
        "ML_VERIFY_FILAS",
        "ML_SCORING_FORZAR",
    ):
        monkeypatch.delenv(nombre, raising=False)


@pytest.mark.usefixtures("sin_entorno_actions")
@pytest.mark.parametrize("status", ["ok", "sin_abiertas"])
def test_scoring_cli_ok_statuses_exit_zero(status):
    """``sin_abiertas`` no es un fallo: no hay licitaciones que puntuar."""
    resumen = {"baja": {"status": status}, "retencion": {}, "drift": {}, "calibracion": {}}
    with (
        patch.object(ml_job, "run_scoring", return_value=resumen),
        patch("db.database.init_db"),
    ):
        assert ml_job.run_scoring_cli() == 0


@pytest.mark.usefixtures("sin_entorno_actions")
@pytest.mark.parametrize("status", ["error", "modelo_ausente", None])
def test_scoring_cli_failure_statuses_exit_nonzero(status):
    resumen = {"baja": {"status": status}, "retencion": {}, "drift": {}, "calibracion": {}}
    with (
        patch.object(ml_job, "run_scoring", return_value=resumen),
        patch("db.database.init_db"),
    ):
        assert ml_job.run_scoring_cli() == 1


@pytest.mark.usefixtures("sin_entorno_actions")
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


@pytest.mark.usefixtures("sin_entorno_actions")
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


@pytest.mark.usefixtures("sin_entorno_actions")
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


_REPO_PREDICCIONES = "db.repositories.predicciones.PrediccionesRepository"
_COMPUTED_AT = "2026-09-24T10:03:12.345678+00:00"


def _ahora_iso(horas_atras: float = 0.0) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(hours=horas_atras)).isoformat()


# Sin ML_VERIFY_COMPUTED_AT en el entorno (uso manual, plano local): la
# comprobación de frescura de siempre.


@pytest.mark.usefixtures("sin_entorno_actions")
def test_verify_cli_fails_when_table_empty():
    estado = {"filas": 0, "ultimo_computed_at": None}
    with patch(f"{_REPO_PREDICCIONES}.estado", return_value=estado):
        assert ml_job.verify_predicciones_cli() == 1


@pytest.mark.usefixtures("sin_entorno_actions")
def test_verify_cli_ok_when_rows_are_fresh():
    estado = {"filas": 42, "ultimo_computed_at": _ahora_iso(1)}
    with patch(f"{_REPO_PREDICCIONES}.estado", return_value=estado):
        assert ml_job.verify_predicciones_cli() == 0


@pytest.mark.usefixtures("sin_entorno_actions")
def test_verify_cli_fails_when_rows_are_stale():
    """Filas de una corrida vieja: el upsert no purga, así que sobreviven a un
    batch que no escribió ninguna y hacían pasar la verificación."""
    estado = {"filas": 42, "ultimo_computed_at": _ahora_iso(72)}
    with patch(f"{_REPO_PREDICCIONES}.estado", return_value=estado):
        assert ml_job.verify_predicciones_cli() == 1


@pytest.mark.usefixtures("sin_entorno_actions")
@pytest.mark.parametrize("valor", [None, "", "no-es-una-fecha"])
def test_verify_cli_fails_when_timestamp_unusable(valor):
    """Con filas pero sin timestamp legible no se puede afirmar frescura."""
    estado = {"filas": 42, "ultimo_computed_at": valor}
    with patch(f"{_REPO_PREDICCIONES}.estado", return_value=estado):
        assert ml_job.verify_predicciones_cli() == 1


@pytest.mark.usefixtures("sin_entorno_actions")
def test_verify_cli_accepts_naive_timestamp():
    """Un ``computed_at`` sin tz se interpreta como UTC, no como local."""
    from datetime import UTC, datetime, timedelta

    naive = (datetime.now(UTC) - timedelta(hours=2)).replace(tzinfo=None).isoformat()
    estado = {"filas": 7, "ultimo_computed_at": naive}
    with patch(f"{_REPO_PREDICCIONES}.estado", return_value=estado):
        assert ml_job.verify_predicciones_cli() == 0


# Con los outputs del step de scoring (ml-scoring.yml los pasa siempre, vacíos
# si el scoring no pudo escribirlos): se verifican las filas de ESA corrida.


def _verify_con_outputs(monkeypatch, computed_at, filas, *, escritas=0, estado=None):
    """Corre el verify con los outputs del scoring; ``filas=None`` = ausente."""
    monkeypatch.setenv("ML_VERIFY_COMPUTED_AT", computed_at)
    if filas is not None:
        monkeypatch.setenv("ML_VERIFY_FILAS", filas)
    estado = estado or {"filas": 0, "ultimo_computed_at": None}
    with (
        patch(f"{_REPO_PREDICCIONES}.contar_baja_de_corrida", return_value=escritas) as contar,
        patch(f"{_REPO_PREDICCIONES}.estado", return_value=estado),
    ):
        codigo = ml_job.verify_predicciones_cli()
    return codigo, contar


@pytest.mark.usefixtures("sin_entorno_actions")
def test_verify_cli_exacto_ok_si_la_corrida_escribio_lo_que_reporto(monkeypatch):
    codigo, contar = _verify_con_outputs(monkeypatch, _COMPUTED_AT, "42", escritas=42)
    assert codigo == 0
    contar.assert_called_once_with(_COMPUTED_AT)


@pytest.mark.usefixtures("sin_entorno_actions")
@pytest.mark.parametrize("escritas", [0, 41, 43])
def test_verify_cli_exacto_falla_si_no_cuadra(monkeypatch, escritas):
    """Filas frescas de otra corrida no cuentan: con el cron arrancando a horas
    distintas cada día, "reciente" no distinguía la corrida de hoy de la de ayer."""
    fresca = {"filas": 500, "ultimo_computed_at": _ahora_iso(1)}
    codigo, _ = _verify_con_outputs(
        monkeypatch, _COMPUTED_AT, "42", escritas=escritas, estado=fresca
    )
    assert codigo == 1


@pytest.mark.usefixtures("sin_entorno_actions")
def test_verify_cli_exacto_falla_con_cero_filas_reportadas(monkeypatch):
    """Un ``ok`` escribe una fila por abierta: con ``computed_at`` y 0 filas algo va mal."""
    codigo, _ = _verify_con_outputs(monkeypatch, _COMPUTED_AT, "0", escritas=0)
    assert codigo == 1


@pytest.mark.usefixtures("sin_entorno_actions")
@pytest.mark.parametrize("filas", ["", "muchas", None])
def test_verify_cli_exacto_falla_con_filas_ilegibles(monkeypatch, filas):
    codigo, contar = _verify_con_outputs(monkeypatch, _COMPUTED_AT, filas, escritas=42)
    assert codigo == 1
    contar.assert_not_called()


@pytest.mark.usefixtures("sin_entorno_actions")
def test_verify_cli_sin_abiertas_sale_verde_sin_mirar_la_tabla(monkeypatch):
    """``sin_abiertas`` es legítimo; con la tabla vacía la frescura habría fallado."""
    codigo, contar = _verify_con_outputs(monkeypatch, "", "0")
    assert codigo == 0
    contar.assert_not_called()


@pytest.mark.usefixtures("sin_entorno_actions")
@pytest.mark.parametrize("filas", ["", None, "12"])
def test_verify_cli_sin_outputs_cae_a_la_frescura(monkeypatch, filas):
    """Outputs vacíos (el scoring no pudo escribirlos) no son por sí solos un fallo."""
    fresca = {"filas": 42, "ultimo_computed_at": _ahora_iso(1)}
    codigo, contar = _verify_con_outputs(monkeypatch, "", filas, estado=fresca)
    assert codigo == 0
    contar.assert_not_called()

    rancia = {"filas": 42, "ultimo_computed_at": _ahora_iso(72)}
    codigo, _ = _verify_con_outputs(monkeypatch, "", filas, estado=rancia)
    assert codigo == 1


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
    resumen = {"fetch": {"extracted": 0, "error": 7}, "embed": {}, "facts": {}}
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
        patch.object(docs_job, "run", return_value={"fetch": fetch, "embed": {}, "facts": {}}),
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
        patch("scraper.seed_negatives.seed_negatives"),
        patch("services.ml.classifier_training.train_from_db", return_value={"error": "sin datos"}),
        patch("services.ml.classifier_training.precompute_ml_proba") as precompute,
    ):
        with pytest.raises(RuntimeError, match="Training failed"):
            training_job.run()
        # No debe precomputar ml_proba si el entrenamiento falló.
        precompute.assert_not_called()


_METRICAS_PROMOCIONADAS = {
    "f1": 0.8,
    "promotion": {"activada": True, "version": 3, "motivos_rechazo": []},
}
# Lo que devuelve `train_from_db(activar=False)` cuando el gate pasa: hay
# artefacto que subir, y la versión espera a que esté publicado.
_METRICAS_PENDIENTES = {
    "f1": 0.8,
    "promotion": {
        "activada": False,
        "pendiente_de_activar": True,
        "version": 3,
        "motivos_rechazo": [],
    },
}
_METRICAS_RECHAZADAS = {
    "f1": 0.8,
    "promotion": {
        "activada": False,
        "version": 4,
        "motivos_rechazo": ["recall_no_keyword 0.0000 < 0.05"],
    },
}


def test_training_run_entrena_sin_activar_y_no_precomputa():
    """Activar y recalcular `ml_proba` van DESPUÉS de subir el artefacto.

    Hasta 2026-10 `run()` activaba y hacía el `precompute` forzado antes de la
    subida: un fallo en medio dejaba activa una versión sin artefacto publicado.
    """
    with (
        patch("scraper.seed_negatives.seed_negatives") as seed,
        patch(
            "services.ml.classifier_training.train_from_db", return_value=_METRICAS_PENDIENTES
        ) as train,
        patch("services.ml.classifier_training.precompute_ml_proba") as precompute,
        patch("db.model_registry.deactivate", return_value=1),
    ):
        assert training_job.run() == _METRICAS_PENDIENTES
        train.assert_called_once_with(activar=False)
        precompute.assert_not_called()
        # Los negativos deben venir de la población de serving (CPV 48/72) y
        # de varios meses: sembrarlos de un solo mes y sin TI le enseña al
        # modelo un separador de CPV que en producción es constante.
        seed.assert_called_once_with(include_ti=True, spread_months=6)


def test_training_run_retira_la_version_activa_antes_de_la_subida():
    """La subida sustituye el asset de nombre fijo: la activa deja de tener el suyo.

    Sin versión activa, ningún estado intermedio —ni un fallo a mitad— deja
    registrado como activo un sha256 que no es el del asset publicado.
    """
    with (
        patch("scraper.seed_negatives.seed_negatives"),
        patch("services.ml.classifier_training.train_from_db", return_value=_METRICAS_PENDIENTES),
        patch("db.model_registry.deactivate", return_value=1) as deactivate,
    ):
        training_job.run()

    deactivate.assert_called_once_with("sap_classifier")


def test_training_run_no_toca_la_version_activa_si_el_gate_rechaza():
    """Un rechazo del gate no es un error, pero tampoco hay nada que aplicar."""
    with (
        patch("scraper.seed_negatives.seed_negatives"),
        patch("services.ml.classifier_training.train_from_db", return_value=_METRICAS_RECHAZADAS),
        patch("services.ml.classifier_training.precompute_ml_proba") as precompute,
        patch("db.model_registry.deactivate") as deactivate,
    ):
        assert training_job.run() == _METRICAS_RECHAZADAS
        precompute.assert_not_called()
        deactivate.assert_not_called()


def test_promocionado_distingue_los_desenlaces():
    assert training_job.promocionado(_METRICAS_PROMOCIONADAS) is True
    # Pasó el gate y espera a que su artefacto se publique: hay fichero que subir.
    assert training_job.promocionado(_METRICAS_PENDIENTES) is True
    assert training_job.promocionado(_METRICAS_RECHAZADAS) is False
    # Métricas sin bloque `promotion` (p. ej. un camino antiguo) no cuentan
    # como promoción: ante la duda, no se publica.
    assert training_job.promocionado({"f1": 0.9}) is False


# -- activar_publicada: el paso de después de la subida ----------------------

_SHA_CANDIDATO = "ab" * 32


def _fila_candidata(version: int = 3) -> dict[str, object]:
    return {
        "name": "sap_classifier",
        "version": version,
        "path": "/home/runner/work/TenderFlow/TenderFlow/data/models/sap_classifier.pkl",
        "sha256": _SHA_CANDIDATO,
        "is_active": 0,
    }


def _release_con(sha256: str | None) -> list[dict[str, object]]:
    """La Release *latest* tal como la devuelve la API tras `gh release upload`."""
    return [
        {
            "id": 2,
            "tag_name": "v1.0.0-models",
            "assets": [
                {
                    "name": "sap_classifier.pkl",
                    "id": 21,
                    "digest": f"sha256:{sha256}" if sha256 else None,
                }
            ],
        }
    ]


def _activar(releases, *, versiones=None, version: int = 3):
    """Corre `activar_publicada` con registro, Releases y precompute simulados.

    ``releases`` es una lista de respuestas sucesivas de `fetch_model_releases`.
    Devuelve ``(resultado_o_excepción, llamadas, esperas)``; ``llamadas``
    conserva el orden en que se activó y se recalculó.
    """
    llamadas: list[str] = []
    esperas: list[float] = []

    def _activate(_name, _version):
        llamadas.append("activar")
        return True

    def _precompute(*, force):
        llamadas.append(f"precompute(force={force})")
        return {"updated": 24113, "skipped_no_model": False}

    with (
        patch(
            "db.model_registry.list_versions",
            return_value=[_fila_candidata()] if versiones is None else versiones,
        ),
        patch("db.model_registry.activate_version", side_effect=_activate),
        patch("shared.model_artifacts.fetch_model_releases", side_effect=releases),
        patch("services.ml.classifier_training.precompute_ml_proba", side_effect=_precompute),
    ):
        try:
            resultado = training_job.activar_publicada(version, sleep=esperas.append)
        except RuntimeError as exc:
            resultado = exc
    return resultado, llamadas, esperas


def test_activa_solo_despues_de_ver_el_artefacto_publicado():
    """Y recalcula `ml_proba` entero, con el modelo ya activo.

    Con ``force=False`` solo se rellenarían los NULL, así que la superficie de
    serving y el test de drift de predicciones seguirían mostrando los scores
    del modelo anterior.
    """
    resultado, llamadas, esperas = _activar([_release_con(_SHA_CANDIDATO)])

    assert llamadas == ["activar", "precompute(force=True)"]
    assert esperas == []
    assert resultado["version"] == 3
    assert resultado["sha256"] == _SHA_CANDIDATO
    assert resultado["release"] == "v1.0.0-models"
    assert resultado["ml_proba"]["updated"] == 24113


def test_no_activa_si_la_release_publica_otro_contenido():
    """La subida falló o subió otro fichero: la versión se queda sin activar."""
    resultado, llamadas, esperas = _activar([_release_con("cd" * 32)] * 3)

    assert isinstance(resultado, RuntimeError)
    assert "divergente" in str(resultado)
    assert llamadas == []
    # Tres lecturas, dos esperas: se rinde, no se queda colgado.
    assert len(esperas) == 2


def test_no_activa_si_el_asset_no_esta_en_ninguna_release():
    resultado, llamadas, _esperas = _activar([[]] * 3)

    assert isinstance(resultado, RuntimeError)
    assert "sin_publicar" in str(resultado)
    assert llamadas == []


def test_un_fallo_pasajero_de_la_api_no_impide_activar():
    """La primera lectura falla (lista vacía) y la segunda ya trae el asset."""
    resultado, llamadas, esperas = _activar([[], _release_con(_SHA_CANDIDATO)])

    assert not isinstance(resultado, RuntimeError)
    assert llamadas == ["activar", "precompute(force=True)"]
    assert len(esperas) == 1


def test_no_activa_una_version_que_no_existe():
    resultado, llamadas, _esperas = _activar([_release_con(_SHA_CANDIDATO)], version=9)

    assert isinstance(resultado, RuntimeError)
    assert "No existe la versión 9" in str(resultado)
    assert llamadas == []


def test_activar_cli_sale_con_1_si_no_se_pudo_activar(sin_entorno_actions):
    with (
        patch("db.model_registry.list_versions", return_value=[]),
        patch("db.model_registry.activate_version") as activate,
    ):
        assert training_job.main(["activar", "--version", "3"]) == 1
    activate.assert_not_called()


def test_activar_cli_sale_con_0_y_deja_el_resumen(tmp_path, monkeypatch, sin_entorno_actions):
    resumen = tmp_path / "resumen.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(resumen))
    with (
        patch("db.model_registry.list_versions", return_value=[_fila_candidata()]),
        patch("db.model_registry.activate_version", return_value=True),
        patch(
            "shared.model_artifacts.fetch_model_releases",
            return_value=_release_con(_SHA_CANDIDATO),
        ),
        patch("services.ml.classifier_training.precompute_ml_proba", return_value={"updated": 7}),
    ):
        assert training_job.main(["activar", "--version", "3"]) == 0

    texto = resumen.read_text(encoding="utf-8")
    assert "Versión activada" in texto
    assert _SHA_CANDIDATO in texto


def test_sin_subcomando_entrena(sin_entorno_actions):
    """`train-model.yml` llama sin argumentos: tiene que seguir entrenando."""
    with patch.object(training_job, "run", return_value=_METRICAS_RECHAZADAS) as run:
        assert training_job.main([]) == 0
    run.assert_called_once_with()


# -- rescore -----------------------------------------------------------------


def test_rescore_recalcula_todo_con_el_modelo_que_se_sirve():
    with patch(
        "services.ml.classifier_training.precompute_ml_proba",
        return_value={"updated": 24594, "skipped_no_model": False},
    ) as precompute:
        assert training_job.rescore()["updated"] == 24594
    precompute.assert_called_once_with(force=True)


def test_rescore_sin_modelo_es_un_fallo_no_un_verde(sin_entorno_actions):
    """Un rescore que no puntúa nada y sale en verde es peor que uno que falla."""
    sin_modelo = {"updated": 0, "skipped_no_model": True}
    with patch("services.ml.classifier_training.precompute_ml_proba", return_value=sin_modelo):
        with pytest.raises(RuntimeError, match="No hay modelo servible"):
            training_job.rescore()
        assert training_job.main(["rescore"]) == 1


def test_salida_github_permite_al_workflow_distinguir_rechazo_de_fallo(tmp_path, monkeypatch):
    """Sin estos outputs, el YAML no puede separar "gate rechazó" de "reventó".

    En los dos casos falta el `.pkl`, y el paso de verificación moría con un
    `ls: cannot access` que no explicaba nada.
    """
    destino = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(destino))

    training_job._emitir_salida_github(
        {
            **_METRICAS_RECHAZADAS,
            "n_train": 900,
            "n_test": 240,
            "promotion": {
                **_METRICAS_RECHAZADAS["promotion"],
                "golden": {"recall_no_keyword": 0.0},
            },
        }
    )
    salida = dict(linea.split("=", 1) for linea in destino.read_text(encoding="utf-8").splitlines())
    assert salida["promoted"] == "false"
    assert salida["version"] == "4"
    assert "recall_no_keyword" in salida["rejection_reasons"]
    assert salida["n_train"] == "900"
    # Una sola línea por clave: un salto dentro del valor rompería el parseo
    # de `$GITHUB_OUTPUT`.
    assert len(destino.read_text(encoding="utf-8").strip().splitlines()) == 6


def test_salida_github_es_no_op_fuera_de_actions(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    training_job._emitir_salida_github(_METRICAS_PROMOCIONADAS)  # no debe lanzar


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
