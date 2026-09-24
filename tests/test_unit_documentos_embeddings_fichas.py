"""La fase de fichas no puede fallar entera y salir en verde (pliegos.yml).

Del run #50 (2026-08-31) al #60 (2026-09-10) todas las llamadas al LLM de la
fase de fichas recibieron HTTP 401 —unas 25 por noche— y los once runs
concluyeron ``success``: ``extract_fact_sheet`` persiste la ficha como
``failed`` y relanza, la fase lo contaba como error suelto y ``run_cli`` solo
miraba el fetch.

Sin BD ni red: repositorios, proveedor y alerta se sustituyen, porque lo que se
prueba es cómo viaja el fallo desde el proveedor hasta el exit code.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from config import settings
from llm.providers import LLMAuthError, LLMModelUnavailableError
from scheduler.jobs import documentos_embeddings
from scheduler.jobs.documentos_embeddings import (
    _run_facts_phase,
    facts_failed_systemically,
    run_cli,
)

# Lo que dejaba cada noche del 401: el lote entero (25) en error, ninguna ficha.
_FACTS_401_NOCTURNO: dict[str, Any] = {
    "procesadas": 0,
    "needs_review": 0,
    "error": 25,
    "disabled": 0,
}
_FETCH_SANO: dict[str, int] = {"extracted": 280, "error": 20, "skipped": 0, "unsupported": 0}
_RECHAZO = "El proveedor rechazó la API key (HTTP 401) para m: hay que rotarla"
_RETIRADO = "El proveedor no sirve el modelo m (HTTP 410): está retirado o no existe"


def _facts(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"procesadas": 0, "needs_review": 0, "error": 0, "disabled": 0}
    base.update(over)
    return base


# ── Criterio de fallo sistémico ────────────────────────────────────────────


class TestFactsFailedSystemically:
    """Decide si la fase fue un fallo de infraestructura o trabajo normal."""

    def test_el_lote_entero_en_error_es_sistemico(self) -> None:
        assert facts_failed_systemically(_FACTS_401_NOCTURNO) is True

    def test_errores_sueltos_con_fichas_no_es_sistemico(self) -> None:
        """Un pliego que el modelo no sabe leer es normal."""
        assert facts_failed_systemically(_facts(procesadas=22, error=3)) is False

    def test_needs_review_cuenta_como_ficha_hecha(self) -> None:
        """``needs_review`` es un subconjunto de ``procesadas``, no un fallo."""
        assert facts_failed_systemically(_facts(procesadas=25, needs_review=25)) is False

    def test_credencial_rechazada_es_sistemica_aunque_haya_fichas(self) -> None:
        """Si la key cae a mitad de lote, la corrida siguiente fallará entera."""
        counts = _facts(procesadas=4, error=1, credencial_rechazada=_RECHAZO)
        assert facts_failed_systemically(counts) is True

    def test_modelo_retirado_es_sistemico_aunque_haya_fichas(self) -> None:
        """El modelo no vuelve solo: la corrida siguiente fallaría entera."""
        counts = _facts(procesadas=4, error=1, modelo_no_disponible=_RETIRADO)
        assert facts_failed_systemically(counts) is True

    def test_lote_aplazado_por_reloj_no_es_sistemico(self) -> None:
        """Quedarse sin tiempo no es un fallo: lo pendiente va en el lote siguiente."""
        assert facts_failed_systemically(_facts(procesadas=6, aplazados=19)) is False

    def test_sin_pendientes_no_es_sistemico(self) -> None:
        assert facts_failed_systemically(_facts()) is False

    def test_fase_desactivada_no_es_sistemica(self) -> None:
        assert facts_failed_systemically(_facts(disabled=1)) is False


# ── El bucle de la fase ────────────────────────────────────────────────────


def _pagina() -> dict[str, Any]:
    return {
        "documento_id": 1,
        "page_number": 1,
        "start_offset": 0,
        "tipo": "legal",
        "filename": "pcap.pdf",
        "texto": "Criterios de adjudicación: precio 60 puntos, calidad 40 puntos.",
    }


@pytest.fixture()
def fase_activada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PLIEGO_FACTS_ENABLED", True, raising=False)
    # Modelo NVIDIA explícito: el proveedor que se sustituye abajo es el suyo.
    # Tiene que estar en AVAILABLE_MODELS: la cadena real lo valida.
    monkeypatch.setattr(
        settings, "PLIEGO_FACTS_MODEL", "nvidia/nemotron-3-super-120b-a12b", raising=False
    )


@pytest.mark.usefixtures("fase_activada")
class TestLaCredencialRechazadaCortaElLote:
    """El 401 viaja del proveedor a la fase sin convertirse en un error suelto.

    Se ejercita la cadena real —``stream_llm_response`` sin fallback y el
    ``except``/``raise`` de ``extract_fact_sheet``— con el proveedor lanzando lo
    que lanza ante un 401 desde ``claude/placsp-scrape-failure-58a49b``.
    """

    def test_el_primer_rechazo_corta_el_lote_y_nombra_la_causa(self) -> None:
        fichas = MagicMock()
        fichas.list_pending_licitaciones.return_value = ["EXP-A1", "EXP-A2", "EXP-A3"]
        documentos = MagicMock()
        documentos.list_pages_by_licitacion.return_value = [_pagina()]
        rechazo = LLMAuthError(model=settings.PLIEGO_FACTS_MODEL, status_code=401)

        with (
            patch(
                "db.repositories.tender_fact_sheets.TenderFactSheetsRepository",
                return_value=fichas,
            ),
            patch("services.rag.fact_sheet.TenderFactSheetsRepository", return_value=fichas),
            patch("services.rag.fact_sheet.DocumentosRepository", return_value=documentos),
            patch("llm.budget.get_budget_guard"),
            patch("llm.providers.openai_provider.stream", side_effect=rechazo) as proveedor,
            patch("services.tech_signal.ingest_llm_technologies") as ingest,
        ):
            counts = _run_facts_phase(limit=3)

        # Antes: una llamada 401 —y una ficha `failed`— por licitación del lote.
        assert proveedor.call_count == 1
        assert counts["procesadas"] == 0
        assert counts["error"] == 1
        assert "HTTP 401" in counts["credencial_rechazada"]
        fichas.upsert.assert_called_once()
        assert fichas.upsert.call_args.kwargs["status"] == "failed"
        ingest.assert_not_called()
        assert facts_failed_systemically(counts) is True

    def test_un_fallo_normal_no_corta_el_lote(self) -> None:
        """Fail-open por licitación: lo que no es la credencial sigue adelante."""
        fichas = MagicMock()
        fichas.list_pending_licitaciones.return_value = ["EXP-B1", "EXP-B2", "EXP-B3"]

        with (
            patch(
                "db.repositories.tender_fact_sheets.TenderFactSheetsRepository",
                return_value=fichas,
            ),
            patch(
                "services.rag.fact_sheet.extract_fact_sheet",
                side_effect=ValueError("El LLM no devolvió un objeto JSON"),
            ) as extraer,
        ):
            counts = _run_facts_phase(limit=3)

        assert extraer.call_count == 3
        assert counts["error"] == 3
        assert "credencial_rechazada" not in counts
        # ...y aun así perder el lote entero es sistémico.
        assert facts_failed_systemically(counts) is True


@pytest.mark.usefixtures("fase_activada")
class TestElModeloRetiradoCortaElLote:
    """El 410 de un modelo retirado recorre el mismo camino que el 401.

    El run #72 (2026-09-22) pidió las 25 fichas del lote a
    ``deepseek-v4-flash-0731``, retirado el día antes: el proveedor devolvía un
    stream vacío, cada ficha quedó ``failed`` con «El extractor no devolvió un
    objeto JSON» y nada nombraba el 410.
    """

    def test_el_primer_410_corta_el_lote_y_nombra_el_modelo(self) -> None:
        fichas = MagicMock()
        fichas.list_pending_licitaciones.return_value = ["EXP-C1", "EXP-C2", "EXP-C3"]
        documentos = MagicMock()
        documentos.list_pages_by_licitacion.return_value = [_pagina()]
        retirado = LLMModelUnavailableError(model=settings.PLIEGO_FACTS_MODEL, status_code=410)

        with (
            patch(
                "db.repositories.tender_fact_sheets.TenderFactSheetsRepository",
                return_value=fichas,
            ),
            patch("services.rag.fact_sheet.TenderFactSheetsRepository", return_value=fichas),
            patch("services.rag.fact_sheet.DocumentosRepository", return_value=documentos),
            patch("llm.budget.get_budget_guard"),
            patch("llm.providers.openai_provider.stream", side_effect=retirado) as proveedor,
            patch("services.tech_signal.ingest_llm_technologies") as ingest,
        ):
            counts = _run_facts_phase(limit=3)

        assert proveedor.call_count == 1
        assert counts["procesadas"] == 0
        assert counts["error"] == 1
        assert "HTTP 410" in counts["modelo_no_disponible"]
        assert settings.PLIEGO_FACTS_MODEL in counts["modelo_no_disponible"]
        assert "credencial_rechazada" not in counts
        fichas.upsert.assert_called_once()
        assert "HTTP 410" in fichas.upsert.call_args.kwargs["error_detail"]
        ingest.assert_not_called()
        assert facts_failed_systemically(counts) is True


@pytest.mark.usefixtures("fase_activada")
class TestTopeDeRelojDeLasFichas:
    """Las fichas que no caben en el tope quedan pendientes, sin contarse como error."""

    def test_agotado_el_tope_no_se_empieza_otra_ficha(self) -> None:
        fichas = MagicMock()
        fichas.list_pending_licitaciones.return_value = ["EXP-D1", "EXP-D2", "EXP-D3"]
        registro = MagicMock(status="extracted")
        # Reloj simulado: la fase arranca en 0 y cada ficha tarda 400 s.
        reloj = iter([0.0, 0.0, 400.0, 800.0])

        with (
            patch(
                "db.repositories.tender_fact_sheets.TenderFactSheetsRepository",
                return_value=fichas,
            ),
            patch("services.rag.fact_sheet.extract_fact_sheet", return_value=registro) as extraer,
            patch("services.tech_signal.ingest_llm_technologies"),
            # Solo el reloj del job: `time.monotonic` global lo usan más módulos.
            patch.object(
                documentos_embeddings, "time", SimpleNamespace(monotonic=lambda: next(reloj))
            ),
        ):
            counts = _run_facts_phase(limit=3, max_seconds=600)

        assert extraer.call_count == 2
        assert counts["procesadas"] == 2
        assert counts["aplazados"] == 1
        assert counts["error"] == 0
        assert facts_failed_systemically(counts) is False


# ── Exit code y alerta ─────────────────────────────────────────────────────


def _correr_cli(
    facts: dict[str, Any], *, fetch: dict[str, int] | None = None
) -> tuple[int, MagicMock]:
    resumen = {
        "fetch": _FETCH_SANO if fetch is None else fetch,
        "embed": {},
        "facts": facts,
        "tech_signal": {},
    }
    with (
        patch("db.database.init_db"),
        patch.object(documentos_embeddings, "run", return_value=resumen),
        patch("observability.alerts.notify") as notify,
    ):
        return run_cli(), notify


class TestRunCli:
    """El exit code pone el workflow en rojo; la alerta es la que dice por qué."""

    def test_las_noches_del_401_salen_en_rojo(self) -> None:
        codigo, notify = _correr_cli(_FACTS_401_NOCTURNO)

        assert codigo == 1
        notify.assert_called_once()
        _nivel, _titulo, cuerpo = notify.call_args.args
        assert "25 extracciones" in cuerpo

    def test_la_alerta_nombra_la_credencial_rechazada(self) -> None:
        codigo, notify = _correr_cli(_facts(error=1, credencial_rechazada=_RECHAZO))

        assert codigo == 1
        _nivel, _titulo, cuerpo = notify.call_args.args
        assert "HTTP 401" in cuerpo

    def test_la_alerta_nombra_el_modelo_retirado(self) -> None:
        codigo, notify = _correr_cli(_facts(error=1, modelo_no_disponible=_RETIRADO))

        assert codigo == 1
        _nivel, _titulo, cuerpo = notify.call_args.args
        assert "HTTP 410" in cuerpo

    def test_una_fase_de_fichas_sana_no_rompe_el_workflow(self) -> None:
        codigo, notify = _correr_cli(_facts(procesadas=22, needs_review=5, error=3))

        assert codigo == 0
        notify.assert_not_called()

    def test_fichas_desactivadas_no_rompen_el_workflow(self) -> None:
        codigo, notify = _correr_cli(_facts(disabled=1))

        assert codigo == 0
        notify.assert_not_called()

    def test_con_el_fetch_roto_tambien_avisa_de_las_fichas(self) -> None:
        """El fetch ya devolvía 1 él solo; eso no puede tapar la alerta de fichas."""
        fetch_roto = {"extracted": 0, "error": 300, "skipped": 0, "unsupported": 0}

        codigo, notify = _correr_cli(_FACTS_401_NOCTURNO, fetch=fetch_roto)

        assert codigo == 1
        notify.assert_called_once()
