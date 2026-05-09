"""Tests para scraper/bulk_downloader.py (iter_xml_files, download_month logic)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pybreaker
import pytest
import requests

from scraper.bulk_downloader import (
    BULK_URL_TEMPLATE,
    CircuitOpenError,
    download_month,
    iter_xml_files,
)

# ─── iter_xml_files ──────────────────────────────────────────────────────────


class TestIterXmlFiles:
    def _make_zip(self, files: dict[str, bytes], tmp_path: Path) -> Path:
        """Crea un ZIP en tmp_path con los ficheros dados."""
        zpath = tmp_path / "test.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return zpath

    def test_yields_xml_files(self, tmp_path):
        zpath = self._make_zip({"feed.xml": b"<data/>", "other.txt": b"skip me"}, tmp_path)
        results = list(iter_xml_files(zpath))
        names = [r[0] for r in results]
        assert "feed.xml" in names
        assert "other.txt" not in names

    def test_yields_atom_files(self, tmp_path):
        zpath = self._make_zip({"feed.atom": b"<atom/>"}, tmp_path)
        results = list(iter_xml_files(zpath))
        assert len(results) == 1
        assert results[0][0] == "feed.atom"

    def test_returns_bytes_content(self, tmp_path):
        content = b"<licitacion>test</licitacion>"
        zpath = self._make_zip({"data.xml": content}, tmp_path)
        results = list(iter_xml_files(zpath))
        assert results[0][1] == content

    def test_empty_zip_returns_nothing(self, tmp_path):
        zpath = self._make_zip({}, tmp_path)
        assert list(iter_xml_files(zpath)) == []

    def test_case_insensitive_extension(self, tmp_path):
        zpath = self._make_zip({"DATA.XML": b"<x/>", "FEED.ATOM": b"<a/>"}, tmp_path)
        results = list(iter_xml_files(zpath))
        assert len(results) == 2

    def test_multiple_xml_files_all_yielded(self, tmp_path):
        files = {f"file{i}.xml": f"<doc id='{i}'/>".encode() for i in range(5)}
        zpath = self._make_zip(files, tmp_path)
        results = list(iter_xml_files(zpath))
        assert len(results) == 5


# ─── download_month ──────────────────────────────────────────────────────────


class TestDownloadMonth:
    def _make_valid_zip(self, tmp_path: Path) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("data.xml", b"<data/>")
        return buf.getvalue()

    def test_cache_hit_returns_existing_file(self, tmp_path):
        """Si el ZIP ya existe y es válido, no descarga de nuevo."""
        dest = tmp_path / "placsp_202401.zip"
        # Crear un ZIP válido en la ruta de caché
        with zipfile.ZipFile(dest, "w") as zf:
            zf.writestr("feed.xml", b"<x/>")

        with (
            patch("scraper.bulk_downloader.settings.DOWNLOADS_DIR", tmp_path),
            patch("scraper.bulk_downloader.ensure_data_dirs"),
        ):
            result = download_month(2024, 1)

        assert result == dest

    def test_cache_hit_with_force_redownloads(self, tmp_path):
        """Con force=True se descarga aunque ya exista el ZIP."""
        dest = tmp_path / "placsp_202401.zip"
        with zipfile.ZipFile(dest, "w") as zf:
            zf.writestr("feed.xml", b"<x/>")

        zip_bytes = self._make_valid_zip(tmp_path)
        mock_response = MagicMock()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {}
        mock_response.iter_content = MagicMock(return_value=[zip_bytes])

        with (
            patch("scraper.bulk_downloader.settings.DOWNLOADS_DIR", tmp_path),
            patch("scraper.bulk_downloader.ensure_data_dirs"),
            patch("scraper.bulk_downloader.time.sleep"),
            patch("requests.get", return_value=mock_response),
        ):
            result = download_month(2024, 1, force=True)

        assert result is not None

    def test_404_returns_none(self, tmp_path):
        """Un 404 significa que el mes no está publicado."""
        http_err = requests.HTTPError()
        http_err.response = MagicMock()
        http_err.response.status_code = 404

        with (
            patch("scraper.bulk_downloader.settings.DOWNLOADS_DIR", tmp_path),
            patch("scraper.bulk_downloader.ensure_data_dirs"),
            patch("scraper.bulk_downloader.time.sleep"),
            patch("scraper.bulk_downloader._download", side_effect=http_err),
        ):
            result = download_month(2024, 1)

        assert result is None

    def test_circuit_breaker_raises_circuit_open_error(self, tmp_path):
        """Un CircuitBreakerError se transforma en CircuitOpenError."""
        with (
            patch("scraper.bulk_downloader.settings.DOWNLOADS_DIR", tmp_path),
            patch("scraper.bulk_downloader.ensure_data_dirs"),
            patch("scraper.bulk_downloader.time.sleep"),
            patch(
                "scraper.bulk_downloader._download",
                side_effect=pybreaker.CircuitBreakerError("open"),
            ),
            pytest.raises(CircuitOpenError),
        ):
            download_month(2024, 1)

    def test_corrupt_cache_is_removed_and_redownloaded(self, tmp_path):
        """Un ZIP corrupto en caché se elimina antes de reintentarlo."""
        dest = tmp_path / "placsp_202402.zip"
        dest.write_bytes(b"NOT A ZIP FILE")

        http_err = requests.HTTPError()
        http_err.response = MagicMock()
        http_err.response.status_code = 404

        with (
            patch("scraper.bulk_downloader.settings.DOWNLOADS_DIR", tmp_path),
            patch("scraper.bulk_downloader.ensure_data_dirs"),
            patch("scraper.bulk_downloader.time.sleep"),
            patch("scraper.bulk_downloader._download", side_effect=http_err),
        ):
            result = download_month(2024, 2)

        assert not dest.exists()
        assert result is None

    def test_url_template_format(self):
        url = BULK_URL_TEMPLATE.format(year=2024, month=3)
        assert "202403" in url
        assert url.startswith("https://")

    def test_non_zip_response_returns_none(self, tmp_path):
        """Si la respuesta no es un ZIP válido, retorna None."""

        def fake_download(url, d):
            d.write_bytes(b"<html>Error page</html>")
            return d

        with (
            patch("scraper.bulk_downloader.settings.DOWNLOADS_DIR", tmp_path),
            patch("scraper.bulk_downloader.ensure_data_dirs"),
            patch("scraper.bulk_downloader.time.sleep"),
            patch("scraper.bulk_downloader._download", side_effect=fake_download),
        ):
            result = download_month(2024, 3)

        assert result is None
