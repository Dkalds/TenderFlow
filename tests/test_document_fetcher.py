"""Tests de scraper/document_fetcher.py (plan Pliegos+RAG, F7).

``_download_bytes`` está decorado con ``@placsp_breaker``/``@http_retry``
(singleton compartido con ``scraper/bulk_downloader.py``). Los tests que
verifican lógica de negocio (extracción, persistencia) parchean
``document_fetcher._download_bytes`` completo — mismo patrón que
``tests/test_bulk_downloader.py`` — para no tocar el breaker compartido.
Solo los tests de guardas (SSRF, tamaño) que fallan en el primer intento con
``ValueError`` (excluido del breaker, no reintentable) llaman al código real.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from scraper.document_fetcher import (
    DocumentFetchError,
    _download_bytes,
    _extract_pdf_text,
    _extract_text,
    fetch_and_extract,
)


def _make_minimal_pdf(text: str = "Pliego de condiciones de prueba") -> bytes:
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, text)
    c.save()
    return buf.getvalue()


# ── Extracción de texto (pura, sin red) ────────────────────────────────────


class TestExtractPdfText:
    def test_extracts_text_from_valid_pdf(self):
        pdf_bytes = _make_minimal_pdf("Cláusula primera: objeto del contrato")
        texto = _extract_pdf_text(pdf_bytes)
        assert "Cláusula primera" in texto or "objeto del contrato" in texto

    def test_corrupt_pdf_raises_document_fetch_error(self):
        with pytest.raises(DocumentFetchError, match="corrupto o ilegible"):
            _extract_pdf_text(b"esto no es un PDF valido, son bytes cualquiera")

    def test_empty_pdf_bytes_raises(self):
        with pytest.raises(DocumentFetchError):
            _extract_pdf_text(b"")

    def test_production_timeout_terminates_isolated_parser(self, monkeypatch):
        """Un PDF que no devuelve resultado no puede retener el worker indefinidamente."""
        from config import settings

        monkeypatch.setattr(settings, "ENV", "prod")
        monkeypatch.setattr(settings, "DOCUMENT_EXTRACTION_TIMEOUT_SECONDS", 0.01)
        receive_connection = MagicMock()
        receive_connection.poll.return_value = False
        send_connection = MagicMock()
        process = MagicMock()
        process.is_alive.return_value = False
        context = MagicMock()
        context.Pipe.return_value = (receive_connection, send_connection)
        context.Process.return_value = process

        with patch("scraper.document_fetcher.multiprocessing.get_context", return_value=context):
            with pytest.raises(DocumentFetchError, match="tiempo máximo"):
                _extract_pdf_text(b"un PDF que no debe llegar al parser")

        process.terminate.assert_called()


class TestExtractText:
    def test_text_plain_decodes(self):
        assert _extract_text(b"contenido del pliego", "text/plain") == "contenido del pliego"

    def test_text_plain_vacio_raises(self):
        with pytest.raises(DocumentFetchError, match="vac"):
            _extract_text(b"   ", "text/plain")

    def test_pdf_content_type_dispatches_to_pdf_extraction(self):
        pdf_bytes = _make_minimal_pdf("Texto del pliego técnico")
        texto = _extract_text(pdf_bytes, "application/pdf")
        assert texto  # no vacío

    def test_none_content_type_falls_back_to_pdf(self):
        """Algunos servidores no envían Content-Type — asumimos PDF (caso común)."""
        pdf_bytes = _make_minimal_pdf("Sin content-type declarado")
        texto = _extract_text(pdf_bytes, None)
        assert texto

    def test_unsupported_content_type_raises(self):
        with pytest.raises(DocumentFetchError, match="no soportado"):
            _extract_text(b"<html></html>", "text/html")


# ── Guardas de descarga: SSRF y tamaño (código real, sin red) ──────────────


class TestDownloadGuards:
    def test_private_ip_rejected_before_any_request(self):
        """SSRF: resolve_and_validate rechaza ANTES de llamar requests.get.
        ValueError excluido del breaker/retry -- un único intento, seguro."""
        with pytest.raises(ValueError):
            _download_bytes("http://127.0.0.1:9999/pliego.pdf")

    def test_dns_rebinding_domain_rejected(self):
        with pytest.raises(ValueError, match="rebinding"):
            _download_bytes("https://10.0.0.1.nip.io/pliego.pdf")

    def test_content_length_header_exceeding_limit_rejected(self, monkeypatch):
        monkeypatch.setattr("scraper.document_fetcher.settings.MAX_DOCUMENT_SIZE_BYTES", 100)
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/pdf", "Content-Length": "999999"}
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("scraper.document_fetcher.pinned_https_request", return_value=mock_resp):
            with pytest.raises(ValueError, match="Content-Length"):
                _download_bytes("https://example.com/pliego.pdf")

    def test_streamed_size_exceeding_limit_aborts(self, monkeypatch):
        """El header puede mentir -- el contador en streaming es la guarda real."""
        monkeypatch.setattr("scraper.document_fetcher.settings.MAX_DOCUMENT_SIZE_BYTES", 10)
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/pdf"}  # sin Content-Length
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content = MagicMock(return_value=iter([b"x" * 20]))
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("scraper.document_fetcher.pinned_https_request", return_value=mock_resp):
            with pytest.raises(ValueError, match="Descarga abortada"):
                _download_bytes("https://example.com/pliego.pdf")


# ── fetch_and_extract: orquestación + persistencia ─────────────────────────


@pytest.fixture()
def repo(tmp_db):
    from db.repositories.documentos import DocumentosRepository

    _db_mod, _ = tmp_db
    return DocumentosRepository()


def _seed_documento(repo, licitacion_id: str = "EXP-FETCH-1") -> dict:
    from db.database import DocumentoReferencia, connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES (?, ?, 'placsp', CURRENT_TIMESTAMP)",
            (licitacion_id, f"Contrato {licitacion_id}"),
        )
    repo.upsert_meta(
        licitacion_id,
        [DocumentoReferencia(tipo="legal", uri="https://x/pliego.pdf", filename="PCAP.pdf")],
    )
    return repo.list_pendientes()[0]


class TestFetchAndExtract:
    def test_success_marks_extracted(self, repo):
        doc = _seed_documento(repo)
        pdf_bytes = _make_minimal_pdf("Objeto del contrato: mantenimiento SAP")

        with patch(
            "scraper.document_fetcher._download_bytes",
            return_value=(pdf_bytes, "application/pdf"),
        ):
            status = fetch_and_extract(doc)

        assert status == "extracted"
        row = repo.get(doc["id"])
        assert row is not None
        assert row["status"] == "extracted"
        assert row["texto"]
        assert row["sha256"] is not None

    def test_download_failure_marks_error(self, repo):
        doc = _seed_documento(repo)

        with patch(
            "scraper.document_fetcher._download_bytes",
            side_effect=ValueError("private network"),
        ):
            status = fetch_and_extract(doc)

        assert status == "error"
        row = repo.get(doc["id"])
        assert row is not None
        assert row["status"] == "error"
        assert "descarga fallida" in (row["error_detail"] or "")

    def test_corrupt_pdf_marks_error_but_records_download_metadata(self, repo):
        """Extracción fallida tras descarga OK: se persiste sha256/size (útil
        para diagnóstico) y el status final es 'error', no 'downloaded'."""
        doc = _seed_documento(repo)

        with patch(
            "scraper.document_fetcher._download_bytes",
            return_value=(b"no es un pdf valido", "application/pdf"),
        ):
            status = fetch_and_extract(doc)

        assert status == "error"
        row = repo.get(doc["id"])
        assert row is not None
        assert row["status"] == "error"
        assert row["sha256"] is not None  # la descarga sí completó
        assert row["size_bytes"] == len(b"no es un pdf valido")
        assert "corrupto" in (row["error_detail"] or "")

    def test_unsupported_content_type_marks_error(self, repo):
        doc = _seed_documento(repo)

        with patch(
            "scraper.document_fetcher._download_bytes",
            return_value=(b"<html>no es un pliego</html>", "text/html"),
        ):
            status = fetch_and_extract(doc)

        assert status == "error"
        row = repo.get(doc["id"])
        assert row is not None
        assert "no soportado" in (row["error_detail"] or "")

    def test_text_plain_document_extracted(self, repo):
        doc = _seed_documento(repo)

        with patch(
            "scraper.document_fetcher._download_bytes",
            return_value=(b"Anexo tecnico en texto plano", "text/plain"),
        ):
            status = fetch_and_extract(doc)

        assert status == "extracted"
        row = repo.get(doc["id"])
        assert row is not None
        assert row["texto"] == "Anexo tecnico en texto plano"
