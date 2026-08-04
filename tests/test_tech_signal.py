"""Tests unitarios (sin BD) de services/tech_signal.py.

``score_documents`` es puro. ``merge_doc_signals`` toca BD solo a través de
``TecnologiaPliegoRepository``, así que aquí se mockea el repo entero -- esto
mantiene el test sin fixture ``tmp_db`` (unit real, no integration) mientras
cubre la aritmética del merge (max, nunca borra, CSV orden proba desc,
dedupe de evento por ``merged_at``). Las pruebas contra un repo real viven en
``tests/test_tech_signal_db.py``.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

from services.tech_signal import _build_merge_result, merge_doc_signals, score_documents


def _patched_patterns():
    return patch.dict(
        "services.tech_signal._TECH_PATTERNS",
        {
            "SAP": re.compile(r"\b(sap|hana)\b", re.IGNORECASE),
            "ORACLE": re.compile(r"\b(oracle)\b", re.IGNORECASE),
        },
        clear=True,
    )


class TestScoreDocuments:
    def test_technical_doc_reaches_threshold_with_few_mentions(self):
        pages = [
            {
                "tipo": "technical",
                "texto": "Migración a SAP S/4HANA. SAP HANA como base de datos.",
            },
        ]
        with _patched_patterns():
            result = score_documents(pages)
        assert "SAP" in result
        assert 0 < result["SAP"].score <= 1.0

    def test_legal_doc_single_mention_is_below_threshold(self):
        """Una mención de pasada en el legal (peso 0.3) no alcanza el mínimo --
        anti "menciona de pasada"."""
        pages = [{"tipo": "legal", "texto": "El adjudicatario deberá disponer de SAP."}]
        with _patched_patterns():
            assert score_documents(pages) == {}

    def test_word_boundary_avoids_false_positive(self):
        """'sap' no debe matchear dentro de 'desaparecer' (mismo caso que
        scraper/filters.py documenta)."""
        pages = [{"tipo": "technical", "texto": "El personal debe desaparecer del listado."}]
        with _patched_patterns():
            assert "SAP" not in score_documents(pages)

    def test_matched_terms_are_lowercased_deduped_and_sorted(self):
        pages = [{"tipo": "technical", "texto": "SAP SAP Sap HANA hana"}]
        with _patched_patterns():
            result = score_documents(pages)
        assert result["SAP"].matched_terms == ["hana", "sap"]

    def test_score_saturates_at_one(self):
        pages = [{"tipo": "technical", "texto": "sap " * 50}]
        with _patched_patterns():
            assert score_documents(pages)["SAP"].score == 1.0

    def test_multiple_technologies_scored_independently(self):
        pages = [
            {
                "tipo": "technical",
                "texto": "Implantación de SAP HANA y consultoría Oracle Oracle.",
            },
        ]
        with _patched_patterns():
            result = score_documents(pages)
        assert set(result) == {"SAP", "ORACLE"}

    def test_empty_pages_returns_empty(self):
        with _patched_patterns():
            assert score_documents([]) == {}

    def test_page_without_texto_is_skipped_not_error(self):
        pages = [{"tipo": "technical", "texto": None}]
        with _patched_patterns():
            assert score_documents(pages) == {}

    def test_unknown_tipo_defaults_to_legal_weight(self):
        """Un tipo de documento inesperado no debe pesar como 'technical'."""
        # * 6 (12 hits): a peso legal/desconocido (0.3) hacen falta >= 6.67
        # hits ponderados para cruzar _MIN_WEIGHTED_HITS (2.0); menos
        # repeticiones dejaban el resultado por debajo del mínimo y
        # score_documents devolvía {} -- KeyError al indexar ["SAP"].
        with _patched_patterns():
            unknown = score_documents([{"tipo": "unexpected", "texto": "SAP HANA " * 6}])
            legal = score_documents([{"tipo": "legal", "texto": "SAP HANA " * 6}])
        assert unknown["SAP"].score == legal["SAP"].score


def _signal_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "licitacion_id": "L1",
        "tecnologia": "META4",
        "method": "keywords",
        "score": 0.8,
        "matched_terms": '["meta4"]',
        "evidence_json": None,
        "signal_version": "keywords-abc123",
        "merged_at": None,
    }
    row.update(overrides)
    return row


class TestBuildMergeResult:
    """``_build_merge_result`` es la aritmética pura del merge -- corre dentro
    de ``TecnologiaPliegoRepository.merge_with_lock`` en producción, pero es
    una función libre de I/O y se prueba directamente aquí."""

    def test_adds_technology_detected_only_in_pliego(self):
        result = _build_merge_result(
            {"predicted": set(), "scores": {}}, {"META4": 0.8}, threshold_aplicado=0.5
        )
        assert result["ml_tecnologias"] == "META4"
        assert result["ml_proba_max"] == 0.8
        assert result["ml_tech_principal"] == "META4"
        assert result["pliego_scores"] == [("META4", 0.8)]

    def test_never_removes_an_existing_predicted_technology(self):
        """El pliego solo detecta META4; SAP (ya predicho por título/ML) sigue
        en ml_tecnologias -- el merge nunca borra, solo añade."""
        result = _build_merge_result(
            {"predicted": {"SAP"}, "scores": {"SAP": 0.9}},
            {"META4": 0.8},
            threshold_aplicado=0.5,
        )
        assert set(result["ml_tecnologias"].split(",")) == {"SAP", "META4"}
        assert result["pliego_scores"] == [("META4", 0.8)]  # SAP no se reescribe

    def test_effective_score_is_the_max_not_the_pliego_value(self):
        """Si el título/ML ya tenía un score mayor para esa tecnología, se conserva."""
        result = _build_merge_result(
            {"predicted": {"SAP"}, "scores": {"SAP": 0.9}},
            {"SAP": 0.4},
            threshold_aplicado=0.5,
        )
        assert result["pliego_scores"] == [("SAP", 0.9)]

    def test_ml_proba_max_and_principal_are_restricted_to_included(self):
        """Una tecnología con score>0 en licitacion_tecnologia_score pero por
        debajo de SU PROPIO threshold ML (nunca "predicha") no debe poder
        salir como ml_tech_principal si ni el título/ML ni el pliego la
        dejaron en el ml_tecnologias final -- de lo contrario el principal
        nombraría una tecnología ausente del propio CSV."""
        result = _build_merge_result(
            # SAP=0.45 quedó en licitacion_tecnologia_score (score>0) pero
            # nunca cruzó su propio threshold, así que no está en "predicted".
            {"predicted": set(), "scores": {"SAP": 0.45}},
            {"DOCKER": 0.25},
            threshold_aplicado=0.2,
        )
        assert result["ml_tecnologias"] == "DOCKER"
        assert result["ml_tech_principal"] == "DOCKER"
        assert result["ml_proba_max"] == 0.25
        assert "SAP" not in result["ml_tecnologias"].split(",")

    def test_ml_tecnologias_ordered_by_proba_desc(self):
        result = _build_merge_result(
            {"predicted": {"SAP"}, "scores": {"SAP": 0.6}},
            {"META4": 0.9},
            threshold_aplicado=0.5,
        )
        assert result["ml_tecnologias"] == "META4,SAP"

    def test_no_signal_at_all_returns_none_ml_fields(self):
        result = _build_merge_result({"predicted": set(), "scores": {}}, {}, threshold_aplicado=0.5)
        assert result["ml_tecnologias"] is None
        assert result["ml_proba_max"] is None
        assert result["ml_tech_principal"] is None
        assert result["pliego_scores"] == []


class TestMergeDocSignals:
    """Orquestación: lectura de señales, dedupe de eventos por ``merged_at``
    y fail-open. La aritmética del merge en sí se prueba en
    ``TestBuildMergeResult``; aquí el repo se mockea con ``merge_with_lock``
    invocando el ``compute`` recibido contra un estado fijo, simulando lo que
    hace la transacción real sin tocar BD."""

    @staticmethod
    def _repo_with_state(state: dict[str, object]) -> MagicMock:
        repo = MagicMock()

        def _merge_with_lock(_licitacion_id: str, compute: object) -> object:
            return compute(state)  # type: ignore[operator]

        repo.merge_with_lock.side_effect = _merge_with_lock
        return repo

    def test_emits_one_event_per_first_time_detection(self):
        repo = self._repo_with_state({"predicted": set(), "scores": {}})
        repo.list_signals_for_merge.return_value = [_signal_row()]

        with (
            patch("services.tech_signal.TecnologiaPliegoRepository", return_value=repo),
            patch("services.tech_signal.append_event") as append_event,
        ):
            result = merge_doc_signals(licitacion_ids=["L1"])

        assert result == {"licitaciones_merged": 1, "events_emitted": 1, "errors": 0}
        append_event.assert_called_once()
        assert append_event.call_args.args[0] == "licitacion.tecnologia_pliego"
        repo.stamp_merged.assert_called_once()
        assert repo.stamp_merged.call_args.args[0] == [("L1", "META4", "keywords")]

    def test_already_merged_row_does_not_re_emit_event_but_still_merges(self):
        repo = self._repo_with_state({"predicted": set(), "scores": {}})
        repo.list_signals_for_merge.return_value = [
            _signal_row(merged_at="2026-08-01T00:00:00+00:00")
        ]

        with (
            patch("services.tech_signal.TecnologiaPliegoRepository", return_value=repo),
            patch("services.tech_signal.append_event") as append_event,
        ):
            result = merge_doc_signals(licitacion_ids=["L1"])

        append_event.assert_not_called()
        repo.stamp_merged.assert_not_called()
        assert result["events_emitted"] == 0
        assert result["licitaciones_merged"] == 1  # el merge SÍ se re-aplica

    def test_two_methods_tied_score_both_get_their_own_event(self):
        """Antes: elegir un único 'best row' por tecnología con comparación
        estricta '>' dejaba sin evento a un empate. Ahora cada (tecnologia,
        method) no fusionada emite su propio evento, sin importar el score
        relativo de otros métodos para la misma tecnología."""
        repo = self._repo_with_state({"predicted": set(), "scores": {}})
        repo.list_signals_for_merge.return_value = [
            _signal_row(method="keywords", score=0.6, merged_at=None),
            _signal_row(method="llm", score=0.6, merged_at=None, evidence_json="[]"),
        ]

        with (
            patch("services.tech_signal.TecnologiaPliegoRepository", return_value=repo),
            patch("services.tech_signal.append_event") as append_event,
        ):
            result = merge_doc_signals(licitacion_ids=["L1"])

        assert result["events_emitted"] == 2
        methods_emitted = {call.args[3]["method"] for call in append_event.call_args_list}
        assert methods_emitted == {"keywords", "llm"}

    def test_a_broken_licitacion_does_not_abort_the_batch(self):
        repo = MagicMock()
        repo.list_signals_for_merge.return_value = [
            _signal_row(licitacion_id="L-BAD"),
            _signal_row(licitacion_id="L-OK"),
        ]
        repo.merge_with_lock.side_effect = [
            RuntimeError("boom"),
            {
                "ml_tecnologias": "META4",
                "ml_proba_max": 0.8,
                "ml_tech_principal": "META4",
                "pliego_scores": [("META4", 0.8)],
                "threshold_aplicado": 0.5,
                "existing_scores": {},
                "full_scores": {"META4": 0.8},
            },
        ]

        with (
            patch("services.tech_signal.TecnologiaPliegoRepository", return_value=repo),
            patch("services.tech_signal.append_event"),
        ):
            result = merge_doc_signals()

        assert result["errors"] == 1
        assert result["licitaciones_merged"] == 1

    def test_append_event_failure_does_not_abort_the_rest_of_the_batch(self):
        """Un fallo emitiendo el evento de L-BAD (ej. error transitorio de
        BD) no debe abortar el merge de L-OK, ni dejar sin fusionar (los
        datos ya escritos vía merge_with_lock) a ninguna licitación."""
        repo = self._repo_with_state({"predicted": set(), "scores": {}})
        repo.list_signals_for_merge.return_value = [
            _signal_row(licitacion_id="L-BAD"),
            _signal_row(licitacion_id="L-OK"),
        ]

        with (
            patch("services.tech_signal.TecnologiaPliegoRepository", return_value=repo),
            patch(
                "services.tech_signal.append_event",
                side_effect=[RuntimeError("boom"), None],
            ),
        ):
            result = merge_doc_signals()

        # Ambas licitaciones se fusionaron (merge_with_lock no falló para
        # ninguna); solo L-OK logró emitir+estampar su evento.
        assert result["licitaciones_merged"] == 2
        assert result["errors"] == 0
        assert result["events_emitted"] == 1

    def test_evidence_is_json_decoded_in_the_event_payload(self):
        repo = self._repo_with_state({"predicted": set(), "scores": {}})
        repo.list_signals_for_merge.return_value = [
            _signal_row(matched_terms='["meta4", "recursos humanos"]')
        ]

        with (
            patch("services.tech_signal.TecnologiaPliegoRepository", return_value=repo),
            patch("services.tech_signal.append_event") as append_event,
        ):
            merge_doc_signals(licitacion_ids=["L1"])

        payload = append_event.call_args.args[3]
        assert payload["evidencia"] == ["meta4", "recursos humanos"]

    def test_no_signals_is_a_cheap_noop(self):
        repo = MagicMock()
        repo.list_signals_for_merge.return_value = []

        with patch("services.tech_signal.TecnologiaPliegoRepository", return_value=repo):
            result = merge_doc_signals()

        assert result == {"licitaciones_merged": 0, "events_emitted": 0, "errors": 0}
        repo.merge_with_lock.assert_not_called()
        repo.stamp_merged.assert_not_called()
