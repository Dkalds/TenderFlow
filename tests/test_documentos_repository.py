"""Tests de db/repositories/documentos.py (plan Pliegos+RAG, F6)."""

from __future__ import annotations

import pytest

from db.database import DocumentoReferencia
from db.repositories.documentos import DocumentosRepository


@pytest.fixture()
def repo(tmp_db):
    _db_mod, _ = tmp_db
    return DocumentosRepository()


def _insert_licitacion(
    id_externo: str, *, tecnologia: str | None = None, ml_tecnologias: str | None = None
) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fuente, fecha_extraccion, tecnologia, ml_tecnologias) "
            "VALUES (%s, %s, 'placsp', CURRENT_TIMESTAMP, %s, %s)",
            (id_externo, f"Contrato {id_externo}", tecnologia, ml_tecnologias),
        )


def _set_created_at(documento_id: int, created_at: str) -> None:
    """Fuerza ``created_at`` para tests deterministas de orden (evita depender
    de la resolución del reloj entre dos INSERT sucesivos)."""
    from db.database import connect

    with connect() as c:
        c.execute(
            "UPDATE documentos SET created_at = %s WHERE id = %s",
            (created_at, documento_id),
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


class TestUpsertMetaIdentidadEstable:
    """Identidad por ``(licitacion_id, tipo, source_hash)`` — v88.

    Los enlaces de PLACSP llevan un token que la plataforma re-emite, así que
    la URI no identifica al documento: antes de v88 cada rotación insertaba una
    fila nueva (262 grupos duplicados en producción).
    """

    def _uno(self, repo, licitacion_id: str) -> dict:
        filas = repo.list_by_licitacion(licitacion_id)
        assert len(filas) == 1, f"esperaba 1 fila, hay {len(filas)}"
        return filas[0]

    def test_rotacion_de_token_refresca_en_vez_de_duplicar(self, repo):
        _insert_licitacion("EXP-H1")
        repo.upsert_meta(
            "EXP-H1",
            [DocumentoReferencia(tipo="legal", uri="https://x/doc?token=VIEJO", source_hash="H1")],
        )

        repo.upsert_meta(
            "EXP-H1",
            [
                DocumentoReferencia(
                    tipo="legal",
                    uri="https://x/doc?token=NUEVO",
                    source_hash="H1",
                    filename="PCAP.pdf",
                )
            ],
        )

        fila = self._uno(repo, "EXP-H1")
        assert fila["uri"] == "https://x/doc?token=NUEVO"
        assert fila["filename"] == "PCAP.pdf"

    def test_rotacion_conserva_el_texto_ya_extraido(self, repo):
        """Mismo hash = mismo contenido: re-extraer sería tirar trabajo bueno."""
        _insert_licitacion("EXP-H2")
        repo.upsert_meta(
            "EXP-H2",
            [DocumentoReferencia(tipo="legal", uri="https://x/doc?token=V", source_hash="H1")],
        )
        doc = repo.list_pendientes()[0]
        repo.mark_extracted(doc["id"], texto="cláusulas del pliego", sha256="abc")

        repo.upsert_meta(
            "EXP-H2",
            [DocumentoReferencia(tipo="legal", uri="https://x/doc?token=N", source_hash="H1")],
        )

        fila = repo.get(doc["id"])
        assert fila is not None
        assert fila["status"] == "extracted"
        assert fila["texto"] == "cláusulas del pliego"
        assert fila["uri"] == "https://x/doc?token=N"

    def test_revive_un_error_de_descarga_cuando_llega_token_nuevo(self, repo):
        _insert_licitacion("EXP-H3")
        repo.upsert_meta(
            "EXP-H3",
            [DocumentoReferencia(tipo="legal", uri="https://x/doc?token=V", source_hash="H1")],
        )
        doc = repo.list_pendientes()[0]
        repo.mark_error(doc["id"], error_detail="descarga fallida: token caducado (500): 500")

        repo.upsert_meta(
            "EXP-H3",
            [DocumentoReferencia(tipo="legal", uri="https://x/doc?token=N", source_hash="H1")],
        )

        fila = repo.get(doc["id"])
        assert fila is not None
        assert fila["status"] == "pending"
        assert fila["error_detail"] is None

    def test_no_revive_un_error_de_extraccion(self, repo):
        """Un .docx sigue sin poder extraerse por mucho que cambie el enlace;
        revivirlo lo metería en un ciclo perpetuo comiéndose el lote diario."""
        _insert_licitacion("EXP-H4")
        repo.upsert_meta(
            "EXP-H4",
            [DocumentoReferencia(tipo="legal", uri="https://x/doc?token=V", source_hash="H1")],
        )
        doc = repo.list_pendientes()[0]
        repo.mark_error(doc["id"], error_detail="content-type no soportado: 'application/zip'")

        repo.upsert_meta(
            "EXP-H4",
            [DocumentoReferencia(tipo="legal", uri="https://x/doc?token=N", source_hash="H1")],
        )

        fila = repo.get(doc["id"])
        assert fila is not None
        assert fila["status"] == "error"

    def test_adopta_identidad_de_una_fila_legacy_con_la_misma_uri(self, repo):
        """Filas anteriores a v88 (sin hash) ganan identidad sin duplicarse."""
        _insert_licitacion("EXP-H5")
        repo.upsert_meta("EXP-H5", [DocumentoReferencia(tipo="legal", uri="https://x/doc?t=X")])

        repo.upsert_meta(
            "EXP-H5",
            [
                DocumentoReferencia(
                    tipo="legal", uri="https://x/doc?t=X", source_hash="H1", filename="PCAP.pdf"
                )
            ],
        )

        fila = self._uno(repo, "EXP-H5")
        assert fila["filename"] == "PCAP.pdf"
        assert repo.get(fila["id"])["source_hash"] == "H1"

    def test_adopcion_por_tipo_unico_repara_el_enlace_legacy(self, repo):
        """Fila legacy + token ya rotado: sin esto, cada re-scrape duplicaría
        (y un backfill histórico completo metería decenas de miles de filas)."""
        _insert_licitacion("EXP-H6")
        repo.upsert_meta(
            "EXP-H6", [DocumentoReferencia(tipo="legal", uri="https://x/doc?token=VIEJO")]
        )

        repo.upsert_meta(
            "EXP-H6",
            [DocumentoReferencia(tipo="legal", uri="https://x/doc?token=NUEVO", source_hash="H1")],
        )

        fila = self._uno(repo, "EXP-H6")
        assert fila["uri"] == "https://x/doc?token=NUEVO"

    def test_no_adopta_cuando_el_mapeo_es_ambiguo(self, repo):
        """Con dos filas legacy del mismo tipo no hay forma de saber cuál es:
        se inserta y no se toca ninguna, en vez de adivinar."""
        _insert_licitacion("EXP-H7")
        repo.upsert_meta(
            "EXP-H7",
            [
                DocumentoReferencia(tipo="legal", uri="https://x/a?token=V1"),
                DocumentoReferencia(tipo="legal", uri="https://x/b?token=V2"),
            ],
        )

        repo.upsert_meta(
            "EXP-H7",
            [DocumentoReferencia(tipo="legal", uri="https://x/a?token=NUEVO", source_hash="H1")],
        )

        uris = {f["uri"] for f in repo.list_by_licitacion("EXP-H7")}
        assert uris == {"https://x/a?token=V1", "https://x/b?token=V2", "https://x/a?token=NUEVO"}

    def test_varios_documentos_del_mismo_tipo_conviven(self, repo):
        """Un expediente con tres anexos son tres documentos, no un duplicado:
        por eso la identidad incluye el hash y no es solo (licitacion, tipo)."""
        _insert_licitacion("EXP-H8")

        n = repo.upsert_meta(
            "EXP-H8",
            [
                DocumentoReferencia(
                    tipo="additional", uri=f"https://x/anexo{i}", source_hash=f"H{i}"
                )
                for i in range(3)
            ],
        )

        assert n == 3
        assert len(repo.list_by_licitacion("EXP-H8")) == 3

    def test_no_adopta_una_fila_ya_extraida(self, repo):
        """Un pliego sustituido no puede heredar el texto del anterior.

        La adopción por tipo único es una inferencia, no una prueba: si la fila
        legacy ya tiene texto extraído, atarle la identidad del documento nuevo
        dejaría al asistente citando el pliego viejo mientras la UI enlaza al
        nuevo, y de forma permanente (no volvería a la cola de pendientes ni a
        la de chunking).
        """
        _insert_licitacion("EXP-H10")
        repo.upsert_meta(
            "EXP-H10", [DocumentoReferencia(tipo="legal", uri="https://x/pcap-v1?token=V")]
        )
        vieja = repo.list_pendientes()[0]
        repo.mark_extracted(vieja["id"], texto="PCAP versión 1", sha256="abc")

        # El órgano publica una corrección: documento distinto (hash nuevo).
        repo.upsert_meta(
            "EXP-H10",
            [DocumentoReferencia(tipo="legal", uri="https://x/pcap-v2?token=N", source_hash="H2")],
        )

        filas = repo.list_by_licitacion("EXP-H10")
        assert len(filas) == 2, "el pliego corregido debe entrar como fila nueva"
        anterior = repo.get(vieja["id"])
        assert anterior is not None
        assert anterior["texto"] == "PCAP versión 1"
        assert anterior["source_hash"] is None  # no se le inventó identidad
        nueva = next(f for f in filas if f["id"] != vieja["id"])
        assert nueva["status"] == "pending"  # se descargará de verdad

    def test_adopcion_por_uri_corrige_el_tipo(self, repo):
        """La adopción por URI casa solo por ``uri``: si el CODICE reclasifica
        el documento, la fila no puede quedarse con el tipo viejo y el hash
        del nuevo."""
        _insert_licitacion("EXP-H11")
        repo.upsert_meta("EXP-H11", [DocumentoReferencia(tipo="legal", uri="https://x/doc")])

        repo.upsert_meta(
            "EXP-H11",
            [DocumentoReferencia(tipo="technical", uri="https://x/doc", source_hash="H1")],
        )

        filas = repo.list_by_licitacion("EXP-H11")
        assert len(filas) == 1
        assert filas[0]["tipo"] == "technical"

    def test_referencia_repetida_en_el_mismo_lote_no_duplica(self, repo):
        _insert_licitacion("EXP-H9")
        ref = DocumentoReferencia(tipo="legal", uri="https://x/doc", source_hash="H1")

        repo.upsert_meta("EXP-H9", [ref, ref])

        assert len(repo.list_by_licitacion("EXP-H9")) == 1


class TestListPendientes:
    def test_respects_limit(self, repo):
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

    def test_tecnologia_keyword_match_goes_first(self, repo):
        """Licitaciones con `tecnologia` (keyword match en título) priman
        sobre las que no tienen ninguna señal de tecnología, sin importar
        cuál se ingirió antes."""
        _insert_licitacion("EXP-PRIO-1")
        _insert_licitacion("EXP-PRIO-2", tecnologia="SAP")
        repo.upsert_meta("EXP-PRIO-1", [DocumentoReferencia(tipo="legal", uri="https://x/p1.pdf")])
        repo.upsert_meta("EXP-PRIO-2", [DocumentoReferencia(tipo="legal", uri="https://x/p2.pdf")])
        doc1 = next(p for p in repo.list_pendientes() if p["licitacion_id"] == "EXP-PRIO-1")
        _set_created_at(doc1["id"], "2026-08-04T00:00:00+00:00")  # más antigua

        pendientes = repo.list_pendientes()

        assert [p["licitacion_id"] for p in pendientes] == ["EXP-PRIO-2", "EXP-PRIO-1"]

    def test_ml_tecnologias_also_counts_as_tech_relevant(self, repo):
        """El clasificador (ml_tecnologias) es la segunda señal de prioridad,
        incluso sin keyword match en título (tecnologia NULL)."""
        _insert_licitacion("EXP-PRIO-3")
        _insert_licitacion("EXP-PRIO-4", ml_tecnologias="ORACLE,SAP")
        repo.upsert_meta("EXP-PRIO-3", [DocumentoReferencia(tipo="legal", uri="https://x/p3.pdf")])
        repo.upsert_meta("EXP-PRIO-4", [DocumentoReferencia(tipo="legal", uri="https://x/p4.pdf")])
        doc3 = next(p for p in repo.list_pendientes() if p["licitacion_id"] == "EXP-PRIO-3")
        _set_created_at(doc3["id"], "2026-08-04T00:00:00+00:00")

        pendientes = repo.list_pendientes()

        assert [p["licitacion_id"] for p in pendientes] == ["EXP-PRIO-4", "EXP-PRIO-3"]

    def test_newest_first_within_same_priority_tier(self, repo):
        """Dentro del mismo nivel de prioridad, más reciente primero (mitiga
        el backlog viejo con tokens PLACSP caducados)."""
        _insert_licitacion("EXP-OLD")
        _insert_licitacion("EXP-NEW")
        repo.upsert_meta("EXP-OLD", [DocumentoReferencia(tipo="legal", uri="https://x/old.pdf")])
        repo.upsert_meta("EXP-NEW", [DocumentoReferencia(tipo="legal", uri="https://x/new.pdf")])
        old_doc = next(p for p in repo.list_pendientes() if p["licitacion_id"] == "EXP-OLD")
        new_doc = next(p for p in repo.list_pendientes() if p["licitacion_id"] == "EXP-NEW")
        _set_created_at(old_doc["id"], "2020-01-01T00:00:00+00:00")
        _set_created_at(new_doc["id"], "2026-08-04T00:00:00+00:00")

        pendientes = repo.list_pendientes()

        assert [p["licitacion_id"] for p in pendientes] == ["EXP-NEW", "EXP-OLD"]


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

    def test_orden_documental_legal_technical_additional(self, repo):
        """El PCAP manda sobre el PPT y este sobre los adicionales, sin importar
        en qué orden los devolviera el CODICE (mismo criterio que
        ``list_chunks_by_licitacion``)."""
        _insert_licitacion("EXP-DOC-ORD")
        repo.upsert_meta(
            "EXP-DOC-ORD",
            [
                DocumentoReferencia(tipo="additional", uri="https://x/anexo.pdf"),
                DocumentoReferencia(tipo="technical", uri="https://x/ppt.pdf"),
                DocumentoReferencia(tipo="legal", uri="https://x/pcap.pdf"),
            ],
        )

        tipos = [i["tipo"] for i in repo.list_by_licitacion("EXP-DOC-ORD")]

        assert tipos == ["legal", "technical", "additional"]

    def test_dentro_de_un_tipo_gana_el_mas_reciente(self, repo):
        """Cuando la rotación de token dejó dos filas del mismo pliego, la UI
        debe ver primero la nueva: la vieja es justo la que ya ha caducado."""
        _insert_licitacion("EXP-DOC-DUP")
        repo.upsert_meta(
            "EXP-DOC-DUP",
            [
                DocumentoReferencia(tipo="legal", uri="https://x/pcap.pdf?token=viejo"),
                DocumentoReferencia(tipo="legal", uri="https://x/pcap.pdf?token=nuevo"),
            ],
        )
        filas = {i["uri"]: i["id"] for i in repo.list_by_licitacion("EXP-DOC-DUP")}
        _set_created_at(filas["https://x/pcap.pdf?token=viejo"], "2026-01-01T00:00:00Z")
        _set_created_at(filas["https://x/pcap.pdf?token=nuevo"], "2026-08-01T00:00:00Z")

        uris = [i["uri"] for i in repo.list_by_licitacion("EXP-DOC-DUP")]

        assert uris[0] == "https://x/pcap.pdf?token=nuevo"

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
                "SELECT texto FROM documento_chunks WHERE documento_id = %s", (doc["id"],)
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
                "WHERE documento_id = %s ORDER BY chunk_index",
                (doc["id"],),
            ).fetchall()
        assert [r[1] for r in rows] == ["primero", "segundo", "tercero"]
        assert [r[0] for r in rows] == [0, 1, 2]


class TestListChunksByLicitacion:
    def test_joins_tipo_filename_and_orders_documentally(self, repo):
        _insert_licitacion("EXP-CH1")
        repo.upsert_meta(
            "EXP-CH1",
            [
                DocumentoReferencia(tipo="technical", uri="https://x/ppt.pdf", filename="PPT.pdf"),
                DocumentoReferencia(tipo="legal", uri="https://x/pcap.pdf", filename="PCAP.pdf"),
            ],
        )
        pendientes = repo.list_pendientes()
        for p in pendientes:
            repo.mark_extracted(p["id"], texto=f"texto {p['tipo']}", sha256="h")
        tech = next(p for p in pendientes if p["tipo"] == "technical")
        legal = next(p for p in pendientes if p["tipo"] == "legal")
        repo.replace_chunks(tech["id"], ["ppt chunk 0"], [[0.1] * 384])
        repo.replace_chunks(legal["id"], ["pcap chunk 0", "pcap chunk 1"], [[0.2] * 384] * 2)

        chunks = repo.list_chunks_by_licitacion("EXP-CH1")

        assert [(c["tipo"], c["chunk_index"]) for c in chunks] == [
            ("legal", 0),
            ("legal", 1),
            ("technical", 0),
        ]
        assert chunks[0]["filename"] == "PCAP.pdf"
        assert chunks[0]["texto"] == "pcap chunk 0"

    def test_respects_limit(self, repo):
        doc = _seed_extracted(repo, "EXP-CH2")
        repo.replace_chunks(doc["id"], ["a", "b", "c"], [[0.1] * 384] * 3)
        assert len(repo.list_chunks_by_licitacion("EXP-CH2", limit=2)) == 2

    def test_empty_when_no_chunks(self, repo):
        _seed_extracted(repo, "EXP-CH3")
        assert repo.list_chunks_by_licitacion("EXP-CH3") == []


class TestListTextosByLicitacion:
    def test_returns_only_extracted_with_texto(self, repo):
        _insert_licitacion("EXP-T1")
        repo.upsert_meta(
            "EXP-T1",
            [
                DocumentoReferencia(tipo="legal", uri="https://x/pcap.pdf"),
                DocumentoReferencia(tipo="technical", uri="https://x/ppt.pdf"),
            ],
        )
        legal = next(p for p in repo.list_pendientes() if p["tipo"] == "legal")
        repo.mark_extracted(legal["id"], texto="contenido del PCAP", sha256="h")
        # el technical queda pending → no debe aparecer

        textos = repo.list_textos_by_licitacion("EXP-T1")

        assert len(textos) == 1
        assert textos[0]["tipo"] == "legal"
        assert textos[0]["texto"] == "contenido del PCAP"


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
