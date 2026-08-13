"""Tests del etiquetado de tecnología por LLM sobre metadata.

La frontera con el proveedor (``stream_llm_response``) se mockea siempre: un
test que llame al LLM real cuesta dinero y no es determinista. Lo que sí se
ejercita de verdad es el contrato de fallo del job, que es donde un error
corrompe estado: un item que falla no debe quedar marcado como procesado.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from config import settings
from config.keywords import TECH_LABELS
from db.repositories.tecnologia_pliego import TecnologiaPliegoRepository
from services.llm_tech_labeling import (
    METHOD,
    build_docs,
    build_question,
    parse_labels,
    signal_version,
)

# ── Prompt y parseo (puros, sin BD ni red) ────────────────────────────────


class TestBuildQuestion:
    def test_fits_client_validation_limits(self):
        """``llm.client._validate_request`` rechaza preguntas > 2000 chars."""
        question = build_question()
        assert 3 <= len(question) <= 2000

    def test_lists_every_known_label(self):
        question = build_question()
        for label in TECH_LABELS:
            assert label in question

    def test_declares_the_empty_case(self):
        """Sin instrucción explícita el modelo fuerza la etiqueta más parecida."""
        assert '{"tecnologias": []}' in build_question()


class TestBuildDocs:
    def test_descripcion_travels_as_chunk_not_excerpt(self):
        """``_doc_block`` recorta ``descripcion`` a 300 chars; el chunk no."""
        descripcion = "Migración a SAP S/4HANA. " + ("relleno " * 200)
        docs = build_docs({"id_externo": "EXP-1", "titulo": "t", "descripcion": descripcion})

        assert docs[0]["descripcion"] == ""
        assert docs[0]["chunks"][0]["texto"] == descripcion

    def test_truncates_a_very_long_description(self):
        docs = build_docs({"id_externo": "EXP-1", "descripcion": "x" * 10_000})
        assert len(docs[0]["chunks"][0]["texto"]) == 3_000

    def test_carries_structural_metadata(self):
        docs = build_docs(
            {
                "id_externo": "EXP-1",
                "titulo": "Soporte ERP",
                "cpv": "72260000",
                "importe": 245_000.0,
                "organo_contratacion": "Ayuntamiento",
                "fecha_publicacion": "2026-06-12",
            }
        )
        assert docs[0]["cpv"] == "72260000"
        assert docs[0]["importe"] == 245_000.0
        assert docs[0]["organo_contratacion"] == "Ayuntamiento"

    def test_renders_without_raising_in_the_prompt_builder(self):
        """El modo nuevo tiene presupuesto de contexto propio."""
        from llm.prompts import build_messages

        system, messages = build_messages(
            build_question(),
            build_docs({"id_externo": "EXP-1", "titulo": "SAP", "descripcion": "d"}),
            [],
            mode="clasificacion",
        )
        assert "JSON" in system
        assert "EXP-1" in messages[-1]["content"]


class TestParseLabels:
    def test_parses_plain_json(self):
        raw = '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.9, "evidencia": "S/4HANA"}]}'
        scores = parse_labels(raw)

        assert set(scores) == {"SAP"}
        assert scores["SAP"].score == 0.9
        assert scores["SAP"].evidence == [{"quote": "S/4HANA", "source": "metadata"}]

    def test_parses_fenced_json(self):
        raw = '```json\n{"tecnologias": [{"tecnologia": "ORACLE", "confidence": 0.7}]}\n```'
        assert set(parse_labels(raw)) == {"ORACLE"}

    def test_normalizes_case_and_whitespace(self):
        raw = '{"tecnologias": [{"tecnologia": " sap ", "confidence": 0.8}]}'
        assert set(parse_labels(raw)) == {"SAP"}

    def test_drops_labels_outside_the_vocabulary(self):
        """Vocabulario cerrado: lo inventado se descarta sin tumbar el resto."""
        raw = (
            '{"tecnologias": ['
            '{"tecnologia": "COBOL_MAINFRAME", "confidence": 0.9},'
            '{"tecnologia": "SAP", "confidence": 0.6}]}'
        )
        assert set(parse_labels(raw)) == {"SAP"}

    def test_drops_low_confidence_noise(self):
        raw = '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.05}]}'
        assert parse_labels(raw) == {}

    def test_keeps_the_highest_confidence_on_duplicates(self):
        raw = (
            '{"tecnologias": ['
            '{"tecnologia": "SAP", "confidence": 0.4},'
            '{"tecnologia": "SAP", "confidence": 0.85}]}'
        )
        assert parse_labels(raw)["SAP"].score == 0.85

    def test_empty_list_is_a_valid_answer(self):
        assert parse_labels('{"tecnologias": []}') == {}

    def test_rejects_confidence_out_of_range(self):
        raw = '{"tecnologias": [{"tecnologia": "SAP", "confidence": 4.2}]}'
        with pytest.raises(ValueError):
            parse_labels(raw)

    def test_rejects_text_without_json(self):
        with pytest.raises(ValueError):
            parse_labels("No he podido clasificar esta licitación.")


class TestSignalVersion:
    def test_includes_prompt_and_model(self):
        """Cambiar de modelo debe dejar pendiente al universo entero."""
        assert signal_version("deepseek-ai/deepseek-v4-pro") != signal_version("gpt-4o-mini")


class TestBatchFailedSystemically:
    """Decide si la corrida fue un fallo de infraestructura o trabajo normal."""

    @staticmethod
    def _counts(**over):
        base = {"scored": 0, "no_signal": 0, "error": 0, "disabled": 0}
        base.update(over)
        return base

    def test_everything_failed_is_systemic(self):
        """Sin NVIDIA_API_KEY todos los items fallan y no queda nada hecho."""
        from scheduler.jobs.llm_tech_labeling import batch_failed_systemically

        assert batch_failed_systemically(self._counts(error=200)) is True

    def test_some_errors_with_progress_is_not_systemic(self):
        from scheduler.jobs.llm_tech_labeling import batch_failed_systemically

        assert batch_failed_systemically(self._counts(error=3, scored=197)) is False

    def test_only_no_signal_is_not_systemic(self):
        """Un lote entero sin tecnologías es un resultado válido, no un fallo."""
        from scheduler.jobs.llm_tech_labeling import batch_failed_systemically

        assert batch_failed_systemically(self._counts(no_signal=200)) is False

    def test_empty_run_is_not_systemic(self):
        """Sin pendientes no hay nada que reportar como roto."""
        from scheduler.jobs.llm_tech_labeling import batch_failed_systemically

        assert batch_failed_systemically(self._counts()) is False

    def test_disabled_run_is_not_systemic(self):
        from scheduler.jobs.llm_tech_labeling import batch_failed_systemically

        assert batch_failed_systemically(self._counts(disabled=1)) is False


class TestPipelineStepReleasesTheWindow:
    """El paso canónico no puede quemar la ventana diaria en silencio."""

    def test_systemic_failure_propagates(self):
        """Lanzar es lo que hace a `_run_periodic` soltar el lock del día."""
        from scheduler.pipeline_runs import _run_llm_tech_labeling

        roto = {"scored": 0, "no_signal": 0, "error": 5, "disabled": 0}
        with (
            patch("scheduler.jobs.llm_tech_labeling.run", return_value=roto),
            patch("scheduler.pipeline_runs._run_periodic", side_effect=lambda _n, _t, fn: fn()),
            pytest.raises(RuntimeError, match="falló entero"),
        ):
            _run_llm_tech_labeling()

    def test_normal_run_does_not_raise(self):
        from scheduler.pipeline_runs import _run_llm_tech_labeling

        bien = {"scored": 10, "no_signal": 2, "error": 1, "disabled": 0}
        with (
            patch("scheduler.jobs.llm_tech_labeling.run", return_value=bien),
            patch("scheduler.pipeline_runs._run_periodic", side_effect=lambda _n, _t, fn: fn()),
        ):
            _run_llm_tech_labeling()

    def test_disabled_run_does_not_raise(self):
        """Con el flag apagado el paso es un no-op, no un fallo."""
        from scheduler.pipeline_runs import _run_llm_tech_labeling

        apagado = {"scored": 0, "no_signal": 0, "error": 0, "disabled": 1}
        with (
            patch("scheduler.jobs.llm_tech_labeling.run", return_value=apagado),
            patch("scheduler.pipeline_runs._run_periodic", side_effect=lambda _n, _t, fn: fn()),
        ):
            _run_llm_tech_labeling()


# ── Selección de pendientes y job (requieren Postgres) ────────────────────


@pytest.fixture()
def repo(tmp_db):
    _db_mod, _ = tmp_db
    return TecnologiaPliegoRepository()


def _insert_licitacion(id_externo: str, fecha: str = "2026-06-01") -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, descripcion, fuente, fecha_publicacion, fecha_extraccion) "
            "VALUES (%s, %s, %s, 'placsp', %s, CURRENT_TIMESTAMP)",
            (id_externo, f"Contrato {id_externo}", "Mantenimiento del ERP", fecha),
        )


class TestListMetadataPendingLlmSignal:
    def test_selects_licitaciones_without_signal(self, repo):
        _insert_licitacion("EXP-P1")

        pendientes = repo.list_metadata_pending_llm_signal(signal_version="v1")

        assert [p["id_externo"] for p in pendientes] == ["EXP-P1"]
        assert pendientes[0]["descripcion"] == "Mantenimiento del ERP"

    def test_excludes_licitaciones_with_current_signal(self, repo):
        from db.repositories.tecnologia_pliego import TechSignal

        _insert_licitacion("EXP-P2")
        repo.upsert_signals(
            "EXP-P2", method=METHOD, signal_version="v1", scores={"SAP": TechSignal(score=0.9)}
        )

        assert repo.list_metadata_pending_llm_signal(signal_version="v1") == []

    def test_sentinel_also_counts_as_processed(self, repo):
        """Una licitación sin tecnología no puede volver cada corrida."""
        _insert_licitacion("EXP-P3")
        repo.upsert_signals("EXP-P3", method=METHOD, signal_version="v1", scores={})

        assert repo.list_metadata_pending_llm_signal(signal_version="v1") == []

    def test_version_bump_makes_them_pending_again(self, repo):
        from db.repositories.tecnologia_pliego import TechSignal

        _insert_licitacion("EXP-P4")
        repo.upsert_signals(
            "EXP-P4", method=METHOD, signal_version="v1", scores={"SAP": TechSignal(score=0.9)}
        )

        pendientes = repo.list_metadata_pending_llm_signal(signal_version="v2")

        assert [p["id_externo"] for p in pendientes] == ["EXP-P4"]

    def test_ignores_signals_from_another_method(self, repo):
        """La señal de keywords de pliego no marca como hecha la del LLM."""
        from db.repositories.tecnologia_pliego import TechSignal

        _insert_licitacion("EXP-P5")
        repo.upsert_signals(
            "EXP-P5", method="keywords", signal_version="v1", scores={"SAP": TechSignal(score=0.9)}
        )

        pendientes = repo.list_metadata_pending_llm_signal(signal_version="v1")

        assert [p["id_externo"] for p in pendientes] == ["EXP-P5"]

    def test_most_recent_first(self, repo):
        _insert_licitacion("EXP-OLD", fecha="2020-01-01")
        _insert_licitacion("EXP-NEW", fecha="2026-08-01")

        pendientes = repo.list_metadata_pending_llm_signal(signal_version="v1")

        assert [p["id_externo"] for p in pendientes] == ["EXP-NEW", "EXP-OLD"]


class TestRunJob:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_TECH_LABELING_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "LLM_TECH_LABELING_BATCH", 10, raising=False)

    def test_disabled_flag_is_a_noop(self, repo, monkeypatch):
        from scheduler.jobs.llm_tech_labeling import run

        monkeypatch.setattr(settings, "LLM_TECH_LABELING_ENABLED", False, raising=False)
        _insert_licitacion("EXP-J0")

        counts = run()

        assert counts["disabled"] == 1
        assert repo.list_for_licitacion("EXP-J0") == []

    def test_persists_signal_and_merges(self, repo):
        from scheduler.jobs.llm_tech_labeling import run

        _insert_licitacion("EXP-J1")
        raw = '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.92}]}'

        with patch("services.llm_tech_labeling.stream_llm_response", return_value=iter([raw])):
            counts = run()

        assert counts["scored"] == 1
        assert counts["error"] == 0
        señales = repo.list_for_licitacion("EXP-J1")
        assert [(s["tecnologia"], s["method"]) for s in señales] == [("SAP", METHOD)]

    def test_merge_reaches_ml_tecnologias(self, repo):
        from db.database import connect
        from scheduler.jobs.llm_tech_labeling import run

        _insert_licitacion("EXP-J2")
        raw = '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.95}]}'

        with patch("services.llm_tech_labeling.stream_llm_response", return_value=iter([raw])):
            run()

        with connect() as c:
            row = c.execute(
                "SELECT ml_tecnologias FROM licitaciones WHERE id_externo = %s", ("EXP-J2",)
            ).fetchone()
        assert "SAP" in str(row[0])

    def test_empty_answer_writes_the_sentinel(self, repo):
        from scheduler.jobs.llm_tech_labeling import run

        _insert_licitacion("EXP-J3")

        with patch(
            "services.llm_tech_labeling.stream_llm_response",
            return_value=iter(['{"tecnologias": []}']),
        ):
            counts = run()

        assert counts["no_signal"] == 1
        assert (
            repo.list_metadata_pending_llm_signal(
                signal_version=signal_version(settings.LLM_TECH_LABELING_MODEL)
            )
            == []
        )

    def test_empty_stream_counts_error_and_leaves_it_pending(self, repo):
        """Sin NVIDIA_API_KEY el provider no emite nada. No es 'sin tecnología'."""
        from scheduler.jobs.llm_tech_labeling import run

        _insert_licitacion("EXP-J4")

        with patch("services.llm_tech_labeling.stream_llm_response", return_value=iter([])):
            counts = run()

        assert counts["error"] == 1
        assert counts["scored"] == 0
        pendientes = repo.list_metadata_pending_llm_signal(
            signal_version=signal_version(settings.LLM_TECH_LABELING_MODEL)
        )
        assert [p["id_externo"] for p in pendientes] == ["EXP-J4"]

    def test_invalid_json_leaves_it_pending(self, repo):
        from scheduler.jobs.llm_tech_labeling import run

        _insert_licitacion("EXP-J5")

        with patch(
            "services.llm_tech_labeling.stream_llm_response",
            return_value=iter(["lo siento, no puedo"]),
        ):
            counts = run()

        assert counts["error"] == 1
        assert repo.list_for_licitacion("EXP-J5") == []

    def test_one_failure_does_not_abort_the_batch(self, repo):
        from scheduler.jobs.llm_tech_labeling import run

        _insert_licitacion("EXP-J6", fecha="2026-08-02")
        _insert_licitacion("EXP-J7", fecha="2026-08-01")
        ok = '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.9}]}'

        with patch(
            "services.llm_tech_labeling.stream_llm_response",
            side_effect=[RuntimeError("boom"), iter([ok])],
        ):
            counts = run()

        assert counts["error"] == 1
        assert counts["scored"] == 1

    def test_budget_exhaustion_stops_cleanly(self, repo):
        from llm.budget import LLMBudgetExceeded
        from scheduler.jobs.llm_tech_labeling import run

        _insert_licitacion("EXP-J8", fecha="2026-08-02")
        _insert_licitacion("EXP-J9", fecha="2026-08-01")
        ok = '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.9}]}'
        agotado = LLMBudgetExceeded("daily", 6.0, 5.0)

        with (
            patch("services.llm_tech_labeling.stream_llm_response", return_value=iter([ok])),
            patch("llm.budget.BudgetGuard.check", side_effect=[None, agotado]),
        ):
            counts = run()

        assert counts["budget_exhausted"] == 1
        assert counts["scored"] == 1
        assert counts["error"] == 0
        # El segundo no se clasificó: sigue pendiente, no marcado como procesado.
        pendientes = repo.list_metadata_pending_llm_signal(
            signal_version=signal_version(settings.LLM_TECH_LABELING_MODEL)
        )
        assert [p["id_externo"] for p in pendientes] == ["EXP-J9"]

    def test_low_confidence_persists_but_stays_out_of_the_merge(self, repo):
        """Entre _MIN_PERSIST_CONF y PLIEGO_TECH_MIN_SCORE: trazable, no aplicada."""
        from db.database import connect
        from scheduler.jobs.llm_tech_labeling import run

        _insert_licitacion("EXP-J10")
        raw = '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.3}]}'

        with patch("services.llm_tech_labeling.stream_llm_response", return_value=iter([raw])):
            run()

        assert [s["tecnologia"] for s in repo.list_for_licitacion("EXP-J10")] == ["SAP"]
        with connect() as c:
            row = c.execute(
                "SELECT ml_tecnologias FROM licitaciones WHERE id_externo = %s", ("EXP-J10",)
            ).fetchone()
        assert not row[0]


# ── Fase 2: volcado a ml_feedback y guard del entrenamiento ───────────────


class TestWriteFeedback:
    """El feedback automático vacía la cola humana sin realimentar al modelo."""

    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_TECH_LABELING_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "LLM_TECH_FEEDBACK_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "LLM_TECH_FEEDBACK_MIN_CONF", 0.9, raising=False)

    @staticmethod
    def _run_with(raw: str):
        from scheduler.jobs.llm_tech_labeling import run

        with patch("services.llm_tech_labeling.stream_llm_response", return_value=iter([raw])):
            return run()

    @staticmethod
    def _feedback_rows(expediente: str) -> list[tuple]:
        from db.database import connect

        with connect() as c:
            return c.execute(
                "SELECT relevante, tecnologia, source FROM ml_feedback WHERE expediente = %s",
                (expediente,),
            ).fetchall()

    def test_confident_label_is_written_as_llm_batch(self, repo):
        _insert_licitacion("EXP-F1")

        counts = self._run_with('{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.97}]}')

        assert counts["feedback_escrito"] == 1
        assert self._feedback_rows("EXP-F1") == [(1, "SAP", "llm_batch")]

    def test_non_sap_technology_is_not_relevante(self, repo):
        _insert_licitacion("EXP-F2")

        self._run_with('{"tecnologias": [{"tecnologia": "ORACLE", "confidence": 0.95}]}')

        assert self._feedback_rows("EXP-F2") == [(0, "ORACLE", "llm_batch")]

    def test_no_technology_empties_the_queue_as_not_relevant(self, repo):
        _insert_licitacion("EXP-F3")

        counts = self._run_with('{"tecnologias": []}')

        assert counts["feedback_escrito"] == 1
        assert self._feedback_rows("EXP-F3") == [(0, None, "llm_batch")]

    def test_uncertain_label_is_left_for_a_human(self, repo):
        """Lo dudoso no se escribe: sigue saliendo en la cola de etiquetado."""
        _insert_licitacion("EXP-F4")

        counts = self._run_with('{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.55}]}')

        assert counts["feedback_escrito"] == 0
        assert counts["feedback_omitido"] == 1
        assert self._feedback_rows("EXP-F4") == []

    def test_disabled_flag_writes_nothing(self, repo, monkeypatch):
        monkeypatch.setattr(settings, "LLM_TECH_FEEDBACK_ENABLED", False, raising=False)
        _insert_licitacion("EXP-F5")

        counts = self._run_with('{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.99}]}')

        assert counts["scored"] == 1
        assert counts["feedback_escrito"] == 0
        assert self._feedback_rows("EXP-F5") == []

    def test_does_not_overwrite_an_existing_human_label(self, repo):
        from db.repositories.feedback import FeedbackRepository

        _insert_licitacion("EXP-F6")
        FeedbackRepository().insert(
            expediente="EXP-F6", relevante=False, nota="revisado a mano", tecnologia=None
        )

        counts = self._run_with('{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.99}]}')

        assert counts["feedback_omitido"] == 1
        assert self._feedback_rows("EXP-F6") == [(0, None, "human")]

    def test_written_label_removes_it_from_the_human_queue(self, repo):
        """El objetivo de la fase: la cola de active learning se vacía."""
        from db.repositories.licitaciones import LicitacionRepository

        _insert_licitacion("EXP-F7")
        antes = LicitacionRepository().get_unlabelled_candidates(10)
        assert "EXP-F7" in [c["id_externo"] for c in antes]

        self._run_with('{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.99}]}')

        despues = LicitacionRepository().get_unlabelled_candidates(10)
        assert "EXP-F7" not in [c["id_externo"] for c in despues]


class TestTrainingIgnoresAutomaticFeedback:
    """Guard anti-realimentación: el modelo no aprende de sus propias etiquetas."""

    def test_llm_feedback_does_not_override_the_training_label(self, tmp_db):
        from db.repositories.feedback import FeedbackRepository
        from scheduler.concept_drift import _fetch_training_dataframe

        _insert_licitacion("EXP-T1")
        FeedbackRepository().insert(
            expediente="EXP-T1", relevante=True, nota="llm", tecnologia="SAP", source="llm_batch"
        )

        df = _fetch_training_dataframe()

        fila = df[df["id_externo"] == "EXP-T1"].iloc[0]
        assert fila["es_relevante"] == 0

    def test_human_feedback_still_overrides(self, tmp_db):
        from db.repositories.feedback import FeedbackRepository
        from scheduler.concept_drift import _fetch_training_dataframe

        _insert_licitacion("EXP-T2")
        FeedbackRepository().insert(expediente="EXP-T2", relevante=True, nota="a mano")

        df = _fetch_training_dataframe()

        fila = df[df["id_externo"] == "EXP-T2"].iloc[0]
        assert fila["es_relevante"] == 1

    def test_retrain_counter_ignores_automatic_feedback(self, tmp_db):
        """Un lote del LLM no puede disparar el reentrenamiento semanal."""
        from db.model_registry import feedbacks_since_last_train
        from db.repositories.feedback import FeedbackRepository

        repo = FeedbackRepository()
        for i in range(3):
            repo.insert(expediente=f"EXP-C{i}", relevante=False, nota="llm", source="llm_batch")

        assert feedbacks_since_last_train() == 0

        repo.insert(expediente="EXP-CH", relevante=True, nota="a mano")

        assert feedbacks_since_last_train() == 1
