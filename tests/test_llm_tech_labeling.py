"""Tests del etiquetado de tecnología por LLM sobre metadata.

La frontera con el proveedor (``stream_llm_response``) se mockea siempre: un
test que llame al LLM real cuesta dinero y no es determinista. Lo que sí se
ejercita de verdad es el contrato de fallo del job, que es donde un error
corrompe estado: un item que falla no debe quedar marcado como procesado.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from config import settings
from config.keywords import TECH_LABELS
from db.repositories.tecnologia_pliego import TecnologiaPliegoRepository
from services.llm_tech_labeling import (
    METHOD,
    Clasificacion,
    build_docs,
    build_question,
    cita_verificable,
    classify_licitacion,
    normalizar_cita,
    parse_labels,
    signal_version,
    texto_enviado,
)

#: Texto «enviado» de los tests de parseo: las citas de las respuestas salen
#: de aquí, y las que no están aquí se descartan.
_TEXTO = (
    "[EXP-1] Migración a SAP S/4HANA y soporte de Oracle Database\n"
    "Descripción: \n"
    "--- Fragmento de pliego (descripcion del anuncio) ---\n"
    "Licencias Oracle Database y mantenimiento evolutivo del ERP."
)

# ── Prompt y parseo (puros, sin BD ni red) ────────────────────────────────


class TestBuildQuestion:
    def test_fits_client_validation_limits(self):
        """El validador real del cliente acepta la pregunta en su modo.

        ``clasificacion`` es plantilla interna: su tope es
        ``MAX_INTERNAL_QUESTION_LEN`` y no los 2000 caracteres de /ask, que la
        pregunta supera desde que lleva una definición por etiqueta.
        """
        from llm.client import _validate_request

        _validate_request(
            build_question(),
            build_docs({"id_externo": "EXP-1", "titulo": "t", "descripcion": "d"}),
            settings.LLM_TECH_LABELING_MODEL,
            mode="clasificacion",
        )

    def test_lists_every_label_with_its_definition(self):
        """Sin definición, «DESARROLLO» se lee como desarrollo nuevo y el
        mantenimiento de una aplicación a medida se queda sin etiqueta."""
        from config.keywords import TECH_DEFINICIONES

        question = build_question()
        for label in TECH_LABELS:
            assert f"- {label}: {TECH_DEFINICIONES[label]}" in question

    def test_generic_it_work_goes_to_the_category_whose_definition_covers_it(self):
        question = build_question()
        assert "cuya definición lo cubre" in question
        assert "Si ninguna definición lo cubre" in question

    def test_declares_the_empty_case(self):
        """El formato de salida para «no es TI» ya declara la lista vacía; sin
        eso el modelo fuerza la etiqueta más parecida."""
        assert '"tecnologias": []' in build_question()

    def test_asks_for_a_literal_quote_and_says_it_is_checked(self):
        """La cita se verifica contra el anuncio: el modelo tiene que saberlo
        para copiarla tal cual en vez de parafrasearla."""
        question = build_question()
        assert "cita literal" in question
        assert "se descarta" in question


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


def _parse(raw: str) -> Clasificacion:
    return parse_labels(raw, texto=_TEXTO, licitacion_id="EXP-1")


class TestParseLabels:
    def test_parses_plain_json(self):
        raw = '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.9, "evidencia": "S/4HANA"}]}'
        resultado = _parse(raw)

        assert set(resultado.scores) == {"SAP"}
        assert resultado.scores["SAP"].score == 0.9
        assert resultado.scores["SAP"].evidence == [{"quote": "S/4HANA", "source": "metadata"}]
        assert resultado.sin_evidencia == ()

    def test_parses_fenced_json(self):
        raw = (
            '```json\n{"tecnologias": [{"tecnologia": "ORACLE", "confidence": 0.7, '
            '"evidencia": "Oracle Database"}]}\n```'
        )
        assert set(_parse(raw).scores) == {"ORACLE"}

    def test_normalizes_case_and_whitespace(self):
        raw = '{"tecnologias": [{"tecnologia": " sap ", "confidence": 0.8, "evidencia": "SAP"}]}'
        assert set(_parse(raw).scores) == {"SAP"}

    def test_drops_labels_outside_the_vocabulary(self):
        """Vocabulario cerrado: lo inventado se descarta sin tumbar el resto."""
        raw = (
            '{"tecnologias": ['
            '{"tecnologia": "COBOL_MAINFRAME", "confidence": 0.9, "evidencia": "ERP"},'
            '{"tecnologia": "SAP", "confidence": 0.6, "evidencia": "SAP"}]}'
        )
        resultado = _parse(raw)
        assert set(resultado.scores) == {"SAP"}
        assert resultado.sin_evidencia == ()

    def test_drops_low_confidence_noise(self):
        """Ruido por confianza, no por cita: no cuenta como «sin evidencia»."""
        raw = '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.05}]}'
        assert _parse(raw) == Clasificacion(scores={}, sin_evidencia=())

    def test_keeps_the_highest_confidence_on_duplicates(self):
        raw = (
            '{"tecnologias": ['
            '{"tecnologia": "SAP", "confidence": 0.4, "evidencia": "SAP"},'
            '{"tecnologia": "SAP", "confidence": 0.85, "evidencia": "S/4HANA"}]}'
        )
        assert _parse(raw).scores["SAP"].score == 0.85

    def test_empty_list_is_a_valid_answer(self):
        assert _parse('{"tecnologias": []}') == Clasificacion(scores={}, sin_evidencia=())

    def test_rejects_confidence_out_of_range(self):
        raw = '{"tecnologias": [{"tecnologia": "SAP", "confidence": 4.2}]}'
        with pytest.raises(ValueError):
            _parse(raw)

    def test_rejects_text_without_json(self):
        with pytest.raises(ValueError):
            _parse("No he podido clasificar esta licitación.")


class TestEsTi:
    def test_es_ti_con_familias(self):
        raw = json.dumps(
            {
                "es_ti": True,
                "confianza_es_ti": 0.9,
                "tecnologias": [
                    {
                        "tecnologia": "ERP",
                        "confidence": 0.8,
                        "evidencia": "mantenimiento evolutivo del ERP",
                    }
                ],
                "otros_fabricantes": [],
            }
        )
        resultado = _parse(raw)
        assert resultado.es_ti is True
        assert resultado.confianza_es_ti == 0.9
        assert set(resultado.scores) == {"ERP"}

    def test_si_no_es_ti_se_descartan_las_familias(self):
        """Una familia en un contrato que no es TI es una contradicción del
        modelo: gana el «no es TI», que es la pregunta de nivel 1."""
        raw = json.dumps(
            {
                "es_ti": False,
                "confianza_es_ti": 0.8,
                "tecnologias": [
                    {
                        "tecnologia": "ERP",
                        "confidence": 0.7,
                        "evidencia": "mantenimiento evolutivo del ERP",
                    }
                ],
            }
        )
        resultado = _parse(raw)
        assert resultado.es_ti is False
        assert resultado.scores == {}

    def test_sin_es_ti_la_respuesta_sigue_valiendo(self):
        raw = '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.9, "evidencia": "S/4HANA"}]}'
        resultado = _parse(raw)
        assert resultado.es_ti is None
        assert set(resultado.scores) == {"SAP"}

    def test_otros_fabricantes_se_limpian(self):
        raw = json.dumps(
            {
                "es_ti": True,
                "tecnologias": [],
                "otros_fabricantes": [" Qlik ", "qlik", "", "Z" * 90],
            }
        )
        assert _parse(raw).otros_fabricantes == ("Qlik", "Z" * 60)

    def test_la_version_del_prompt_es_v3(self):
        assert signal_version("m").startswith("llm-meta-v3/")


def _respuesta_v3(**informativos: object) -> str:
    """Una respuesta v3 válida (TI, ERP con cita) con los campos informativos dados."""
    return json.dumps(
        {
            "es_ti": True,
            "tecnologias": [
                {
                    "tecnologia": "ERP",
                    "confidence": 0.8,
                    "evidencia": "mantenimiento evolutivo del ERP",
                }
            ],
            **informativos,
        }
    )


class TestCamposInformativosSeDegradan:
    """``otros_fabricantes`` y ``confianza_es_ti`` son informativos: uno mal
    formado no puede anular la respuesta entera. Si la anulara, la licitación
    seguiría pendiente y se volvería a mandar (y a pagar) en cada corrida, y
    como la cola va de lo más nuevo a lo más viejo, también frenaría el
    backlog. ``es_ti``, las familias y su evidencia se validan como siempre."""

    @staticmethod
    def _sigue_valiendo(resultado: Clasificacion) -> None:
        assert resultado.es_ti is True
        assert set(resultado.scores) == {"ERP"}

    def test_otros_fabricantes_null_es_lista_vacia(self):
        resultado = _parse(_respuesta_v3(otros_fabricantes=None))
        self._sigue_valiendo(resultado)
        assert resultado.otros_fabricantes == ()

    def test_otros_fabricantes_que_no_es_lista_es_lista_vacia(self):
        resultado = _parse(_respuesta_v3(otros_fabricantes="Qlik"))
        self._sigue_valiendo(resultado)
        assert resultado.otros_fabricantes == ()

    def test_las_entradas_de_otros_fabricantes_que_no_son_texto_se_descartan(self):
        resultado = _parse(_respuesta_v3(otros_fabricantes=["Qlik", 3, None, {"n": "x"}, "SUSE"]))
        self._sigue_valiendo(resultado)
        assert resultado.otros_fabricantes == ("Qlik", "SUSE")

    @pytest.mark.parametrize("confianza", [1.5, -0.1])
    def test_confianza_es_ti_fuera_de_rango_es_none(self, confianza: float):
        resultado = _parse(_respuesta_v3(confianza_es_ti=confianza))
        self._sigue_valiendo(resultado)
        assert resultado.confianza_es_ti is None

    @pytest.mark.parametrize("confianza", ["alta", True, [0.9]])
    def test_confianza_es_ti_que_no_es_un_numero_es_none(self, confianza: object):
        """Un booleano tampoco: ``true`` no es una confianza, aunque pydantic
        lo convertiría en 1.0."""
        resultado = _parse(_respuesta_v3(confianza_es_ti=confianza))
        self._sigue_valiendo(resultado)
        assert resultado.confianza_es_ti is None

    def test_una_confianza_valida_se_conserva(self):
        assert _parse(_respuesta_v3(confianza_es_ti=0.85)).confianza_es_ti == 0.85

    def test_es_ti_sigue_validandose_estricto(self):
        with pytest.raises(ValueError):
            _parse(json.dumps({"es_ti": "puede", "tecnologias": []}))


class TestEvidencia:
    """Una etiqueta vale lo que su cita: si no está en el texto que el modelo
    recibió, no se persiste."""

    def test_a_label_with_an_empty_quote_is_dropped(self):
        raw = '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.9, "evidencia": ""}]}'
        assert _parse(raw) == Clasificacion(scores={}, sin_evidencia=("SAP",))

    def test_a_missing_quote_counts_as_empty(self):
        raw = '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.9}]}'
        assert _parse(raw).sin_evidencia == ("SAP",)

    def test_a_null_quote_drops_the_label_not_the_answer(self):
        """``null`` es una cita vacía: cae esa etiqueta, no la respuesta entera
        (que dejaría la licitación pendiente y se repagaría cada corrida)."""
        raw = (
            '{"tecnologias": ['
            '{"tecnologia": "SAP", "confidence": 0.9, "evidencia": null},'
            '{"tecnologia": "ORACLE", "confidence": 0.8, "evidencia": "Oracle Database"}]}'
        )
        resultado = _parse(raw)

        assert set(resultado.scores) == {"ORACLE"}
        assert resultado.sin_evidencia == ("SAP",)

    def test_a_quote_that_is_not_in_the_text_is_dropped_and_logged(self):
        raw = (
            '{"tecnologias": [{"tecnologia": "SALESFORCE", "confidence": 0.9, '
            '"evidencia": "Implantación de Salesforce Service Cloud"}]}'
        )
        with patch("services.llm_tech_labeling.log") as mock_log:
            resultado = _parse(raw)

        assert resultado == Clasificacion(scores={}, sin_evidencia=("SALESFORCE",))
        mock_log.info.assert_any_call(
            "llm_tech_label_sin_evidencia",
            licitacion_id="EXP-1",
            tecnologia="SALESFORCE",
            evidencia="Implantación de Salesforce Service Cloud",
        )

    def test_keeps_the_verified_labels_and_reports_the_rest(self):
        raw = (
            '{"tecnologias": ['
            '{"tecnologia": "SAP", "confidence": 0.9, "evidencia": "Migración a SAP S/4HANA"},'
            '{"tecnologia": "WORKDAY", "confidence": 0.8, "evidencia": "Workday HCM"}]}'
        )
        resultado = _parse(raw)

        assert set(resultado.scores) == {"SAP"}
        assert resultado.sin_evidencia == ("WORKDAY",)

    def test_a_verified_duplicate_rescues_the_label(self):
        """Si el modelo repite una etiqueta, basta con que una de sus citas sea
        buena: la de más confianza no gana si es la inventada."""
        raw = (
            '{"tecnologias": ['
            '{"tecnologia": "SAP", "confidence": 0.95, "evidencia": "SAP Business One"},'
            '{"tecnologia": "SAP", "confidence": 0.7, "evidencia": "S/4HANA"}]}'
        )
        resultado = _parse(raw)

        assert resultado.scores["SAP"].score == 0.7
        assert resultado.sin_evidencia == ()


class TestCitaVerificable:
    @pytest.mark.parametrize(
        ("cita", "texto"),
        [
            ("Gestion economico financiera", "Gestión económico financiera"),
            ("MANTENIMIENTO sap", "Mantenimiento SAP"),
            ('sistema "Aries"', "sistema «Aries»"),
            (
                'sistema "Aries"',
                "sistema \N{LEFT DOUBLE QUOTATION MARK}Aries\N{RIGHT DOUBLE QUOTATION MARK}",
            ),
            ("l'aplicació", "l\N{RIGHT SINGLE QUOTATION MARK}aplicació"),
            ("l'aplicació", "l\N{ACUTE ACCENT}aplicació"),
            ("Lote 1 - Soporte", "Lote 1 \N{EN DASH} Soporte"),
            ("soporte del ERP", "soporte  del\nERP"),
            ('"soporte del ERP."', "Contrato de soporte del ERP municipal"),
        ],
        ids=[
            "tildes",
            "mayusculas",
            "comillas-angulares",
            "comillas-tipograficas",
            "apostrofo-tipografico",
            "acento-como-apostrofo",
            "guion-tipografico",
            "espacios-y-saltos",
            "comillas-y-punto-de-la-cita",
        ],
    )
    def test_matches_after_normalising(self, cita: str, texto: str):
        assert cita_verificable(cita, normalizar_cita(texto))

    @pytest.mark.parametrize("cita", ["", "   ", '""', "...", " - "])
    def test_an_empty_quote_is_never_evidence(self, cita: str):
        assert not cita_verificable(cita, normalizar_cita('Soporte del ERP ... - ""'))

    def test_a_paraphrase_is_not_a_quote(self):
        texto = normalizar_cita("Mantenimiento del sistema SAP")
        assert not cita_verificable("mantenimiento SAP", texto)


#: Anuncio de los tests de texto enviado y de clasificación con cita.
_LIC_CON_SAP = {
    "id_externo": "EXP-T",
    "titulo": "Soporte del ERP municipal",
    "descripcion": "Mantenimiento evolutivo de SAP S/4HANA y de sus interfaces.",
    "cpv": "72267000",
    "organo_contratacion": "Ayuntamiento de Alcúdia",
}


class TestTextoEnviado:
    def test_is_exactly_the_context_block_the_model_receives(self):
        from llm.prompts import build_messages

        docs = build_docs(_LIC_CON_SAP)
        _system, messages = build_messages(build_question(), docs, [], mode="clasificacion")
        bloque = texto_enviado(docs)

        assert "Mantenimiento evolutivo de SAP S/4HANA" in bloque
        assert (
            f"<fuentes_no_confiables>\n{bloque}\n</fuentes_no_confiables>"
            in messages[-1]["content"]
        )

    def test_leaves_the_question_out(self):
        """Una cita copiada de las definiciones no es evidencia del anuncio."""
        assert "Productos de SAP" not in texto_enviado(build_docs(_LIC_CON_SAP))


class TestClassifyLicitacion:
    @staticmethod
    def _classify(raw: str) -> Clasificacion:
        with patch("services.llm_tech_labeling.stream_llm_response", return_value=iter([raw])):
            return classify_licitacion(_LIC_CON_SAP, model=settings.LLM_TECH_LABELING_MODEL)

    def test_checks_the_quote_against_the_announcement(self):
        raw = (
            '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.9, '
            '"evidencia": "mantenimiento evolutivo de SAP S/4HANA"}]}'
        )
        assert set(self._classify(raw).scores) == {"SAP"}

    def test_a_quote_taken_from_the_definitions_is_not_evidence(self):
        raw = (
            '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.9, '
            '"evidencia": "Productos de SAP"}]}'
        )
        assert self._classify(raw) == Clasificacion(scores={}, sin_evidencia=("SAP",))

    def test_the_structural_metadata_is_quotable(self):
        """El CPV también viaja en el bloque: citarlo tal cual es evidencia."""
        raw = (
            '{"tecnologias": [{"tecnologia": "DESARROLLO", "confidence": 0.7, '
            '"evidencia": "CPV: 72267000"}]}'
        )
        assert set(self._classify(raw).scores) == {"DESARROLLO"}


class TestSignalVersion:
    def test_includes_prompt_and_model(self):
        """Cambiar de modelo debe dejar pendiente al universo entero."""
        assert signal_version("deepseek-ai/deepseek-v4-pro") != signal_version("gpt-4o-mini")

    def test_the_prompt_with_the_level_1_question_is_v3(self):
        """La pregunta de nivel 1 (``es_ti``) es otro prompt: el corpus
        clasificado con el v2 vuelve a la cola en vez de mezclarse con el
        nuevo."""
        assert signal_version("nvidia/modelo") == "llm-meta-v3/nvidia/modelo"


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

    def test_answers_without_evidence_are_progress_not_a_systemic_failure(self):
        """El proveedor respondió y la licitación quedó procesada: que sus
        citas no se sostengan no es infraestructura rota."""
        from scheduler.jobs.llm_tech_labeling import batch_failed_systemically

        assert batch_failed_systemically(self._counts(error=3, sin_evidencia=5)) is False


class TestSinEvidenciaEnElJob:
    """Qué persiste el job según lo que quede tras verificar las citas.

    Sin BD: repositorio, guard, merge, feedback y ``record_event`` se
    sustituyen; lo que se prueba es la decisión del bucle.
    """

    @staticmethod
    def _run_with(raw: str, monkeypatch):
        from unittest.mock import MagicMock

        from scheduler.jobs.llm_tech_labeling import run

        monkeypatch.setattr(settings, "LLM_TECH_LABELING_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "LLM_TECH_FEEDBACK_ENABLED", True, raising=False)
        repo = MagicMock()
        repo.list_metadata_pending_llm_signal.return_value = [
            {
                "id_externo": "EXP-E1",
                "titulo": "Soporte del ERP municipal",
                "descripcion": "Mantenimiento evolutivo de la aplicación de nóminas.",
            }
        ]
        with (
            patch(
                "db.repositories.tecnologia_pliego.TecnologiaPliegoRepository", return_value=repo
            ),
            patch("llm.budget.get_budget_guard"),
            patch("observability.ops_events.record_event"),
            patch(
                "services.tech_signal.merge_doc_signals", return_value={"licitaciones_merged": 0}
            ),
            patch("db.repositories.feedback.FeedbackRepository") as feedback,
            patch("services.llm_tech_labeling.stream_llm_response", return_value=iter([raw])),
        ):
            counts = run()
        return counts, repo, feedback

    def test_all_labels_without_evidence_store_the_sin_evidencia_sentinel(self, monkeypatch):
        """No es «ninguna tecnología»: el LLM afirmó una y no la sostuvo."""
        raw = (
            '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.95, '
            '"evidencia": "Migración a SAP S/4HANA"}]}'
        )
        counts, repo, feedback = self._run_with(raw, monkeypatch)

        repo.upsert_signals.assert_called_once_with(
            "EXP-E1",
            method=METHOD,
            signal_version=signal_version(settings.LLM_TECH_LABELING_MODEL),
            scores={},
            sin_evidencia=True,
        )
        assert counts["sin_evidencia"] == 1
        assert counts["no_signal"] == 0
        assert counts["scored"] == 0
        assert counts["etiquetas_sin_evidencia"] == 1
        # Tampoco un «no relevante» en la cola humana: es justo lo dudoso.
        feedback.assert_not_called()

    def test_a_genuine_empty_answer_still_writes_no_signal(self, monkeypatch):
        counts, repo, _ = self._run_with('{"tecnologias": []}', monkeypatch)

        assert repo.upsert_signals.call_args.kwargs["scores"] == {}
        assert repo.upsert_signals.call_args.kwargs["sin_evidencia"] is False
        assert counts["no_signal"] == 1
        assert counts["sin_evidencia"] == 0
        assert counts["etiquetas_sin_evidencia"] == 0

    def test_a_partial_drop_keeps_the_verified_labels(self, monkeypatch):
        raw = (
            '{"tecnologias": ['
            '{"tecnologia": "DESARROLLO", "confidence": 0.9, '
            '"evidencia": "Mantenimiento evolutivo de la aplicación"},'
            '{"tecnologia": "SAP", "confidence": 0.9, "evidencia": "SAP S/4HANA"}]}'
        )
        counts, repo, _ = self._run_with(raw, monkeypatch)

        assert set(repo.upsert_signals.call_args.kwargs["scores"]) == {"DESARROLLO"}
        assert repo.upsert_signals.call_args.kwargs["sin_evidencia"] is False
        assert counts["scored"] == 1
        assert counts["sin_evidencia"] == 0
        assert counts["etiquetas_sin_evidencia"] == 1

    def test_escribe_el_marcador_de_es_ti_en_la_fila_de_familias(self, monkeypatch):
        """El marcador vive en ``method=METHOD`` (``llm_metadata``) -- la
        CHECK ``ck_lic_tec_pliego_method`` de la tabla no admite un
        ``method`` propio sin migración (F5) -- así que va en la MISMA
        llamada que las familias, no en una aparte."""
        from db.repositories.tecnologia_pliego import NO_ES_TI_SENTINEL, TechSignal

        raw = '{"es_ti": false, "confianza_es_ti": 0.85, "tecnologias": []}'
        counts, repo, _feedback = self._run_with(raw, monkeypatch)

        version = signal_version(settings.LLM_TECH_LABELING_MODEL)
        repo.upsert_signals.assert_called_once_with(
            "EXP-E1",
            method=METHOD,
            signal_version=version,
            scores={
                NO_ES_TI_SENTINEL: TechSignal(
                    score=0.0,
                    evidence=[{"es_ti": False, "confianza": 0.85, "otros_fabricantes": []}],
                )
            },
            sin_evidencia=False,
        )
        assert counts["es_ti_no"] == 1

    def test_sin_es_ti_la_fila_no_lleva_marcador(self, monkeypatch):
        from db.repositories.tecnologia_pliego import ES_TI_SENTINEL, NO_ES_TI_SENTINEL

        raw = '{"tecnologias": []}'
        counts, repo, _feedback = self._run_with(raw, monkeypatch)

        scores = repo.upsert_signals.call_args.kwargs["scores"]
        assert ES_TI_SENTINEL not in scores
        assert NO_ES_TI_SENTINEL not in scores
        assert counts["es_ti_sin_respuesta"] == 1

    def test_una_sola_llamada_lleva_familias_y_marcador_juntos(self, monkeypatch):
        """Familias y marcador van en la MISMA llamada: dos llamadas al
        mismo ``method`` se pisarían la una a la otra (``upsert_signals``
        borra lo que el ``method`` de la corrida en curso ya no detecta),
        en vez de sumarse."""
        from db.repositories.tecnologia_pliego import ES_TI_SENTINEL

        raw = (
            '{"es_ti": true, "confianza_es_ti": 0.9, "tecnologias": '
            '[{"tecnologia": "SAP", "confidence": 0.9, '
            '"evidencia": "Mantenimiento evolutivo de la aplicación de nóminas"}]}'
        )
        counts, repo, _feedback = self._run_with(raw, monkeypatch)

        assert repo.upsert_signals.call_count == 1
        scores = repo.upsert_signals.call_args.kwargs["scores"]
        assert set(scores) == {"SAP", ES_TI_SENTINEL}
        assert scores[ES_TI_SENTINEL].score == 0.0
        assert counts["scored"] == 1
        assert counts["es_ti_si"] == 1


class TestMuestraModeEnElJob:
    """Modo muestra estratificada (F2, spec §3.2): con ``muestra`` no nulo el
    job cambia de camino de selección -- el resto del bucle (clasificar,
    fundir, contar) no se entera, así que se mockea igual que en
    ``TestSinEvidenciaEnElJob``."""

    @staticmethod
    def _run_with(monkeypatch, *, muestra=50, semilla="sem-x", pendientes=None):
        from unittest.mock import MagicMock

        from scheduler.jobs.llm_tech_labeling import run

        monkeypatch.setattr(settings, "LLM_TECH_LABELING_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "LLM_TECH_FEEDBACK_ENABLED", False, raising=False)
        # Deliberadamente bajo: la prueba de que este tope NO acota la
        # muestra es que, aun así, se procesan todos los ``pendientes``.
        monkeypatch.setattr(settings, "LLM_TECH_LABELING_BATCH", 1, raising=False)
        if pendientes is None:
            pendientes = [
                {
                    "id_externo": "EXP-M1",
                    "titulo": "Soporte del ERP municipal",
                    "descripcion": "Mantenimiento evolutivo de la aplicación de nóminas.",
                }
            ]
        repo = MagicMock()
        repo.tamanos_estratos_muestra.return_value = {"pscp|otros|es|sin_kw|sin_modelo": 5}
        repo.list_muestra_pending_llm_signal.return_value = pendientes
        # Un iterador propio por item: ``stream_llm_response`` se llama una
        # vez por licitación y un ``return_value`` fijo se agotaría tras la
        # primera (ver ``TestRunJob.test_one_failure_does_not_abort_the_batch``
        # para el mismo patrón con ``side_effect``).
        respuestas = [iter(['{"tecnologias": []}']) for _ in pendientes]
        with (
            patch(
                "db.repositories.tecnologia_pliego.TecnologiaPliegoRepository", return_value=repo
            ),
            patch("llm.budget.get_budget_guard"),
            patch("observability.ops_events.record_event"),
            patch(
                "services.tech_signal.merge_doc_signals", return_value={"licitaciones_merged": 0}
            ),
            patch("services.llm_tech_labeling.stream_llm_response", side_effect=respuestas),
        ):
            counts = run(muestra=muestra, semilla=semilla)
        return counts, repo

    def test_uses_the_sample_path_not_the_backlog(self, monkeypatch):
        counts, repo = self._run_with(monkeypatch)

        repo.list_muestra_pending_llm_signal.assert_called_once()
        repo.list_metadata_pending_llm_signal.assert_not_called()
        assert counts["no_signal"] == 1

    def test_passes_the_quotas_from_repartir_cuotas(self, monkeypatch):
        from services.ml.muestra_estratificada import repartir_cuotas

        counts, repo = self._run_with(monkeypatch, muestra=50, semilla="sem-x")

        repo.tamanos_estratos_muestra.assert_called_once_with()
        esperado = repartir_cuotas({"pscp|otros|es|sin_kw|sin_modelo": 5}, 50)
        repo.list_muestra_pending_llm_signal.assert_called_once_with(
            cuotas=esperado,
            semilla="sem-x",
            signal_version=signal_version(settings.LLM_TECH_LABELING_MODEL),
            method=METHOD,
        )
        assert counts["no_signal"] == 1

    def test_counts_include_muestra_and_muestra_pendientes(self, monkeypatch):
        pendientes = [
            {"id_externo": "EXP-M1", "titulo": "A", "descripcion": "Mantenimiento del ERP"},
            {"id_externo": "EXP-M2", "titulo": "B", "descripcion": "Mantenimiento del ERP"},
        ]

        counts, _repo = self._run_with(monkeypatch, muestra=50, pendientes=pendientes)

        assert counts["muestra"] == 50
        assert counts["muestra_pendientes"] == 2

    def test_llm_tech_labeling_batch_does_not_cap_the_sample(self, monkeypatch):
        """El tope de lote del backlog (``LLM_TECH_LABELING_BATCH=1`` en
        ``_run_with``) no se aplica al camino de muestra: el drenado manual
        procesa la muestra pendiente entera."""
        pendientes = [
            {"id_externo": f"EXP-M{i}", "titulo": "A", "descripcion": "Mantenimiento del ERP"}
            for i in range(3)
        ]

        counts, repo = self._run_with(monkeypatch, muestra=50, pendientes=pendientes)

        repo.list_muestra_pending_llm_signal.assert_called_once()
        assert counts["no_signal"] == 3
        assert counts["muestra_pendientes"] == 3


#: Resumen mínimo que no dispara ``batch_failed_systemically`` -- estas
#: pruebas verifican el parseo de argumentos, no la decisión de fallo.
_RESUMEN_CLI_OK = {"scored": 0, "no_signal": 0, "error": 0, "disabled": 0}


class TestRunCli:
    """Parseo de argumentos del drenado manual (F2, spec §3.2): con flags pasa
    lo pedido a ``run``; sin flags, el comportamiento de siempre."""

    def test_sin_flags_llama_a_run_con_los_valores_por_defecto(self):
        from services.ml.muestra_estratificada import SEMILLA_POR_DEFECTO

        with (
            patch("db.database.init_db") as init_db,
            patch("scheduler.jobs.llm_tech_labeling.run", return_value=_RESUMEN_CLI_OK) as run_mock,
        ):
            from scheduler.jobs.llm_tech_labeling import run_cli

            codigo = run_cli([])

        run_mock.assert_called_once_with(muestra=None, semilla=SEMILLA_POR_DEFECTO)
        init_db.assert_called_once_with()
        assert codigo == 0

    def test_muestra_y_semilla_se_pasan_a_run(self):
        with (
            patch("db.database.init_db"),
            patch("scheduler.jobs.llm_tech_labeling.run", return_value=_RESUMEN_CLI_OK) as run_mock,
        ):
            from scheduler.jobs.llm_tech_labeling import run_cli

            codigo = run_cli(["--muestra", "10", "--semilla", "x"])

        run_mock.assert_called_once_with(muestra=10, semilla="x")
        assert codigo == 0

    def test_muestra_cero_se_rechaza(self):
        with (
            patch("db.database.init_db"),
            patch("scheduler.jobs.llm_tech_labeling.run") as run_mock,
            pytest.raises(SystemExit),
        ):
            from scheduler.jobs.llm_tech_labeling import run_cli

            run_cli(["--muestra", "0"])

        run_mock.assert_not_called()


class TestEstratoMuestraSqlPlaceholders:
    """Regresión (fix round 1 de revisión): ``_ESTRATO_MUESTRA_SQL`` se
    empalma dentro de las consultas de ``TecnologiaPliegoRepository``, y
    ``list_muestra_pending_llm_signal`` las ejecuta con un dict de parámetros
    (``c.execute(sql, {...})``). psycopg tokeniza el SQL entero buscando
    placeholders (``%s``/``%b``/``%t``/``%(nombre)s``) antes de tocar la red;
    un ``%`` suelto -- el que dejaba un ``LIKE 'placsp%'`` -- no calza
    ninguna forma reconocida y psycopg 3 lanza ``ProgrammingError`` en el
    primer ``execute`` con quotas no vacías. Mismo bug que documenta ADR-018
    para ``db/repositories/extraction_runs.py:104-107`` (ahí se optó por
    escapar a ``%%``; aquí, al no hacer falta ``LIKE``, se quita el ``%`` del
    todo con ``starts_with``)."""

    def test_la_constante_no_tiene_ningun_porcentaje(self):
        from db.repositories.tecnologia_pliego import _ESTRATO_MUESTRA_SQL

        assert "%" not in _ESTRATO_MUESTRA_SQL

    def test_la_query_ensamblada_no_deja_placeholders_sueltos(self, monkeypatch):
        """Sin BD: ``connect_read`` se sustituye por un doble que solo
        captura el SQL que se le pasaría a psycopg. Tras quitar los
        placeholders válidos (``%(nombre)s``) no debe quedar ningún ``%`` --
        si quedara alguno, sería exactamente el bug que cubre esta clase."""
        import re
        from contextlib import contextmanager

        from db.repositories.tecnologia_pliego import TecnologiaPliegoRepository

        capturado: dict[str, object] = {}

        class _CursorFalso:
            def __init__(self):
                self.description: list[object] = []

            def fetchall(self):
                return []

        class _ConexionFalsa:
            def execute(self, sql, params=None):
                capturado["sql"] = sql
                capturado["params"] = params
                return _CursorFalso()

        @contextmanager
        def _connect_read_falso(*, statement_timeout_ms=None):
            yield _ConexionFalsa()

        monkeypatch.setattr("db.repositories.tecnologia_pliego.connect_read", _connect_read_falso)

        TecnologiaPliegoRepository().list_muestra_pending_llm_signal(
            cuotas={"pscp|otros|es|sin_kw|sin_modelo": 1}, semilla="s", signal_version="v1"
        )

        sql = capturado["sql"]
        assert isinstance(sql, str)
        sin_placeholders_validos = re.sub(r"%\([a-zA-Z_][a-zA-Z0-9_]*\)s", "", sql)
        assert "%" not in sin_placeholders_validos


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

    def test_rejected_key_reaches_the_step_message(self):
        """El mensaje del paso es el cuerpo del email de alerta: tiene que
        nombrar la causa, no solo el recuento de errores."""
        from scheduler.pipeline_runs import _run_llm_tech_labeling

        rechazado = {
            "scored": 0,
            "no_signal": 0,
            "error": 1,
            "disabled": 0,
            "credencial_rechazada": "El proveedor rechazó la API key (HTTP 401) para m",
        }
        with (
            patch("scheduler.jobs.llm_tech_labeling.run", return_value=rechazado),
            patch("scheduler.pipeline_runs._run_periodic", side_effect=lambda _n, _t, fn: fn()),
            pytest.raises(RuntimeError, match=r"HTTP 401"),
        ):
            _run_llm_tech_labeling()

    def test_unavailable_model_reaches_the_step_message(self):
        """Del 2026-09-21 al 2026-09-24 el email decía «respuesta vacía» ×200."""
        from scheduler.pipeline_runs import _run_llm_tech_labeling

        retirado = {
            "scored": 0,
            "no_signal": 0,
            "error": 1,
            "disabled": 0,
            "modelo_no_disponible": "El proveedor no sirve el modelo m (HTTP 410)",
        }
        with (
            patch("scheduler.jobs.llm_tech_labeling.run", return_value=retirado),
            patch("scheduler.pipeline_runs._run_periodic", side_effect=lambda _n, _t, fn: fn()),
            pytest.raises(RuntimeError, match=r"HTTP 410"),
        ):
            _run_llm_tech_labeling()


class TestRejectedKeyStopsTheBatch:
    """Con la key rechazada el lote se corta en el primer item y dice por qué.

    Sin BD: repositorio, guard y ``record_event`` se sustituyen, porque lo que
    se prueba es el bucle del job y no la persistencia.
    """

    def test_first_rejection_stops_the_batch_and_names_the_cause(self, monkeypatch):
        from unittest.mock import MagicMock

        from llm.providers import LLMAuthError
        from scheduler.jobs.llm_tech_labeling import batch_failed_systemically, run

        monkeypatch.setattr(settings, "LLM_TECH_LABELING_ENABLED", True, raising=False)
        repo = MagicMock()
        repo.list_metadata_pending_llm_signal.return_value = [
            {"id_externo": f"EXP-K{i}", "titulo": "t", "descripcion": "d"} for i in range(3)
        ]
        rechazo = LLMAuthError(model=settings.LLM_TECH_LABELING_MODEL, status_code=401)

        with (
            patch(
                "db.repositories.tecnologia_pliego.TecnologiaPliegoRepository", return_value=repo
            ),
            patch("llm.budget.get_budget_guard"),
            patch("observability.ops_events.record_event"),
            patch("services.llm_tech_labeling.stream_llm_response", side_effect=rechazo) as llm,
        ):
            counts = run()

        # Antes: una llamada 401 por item del lote (200 en producción).
        assert llm.call_count == 1
        assert counts["error"] == 1
        assert "HTTP 401" in counts["credencial_rechazada"]
        repo.upsert_signals.assert_not_called()
        assert batch_failed_systemically(counts) is True


class TestUnavailableModelStopsTheBatch:
    """Con el modelo retirado, el mismo corte que con la key, y con su nombre.

    El run #795 de scrape-daily (2026-09-21) hizo 200 llamadas y las 200 dieron
    410; como el paso fallaba, la ventana diaria no se consumía y cada pasada
    repetía las 200.
    """

    def test_first_410_stops_the_batch_and_names_the_model(self, monkeypatch):
        from unittest.mock import MagicMock

        from llm.providers import LLMModelUnavailableError
        from scheduler.jobs.llm_tech_labeling import batch_failed_systemically, run

        monkeypatch.setattr(settings, "LLM_TECH_LABELING_ENABLED", True, raising=False)
        repo = MagicMock()
        repo.list_metadata_pending_llm_signal.return_value = [
            {"id_externo": f"EXP-M{i}", "titulo": "t", "descripcion": "d"} for i in range(3)
        ]
        retirado = LLMModelUnavailableError(model=settings.LLM_TECH_LABELING_MODEL, status_code=410)

        with (
            patch(
                "db.repositories.tecnologia_pliego.TecnologiaPliegoRepository", return_value=repo
            ),
            patch("llm.budget.get_budget_guard"),
            patch("observability.ops_events.record_event"),
            patch("services.llm_tech_labeling.stream_llm_response", side_effect=retirado) as llm,
        ):
            counts = run()

        assert llm.call_count == 1
        assert counts["error"] == 1
        assert "HTTP 410" in counts["modelo_no_disponible"]
        assert "credencial_rechazada" not in counts
        repo.upsert_signals.assert_not_called()
        assert batch_failed_systemically(counts) is True


class TestWriteFeedbackSinBD:
    """``_write_feedback`` unitario, sin BD (``FeedbackRepository`` mockeado
    como en ``TestSinEvidenciaEnElJob._run_with``): ejercita directamente lo
    que ``TestWriteFeedback`` (que exige ``tmp_db`` y no corre en este
    entorno) no puede probar aquí.

    Quitar la puerta «familias sin confianza -> se omite» (ver el commit que
    introdujo ``es_ti``, cuando ``relevante`` dejó de derivarse de
    ``clasificacion.scores`` para ser ``clasificacion.es_ti`` tal cual) abrió
    un camino nuevo: ``es_ti=True`` con ``scores`` vacío o con todas las
    familias por debajo del umbral ahora SÍ escribe una fila (``relevante``
    es una respuesta del nivel 1, independiente de si el nivel 2 encontró
    algo confiado). Antes de esta tarea esa combinación se omitía.
    """

    @staticmethod
    def _call(clasificadas: dict[str, Clasificacion], monkeypatch, *, version: str = "v-test"):
        from scheduler.jobs.llm_tech_labeling import _write_feedback

        monkeypatch.setattr(settings, "LLM_TECH_FEEDBACK_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "LLM_TECH_FEEDBACK_MIN_CONF", 0.9, raising=False)
        with patch("db.repositories.feedback.FeedbackRepository") as feedback:
            feedback.return_value.existing_expedientes.return_value = set()
            counts = _write_feedback(clasificadas, version=version)
        return counts, feedback.return_value

    def test_es_ti_sin_ninguna_familia_escribe_relevante_sin_tecnologia(self, monkeypatch):
        """``scores`` vacío (nivel 2 no vio nada) no bloquea la fila: el
        nivel 1 ya contestó que sí es TI."""
        from scheduler.jobs.llm_tech_labeling import FEEDBACK_SOURCE

        clasificacion = Clasificacion(scores={}, es_ti=True, confianza_es_ti=0.9)
        counts, repo = self._call({"EXP-U1": clasificacion}, monkeypatch)

        repo.insert.assert_called_once_with(
            expediente="EXP-U1",
            relevante=True,
            nota=f"{FEEDBACK_SOURCE}:v-test",
            tecnologia=None,
            tecnologias_secundarias=[],
            source=FEEDBACK_SOURCE,
        )
        assert counts == {"feedback_escrito": 1, "feedback_omitido": 0}

    def test_es_ti_con_familias_por_debajo_del_umbral_escribe_igual(self, monkeypatch):
        """Hay familias, pero ninguna llega a ``LLM_TECH_FEEDBACK_MIN_CONF``:
        la fila se escribe igual (``relevante`` no depende de ellas), solo
        que sin tecnología principal ni secundarias."""
        from db.repositories.tecnologia_pliego import TechSignal
        from scheduler.jobs.llm_tech_labeling import FEEDBACK_SOURCE

        clasificacion = Clasificacion(
            scores={"SAP": TechSignal(score=0.5), "ORACLE": TechSignal(score=0.3)},
            es_ti=True,
            confianza_es_ti=0.9,
        )
        counts, repo = self._call({"EXP-U2": clasificacion}, monkeypatch)

        repo.insert.assert_called_once_with(
            expediente="EXP-U2",
            relevante=True,
            nota=f"{FEEDBACK_SOURCE}:v-test",
            tecnologia=None,
            tecnologias_secundarias=[],
            source=FEEDBACK_SOURCE,
        )
        assert counts == {"feedback_escrito": 1, "feedback_omitido": 0}

    def test_es_ti_false_con_scores_vacio_escribe_no_relevante(self, monkeypatch):
        """Simétrico: ``es_ti=False`` (``scores`` ya viene vacío por diseño
        de ``parse_labels``) escribe ``relevante=False``."""
        from scheduler.jobs.llm_tech_labeling import FEEDBACK_SOURCE

        clasificacion = Clasificacion(scores={}, es_ti=False, confianza_es_ti=0.8)
        counts, repo = self._call({"EXP-U3": clasificacion}, monkeypatch)

        repo.insert.assert_called_once_with(
            expediente="EXP-U3",
            relevante=False,
            nota=f"{FEEDBACK_SOURCE}:v-test",
            tecnologia=None,
            tecnologias_secundarias=[],
            source=FEEDBACK_SOURCE,
        )
        assert counts == {"feedback_escrito": 1, "feedback_omitido": 0}


# ── Selección de pendientes y job (requieren Postgres) ────────────────────


@pytest.fixture()
def repo(tmp_db):
    _db_mod, _ = tmp_db
    return TecnologiaPliegoRepository()


#: Cita que sí está en el anuncio que siembra ``_insert_licitacion``.
_CITA_SEMBRADA = "Mantenimiento del ERP"


def _respuesta(
    *etiquetas: tuple[str, float], evidencia: str = _CITA_SEMBRADA, es_ti: bool | None = None
) -> str:
    """Respuesta del LLM cuya cita se verifica contra el anuncio sembrado.

    ``es_ti`` se omite del JSON por defecto (``None``): los tests que no lo
    necesitan siguen viendo la misma respuesta que antes de la pregunta de
    nivel 1.
    """
    payload = {
        "tecnologias": [
            {"tecnologia": tecnologia, "confidence": confianza, "evidencia": evidencia}
            for tecnologia, confianza in etiquetas
        ]
    }
    if es_ti is not None:
        payload["es_ti"] = es_ti
    return json.dumps(payload)


def _insert_licitacion(id_externo: str, fecha: str = "2026-06-01") -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, descripcion, fuente, fecha_publicacion, fecha_extraccion) "
            "VALUES (%s, %s, %s, 'placsp', %s, CURRENT_TIMESTAMP)",
            (id_externo, f"Contrato {id_externo}", _CITA_SEMBRADA, fecha),
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

    def test_sin_evidencia_sentinel_also_counts_as_processed(self, repo):
        """Reclasificarla con el mismo prompt daría la misma respuesta: espera
        al siguiente bump de versión, como el «sin tecnología»."""
        _insert_licitacion("EXP-P6")
        repo.upsert_signals(
            "EXP-P6", method=METHOD, signal_version="v1", scores={}, sin_evidencia=True
        )

        assert repo.list_metadata_pending_llm_signal(signal_version="v1") == []
        pendientes = repo.list_metadata_pending_llm_signal(signal_version="v2")
        assert [p["id_externo"] for p in pendientes] == ["EXP-P6"]

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


# ── Muestra estratificada de F2 (spec §3.2) -- requieren Postgres ─────────
#
# NOTA para quien las ejecute: no se corrieron en esta sesión (sin Postgres
# disponible en el entorno). Están trazadas a mano contra la SQL de
# ``TecnologiaPliegoRepository.tamanos_estratos_muestra``/
# ``list_muestra_pending_llm_signal`` -- incluidas las cadenas MD5 reales de
# los ids usados en ``TestListMuestraPendingLlmSignal``, calculadas con
# ``hashlib.md5`` para no adivinar el orden del desempate.


def _insert_con_estrato(
    id_externo: str,
    *,
    fuente: str = "placsp",
    cpv: str | None = None,
    ccaa: str | None = None,
    ml_proba: float | None = None,
    tecnologia: str | None = None,
    fecha: str = "2026-06-01",
) -> None:
    """Como ``_insert_licitacion``, pero con control fino de las columnas que
    forman la clave de estrato. Independiente a propósito: no toca el
    fixture que ya usan ``TestListMetadataPendingLlmSignal``/``TestRunJob``."""
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, descripcion, fuente, cpv, ccaa, ml_proba, tecnologia, "
            "fecha_publicacion, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)",
            (
                id_externo,
                f"Contrato {id_externo}",
                _CITA_SEMBRADA,
                fuente,
                cpv,
                ccaa,
                ml_proba,
                tecnologia,
                fecha,
            ),
        )


class TestTamanosEstratosMuestra:
    def test_sizes_per_stratum_cover_each_dimension(self, repo):
        """Cubre las cinco dimensiones, incluidos ``ccaa``/``ml_proba`` NULL
        y una fuente ``bulk_*``; EST-1 y EST-6 comparten estrato para
        verificar que el ``count(*)`` de verdad agrupa."""
        _insert_con_estrato("EST-1", fuente="pscp", cpv="48000000-8")
        _insert_con_estrato("EST-6", fuente="pscp", cpv="48000000-8")
        _insert_con_estrato(
            "EST-2",
            fuente="ted",
            cpv="72212200-1",
            ccaa="Cataluña",
            ml_proba=0.1,
            tecnologia="SAP",
        )
        _insert_con_estrato(
            "EST-3", fuente="bulk_202409", cpv="79999999-0", ccaa="País Vasco", ml_proba=0.5
        )
        _insert_con_estrato(
            "EST-4",
            fuente="placsp_watched_company_awards",
            cpv="79999999-0",
            ccaa="Galicia",
            ml_proba=0.85,
            tecnologia="ERP",
        )
        _insert_con_estrato("EST-5", fuente="otro_conector_raro", ccaa="Navarra")

        tamanos = repo.tamanos_estratos_muestra()

        assert tamanos == {
            "pscp|48|es|sin_kw|sin_modelo": 2,
            "ted|72|ca|kw|baja": 1,
            "placsp|otros|eu|sin_kw|media": 1,
            "placsp|otros|gl|kw|alta": 1,
            "otras|otros|eu|sin_kw|sin_modelo": 1,
        }


class TestListMuestraPendingLlmSignal:
    _CLAVE = "pscp|otros|es|sin_kw|sin_modelo"

    def test_respects_quotas_and_is_deterministic_for_a_seed(self, repo):
        """5 candidatos, cupo 2: el orden de ``md5(id || 'test-seed')`` es
        (ascendente) EST-Q2, EST-Q4, EST-Q5, EST-Q3, EST-Q1 -- calculado con
        ``hashlib.md5``, no adivinado -- así que el top-2 es {EST-Q2, EST-Q4}.
        Con la semilla 'otra-semilla' el orden cambia (EST-Q1, EST-Q4, EST-Q2,
        EST-Q5, EST-Q3) y el top-2 pasa a ser {EST-Q1, EST-Q4}: incluye a
        EST-Q4 en ambos a propósito, para que la prueba no dependa de que las
        dos semillas den conjuntos disjuntos."""
        for id_ in ("EST-Q1", "EST-Q2", "EST-Q3", "EST-Q4", "EST-Q5"):
            _insert_con_estrato(id_, fuente="pscp")
        cuotas = {self._CLAVE: 2}

        primera = repo.list_muestra_pending_llm_signal(
            cuotas=cuotas, semilla="test-seed", signal_version="v1"
        )
        repetida = repo.list_muestra_pending_llm_signal(
            cuotas=cuotas, semilla="test-seed", signal_version="v1"
        )
        otra_semilla = repo.list_muestra_pending_llm_signal(
            cuotas=cuotas, semilla="otra-semilla", signal_version="v1"
        )

        assert {p["id_externo"] for p in primera} == {"EST-Q2", "EST-Q4"}
        assert {p["id_externo"] for p in repetida} == {"EST-Q2", "EST-Q4"}
        assert {p["id_externo"] for p in otra_semilla} == {"EST-Q1", "EST-Q4"}

    def test_excludes_a_tender_with_a_current_answer(self, repo):
        """3 candidatos, cupo 3 (los tres rankean dentro de cupo): EXC-2 ya
        tiene fila vigente de ``(METHOD, 'v1')`` y se descarta DESPUÉS de
        rankear -- no libera su puesto a un cuarto candidato inexistente, solo
        deja fuera al ya respondido."""
        for id_ in ("EXC-1", "EXC-2", "EXC-3"):
            _insert_con_estrato(id_, fuente="pscp")
        repo.upsert_signals("EXC-2", method=METHOD, signal_version="v1", scores={})

        pendientes = repo.list_muestra_pending_llm_signal(
            cuotas={self._CLAVE: 3}, semilla="seed-excl", signal_version="v1"
        )

        assert {p["id_externo"] for p in pendientes} == {"EXC-1", "EXC-3"}

    def test_returns_the_same_row_shape_as_list_metadata_pending_llm_signal(self, repo):
        _insert_con_estrato("EST-SHAPE", fuente="pscp")

        de_la_muestra = repo.list_muestra_pending_llm_signal(
            cuotas={self._CLAVE: 1}, semilla="shape-seed", signal_version="v1"
        )
        normal = repo.list_metadata_pending_llm_signal(signal_version="v1")

        assert len(de_la_muestra) == 1
        assert len(normal) == 1
        assert set(de_la_muestra[0]) == set(normal[0])
        assert de_la_muestra[0] == normal[0]


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
        raw = _respuesta(("SAP", 0.92))

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
        raw = _respuesta(("SAP", 0.95))

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
        ok = _respuesta(("SAP", 0.9))

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
        ok = _respuesta(("SAP", 0.9))
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
        raw = _respuesta(("SAP", 0.3))

        with patch("services.llm_tech_labeling.stream_llm_response", return_value=iter([raw])):
            run()

        assert [s["tecnologia"] for s in repo.list_for_licitacion("EXP-J10")] == ["SAP"]
        with connect() as c:
            row = c.execute(
                "SELECT ml_tecnologias FROM licitaciones WHERE id_externo = %s", ("EXP-J10",)
            ).fetchone()
        assert not row[0]

    def test_labels_without_evidence_write_the_sin_evidencia_sentinel(self, repo):
        """El LLM afirmó SAP con una cita que el anuncio no contiene: la
        licitación queda procesada para esta versión, pero ni como SAP ni como
        «sin tecnología», y nada llega al resumen ML."""
        from db.database import connect
        from db.repositories.tecnologia_pliego import SIN_EVIDENCIA_SENTINEL
        from scheduler.jobs.llm_tech_labeling import run

        _insert_licitacion("EXP-J11")
        raw = _respuesta(("SAP", 0.95), evidencia="Migración a SAP S/4HANA")

        with patch("services.llm_tech_labeling.stream_llm_response", return_value=iter([raw])):
            counts = run()

        assert counts["sin_evidencia"] == 1
        assert counts["no_signal"] == 0
        assert counts["etiquetas_sin_evidencia"] == 1
        assert (
            repo.list_metadata_pending_llm_signal(
                signal_version=signal_version(settings.LLM_TECH_LABELING_MODEL)
            )
            == []
        )
        assert repo.list_for_licitacion("EXP-J11") == []
        with connect() as c:
            filas = c.execute(
                "SELECT tecnologia, score FROM licitacion_tecnologia_pliego "
                "WHERE licitacion_id = %s",
                ("EXP-J11",),
            ).fetchall()
            resumen = c.execute(
                "SELECT ml_tecnologias FROM licitaciones WHERE id_externo = %s", ("EXP-J11",)
            ).fetchone()
        assert [(f[0], float(f[1])) for f in filas] == [(SIN_EVIDENCIA_SENTINEL, 0.0)]
        assert not resumen[0]


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

        counts = self._run_with(_respuesta(("SAP", 0.97), es_ti=True))

        assert counts["feedback_escrito"] == 1
        assert self._feedback_rows("EXP-F1") == [(1, "SAP", "llm_batch")]

    def test_relevante_no_longer_depends_on_the_specific_technology(self, repo):
        """``relevante`` es ahora ``es_ti`` y no «es SAP»: cualquier familia
        con ``es_ti=True`` cuenta como relevante, no solo SAP (spec §3.3)."""
        _insert_licitacion("EXP-F2")

        self._run_with(_respuesta(("ORACLE", 0.95), es_ti=True))

        assert self._feedback_rows("EXP-F2") == [(1, "ORACLE", "llm_batch")]

    def test_not_it_empties_the_queue_as_not_relevant(self, repo):
        """«No es TI» sigue siendo la respuesta masiva y de bajo riesgo: vacía
        la cola humana como «no relevante»."""
        _insert_licitacion("EXP-F3")

        counts = self._run_with(_respuesta(es_ti=False))

        assert counts["feedback_escrito"] == 1
        assert self._feedback_rows("EXP-F3") == [(0, None, "llm_batch")]

    def test_no_answer_to_the_level_1_question_is_left_for_a_human(self, repo):
        """Sin ``es_ti`` -- una respuesta que no contestó el nivel 1 -- la
        licitación se deja para un humano en vez de arriesgar un
        ``relevante`` inventado, aunque la familia sea de alta confianza."""
        _insert_licitacion("EXP-F4")

        counts = self._run_with(_respuesta(("SAP", 0.97)))

        assert counts["feedback_escrito"] == 0
        assert counts["feedback_omitido"] == 1
        assert self._feedback_rows("EXP-F4") == []

    def test_labels_without_evidence_are_left_for_a_human(self, repo):
        """Un «no relevante» automático sobre una etiqueta que el LLM afirmó y
        no sostuvo sacaría de la cola justo lo que merece otra mirada."""
        _insert_licitacion("EXP-F8")

        counts = self._run_with(_respuesta(("SAP", 0.99), evidencia="Licencias SAP ECC"))

        assert counts["sin_evidencia"] == 1
        assert counts["feedback_escrito"] == 0
        assert self._feedback_rows("EXP-F8") == []

    def test_disabled_flag_writes_nothing(self, repo, monkeypatch):
        monkeypatch.setattr(settings, "LLM_TECH_FEEDBACK_ENABLED", False, raising=False)
        _insert_licitacion("EXP-F5")

        counts = self._run_with(_respuesta(("SAP", 0.99)))

        assert counts["scored"] == 1
        assert counts["feedback_escrito"] == 0
        assert self._feedback_rows("EXP-F5") == []

    def test_does_not_overwrite_an_existing_human_label(self, repo):
        from db.repositories.feedback import FeedbackRepository

        _insert_licitacion("EXP-F6")
        FeedbackRepository().insert(
            expediente="EXP-F6", relevante=False, nota="revisado a mano", tecnologia=None
        )

        counts = self._run_with(_respuesta(("SAP", 0.99)))

        assert counts["feedback_omitido"] == 1
        assert self._feedback_rows("EXP-F6") == [(0, None, "human")]

    def test_written_label_removes_it_from_the_human_queue(self, repo):
        """El objetivo de la fase: la cola de active learning se vacía."""
        from db.repositories.licitaciones import LicitacionRepository

        _insert_licitacion("EXP-F7")
        antes = LicitacionRepository().get_unlabelled_candidates(10)
        assert "EXP-F7" in [c["id_externo"] for c in antes]

        self._run_with(_respuesta(("SAP", 0.99), es_ti=True))

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

    def test_revision_ti_feedback_still_overrides(self, tmp_db):
        """Solo `revision_ti` pisa la etiqueta base: es la fuente cuyo
        `relevante` significa «es TI», lo mismo que entrena el binario. Una
        fila `human` (histórica, «es SAP») ya no participa aquí -- lo cubre
        `test_human_feedback_no_longer_overrides` más abajo."""
        from db.repositories.feedback import FUENTE_REVISION_TI, FeedbackRepository
        from scheduler.concept_drift import _fetch_training_dataframe

        _insert_licitacion("EXP-T2")
        FeedbackRepository().insert(
            expediente="EXP-T2", relevante=True, nota="a mano", source=FUENTE_REVISION_TI
        )

        df = _fetch_training_dataframe()

        fila = df[df["id_externo"] == "EXP-T2"].iloc[0]
        assert fila["es_relevante"] == 1

    def test_human_feedback_no_longer_overrides(self, tmp_db):
        """Una fila `human` (histórica) significaba «es SAP», no «es TI»: desde
        el plan de clasificación en tres niveles ya no puede pisar la etiqueta
        base de este entrenamiento, que es «es TI»."""
        from db.repositories.feedback import FeedbackRepository
        from scheduler.concept_drift import _fetch_training_dataframe

        _insert_licitacion("EXP-T2B")
        FeedbackRepository().insert(expediente="EXP-T2B", relevante=True, nota="a mano")

        df = _fetch_training_dataframe()

        fila = df[df["id_externo"] == "EXP-T2B"].iloc[0]
        assert fila["es_relevante"] == 0

    def test_una_correccion_manda_sobre_la_revision_anterior(self, tmp_db):
        """Con correcciones, la etiqueta es la revisión más reciente por
        expediente. La corrección se inserta primero a propósito: leída sin
        ``DISTINCT ON … ORDER BY created_at DESC``, el dict se quedaba con la
        última fila que devolviera el SELECT, que en orden físico es la vieja."""
        from db.database import connect
        from db.repositories.feedback import FUENTE_REVISION_TI
        from scheduler.concept_drift import _fetch_training_dataframe

        _insert_licitacion("EXP-T3")
        with connect() as c:
            for relevante, created_at in (
                (1, "2026-09-20T10:00:00+00:00"),
                (0, "2026-09-01T10:00:00+00:00"),
            ):
                c.execute(
                    "INSERT INTO ml_feedback (expediente, relevante, source, created_at) "
                    "VALUES (%s, %s, %s, %s)",
                    ("EXP-T3", relevante, FUENTE_REVISION_TI, created_at),
                )

        df = _fetch_training_dataframe()

        fila = df[df["id_externo"] == "EXP-T3"].iloc[0]
        assert fila["es_relevante"] == 1

    def test_la_etiqueta_sale_de_la_revision_vigente_sin_bd(self, monkeypatch):
        """Sin BD: la etiqueta sale de ``feedback_humano_es_ti`` (una fila por
        expediente, la más reciente). La conexión falsa sirve la licitación y,
        a quien vuelva a leer ``ml_feedback`` a mano, la revisión vigente
        seguida de la vieja que la contradice: lo que un SELECT sin orden
        puede devolver."""
        import scheduler.concept_drift as concept_drift

        columnas_lic = [
            "id_externo",
            "titulo",
            "descripcion",
            "raw_keywords",
            "cpv",
            "importe",
            "fecha_publicacion",
            "tecnologia",
        ]

        class _Cursor:
            def __init__(self, filas: list[tuple[object, ...]], columnas: list[str]) -> None:
                self._filas = filas
                self.description = [(c,) for c in columnas]

            def fetchall(self) -> list[tuple[object, ...]]:
                return self._filas

        class _Conexion:
            def execute(self, sql: str, params: object = None) -> _Cursor:
                if "FROM licitaciones" in sql:
                    fila = ("EXP-K", "t", "d", None, None, None, "2026-06-01", None)
                    return _Cursor([fila], columnas_lic)
                return _Cursor([("EXP-K", 1), ("EXP-K", 0)], ["expediente", "relevante"])

            def __enter__(self) -> _Conexion:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

        monkeypatch.setattr(concept_drift, "connect", lambda: _Conexion())
        monkeypatch.setattr(
            "db.repositories.ml_dataset.feedback_humano_es_ti",
            lambda: [{"expediente": "EXP-K", "relevante": 1}],
        )

        df = concept_drift._fetch_training_dataframe()

        assert df[df["id_externo"] == "EXP-K"].iloc[0]["es_relevante"] == 1

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
