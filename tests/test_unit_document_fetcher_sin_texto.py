"""Detección de PDF escaneado y estado ``sin_texto`` (``v161``).

Unitario: ni BD ni red. El repositorio se sustituye por un doble que registra
qué se marcó, que es lo que importa aquí —que un escaneado sin OCR acabe en
``sin_texto`` y no en ``error``— y la ficha bajo demanda se prueba sobre su
mensaje, que es lo que ve quien pulsa «Extraer ficha».
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import scraper.document_fetcher as df
from scraper.document_fetcher import (
    CONTENT_TYPE_PDF,
    CONTENT_TYPE_ZIP,
    DocumentFetchError,
    PdfSinTextoError,
    UnsupportedDocumentError,
    _extract_paginas,
    _tiene_texto,
)

FIXTURES = Path(__file__).parent / "fixtures" / "documentos"


def _fixture(nombre: str) -> bytes:
    return (FIXTURES / nombre).read_bytes()


@pytest.fixture(autouse=True)
def _sin_ocr(monkeypatch):
    """Ningún test depende de que ``ocrmypdf`` esté instalado ni de un almacén."""
    from config.settings import settings
    from shared.object_store import reset_object_store_cache

    monkeypatch.setattr(df, "_ocr_pdf", lambda _datos: None)
    for var in ("DOCUMENT_BLOB_DIR", "DOCUMENT_BLOB_BUCKET"):
        monkeypatch.setenv(var, "")
        monkeypatch.setattr(settings, var, "")
    reset_object_store_cache()
    yield
    reset_object_store_cache()


class TestDeteccion:
    @pytest.mark.parametrize(
        "paginas",
        [
            [],
            ["", "   ", "\n"],
            ["1", "2", "3", "- 4 -", "...."],
            ["12345678901234567890"],
        ],
    )
    def test_restos_de_escaneo_no_son_capa_de_texto(self, paginas):
        """Vacío, paginación estampada o puntuación: sin letras no hay texto."""
        assert _tiene_texto(paginas) is False

    @pytest.mark.parametrize(
        "paginas",
        [["Objeto del contrato"], ["", "", "Cláusula primera"], ["Pág", "ina uno"]],
    )
    def test_unas_pocas_palabras_si_son_texto(self, paginas):
        assert _tiene_texto(paginas) is True

    def test_pdf_escaneado_lanza_pdf_sin_texto(self):
        with pytest.raises(PdfSinTextoError, match="sin texto extraíble"):
            _extract_paginas(_fixture("pliego_escaneado.pdf"), CONTENT_TYPE_PDF)

    def test_pdf_sin_texto_sigue_siendo_document_fetch_error(self):
        """Compatibilidad: quien capturaba ``DocumentFetchError`` lo sigue viendo."""
        assert issubclass(PdfSinTextoError, DocumentFetchError)
        assert not issubclass(PdfSinTextoError, UnsupportedDocumentError)

    def test_pdf_con_texto_no_es_escaneado(self):
        paginas = _extract_paginas(_fixture("pliego_con_texto.pdf"), CONTENT_TYPE_PDF)
        assert paginas and not any(p.ocr for p in paginas)

    def test_si_el_ocr_lee_el_escaneado_no_hay_sin_texto(self, monkeypatch):
        monkeypatch.setattr(df, "_ocr_pdf", lambda _datos: _fixture("pliego_con_texto.pdf"))
        paginas = _extract_paginas(_fixture("pliego_escaneado.pdf"), CONTENT_TYPE_PDF)
        assert paginas and all(p.ocr for p in paginas)

    def test_el_error_del_proceso_aislado_conserva_el_tipo(self, monkeypatch):
        """En prod el parser corre en otro proceso y el tipo no cruza el pipe."""

        def worker_falso(content, max_pages, max_text_chars, conexion):
            conexion.send(("error", df._MSG_PDF_SIN_TEXTO))
            conexion.close()

        class _Proceso:
            def __init__(self, target, args, daemon):
                self._target, self._args = target, args

            def start(self):
                self._target(*self._args)

            def join(self, timeout=None):
                return None

            def is_alive(self):
                return False

            def terminate(self):
                return None

        import multiprocessing

        contexto_real = multiprocessing.get_context("spawn")

        class _Contexto:
            Pipe = staticmethod(contexto_real.Pipe)
            Process = _Proceso

        monkeypatch.setattr(df.settings, "ENV", "prod")
        monkeypatch.setattr(df.settings, "DOCUMENT_EXTRACTION_TIMEOUT_SECONDS", 5)
        monkeypatch.setattr(df, "_pdf_extraction_worker", worker_falso)
        monkeypatch.setattr(df.multiprocessing, "get_context", lambda _metodo: _Contexto)
        with pytest.raises(PdfSinTextoError):
            df._extract_pdf_pages(b"%PDF-1.4")


def _zip(entradas: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nombre, datos in entradas.items():
            z.writestr(nombre, datos)
    return buf.getvalue()


class TestZip:
    def test_zip_solo_con_escaneados_es_sin_texto_no_unsupported(self):
        contenido = _zip(
            {
                "pliego-1.pdf": _fixture("pliego_escaneado.pdf"),
                "pliego-2.pdf": _fixture("pliego_escaneado.pdf"),
            }
        )
        with pytest.raises(PdfSinTextoError, match="2 de 2 entradas"):
            _extract_paginas(contenido, CONTENT_TYPE_ZIP)

    def test_zip_con_un_escaneado_y_uno_legible_se_extrae(self):
        contenido = _zip(
            {
                "a-escaneado.pdf": _fixture("pliego_escaneado.pdf"),
                "b-texto.pdf": _fixture("pliego_con_texto.pdf"),
            }
        )
        paginas = _extract_paginas(contenido, CONTENT_TYPE_ZIP)
        assert "b-texto.pdf" in paginas[0].texto


class _RepoDoble:
    """Registra las marcas; ``get`` devuelve la fila ya completa."""

    def __init__(self) -> None:
        self.marcas: list[tuple[str, dict[str, Any]]] = []

    def get(self, documento_id: int) -> dict[str, Any]:
        return {"id": documento_id, "source_hash": None, "blob_key": None}

    def __getattr__(self, nombre: str) -> Any:
        if not nombre.startswith("mark_"):
            raise AttributeError(nombre)

        def marcar(documento_id: int, **kwargs: Any) -> None:
            self.marcas.append((nombre, kwargs))

        return marcar


class TestFetchAndExtract:
    def test_escaneado_sin_ocr_marca_sin_texto(self, monkeypatch):
        repo = _RepoDoble()
        monkeypatch.setattr("db.repositories.documentos.DocumentosRepository", lambda: repo)
        with patch.object(
            df, "_download_bytes", return_value=(_fixture("pliego_escaneado.pdf"), CONTENT_TYPE_PDF)
        ):
            resultado = df.fetch_and_extract(
                {"id": 7, "uri": "https://x/p.pdf", "source_hash": None, "blob_key": None}
            )

        assert resultado == "sin_texto"
        nombres = [nombre for nombre, _ in repo.marcas]
        assert nombres == ["mark_downloaded", "mark_sin_texto"]
        _, kwargs = repo.marcas[-1]
        assert kwargs["content_type"] == CONTENT_TYPE_PDF
        assert "sin texto" in kwargs["error_detail"]
        assert "mark_error" not in nombres

    def test_pdf_roto_sigue_siendo_error(self, monkeypatch):
        repo = _RepoDoble()
        monkeypatch.setattr("db.repositories.documentos.DocumentosRepository", lambda: repo)
        with patch.object(df, "_download_bytes", return_value=(b"%PDF-roto", CONTENT_TYPE_PDF)):
            resultado = df.fetch_and_extract(
                {"id": 8, "uri": "https://x/p.pdf", "source_hash": None, "blob_key": None}
            )
        assert resultado == "error"
        assert [nombre for nombre, _ in repo.marcas][-1] == "mark_error"


class TestFichaBajoDemanda:
    """La ficha dice «escaneado, falta OCR» en vez de «descargas fallidas»."""

    def _detalle(self, monkeypatch, filas: list[dict[str, Any]]) -> str:
        from services.rag import fact_sheet

        class _Repo:
            def list_by_licitacion(self, _licitacion_id: str) -> list[dict[str, Any]]:
                return filas

        monkeypatch.setattr(fact_sheet, "DocumentosRepository", _Repo)
        return fact_sheet._missing_pages_detail("EXP-1", {"attempted": 0})

    def test_un_solo_pliego_escaneado(self, monkeypatch):
        detalle = self._detalle(monkeypatch, [{"status": "sin_texto"}])
        assert "escaneado sin capa de texto" in detalle
        assert "OCR" in detalle
        assert "caducan" not in detalle

    def test_varios_y_solo_algunos_escaneados(self, monkeypatch):
        detalle = self._detalle(
            monkeypatch, [{"status": "sin_texto"}, {"status": "sin_texto"}, {"status": "pending"}]
        )
        assert detalle.startswith("2 de los 3 pliegos")

    def test_con_errores_de_descarga_manda_el_mensaje_de_siempre(self, monkeypatch):
        detalle = self._detalle(monkeypatch, [{"status": "sin_texto"}, {"status": "error"}])
        assert "descargas fallaron" in detalle
