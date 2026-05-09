"""Descarga y procesa los ficheros mensuales de datos abiertos del PLACSP.

La Plataforma de Contratación del Sector Público publica mensualmente
ficheros ATOM/XML con todas las licitaciones agregadas. Esta es la vía
oficial y recomendada para reutilización (Ley 37/2007).

URL pattern (verificar contra la última publicación oficial):
  https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/
  licitacionesPerfilesContratanteCompleto3_YYYYMM.zip
"""

from __future__ import annotations

import time
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pybreaker
import requests

from config import (
    DOWNLOADS_DIR,
    MAX_DOWNLOAD_SIZE_BYTES,
    MAX_XML_SIZE_BYTES,
    REQUEST_DELAY_SECONDS,
    REQUEST_TIMEOUT,
    USER_AGENT,
    ensure_data_dirs,
)
from observability.logging import get_logger
from scraper.resilience import http_retry, placsp_breaker

log = get_logger(__name__)

# Rutas base conocidas para los datasets mensuales
BULK_URL_TEMPLATE = (
    "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/"
    "licitacionesPerfilesContratanteCompleto3_{year}{month:02d}.zip"
)


@placsp_breaker
@http_retry
def _download(url: str, dest: Path) -> Path:
    log.info("bulk_download_start", url=url, dest=str(dest))
    headers = {"User-Agent": USER_AGENT}
    with requests.get(url, headers=headers, stream=True, timeout=REQUEST_TIMEOUT) as r:
        r.raise_for_status()
        content_length = r.headers.get("Content-Length")
        if content_length is not None:
            size = int(content_length)
            if size > MAX_DOWNLOAD_SIZE_BYTES:
                raise ValueError(
                    f"Descarga rechazada: Content-Length {size:,} bytes "
                    f"supera el límite de {MAX_DOWNLOAD_SIZE_BYTES:,} bytes."
                )
        with open(dest, "wb") as f:
            downloaded = 0
            for chunk in r.iter_content(chunk_size=8192):
                downloaded += len(chunk)
                if downloaded > MAX_DOWNLOAD_SIZE_BYTES:
                    dest.unlink(missing_ok=True)
                    raise ValueError(
                        f"Descarga abortada: tamaño real supera {MAX_DOWNLOAD_SIZE_BYTES:,} bytes."
                    )
                f.write(chunk)
    log.info("bulk_download_ok", url=url, bytes=downloaded)
    return dest


class CircuitOpenError(RuntimeError):
    """El circuit breaker está abierto — PLACSP está caído."""


def download_month(year: int, month: int, force: bool = False) -> Path | None:
    """Descarga el ZIP mensual. Devuelve la ruta o None si no existe."""
    ensure_data_dirs()
    assert DOWNLOADS_DIR is not None  # garantizado por ensure_data_dirs()
    url = BULK_URL_TEMPLATE.format(year=year, month=month)
    dest = DOWNLOADS_DIR / f"placsp_{year}{month:02d}.zip"

    if dest.exists() and not force:
        if zipfile.is_zipfile(dest):
            log.info("bulk_cache_hit", dest=dest.name)
            return dest
        log.warning("bulk_cache_corrupt", dest=dest.name)
        dest.unlink()

    try:
        time.sleep(REQUEST_DELAY_SECONDS)
        _download(url, dest)
        if not zipfile.is_zipfile(dest):
            log.warning("bulk_not_a_zip", year=year, month=month)
            dest.unlink(missing_ok=True)
            return None
        return dest
    except pybreaker.CircuitBreakerError as e:
        raise CircuitOpenError(str(e)) from e
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            log.warning("bulk_not_published", year=year, month=month)
            return None
        raise


def iter_xml_files(zip_path: Path) -> Iterator[tuple[str, bytes]]:
    """Itera sobre los XML contenidos en el ZIP descargado."""
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.lower().endswith(".atom") or name.lower().endswith(".xml"):
                info = zf.getinfo(name)
                if info.file_size > MAX_XML_SIZE_BYTES:
                    log.warning(
                        "zip_member_too_large",
                        name=name,
                        file_size=info.file_size,
                        limit=MAX_XML_SIZE_BYTES,
                    )
                    continue
                with zf.open(name) as f:
                    yield name, f.read()
