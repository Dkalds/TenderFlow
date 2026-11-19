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


_HTML_NO_SOPORTADO = "content-type no soportado: 'text/html'"


def _sembrar_rechazos(repo) -> dict[str, int]:
    """Lo que se guardó como documento siendo un rechazo, y lo que solo se le parece."""
    from db.database import DocumentoReferencia, connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES ('EXP-RECH', 'Contrato', 'placsp', CURRENT_TIMESTAMP)"
        )
    # (status, size_bytes, error_detail)
    casos = {
        # La página «Request Rejected» del cortafuegos de PLACSP: 245 bytes.
        "placsp": ("unsupported", 245, _HTML_NO_SOPORTADO),
        # El reto del WAF de TED: un 202 vacío.
        "ted": ("unsupported", 0, _HTML_NO_SOPORTADO),
        "sin_tamano": ("unsupported", None, _HTML_NO_SOPORTADO),
        # Un HTML que alguien publicó de verdad: sigue sin leerse.
        "html_de_verdad": ("unsupported", 54_000, _HTML_NO_SOPORTADO),
        "otro_formato": ("unsupported", 120, "content-type no soportado: 'application/xml'"),
        "ya_es_fallo": ("error", 245, "descarga fallida: el cortafuegos rechazó la petición"),
    }
    repo.upsert_meta(
        "EXP-RECH",
        [
            DocumentoReferencia(tipo="legal", uri=f"https://x.example/{n}", source_hash=n)
            for n in casos
        ],
    )
    ids: dict[str, int] = {}
    with connect() as c:
        for nombre, (status, size_bytes, detalle) in casos.items():
            fila = c.execute(
                "UPDATE documentos SET status = %s, content_type = 'text/html', size_bytes = %s, "
                "error_detail = %s WHERE source_hash = %s RETURNING id",
                (status, size_bytes, detalle, nombre),
            ).fetchone()
            assert fila is not None
            ids[nombre] = int(fila[0])
    return ids


def test_los_rechazos_del_cortafuegos_vuelven_a_la_cola_y_un_html_de_verdad_no(repo):
    ids = _sembrar_rechazos(repo)

    assert repo.reencolar_rechazos_del_cortafuegos(aplicar=False) == 3
    assert _estado(repo, ids["placsp"]) == "unsupported"  # contar no escribe

    assert repo.reencolar_rechazos_del_cortafuegos(aplicar=True) == 3
    for nombre in ("placsp", "ted", "sin_tamano"):
        assert _estado(repo, ids[nombre]) == "pending", nombre
        assert repo.get(ids[nombre])["error_detail"] is None
    assert _estado(repo, ids["html_de_verdad"]) == "unsupported"
    assert _estado(repo, ids["otro_formato"]) == "unsupported"
    assert _estado(repo, ids["ya_es_fallo"]) == "error"
    # Idempotente: lo reencolado ya no está.
    assert repo.reencolar_rechazos_del_cortafuegos(aplicar=True) == 0


def test_el_script_reencola_los_rechazos_solo_con_aplicar(repo, capsys):
    import importlib

    ids = _sembrar_rechazos(repo)
    script = importlib.import_module("scripts.reencolar_documentos_no_soportados")

    assert script.main(["--rechazados"]) == 0
    assert "Se reencolarían 3 documentos" in capsys.readouterr().out
    assert _estado(repo, ids["placsp"]) == "unsupported"

    assert script.main(["--rechazados", "--aplicar"]) == 0
    assert "Reencolados 3 documentos" in capsys.readouterr().out
    assert _estado(repo, ids["placsp"]) == "pending"
