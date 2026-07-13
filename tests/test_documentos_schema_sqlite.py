"""Verifica el equivalente SQLite de las tablas ``documentos``/``documento_chunks``
(``db/schema.py``, contraparte de la migración Postgres v56) contra el fixture
``tmp_db`` que usa toda la suite unitaria.
"""

from __future__ import annotations

import pytest

# db.database.connect() envuelve el driver libsql/sqlite3: las violaciones de
# constraint (UNIQUE/CHECK/FK) llegan como ValueError, no sqlite3.IntegrityError.


def _insert_licitacion(c, id_externo: str) -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
        "VALUES (?, ?, 'placsp', datetime('now'))",
        (id_externo, f"Contrato {id_externo}"),
    )


def test_documentos_insert_and_unique_licitacion_uri(tmp_db):
    from db.database import connect

    with connect() as c:
        _insert_licitacion(c, "EXP-1")
        c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri, status) "
            "VALUES (?, 'legal', 'https://placsp.example/pliego.pdf', 'pending')",
            ("EXP-1",),
        )
        row = c.execute(
            "SELECT tipo, status, storage_key FROM documentos WHERE licitacion_id = 'EXP-1'"
        ).fetchone()
    assert row == ("legal", "pending", None)

    with connect() as c, pytest.raises(ValueError):
        c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri) "
            "VALUES (?, 'technical', 'https://placsp.example/pliego.pdf')",
            ("EXP-1",),
        )


def test_documentos_tipo_check_constraint_rejects_invalid_value(tmp_db):
    from db.database import connect

    with connect() as c:
        _insert_licitacion(c, "EXP-2")
        with pytest.raises(ValueError):
            c.execute(
                "INSERT INTO documentos (licitacion_id, tipo, uri) "
                "VALUES (?, 'invalido', 'https://placsp.example/x.pdf')",
                ("EXP-2",),
            )


def test_documentos_cascade_delete_removes_chunks(tmp_db):
    from db.database import connect

    with connect() as c:
        _insert_licitacion(c, "EXP-3")
        c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri) "
            "VALUES (?, 'technical', 'https://placsp.example/y.pdf')",
            ("EXP-3",),
        )
        doc_id = c.execute("SELECT id FROM documentos WHERE licitacion_id = 'EXP-3'").fetchone()[0]
        c.execute(
            "INSERT INTO documento_chunks (documento_id, chunk_index, texto, embedding) "
            "VALUES (?, 0, 'fragmento de texto', NULL)",
            (doc_id,),
        )
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("DELETE FROM licitaciones WHERE id_externo = 'EXP-3'")
        remaining_docs = c.execute(
            "SELECT COUNT(*) FROM documentos WHERE licitacion_id = 'EXP-3'"
        ).fetchone()[0]
        remaining_chunks = c.execute(
            "SELECT COUNT(*) FROM documento_chunks WHERE documento_id = ?", (doc_id,)
        ).fetchone()[0]
    assert remaining_docs == 0
    assert remaining_chunks == 0  # cascada documentos -> documento_chunks


def test_documento_chunks_unique_documento_chunk_index(tmp_db):
    from db.database import connect

    with connect() as c:
        _insert_licitacion(c, "EXP-4")
        c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri) "
            "VALUES (?, 'additional', 'https://placsp.example/z.pdf')",
            ("EXP-4",),
        )
        doc_id = c.execute("SELECT id FROM documentos WHERE licitacion_id = 'EXP-4'").fetchone()[0]
        c.execute(
            "INSERT INTO documento_chunks (documento_id, chunk_index, texto) "
            "VALUES (?, 0, 'chunk 0')",
            (doc_id,),
        )
        with pytest.raises(ValueError):
            c.execute(
                "INSERT INTO documento_chunks (documento_id, chunk_index, texto) "
                "VALUES (?, 0, 'chunk 0 duplicado')",
                (doc_id,),
            )


def test_documento_chunks_embedding_stores_blob(tmp_db):
    from db.database import connect

    with connect() as c:
        _insert_licitacion(c, "EXP-5")
        c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri, status) "
            "VALUES (?, 'legal', 'https://placsp.example/w.pdf', 'extracted')",
            ("EXP-5",),
        )
        doc_id = c.execute("SELECT id FROM documentos WHERE licitacion_id = 'EXP-5'").fetchone()[0]
        fake_embedding = (1.0).hex().encode()  # placeholder — el formato real lo define F8
        c.execute(
            "INSERT INTO documento_chunks (documento_id, chunk_index, texto, embedding) "
            "VALUES (?, 0, 'texto del chunk', ?)",
            (doc_id, fake_embedding),
        )
        row = c.execute(
            "SELECT texto, embedding FROM documento_chunks WHERE documento_id = ?", (doc_id,)
        ).fetchone()
    assert row[0] == "texto del chunk"
    assert row[1] == fake_embedding
