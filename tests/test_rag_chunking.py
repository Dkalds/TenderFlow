"""Tests de services/rag/chunking.py (plan Pliegos+RAG, F8)."""

from __future__ import annotations

import pytest

from services.rag.chunking import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP_RATIO, chunk_text


class TestChunkText:
    def test_empty_text_returns_empty_list(self):
        assert chunk_text("") == []
        assert chunk_text("   \n  ") == []

    def test_short_text_returns_single_chunk(self):
        texto = "Cláusula primera: objeto del contrato."
        assert chunk_text(texto) == [texto]

    def test_long_text_splits_into_multiple_chunks(self):
        texto = "palabra " * 1000  # ~8000 chars
        chunks = chunk_text(texto, chunk_size=1400, overlap_ratio=0.15)
        assert len(chunks) > 1
        assert all(chunks)

    def test_chunks_within_size_bounds(self):
        """Ningún chunk debería superar chunk_size significativamente (el
        recorte por límite de palabra puede acortarlo, nunca alargarlo)."""
        texto = "palabra " * 2000
        chunks = chunk_text(texto, chunk_size=1400, overlap_ratio=0.15)
        assert all(len(c) <= 1400 for c in chunks)

    def test_deterministic_same_input_same_output(self):
        texto = "El adjudicatario deberá cumplir con las especificaciones técnicas. " * 50
        r1 = chunk_text(texto)
        r2 = chunk_text(texto)
        assert r1 == r2

    def test_overlap_produces_shared_content_between_consecutive_chunks(self):
        texto = " ".join(f"palabra{i}" for i in range(500))
        chunks = chunk_text(texto, chunk_size=200, overlap_ratio=0.2)
        assert len(chunks) >= 2
        # Al menos el final del primer chunk y el inicio del segundo comparten
        # alguna palabra (el solape es real, no solo nominal).
        words_a = set(chunks[0].split()[-5:])
        words_b = set(chunks[1].split()[:15])
        assert words_a & words_b

    def test_zero_overlap_no_shared_content(self):
        texto = " ".join(f"w{i}" for i in range(500))
        chunks = chunk_text(texto, chunk_size=200, overlap_ratio=0.0)
        assert len(chunks) >= 2
        words_a = set(chunks[0].split())
        words_b = set(chunks[1].split())
        assert not (words_a & words_b)

    def test_no_word_is_split_mid_word(self):
        """Cada palabra completa del texto original aparece entera en algún
        chunk -- ninguna palabra queda partida por el corte de ventana."""
        texto = " ".join(f"palabra{i:04d}" for i in range(300))
        chunks = chunk_text(texto, chunk_size=150, overlap_ratio=0.1)
        all_words_in_chunks: set[str] = set()
        for c in chunks:
            all_words_in_chunks.update(c.split())
        original_words = set(texto.split())
        assert original_words <= all_words_in_chunks

    def test_reconstructs_full_content_ignoring_overlap_duplication(self):
        """Concatenar chunks (deduplicando solape) debe cubrir todo el texto
        -- no se pierde contenido entre chunks."""
        texto = " ".join(f"token{i}" for i in range(400))
        chunks = chunk_text(texto, chunk_size=300, overlap_ratio=0.15)
        covered: set[str] = set()
        for c in chunks:
            covered.update(c.split())
        assert set(texto.split()) <= covered

    def test_invalid_chunk_size_raises(self):
        with pytest.raises(ValueError, match="chunk_size"):
            chunk_text("texto", chunk_size=0)
        with pytest.raises(ValueError, match="chunk_size"):
            chunk_text("texto", chunk_size=-10)

    def test_invalid_overlap_ratio_raises(self):
        with pytest.raises(ValueError, match="overlap_ratio"):
            chunk_text("texto de sobra " * 200, overlap_ratio=1.0)
        with pytest.raises(ValueError, match="overlap_ratio"):
            chunk_text("texto de sobra " * 200, overlap_ratio=-0.1)

    def test_default_params_within_plan_spec(self):
        """El plan pide ~1200-1500 chars de chunk_size y ~15% de solape."""
        assert 1200 <= DEFAULT_CHUNK_SIZE <= 1500
        assert pytest.approx(0.15) == DEFAULT_OVERLAP_RATIO

    def test_very_long_document_terminates(self):
        """Guarda anti-loop-infinito: un documento largo con palabras largas
        (sin espacios cercanos al límite) debe terminar en tiempo acotado."""
        texto = "x" * 50 + " " + "y" * 50000  # una palabra gigante sin espacios
        chunks = chunk_text(texto, chunk_size=1000, overlap_ratio=0.5)
        assert len(chunks) >= 1
        assert sum(len(c) for c in chunks) >= len(texto.replace(" ", ""))
