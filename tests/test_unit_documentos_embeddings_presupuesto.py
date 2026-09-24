"""Topes de reloj y fallos inesperados del job de pliegos (pliegos.yml).

Del run #65 (2026-09-15) al #73 (2026-09-23) el job se canceló nueve noches
seguidas por el ``timeout-minutes`` del workflow: el fetch y el embed no tenían
más límite que el número de documentos y tardaban lo que tardaran, así que las
fases de después no llegaban a correr. A la vez, 64 documentos con bytes NUL se
reintentaban cada noche, porque un fallo inesperado no sacaba la fila de
``pending``.

Sin BD: repositorio, fetcher y encoder se sustituyen, y el reloj del job es una
secuencia fija de lecturas. Lo que se prueba es el bucle de cada fase.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from config import settings
from db.repositories.documentos import _texto_para_postgres
from scheduler.jobs import documentos_embeddings
from scheduler.jobs.documentos_embeddings import (
    _presupuesto_agotado,
    _run_embed_phase,
    _run_fetch_phase,
    run,
)


def _reloj(*lecturas: float) -> SimpleNamespace:
    """Sustituto del ``time`` del job: cada ``monotonic()`` devuelve la siguiente.

    Solo se reemplaza la referencia del módulo del job; ``time.monotonic``
    global lo usan más módulos y no debe verse afectado.
    """
    secuencia: Iterator[float] = iter(lecturas)
    return SimpleNamespace(monotonic=lambda: next(secuencia))


def _docs(n: int) -> list[dict[str, Any]]:
    return [
        {"id": i, "licitacion_id": f"EXP-{i}", "uri": f"https://x/{i}.pdf"} for i in range(1, n + 1)
    ]


def _extraidos(*ids: int) -> list[dict[str, Any]]:
    return [{"id": i, "licitacion_id": f"EXP-{i}", "texto": "palabra " * 500} for i in ids]


class TestPresupuestoAgotado:
    def test_sin_tope_nunca_se_agota(self) -> None:
        assert _presupuesto_agotado(0.0, None) is False
        assert _presupuesto_agotado(0.0, 0) is False

    def test_se_agota_al_llegar_al_tope(self) -> None:
        with patch.object(documentos_embeddings, "time", _reloj(599.0, 600.0)):
            assert _presupuesto_agotado(0.0, 600) is False
            assert _presupuesto_agotado(0.0, 600) is True


# ── Fase fetch ────────────────────────────────────────────────────────────


@pytest.fixture()
def repo_fetch() -> Iterator[MagicMock]:
    repo = MagicMock()
    with patch("db.repositories.documentos.DocumentosRepository", return_value=repo):
        yield repo


class TestFetchConTope:
    def test_agotado_el_tope_lo_que_queda_se_aplaza(self, repo_fetch: MagicMock) -> None:
        repo_fetch.list_pendientes.return_value = _docs(5)

        # Arranque de la fase y una lectura antes de cada documento: el
        # tercero ya llega pasado el tope.
        with (
            patch.object(documentos_embeddings, "time", _reloj(0.0, 0.0, 500.0, 1300.0)),
            patch("scraper.document_fetcher.fetch_and_extract", return_value="extracted") as fetch,
        ):
            counts = _run_fetch_phase(limit=5, max_seconds=1200)

        assert fetch.call_count == 2
        assert counts == {
            "extracted": 2,
            "error": 0,
            "skipped": 0,
            "unsupported": 0,
            "aplazados": 3,
        }
        # Aplazar no es fallar: la fila sigue `pending` para el lote siguiente.
        repo_fetch.mark_error.assert_not_called()

    def test_sin_tope_procesa_el_lote_entero(self, repo_fetch: MagicMock) -> None:
        repo_fetch.list_pendientes.return_value = _docs(3)

        with patch("scraper.document_fetcher.fetch_and_extract", return_value="extracted") as fetch:
            counts = _run_fetch_phase(limit=3)

        assert fetch.call_count == 3
        assert counts["aplazados"] == 0


class TestFalloInesperadoSaleDePending:
    def test_el_documento_se_marca_error_con_la_causa(self, repo_fetch: MagicMock) -> None:
        repo_fetch.list_pendientes.return_value = _docs(2)
        nul = ValueError("PostgreSQL text fields cannot contain NUL (0x00) bytes")

        with patch("scraper.document_fetcher.fetch_and_extract", side_effect=[nul, "extracted"]):
            counts = _run_fetch_phase(limit=2)

        assert (counts["error"], counts["extracted"]) == (1, 1)
        repo_fetch.mark_error.assert_called_once()
        assert repo_fetch.mark_error.call_args.args == (1,)
        assert "NUL" in repo_fetch.mark_error.call_args.kwargs["error_detail"]

    def test_si_marcar_el_error_tambien_falla_el_lote_sigue(self, repo_fetch: MagicMock) -> None:
        """Con la BD caída el UPDATE falla igual: el documento se queda
        ``pending`` y lo reintenta el lote siguiente, pero el resto sigue."""
        repo_fetch.list_pendientes.return_value = _docs(2)
        repo_fetch.mark_error.side_effect = ConnectionError("BD caída")

        with patch(
            "scraper.document_fetcher.fetch_and_extract",
            side_effect=[RuntimeError("inesperado"), "extracted"],
        ):
            counts = _run_fetch_phase(limit=2)

        assert (counts["error"], counts["extracted"]) == (1, 1)


# ── Fase embed ────────────────────────────────────────────────────────────


@pytest.fixture()
def repo_embed() -> Iterator[MagicMock]:
    repo = MagicMock()
    repo.list_pages.return_value = []
    repo.documentos_con_embedding_obsoleto.return_value = []
    repo.replace_chunks.side_effect = lambda _id, chunks, *_a, **_k: len(chunks)
    with (
        patch("db.repositories.documentos.DocumentosRepository", return_value=repo),
        patch("services.embeddings.embeddings_available", return_value=True),
        patch(
            "services.embeddings.encode_texts",
            side_effect=lambda texts, **_kw: np.zeros((len(texts), 4), dtype="float32"),
        ),
    ):
        yield repo


class TestEmbedConTope:
    def test_agotado_el_tope_los_documentos_quedan_para_el_lote_siguiente(
        self, repo_embed: MagicMock
    ) -> None:
        repo_embed.list_extracted_without_chunks.return_value = _extraidos(1, 2, 3)

        with patch.object(documentos_embeddings, "time", _reloj(0.0, 0.0, 950.0)):
            counts = _run_embed_phase(limit=3, max_seconds=900)

        assert counts["documentos_procesados"] == 1
        assert counts["aplazados"] == 2
        assert repo_embed.replace_chunks.call_count == 1

    def test_el_reembedding_solo_usa_lo_que_sobra(
        self, repo_embed: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Los documentos sin índice van primero y comparten el mismo tope."""
        monkeypatch.setattr(settings, "EMBEDDING_VERSION", "v-test", raising=False)
        repo_embed.list_extracted_without_chunks.return_value = _extraidos(1)
        repo_embed.documentos_con_embedding_obsoleto.return_value = _extraidos(2, 3)

        with patch.object(documentos_embeddings, "time", _reloj(0.0, 0.0, 950.0)):
            counts = _run_embed_phase(limit=3, max_seconds=900)

        assert counts["documentos_procesados"] == 1
        assert counts["reembebidos"] == 0
        assert counts["aplazados"] == 2


# ── run() ─────────────────────────────────────────────────────────────────


def test_run_pasa_a_cada_fase_su_tope_de_settings() -> None:
    with (
        patch.object(settings, "PLIEGO_FETCH_MAX_SECONDS", 11),
        patch.object(settings, "PLIEGO_EMBED_MAX_SECONDS", 22),
        patch.object(settings, "PLIEGO_FACTS_MAX_SECONDS", 33),
        patch.object(documentos_embeddings, "_run_fetch_phase", return_value={}) as fetch,
        patch.object(documentos_embeddings, "_run_embed_phase", return_value={}) as embed,
        patch.object(documentos_embeddings, "_run_facts_phase", return_value={}) as facts,
        patch.object(documentos_embeddings, "_run_tech_signal_phase", return_value={}),
        patch.object(documentos_embeddings, "_run_resumen_pregen_phase", return_value={}),
    ):
        run()

    assert fetch.call_args.kwargs["max_seconds"] == 11
    assert embed.call_args.kwargs["max_seconds"] == 22
    assert facts.call_args.kwargs["max_seconds"] == 33


# ── Texto que Postgres no acepta ──────────────────────────────────────────


class TestTextoParaPostgres:
    def test_quita_los_nul(self) -> None:
        # UTF-16 leído como texto de un byte: el caso típico de un PDF roto.
        assert _texto_para_postgres("T\x00e\x00x\x00t\x00o\x00") == "Texto"

    def test_sustituye_los_surrogates_sueltos(self) -> None:
        saneado = _texto_para_postgres("importe \udbc0 euros")

        assert saneado == "importe � euros"
        saneado.encode("utf-8")  # lo que psycopg hace al enviarlo: ya no lanza

    def test_el_texto_limpio_no_cambia(self) -> None:
        limpio = "Pliego — 1.500 € (IVA incl.)\n¿Plazo? 30 días \U0001f4c4"
        assert _texto_para_postgres(limpio) == limpio

    def test_sanear_por_paginas_da_lo_mismo_que_sanear_el_texto_unido(self) -> None:
        """Es lo que mantiene los offsets de página cuadrando con ``texto``."""
        paginas = ["a\x00b", "\udbc0c", "d\x00\x00", ""]

        por_paginas = "\n".join(_texto_para_postgres(p) for p in paginas)

        assert por_paginas == _texto_para_postgres("\n".join(paginas))
