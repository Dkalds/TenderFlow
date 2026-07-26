"""Tests para services/rag/context.py — contexto de licitación para el LLM."""

from __future__ import annotations

import pytest

from db.database import DocumentoReferencia
from db.repositories.documentos import DocumentosRepository
from services.rag.context import (
    LicitacionContext,
    build_licitacion_context,
    primary_doc_from_context,
)


@pytest.fixture()
def repo(tmp_db, monkeypatch):
    _db_mod, _ = tmp_db
    # Ranking determinista en tests: fuerza el fallback substring de smart_match.
    import services.embeddings as emb

    monkeypatch.setattr(emb, "embeddings_available", lambda: False)
    return DocumentosRepository()


def _insert_licitacion(id_externo: str, titulo: str = "Contrato de prueba") -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, descripcion, organo_contratacion, importe, estado, "
            " fuente, fecha_extraccion) "
            "VALUES (?, ?, 'Descripción del anuncio', 'Ayuntamiento', 100000.0, 'PUB', "
            "'placsp', CURRENT_TIMESTAMP)",
            (id_externo, titulo),
        )


def _seed_chunked_doc(
    repo: DocumentosRepository,
    licitacion_id: str,
    chunks: list[str],
    *,
    tipo: str = "legal",
    filename: str = "PCAP.pdf",
) -> None:
    repo.upsert_meta(
        licitacion_id,
        [DocumentoReferencia(tipo=tipo, uri=f"https://x/{licitacion_id}-{tipo}.pdf")],
    )
    doc = next(p for p in repo.list_pendientes() if p["licitacion_id"] == licitacion_id)
    repo.mark_downloaded(
        doc["id"], filename=filename, content_type="application/pdf", size_bytes=1, sha256="h"
    )
    repo.mark_extracted(doc["id"], texto=" ".join(chunks), sha256="h")
    repo.replace_chunks(doc["id"], chunks, [[0.1] * 384] * len(chunks))


# ---------------------------------------------------------------------------
# build_licitacion_context
# ---------------------------------------------------------------------------


def test_returns_none_for_unknown_licitacion(repo):
    assert build_licitacion_context("EXP-NADA", None) is None


def test_context_without_documentos(repo):
    _insert_licitacion("EXP-1")

    ctx = build_licitacion_context("EXP-1", None)

    assert ctx is not None
    assert ctx["detail"]["titulo"] == "Contrato de prueba"
    assert ctx["documentos"] == []
    assert ctx["chunks"] == []
    assert ctx["has_pliego_text"] is False
    assert ctx["truncated"] is False


def test_context_with_pending_documento_has_no_pliego_text(repo):
    """Referencias aún no descargadas: hay documentos pero sin texto."""
    _insert_licitacion("EXP-2")
    repo.upsert_meta("EXP-2", [DocumentoReferencia(tipo="legal", uri="https://x/p.pdf")])

    ctx = build_licitacion_context("EXP-2", None)

    assert ctx is not None
    assert len(ctx["documentos"]) == 1
    assert ctx["documentos"][0]["status"] == "pending"
    assert ctx["has_pliego_text"] is False
    assert ctx["chunks"] == []


def test_context_with_chunks_resumen_mode_uses_documental_order(repo):
    _insert_licitacion("EXP-3")
    _seed_chunked_doc(repo, "EXP-3", ["objeto del contrato", "criterios de adjudicación"])

    ctx = build_licitacion_context("EXP-3", None, max_chunks=1)

    assert ctx is not None
    assert ctx["has_pliego_text"] is True
    assert [c["texto"] for c in ctx["chunks"]] == ["objeto del contrato"]
    assert ctx["truncated"] is True  # quedó un chunk fuera
    assert ctx["chunks"][0]["filename"] == "PCAP.pdf"
    assert ctx["chunks"][0]["tipo"] == "legal"


def test_context_question_ranks_matching_chunk(repo):
    _insert_licitacion("EXP-4")
    _seed_chunked_doc(
        repo,
        "EXP-4",
        ["cláusulas generales del contrato", "la solvencia técnica exigida es ISO 9001"],
    )

    ctx = build_licitacion_context("EXP-4", "¿qué solvencia técnica exigida hay?", max_chunks=1)

    assert ctx is not None
    assert len(ctx["chunks"]) == 1
    assert "solvencia" in ctx["chunks"][0]["texto"]


def test_context_respects_char_budget(repo):
    _insert_licitacion("EXP-5")
    _seed_chunked_doc(repo, "EXP-5", ["a" * 500, "b" * 500, "c" * 500])

    ctx = build_licitacion_context("EXP-5", None, max_chars=1100)

    assert ctx is not None
    assert len(ctx["chunks"]) == 2  # el tercero no entra en presupuesto
    assert ctx["truncated"] is True


def test_context_falls_back_to_texto_when_no_chunks(repo):
    """Documento extraído sin pasar por el job de chunking: chunkea al vuelo."""
    _insert_licitacion("EXP-6")
    repo.upsert_meta("EXP-6", [DocumentoReferencia(tipo="legal", uri="https://x/p.pdf")])
    doc = repo.list_pendientes()[0]
    repo.mark_extracted(doc["id"], texto="texto del pliego sin chunkear todavía", sha256="h")

    ctx = build_licitacion_context("EXP-6", None)

    assert ctx is not None
    assert ctx["has_pliego_text"] is True
    assert len(ctx["chunks"]) == 1
    assert "sin chunkear" in ctx["chunks"][0]["texto"]


# ---------------------------------------------------------------------------
# primary_doc_from_context
# ---------------------------------------------------------------------------


def test_primary_doc_from_context_shape(repo):
    _insert_licitacion("EXP-7", titulo="Implantación S/4HANA")
    _seed_chunked_doc(repo, "EXP-7", ["requisitos del pliego"])
    ctx: LicitacionContext | None = build_licitacion_context("EXP-7", None)
    assert ctx is not None

    doc = primary_doc_from_context("EXP-7", ctx)

    assert doc["id_externo"] == "EXP-7"
    assert doc["titulo"] == "Implantación S/4HANA"
    assert doc["organo_contratacion"] == "Ayuntamiento"
    assert doc["descripcion"] == "Descripción del anuncio"
    assert doc["_score"] == 2.0
    assert [c["texto"] for c in doc["chunks"]] == ["requisitos del pliego"]
