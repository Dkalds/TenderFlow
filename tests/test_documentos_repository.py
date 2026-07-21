"""Tests de db/repositories/documentos.py (plan Pliegos+RAG, F6)."""

from __future__ import annotations

import pytest

from db.database import DocumentoReferencia
from db.repositories.documentos import DocumentosRepository


@pytest.fixture()
def repo(tmp_db):
    _db_mod, _ = tmp_db
    return DocumentosRepository()


def _insert_licitacion(id_externo: str) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES (?, ?, 'placsp', datetime('now'))",
            (id_externo, f"Contrato {id_externo}"),
        )


class TestUpsertMeta:
    def test_inserts_new_documentos_as_pending(self, repo):
        _insert_licitacion("EXP-1")
        refs = [
            DocumentoReferencia(tipo="legal", uri="https://x/pcap.pdf", filename="PCAP.pdf"),
            DocumentoReferencia(tipo="technical", uri="https://x/ptt.pdf"),
        ]

        n = repo.upsert_meta("EXP-1", refs)

        assert n == 2
        pendientes = repo.list_pendientes()
        assert {p["uri"] for p in pendientes} == {"https://x/pcap.pdf", "https://x/ptt.pdf"}
        legal = next(p for p in pendientes if p["tipo"] == "legal")
        assert legal["filename"] == "PCAP.pdf"

    def test_empty_refs_is_noop(self, repo):
        _insert_licitacion("EXP-2")
        assert repo.upsert_meta("EXP-2", []) == 0
        assert repo.list_pendientes() == []

    def test_reingesta_no_duplica_ni_resetea_status(self, repo):
        """Idempotencia (UNIQUE licitacion_id+uri): re-ingerir la misma
        licitación no duplica filas ni resetea el status de un doc ya extraído."""
        _insert_licitacion("EXP-3")
        ref = DocumentoReferencia(tipo="legal", uri="https://x/pcap.pdf")
        repo.upsert_meta("EXP-3", [ref])

        doc = repo.list_pendientes()[0]
        repo.mark_extracted(doc["id"], texto="contenido del pliego", sha256="abc123")

        # Re-scrape del mismo día vuelve a ver la misma referencia
        repo.upsert_meta("EXP-3", [ref])

        assert repo.list_pendientes() == []  # sigue "extracted", no volvió a "pending"
        row = repo.get(doc["id"])
        assert row is not None
        assert row["status"] == "extracted"
        assert row["texto"] == "contenido del pliego"

        from db.database import connect

        with connect() as c:
            count = c.execute(
                "SELECT COUNT(*) FROM documentos WHERE licitacion_id = 'EXP-3'"
            ).fetchone()[0]
        assert count == 1  # no duplicado

    def test_distintas_licitaciones_mismo_uri_no_colisionan(self, repo):
        """UNIQUE es compuesto (licitacion_id, uri) — dos licitaciones pueden
        referenciar la misma URL de plantilla sin pisarse."""
        _insert_licitacion("EXP-4")
        _insert_licitacion("EXP-5")
        ref = DocumentoReferencia(tipo="legal", uri="https://x/plantilla-comun.pdf")

        repo.upsert_meta("EXP-4", [ref])
        repo.upsert_meta("EXP-5", [ref])

        assert len(repo.list_pendientes()) == 2


class TestListPendientes:
    def test_orders_by_created_at_fifo(self, repo):
        _insert_licitacion("EXP-6")
        repo.upsert_meta(
            "EXP-6",
            [
                DocumentoReferencia(tipo="legal", uri="https://x/a.pdf"),
                DocumentoReferencia(tipo="technical", uri="https://x/b.pdf"),
            ],
        )
        pendientes = repo.list_pendientes(limit=1)
        assert len(pendientes) == 1

    def test_excludes_non_pending(self, repo):
        _insert_licitacion("EXP-7")
        repo.upsert_meta("EXP-7", [DocumentoReferencia(tipo="legal", uri="https://x/c.pdf")])
        doc = repo.list_pendientes()[0]
        repo.mark_error(doc["id"], error_detail="descarga fallida")
        assert repo.list_pendientes() == []


class TestListByLicitacion:
    def test_returns_docs_of_that_licitacion_only(self, repo):
        _insert_licitacion("EXP-DOC1")
        _insert_licitacion("EXP-DOC2")
        repo.upsert_meta(
            "EXP-DOC1",
            [
                DocumentoReferencia(tipo="legal", uri="https://x/pcap.pdf", filename="PCAP.pdf"),
                DocumentoReferencia(tipo="technical", uri="https://x/ppt.pdf"),
            ],
        )
        repo.upsert_meta("EXP-DOC2", [DocumentoReferencia(tipo="legal", uri="https://x/otro.pdf")])

        items = repo.list_by_licitacion("EXP-DOC1")

        assert {i["uri"] for i in items} == {"https://x/pcap.pdf", "https://x/ppt.pdf"}
        pcap = next(i for i in items if i["uri"] == "https://x/pcap.pdf")
        assert pcap["filename"] == "PCAP.pdf"
        assert pcap["status"] == "pending"
        assert "texto" not in pcap

    def test_returns_empty_list_when_no_documentos(self, repo):
        _insert_licitacion("EXP-DOC3")
        assert repo.list_by_licitacion("EXP-DOC3") == []

    def test_returns_empty_list_for_unknown_licitacion(self, repo):
        assert repo.list_by_licitacion("NOPE-DOC") == []


class TestMarkTransitions:
    def test_mark_downloaded_sets_metadata(self, repo):
        _insert_licitacion("EXP-8")
        repo.upsert_meta("EXP-8", [DocumentoReferencia(tipo="legal", uri="https://x/d.pdf")])
        doc_id = repo.list_pendientes()[0]["id"]

        repo.mark_downloaded(
            doc_id, filename="d.pdf", content_type="application/pdf", size_bytes=1234, sha256="h1"
        )

        row = repo.get(doc_id)
        assert row is not None
        assert row["status"] == "downloaded"
        assert row["size_bytes"] == 1234
        assert row["sha256"] == "h1"
        assert row["fetched_at"] is not None

    def test_mark_extracted_sets_texto(self, repo):
        _insert_licitacion("EXP-9")
        repo.upsert_meta("EXP-9", [DocumentoReferencia(tipo="legal", uri="https://x/e.pdf")])
        doc_id = repo.list_pendientes()[0]["id"]

        repo.mark_extracted(doc_id, texto="texto extraído del PDF", sha256="h2")

        row = repo.get(doc_id)
        assert row is not None
        assert row["status"] == "extracted"
        assert row["texto"] == "texto extraído del PDF"

    def test_mark_error_sets_detail_and_truncates(self, repo):
        _insert_licitacion("EXP-10")
        repo.upsert_meta("EXP-10", [DocumentoReferencia(tipo="legal", uri="https://x/f.pdf")])
        doc_id = repo.list_pendientes()[0]["id"]

        repo.mark_error(doc_id, error_detail="x" * 5000)

        row = repo.get(doc_id)
        assert row is not None
        assert row["status"] == "error"
        assert len(row["error_detail"]) == 2000

    def test_get_returns_none_for_unknown_id(self, repo):
        assert repo.get(999999) is None


# ── documento_chunks (F8) ────────────────────────────────────────────────


def _seed_extracted(repo, licitacion_id: str, texto: str = "contenido del pliego") -> dict:
    _insert_licitacion(licitacion_id)
    repo.upsert_meta(
        licitacion_id, [DocumentoReferencia(tipo="legal", uri=f"https://x/{licitacion_id}.pdf")]
    )
    doc = repo.list_pendientes()[0]
    repo.mark_extracted(doc["id"], texto=texto, sha256="hash1")
    return repo.get(doc["id"])


class TestListExtractedWithoutChunks:
    def test_returns_extracted_docs_without_chunks(self, repo):
        doc = _seed_extracted(repo, "EXP-E1")
        candidatos = repo.list_extracted_without_chunks()
        assert [c["id"] for c in candidatos] == [doc["id"]]
        assert candidatos[0]["texto"] == "contenido del pliego"

    def test_excludes_docs_that_already_have_chunks(self, repo):
        doc = _seed_extracted(repo, "EXP-E2")
        repo.replace_chunks(doc["id"], ["chunk uno"], [[0.1] * 384])
        assert repo.list_extracted_without_chunks() == []

    def test_excludes_pending_and_error_docs(self, repo):
        _insert_licitacion("EXP-E3")
        repo.upsert_meta("EXP-E3", [DocumentoReferencia(tipo="legal", uri="https://x/p.pdf")])
        pendiente = repo.list_pendientes()[0]
        repo.mark_error(pendiente["id"], error_detail="fallo")
        assert repo.list_extracted_without_chunks() == []


class TestReplaceChunks:
    def test_inserts_chunks_with_embeddings(self, repo):
        doc = _seed_extracted(repo, "EXP-C1")
        n = repo.replace_chunks(doc["id"], ["chunk a", "chunk b"], [[0.1] * 384, [0.2] * 384])
        assert n == 2
        assert repo.count_chunks(doc["id"]) == 2

    def test_replace_deletes_previous_chunks(self, repo):
        """delete+insert: la segunda llamada reemplaza, no acumula."""
        doc = _seed_extracted(repo, "EXP-C2")
        repo.replace_chunks(doc["id"], ["v1 chunk a", "v1 chunk b"], [[0.1] * 384, [0.2] * 384])
        repo.replace_chunks(doc["id"], ["v2 chunk unico"], [[0.3] * 384])

        assert repo.count_chunks(doc["id"]) == 1
        from db.database import connect

        with connect() as c:
            texto = c.execute(
                "SELECT texto FROM documento_chunks WHERE documento_id = ?", (doc["id"],)
            ).fetchone()[0]
        assert texto == "v2 chunk unico"

    def test_empty_chunks_deletes_and_returns_zero(self, repo):
        doc = _seed_extracted(repo, "EXP-C3")
        repo.replace_chunks(doc["id"], ["algo"], [[0.1] * 384])
        n = repo.replace_chunks(doc["id"], [], [])
        assert n == 0
        assert repo.count_chunks(doc["id"]) == 0

    def test_mismatched_lengths_raises(self, repo):
        doc = _seed_extracted(repo, "EXP-C4")
        with pytest.raises(ValueError, match="misma longitud"):
            repo.replace_chunks(doc["id"], ["a", "b"], [[0.1] * 384])

    def test_chunk_index_matches_order(self, repo):
        doc = _seed_extracted(repo, "EXP-C5")
        repo.replace_chunks(doc["id"], ["primero", "segundo", "tercero"], [[0.1] * 384] * 3)
        from db.database import connect

        with connect() as c:
            rows = c.execute(
                "SELECT chunk_index, texto FROM documento_chunks "
                "WHERE documento_id = ? ORDER BY chunk_index",
                (doc["id"],),
            ).fetchall()
        assert [r[1] for r in rows] == ["primero", "segundo", "tercero"]
        assert [r[0] for r in rows] == [0, 1, 2]


class TestCountAll:
    def test_counts_across_licitaciones(self, repo):
        _insert_licitacion("EXP-N1")
        _insert_licitacion("EXP-N2")
        assert repo.count_all() == 0

        repo.upsert_meta("EXP-N1", [DocumentoReferencia(tipo="legal", uri="https://x/a.pdf")])
        repo.upsert_meta(
            "EXP-N2",
            [
                DocumentoReferencia(tipo="legal", uri="https://x/b.pdf"),
                DocumentoReferencia(tipo="technical", uri="https://x/c.pdf"),
            ],
        )

        assert repo.count_all() == 3
