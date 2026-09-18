"""Tests de scheduler/jobs/documentos_embeddings.py (plan Pliegos+RAG, F8).

``services.embeddings.encode_texts`` se mockea siempre (pull de un modelo
real de ~400MB no pertenece a un test unitario) — mismo criterio que el
plan pide explícitamente para este job.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

# Registra en el REGISTRY las series que leen los tests de métricas. Hoy ya
# llegan por la cadena de `db.database`, pero el job importa las métricas tarde,
# dentro de cada fase, y `_metric_value` falla con una serie sin registrar: el
# resultado no puede depender de un import transitivo.
import observability.runtime_metrics  # noqa: F401  -- registra las series antes de leerlas
from db.database import DocumentoReferencia
from db.repositories.documentos import DocumentosRepository
from scheduler.jobs import documentos_embeddings
from scheduler.jobs.documentos_embeddings import _run_embed_phase, _run_fetch_phase, run


@pytest.fixture()
def repo(tmp_db):
    _db_mod, _ = tmp_db
    return DocumentosRepository()


def _insert_licitacion(id_externo: str) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES (%s, %s, 'placsp', CURRENT_TIMESTAMP)",
            (id_externo, f"Contrato {id_externo}"),
        )


def _seed_pending(repo, licitacion_id: str) -> dict:
    _insert_licitacion(licitacion_id)
    repo.upsert_meta(
        licitacion_id, [DocumentoReferencia(tipo="legal", uri=f"https://x/{licitacion_id}.pdf")]
    )
    return repo.list_pendientes()[0]


def _seed_extracted(repo, licitacion_id: str, texto: str = "contenido largo del pliego") -> dict:
    doc = _seed_pending(repo, licitacion_id)
    repo.mark_extracted(doc["id"], texto=texto, sha256="h")
    return repo.get(doc["id"])


def _fake_embeddings(n: int, dim: int = 384) -> np.ndarray:
    return np.random.default_rng(0).random((n, dim)).astype("float32")


def _mock_ml_available():
    """sentence-transformers no está instalado en el entorno de test --
    parchea embeddings_available() a True para ejercitar la fase de embed."""
    return patch("services.embeddings.embeddings_available", return_value=True)


def _metric_value(name: str, labels: dict[str, str]) -> float:
    """Valor de una serie del REGISTRY: 0.0 si está registrada y aún sin muestra.

    Copia de ``tests/test_dedupe_quality.py::_metric_value``, que explica el
    detalle. ``REGISTRY.get_sample_value`` devuelve ``None`` tanto si la serie
    no está registrada —regresión: ``/metrics`` deja de publicarla— como si lo
    está y el hijo con esas labels aún no se incrementó en este proceso (lo que
    ve la primera lectura de ``documentos_fetched_total{status}`` en un proceso
    nuevo). Los tests de este fichero hacían ``if before is not None``, así que
    cualquiera de los dos casos se saltaba la aserción en silencio. Aquí el
    primero falla y el segundo cuenta como 0.
    """
    from prometheus_client import REGISTRY

    # Los Counter publican la familia sin el sufijo `_total` que llevan sus
    # muestras; por eso se normaliza antes de comparar con `name`.
    registrada = False
    for familia in REGISTRY.collect():
        nombre_publicado = f"{familia.name}_total" if familia.type == "counter" else familia.name
        if name != nombre_publicado:
            continue
        registrada = True
        for muestra in familia.samples:
            if muestra.name == name and muestra.labels == labels:
                return float(muestra.value)
    assert registrada, (
        f"la métrica {name!r} no está registrada en el REGISTRY de prometheus_client: "
        "¿se renombró o su módulo cayó al fallback no-op? Sin registrar, /metrics no la publica."
    )
    return 0.0


# ── Fase fetch ────────────────────────────────────────────────────────────


class TestRunFetchPhase:
    def test_processes_pending_documents(self, repo):
        _seed_pending(repo, "EXP-F1")
        _seed_pending(repo, "EXP-F2")

        with patch(
            "scraper.document_fetcher.fetch_and_extract", side_effect=["extracted", "error"]
        ):
            counts = _run_fetch_phase()

        assert counts == {"extracted": 1, "error": 1, "skipped": 0, "unsupported": 0}

    def test_no_pending_returns_zero_counts(self, repo):
        assert _run_fetch_phase() == {
            "extracted": 0,
            "error": 0,
            "skipped": 0,
            "unsupported": 0,
        }

    def test_skipped_no_consume_la_fila(self, repo):
        """Un documento saltado por breaker abierto se cuenta aparte y sigue
        ``pending``: el lote de mañana lo reintenta."""
        _seed_pending(repo, "EXP-F5")

        with patch("scraper.document_fetcher.fetch_and_extract", side_effect=["skipped"]):
            counts = _run_fetch_phase()

        assert counts == {"extracted": 0, "error": 0, "skipped": 1, "unsupported": 0}
        assert len(repo.list_pendientes()) == 1

    def test_unsupported_se_cuenta_aparte_del_error(self, repo):
        """S8.2 partió ``error`` en dos: un formato sin parser no es un fallo.

        Los tres asertos de arriba se ampliaron con ``unsupported`` por lo
        mismo: la clave se declara en el diccionario inicial (y no aparece solo
        cuando toca) para que el informe del cron tenga siempre la misma forma.
        Este test fija que además se cuenta en su cubo y no en ``error``, que
        es lo que decide si ``run_cli`` deja el workflow en rojo.
        """
        _seed_pending(repo, "EXP-F6")

        with patch("scraper.document_fetcher.fetch_and_extract", side_effect=["unsupported"]):
            counts = _run_fetch_phase()

        assert counts == {"extracted": 0, "error": 0, "skipped": 0, "unsupported": 1}

    def test_unexpected_exception_counts_as_error(self, repo):
        _seed_pending(repo, "EXP-F3")

        with patch("scraper.document_fetcher.fetch_and_extract", side_effect=RuntimeError("boom")):
            counts = _run_fetch_phase()

        assert counts["error"] == 1

    def test_increments_prometheus_metric(self, repo):
        etiquetas = {"status": "extracted"}
        before = _metric_value("documentos_fetched_total", etiquetas)
        _seed_pending(repo, "EXP-F4")

        with patch("scraper.document_fetcher.fetch_and_extract", return_value="extracted"):
            counts = _run_fetch_phase()

        # Igual que abajo con los chunks: si la fase no extrae nada, el delta no
        # se ejercita y el fallo diría "no se contó" cuando lo roto es otra cosa.
        assert counts["extracted"] == 1, f"la fase de fetch no extrajo el documento: {counts}"
        after = _metric_value("documentos_fetched_total", etiquetas)
        assert after - before == 1.0, (
            f"documentos_fetched_total{{status=extracted}} pasó de {before} a {after}: "
            "el documento extraído no se contó"
        )


# ── Fase embed ────────────────────────────────────────────────────────────


class TestRunEmbedPhase:
    def test_chunks_and_embeds_extracted_documents(self, repo):
        doc = _seed_extracted(repo, "EXP-E1", texto="palabra " * 500)

        with (
            _mock_ml_available(),
            patch(
                "services.embeddings.encode_texts",
                side_effect=lambda texts, **kw: _fake_embeddings(len(texts)),
            ),
        ):
            counts = _run_embed_phase()

        assert counts["documentos_procesados"] == 1
        assert counts["chunks_creados"] > 0
        assert repo.count_chunks(doc["id"]) == counts["chunks_creados"]

    def test_no_candidates_returns_zero_counts(self, repo):
        assert _run_embed_phase() == {
            "documentos_procesados": 0,
            "chunks_creados": 0,
            "sin_texto": 0,
            "error": 0,
            # C5.7: cuántos chunks se rehicieron por cambio de versión de
            # embedding. Sin candidatos no hay nada que reembeber, pero la clave
            # tiene que estar: un job de re-embedding sin contador es un job sin
            # progreso observable, que es lo que el ítem vino a arreglar.
            "reembebidos": 0,
        }

    def test_second_run_is_idempotent_noop(self, repo):
        """Un documento ya chunkeado no vuelve a aparecer como candidato."""
        _seed_extracted(repo, "EXP-E2", texto="contenido de prueba " * 200)

        with (
            _mock_ml_available(),
            patch(
                "services.embeddings.encode_texts",
                side_effect=lambda texts, **kw: _fake_embeddings(len(texts)),
            ) as mock_encode,
        ):
            first = _run_embed_phase()
            second = _run_embed_phase()

        assert first["documentos_procesados"] == 1
        assert second == {
            "documentos_procesados": 0,
            "chunks_creados": 0,
            "sin_texto": 0,
            "error": 0,
            # C5.7: cuántos chunks se rehicieron por cambio de versión de
            # embedding. Sin candidatos no hay nada que reembeber, pero la clave
            # tiene que estar: un job de re-embedding sin contador es un job sin
            # progreso observable, que es lo que el ítem vino a arreglar.
            "reembebidos": 0,
        }
        mock_encode.assert_called_once()  # la segunda corrida no reembebe nada

    def test_document_with_empty_texto_is_skipped(self, repo):
        doc = _seed_pending(repo, "EXP-E3")
        repo.mark_extracted(doc["id"], texto="   ", sha256="h")  # solo whitespace

        with _mock_ml_available():
            counts = _run_embed_phase()

        assert counts["sin_texto"] == 1
        assert counts["documentos_procesados"] == 0

    def test_encode_texts_failure_marks_error_and_continues(self, repo):
        _seed_extracted(repo, "EXP-E4", texto="pliego uno " * 100)
        _seed_extracted(repo, "EXP-E5", texto="pliego dos " * 100)

        calls = {"n": 0}

        def _flaky_encode(texts, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("modelo no disponible")
            return _fake_embeddings(len(texts))

        with (
            _mock_ml_available(),
            patch("services.embeddings.encode_texts", side_effect=_flaky_encode),
        ):
            counts = _run_embed_phase()

        assert counts["error"] == 1
        assert counts["documentos_procesados"] == 1

    def test_missing_ml_extra_skips_gracefully(self, repo):
        """Sin sentence-transformers instalado, la fase se salta sin romper el
        job ni contar cada documento del lote como error individual."""
        _seed_extracted(repo, "EXP-E6")

        with (
            patch("services.embeddings.embeddings_available", return_value=False),
            patch("services.embeddings.encode_texts") as mock_encode,
        ):
            counts = _run_embed_phase()
            mock_encode.assert_not_called()

        assert counts["documentos_procesados"] == 0
        assert counts["error"] == 0  # no cuenta como error -- es un skip esperado

    def test_increments_chunk_count_metric(self, repo):
        before = _metric_value("documento_chunks_total", {})
        _seed_extracted(repo, "EXP-E7", texto="palabra " * 500)

        with (
            _mock_ml_available(),
            patch(
                "services.embeddings.encode_texts",
                side_effect=lambda texts, **kw: _fake_embeddings(len(texts)),
            ),
        ):
            counts = _run_embed_phase()

        # Sin chunks, un contador mudo daría `0 == 0` y el delta pasaría en vacío.
        assert counts["chunks_creados"] > 0, (
            f"la fase de embed no creó chunks ({counts}): el delta del contador no se ejercita"
        )
        after = _metric_value("documento_chunks_total", {})
        assert after - before == counts["chunks_creados"], (
            f"documento_chunks_total pasó de {before} a {after} con "
            f"{counts['chunks_creados']} chunks creados: los chunks no se contaron"
        )


# ── run() combinado ─────────────────────────────────────────────────────────


def test_run_combines_both_phases(repo):
    _seed_pending(repo, "EXP-R1")
    _seed_extracted(repo, "EXP-R2", texto="pliego tecnico " * 200)

    with (
        patch("scraper.document_fetcher.fetch_and_extract", return_value="extracted"),
        _mock_ml_available(),
        patch(
            "services.embeddings.encode_texts",
            side_effect=lambda texts, **kw: _fake_embeddings(len(texts)),
        ),
    ):
        result = run()

    assert result["fetch"]["extracted"] == 1
    assert result["embed"]["documentos_procesados"] == 1


def test_run_passes_batch_sizes_from_settings(repo):
    """``run()`` delega el tamaño de lote de cada fase a config.settings en
    vez de las constantes de módulo -- así el workflow_dispatch de
    pliegos.yml puede sobreescribirlas sin tocar código."""
    from config import settings

    with (
        patch.object(settings, "PLIEGO_FETCH_BATCH", 7),
        patch.object(settings, "PLIEGO_EMBED_BATCH", 3),
        patch.object(settings, "PLIEGO_FACTS_BATCH", 2),
        patch.object(settings, "PLIEGO_TECH_SIGNAL_BATCH", 9),
        patch.object(documentos_embeddings, "_run_fetch_phase", return_value={}) as fetch,
        patch.object(documentos_embeddings, "_run_embed_phase", return_value={}) as embed,
        patch.object(documentos_embeddings, "_run_facts_phase", return_value={}) as facts,
        patch.object(
            documentos_embeddings, "_run_tech_signal_phase", return_value={}
        ) as tech_signal,
    ):
        run()

    fetch.assert_called_once_with(limit=7)
    embed.assert_called_once_with(limit=3)
    facts.assert_called_once_with(limit=2)
    tech_signal.assert_called_once_with(limit=9)
