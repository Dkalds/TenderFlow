"""Reencolado de los documentos sin soporte cuyo formato ya se lee (S8).

Contra Postgres (``tmp_db``): lo que importa es qué filas toca el ``UPDATE`` y
cuáles no, y eso solo se puede comprobar con la tabla de verdad.
"""

from __future__ import annotations

import pytest

from scraper.document_fetcher import supported_content_types

_DOCX_MAL_ESCRITO = "application/vnd.openxmlformatsofficedocument.wordprocessingml.document"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def repo(tmp_db):
    from db.repositories.documentos import DocumentosRepository

    return DocumentosRepository()


def _sembrar(repo) -> dict[str, int]:
    """Una licitación con un documento por caso, en el estado que toca."""
    from db.database import DocumentoReferencia, connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES ('EXP-REENC', 'Contrato', 'placsp', CURRENT_TIMESTAMP)"
        )
    casos = {
        "docx_unsupported": ("unsupported", _DOCX_MAL_ESCRITO, "content-type no soportado: x"),
        "docx_error_legacy": ("error", _DOCX_MAL_ESCRITO, "content-type no soportado: x"),
        "odt_error_legacy": (
            "error",
            "application/vnd.oasis.opendocument.text",
            "content-type no soportado: x",
        ),
        "zip_unsupported": ("unsupported", "application/zip", "ZIP sin PDF ni DOCX procesables"),
        "xlsx_unsupported": ("unsupported", _XLSX, "content-type no soportado: x"),
        "pdf_roto": ("error", "application/pdf", "PDF cifrado — extracción no soportada en v1"),
        "descarga_fallida": ("error", None, "descarga fallida: 500"),
        "extraido": ("extracted", "application/pdf", None),
    }
    repo.upsert_meta(
        "EXP-REENC",
        [
            DocumentoReferencia(tipo="additional", uri=f"https://x.example/{n}", source_hash=n)
            for n in casos
        ],
    )
    ids: dict[str, int] = {}
    with connect() as c:
        for nombre, (status, content_type, detalle) in casos.items():
            fila = c.execute(
                "UPDATE documentos SET status = %s, content_type = %s, error_detail = %s "
                "WHERE source_hash = %s RETURNING id",
                (status, content_type, detalle, nombre),
            ).fetchone()
            assert fila is not None
            ids[nombre] = int(fila[0])
    return ids


def _estado(repo, documento_id: int) -> str:
    fila = repo.get(documento_id)
    assert fila is not None
    return str(fila["status"])


def test_sin_aplicar_solo_cuenta(repo):
    ids = _sembrar(repo)
    filas = repo.reencolar_formatos_soportados(supported_content_types(), aplicar=False)

    assert sum(f["total"] for f in filas) == 4
    assert {(f["content_type"], f["status"]) for f in filas} >= {
        (_DOCX_MAL_ESCRITO, "unsupported"),
        (_DOCX_MAL_ESCRITO, "error"),
    }
    assert _estado(repo, ids["docx_unsupported"]) == "unsupported"


def test_aplicar_reencola_solo_los_formatos_que_ya_se_leen(repo):
    ids = _sembrar(repo)
    filas = repo.reencolar_formatos_soportados(supported_content_types(), aplicar=True)

    assert sum(f["total"] for f in filas) == 4
    for nombre in ("docx_unsupported", "docx_error_legacy", "odt_error_legacy", "zip_unsupported"):
        assert _estado(repo, ids[nombre]) == "pending", nombre
        assert repo.get(ids[nombre])["error_detail"] is None
    # Lo que sigue sin leerse, los fallos que no son de formato y lo ya extraído
    # se quedan donde estaban.
    assert _estado(repo, ids["xlsx_unsupported"]) == "unsupported"
    assert _estado(repo, ids["pdf_roto"]) == "error"
    assert _estado(repo, ids["descarga_fallida"]) == "error"
    assert _estado(repo, ids["extraido"]) == "extracted"
    # Y vuelven a la cola del lote nocturno.
    pendientes = {d["id"] for d in repo.list_pendientes(limit=100)}
    assert ids["docx_unsupported"] in pendientes


def test_es_idempotente(repo):
    _sembrar(repo)
    repo.reencolar_formatos_soportados(supported_content_types(), aplicar=True)
    assert repo.reencolar_formatos_soportados(supported_content_types(), aplicar=True) == []


def test_el_script_por_defecto_no_escribe(repo, capsys):
    import importlib

    ids = _sembrar(repo)
    script = importlib.import_module("scripts.reencolar_documentos_no_soportados")

    assert script.main([]) == 0
    assert "Se reencolarían 4 documentos" in capsys.readouterr().out
    assert _estado(repo, ids["docx_unsupported"]) == "unsupported"

    assert script.main(["--aplicar"]) == 0
    assert _estado(repo, ids["docx_unsupported"]) == "pending"
