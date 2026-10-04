"""Tests de scraper/document_fetcher.py (plan Pliegos+RAG, F7).

``_download_bytes`` pasa por el circuito de su plataforma
(``breaker_para_host``; el de PLACSP es el singleton compartido con
``scraper/bulk_downloader.py``) y por ``@http_retry``. Los tests que
verifican lógica de negocio (extracción, persistencia) parchean
``document_fetcher._download_bytes`` completo — mismo patrón que
``tests/test_bulk_downloader.py`` — para no tocar el breaker compartido.
Solo los tests de guardas (SSRF, tamaño) que fallan en el primer intento con
``ValueError`` (excluido del breaker, no reintentable) llaman al código real.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pybreaker
import pytest
import requests

from scraper.document_fetcher import (
    DocumentFetchError,
    _download_bytes,
    _extract_paginas,
    _extract_pdf_pages,
    fetch_and_extract,
)


def _extract_pdf_text(content: bytes) -> str:
    """Texto agregado de las páginas de un PDF (el antiguo ``_extract_pdf_text``)."""
    return "\n".join(_extract_pdf_pages(content)).strip()


def _extract_text(content: bytes, content_type: str | None) -> str:
    """Texto agregado según content-type (el antiguo ``_extract_text``)."""
    return "\n".join(p.texto for p in _extract_paginas(content, content_type)).strip()


def _http_error_del_transporte_real(status_code: int) -> requests.HTTPError:
    """El ``HTTPError`` tal y como lo produce la ruta de descarga de verdad.

    Se invoca el ``raise_for_status`` real de ``PinnedHttpsResponse`` en vez de
    construir la excepción a mano: ese método no pasa ``response=``, así que
    ``exc.response`` es ``None`` y cualquier clasificación por
    ``exc.response.status_code`` queda muda en producción aunque el test pase.
    Atarse aquí al transporte real hace que un cambio en el formato del mensaje
    rompa el test en vez de degradar la clasificación en silencio.
    """
    from shared.outbound_http import PinnedHttpsResponse

    respuesta = PinnedHttpsResponse.__new__(PinnedHttpsResponse)
    respuesta.status_code = status_code
    try:
        respuesta.raise_for_status()
    except requests.HTTPError as exc:
        return exc
    raise AssertionError(f"raise_for_status() no lanzó para status {status_code}")


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
        """SSRF: la validación de ``shared/ssrf.py`` rechaza ANTES de llamar requests.get.
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


# ── El 500 con el que el servlet de PLACSP no sirve UN documento ────────────

_URI_SERVLET = (
    "https://contrataciondelestado.es/FileSystem/servlet/GetDocumentByIdServlet"
    "?cifrado=QUC1GjXXSiLkydRHJBmbpw%3D%3D&DocumentIdParam=UR4k/CIhvDBfNUQ5HFSORz"
)
# Respuesta medida el 2026-10-04 con el transporte real para los documentos
# 202384 y 202385 («2026/56 PAS»): 500 en 0,15 s, 42 bytes, sin Content-Length.
_CUERPO_NO_SERVIDO = b"Error 500: java.lang.NullPointerException\n"
_TIPO_NO_SERVIDO = "text/html;charset=ISO-8859-1"


class _RespuestaCruda:
    """Lo que envuelve ``PinnedHttpsResponse``: la respuesta de urllib3 sin precargar."""

    def __init__(self, status: int, cuerpo: bytes, content_type: str) -> None:
        self.status = status
        self.headers = {"Content-Type": content_type}
        self._cuerpo = cuerpo

    def stream(self, amt: int, decode_content: bool = True):
        for inicio in range(0, len(self._cuerpo), amt):
            yield self._cuerpo[inicio : inicio + amt]

    def release_conn(self) -> None:
        pass


class _PoolFalso:
    def close(self) -> None:
        pass


def _respuesta_del_transporte(status: int, cuerpo: bytes, content_type: str):
    """Un ``PinnedHttpsResponse`` de verdad sobre una respuesta enlatada.

    Mismo motivo que ``_http_error_del_transporte_real``: el estado, el cuerpo y
    el ``raise_for_status`` son los del transporte, no los de un ``MagicMock``
    que aceptaría cualquier cosa.
    """
    from shared.outbound_http import PinnedHttpsResponse

    return PinnedHttpsResponse(_PoolFalso(), _RespuestaCruda(status, cuerpo, content_type))


@pytest.fixture()
def circuito(monkeypatch):
    """Un circuito con la configuración real, para no ensuciar el compartido."""
    from scraper import document_fetcher
    from scraper.resilience import _nuevo_breaker

    propio = _nuevo_breaker("placsp-test")
    monkeypatch.setattr(document_fetcher, "breaker_para_host", lambda _host: propio)
    # tenacity duerme entre intentos con el ``sleep`` del decorador: sin
    # anularlo, el caso que sí reintenta tardaría sus ~19 s de verdad.
    monkeypatch.setattr(
        document_fetcher._download_bytes_con_reintentos.retry, "sleep", lambda _s: None
    )
    return propio


def _servir(status: int, cuerpo: bytes, content_type: str):
    """El transporte contesta eso a cualquier petición del fetcher."""
    return patch(
        "scraper.document_fetcher.pinned_https_request",
        side_effect=lambda *_a, **_k: _respuesta_del_transporte(status, cuerpo, content_type),
    )


class TestServletNoSirveElDocumento:
    """El lote de ``pliegos.yml`` se saltó entero tres veces en un mes por esto.

    Cinco documentos seguidos con este 500 abrían el circuito de PLACSP, y
    saltar los demás es instantáneo mientras el circuito tarda 60 s en volver a
    probar: 142 documentos sin intentar el 2026-09-12, 139 el 2026-09-28 y 255
    el 2026-10-01, con el resto de PLACSP contestando 200 en ese mismo momento.
    """

    def test_no_se_reintenta(self, circuito):
        from scraper.resilience import RecursoNoServidoError

        with _servir(500, _CUERPO_NO_SERVIDO, _TIPO_NO_SERVIDO) as transporte:
            with pytest.raises(RecursoNoServidoError):
                _download_bytes(_URI_SERVLET)

        assert transporte.call_count == 1

    def test_cinco_seguidos_no_abren_el_circuito_y_el_lote_sigue(self, circuito):
        from scraper.resilience import RecursoNoServidoError

        with _servir(500, _CUERPO_NO_SERVIDO, _TIPO_NO_SERVIDO):
            for _ in range(circuito.fail_max + 1):
                with pytest.raises(RecursoNoServidoError):
                    _download_bytes(_URI_SERVLET)

        assert circuito.current_state == "closed"
        with _servir(200, b"%PDF-1.6 pliego", "application/pdf"):
            assert _download_bytes(_URI_SERVLET) == (b"%PDF-1.6 pliego", "application/pdf")

    def test_el_error_conserva_el_estado_para_quien_lo_clasifica(self, circuito):
        """``fetch_and_extract`` lee el código con ``_status_de``, del mensaje."""
        from scraper.document_fetcher import _status_de
        from scraper.resilience import RecursoNoServidoError

        with _servir(500, _CUERPO_NO_SERVIDO, _TIPO_NO_SERVIDO):
            with pytest.raises(RecursoNoServidoError) as fallo:
                _download_bytes(_URI_SERVLET)

        assert _status_de(fallo.value) == 500
        assert "NullPointerException" in str(fallo.value)

    def test_otro_500_del_servlet_sigue_siendo_de_la_plataforma(self, circuito):
        """Sin esa firma no se sabe de quién es el fallo: se reintenta y cuenta."""
        from scraper.resilience import RecursoNoServidoError

        with _servir(500, b"<html>Service Unavailable</html>", "text/html") as transporte:
            with pytest.raises(requests.HTTPError) as fallo:
                _download_bytes(_URI_SERVLET)

        assert not isinstance(fallo.value, RecursoNoServidoError)
        assert transporte.call_count == 4
        assert circuito.fail_counter == 1

    def test_la_misma_firma_fuera_del_servlet_no_cambia_de_trato(self, circuito):
        """La regla es la medida en PLACSP; de otro servidor no se sabe nada."""
        from scraper.resilience import RecursoNoServidoError

        with _servir(500, _CUERPO_NO_SERVIDO, _TIPO_NO_SERVIDO) as transporte:
            with pytest.raises(requests.HTTPError) as fallo:
                _download_bytes("https://example.org/pliegos/pcap.pdf")

        assert not isinstance(fallo.value, RecursoNoServidoError)
        assert transporte.call_count == 4


# ── fetch_and_extract: orquestación + persistencia ─────────────────────────


@pytest.fixture()
def repo(tmp_db):
    from db.repositories.documentos import DocumentosRepository

    _db_mod, _ = tmp_db
    return DocumentosRepository()


def _seed_documento(
    repo, licitacion_id: str = "EXP-FETCH-1", *, uri: str = "https://x/pliego.pdf"
) -> dict:
    from db.database import DocumentoReferencia, connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES (%s, %s, 'placsp', CURRENT_TIMESTAMP)",
            (licitacion_id, f"Contrato {licitacion_id}"),
        )
    repo.upsert_meta(
        licitacion_id,
        [DocumentoReferencia(tipo="legal", uri=uri, filename="PCAP.pdf")],
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

    def test_breaker_abierto_no_marca_error_y_deja_la_fila_reintentable(self, repo):
        """El breaker abierto es una condición del servidor, no del documento.

        Marcarlo 'error' lo expulsaría de ``list_pendientes`` para siempre; en
        producción eso convirtió 1.702 documentos sanos en bajas definitivas.
        """
        doc = _seed_documento(repo)

        with patch(
            "scraper.document_fetcher._download_bytes",
            side_effect=pybreaker.CircuitBreakerError(
                "Timeout not elapsed yet, circuit breaker still open"
            ),
        ):
            status = fetch_and_extract(doc)

        assert status == "skipped"
        row = repo.get(doc["id"])
        assert row is not None
        assert row["status"] == "pending"  # sigue en la cola
        assert row["error_detail"] is None

    def test_token_caducado_500_marca_error_nombrando_la_causa(self, repo):
        """El 500 del servlet (token rotativo muerto) conserva el prefijo de
        descarga —es lo que distingue un fallo de red de uno de extracción, y
        lo que permitirá revivir la fila cuando el CODICE traiga token nuevo—
        pero deja la causa escrita para poder contarlos.

        La excepción la produce el ``raise_for_status`` **real** del transporte,
        no una fabricada a mano: ``PinnedHttpsResponse`` construye el
        ``HTTPError`` sin ``response=``, así que un test que inyecte
        ``HTTPError(..., response=Mock(status_code=500))`` pasa en verde contra
        una rama que en producción no se ejecuta nunca.
        """
        doc = _seed_documento(repo)

        with patch(
            "scraper.document_fetcher._download_bytes",
            side_effect=_http_error_del_transporte_real(500),
        ):
            status = fetch_and_extract(doc)

        assert status == "error"
        row = repo.get(doc["id"])
        assert row is not None
        detalle = row["error_detail"] or ""
        assert detalle.startswith("descarga fallida:")
        assert "token caducado (500)" in detalle

    def test_documento_no_servido_marca_error_con_su_causa_y_no_la_del_token(self, repo):
        """El 500 que el servlet da por UN documento no es un token caducado.

        Conserva el prefijo de descarga —sigue siendo un fallo de descarga, y es
        lo que deja que la fila vuelva a intentarse— y nombra lo que pasó, que
        además es lo que distingue estas filas al contarlas.
        """
        from scraper.resilience import RecursoNoServidoError

        doc = _seed_documento(repo)

        with patch(
            "scraper.document_fetcher._download_bytes",
            side_effect=RecursoNoServidoError(
                "Pinned HTTPS response status 500: el servlet de PLACSP "
                "no sirve este documento (NullPointerException)"
            ),
        ):
            status = fetch_and_extract(doc)

        assert status == "error"
        row = repo.get(doc["id"])
        assert row is not None
        detalle = row["error_detail"] or ""
        assert detalle.startswith("descarga fallida:")
        assert "no sirve este documento" in detalle
        assert "token caducado" not in detalle

    def test_http_error_no_500_no_se_etiqueta_como_token_caducado(self, repo):
        doc = _seed_documento(repo)

        with patch(
            "scraper.document_fetcher._download_bytes",
            side_effect=_http_error_del_transporte_real(404),
        ):
            status = fetch_and_extract(doc)

        assert status == "error"
        row = repo.get(doc["id"])
        assert row is not None
        detalle = row["error_detail"] or ""
        assert detalle.startswith("descarga fallida:")
        assert "token caducado" not in detalle

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

    def test_unsupported_content_type_marks_unsupported_not_error(self, repo):
        """Desde S8.2 (``v103``) «no lo sé leer» dejó de ser «falló».

        El aserto viejo (``status == "error"``) ya no vale porque medía dos
        cosas distintas con la misma etiqueta: un PDF corrupto es un fallo y un
        formato sin parser es cobertura que falta. Solo separados se puede
        contar cuánta falta y de qué tipo (``formato_counts``), así que el
        estado terminal es ``unsupported`` y conserva el ``content_type``.
        """
        doc = _seed_documento(repo)

        with patch(
            "scraper.document_fetcher._download_bytes",
            return_value=(b"<html>no es un pliego</html>", "text/html"),
        ):
            status = fetch_and_extract(doc)

        assert status == "unsupported"
        row = repo.get(doc["id"])
        assert row is not None
        assert row["status"] == "unsupported"
        assert row["content_type"] == "text/html"
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


class TestLoQueEscribeElFetcherYLoQueSeReintenta:
    """Contrato entre quien escribe ``error_detail`` y quien decide el reintento.

    ``DocumentosRepository.revivir_descargas_fallidas`` reconoce por el texto
    los fallos que vinieron de la fuente. Aquí cada fallo recorre el camino de
    verdad —el transporte, el servlet, la guarda de tamaño— para que cambiar la
    redacción de cualquiera rompa este test en vez de dejar el reintento mudo.
    """

    def _detalle_tras_fallar(self, repo, uri: str = "https://x/pliego.pdf") -> str:
        doc = _seed_documento(repo, uri=uri)
        assert fetch_and_extract(doc) == "error"
        return str(repo.get(doc["id"])["error_detail"])

    def test_un_estado_http_de_error_es_de_la_fuente(self, repo, circuito):
        from db.repositories.documentos import _fallo_achacable_a_la_fuente

        with _servir(503, b"Service Unavailable", "text/html"):
            detalle = self._detalle_tras_fallar(repo)

        assert _fallo_achacable_a_la_fuente(detalle), detalle

    def test_el_documento_que_el_servlet_no_sirve_es_de_la_fuente(self, repo, circuito):
        from db.repositories.documentos import _fallo_achacable_a_la_fuente

        with _servir(500, _CUERPO_NO_SERVIDO, _TIPO_NO_SERVIDO):
            detalle = self._detalle_tras_fallar(repo, uri=_URI_SERVLET)

        assert _fallo_achacable_a_la_fuente(detalle), detalle

    def test_un_corte_de_red_es_de_la_fuente(self, repo, circuito, monkeypatch):
        """Sale del ``pinned_https_request`` real, con la conexión cortada debajo."""
        import urllib3

        from db.repositories.documentos import _fallo_achacable_a_la_fuente
        from shared import outbound_http
        from shared.ssrf import PinnedHttpsTarget

        def sin_red(*_a, **_k):
            raise urllib3.exceptions.ConnectTimeoutError("sin red")

        monkeypatch.setattr(
            outbound_http,
            "resolve_pinned_https_target",
            lambda _url, **_k: PinnedHttpsTarget(
                hostname="x", address="192.0.2.1", port=443, request_uri="/pliego.pdf"
            ),
        )
        monkeypatch.setattr(urllib3.HTTPSConnectionPool, "urlopen", sin_red)

        detalle = self._detalle_tras_fallar(repo)

        assert _fallo_achacable_a_la_fuente(detalle), detalle

    def test_lo_que_frena_la_guarda_de_tamano_no_lo_es(self, repo, circuito, monkeypatch):
        from db.repositories.documentos import _fallo_achacable_a_la_fuente

        monkeypatch.setattr("scraper.document_fetcher.settings.MAX_DOCUMENT_SIZE_BYTES", 10)

        with _servir(200, b"x" * 20, "application/pdf"):
            detalle = self._detalle_tras_fallar(repo)

        assert detalle.startswith("descarga fallida:")
        assert not _fallo_achacable_a_la_fuente(detalle), detalle
