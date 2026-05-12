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
    USER_AGENT,
    ensure_data_dirs,
    settings,
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
    tmp = dest.with_suffix(".tmp")
    with requests.get(url, headers=headers, stream=True, timeout=settings.REQUEST_TIMEOUT) as r:
        r.raise_for_status()
        content_length = r.headers.get("Content-Length")
        if content_length is not None:
            size = int(content_length)
            if size > settings.MAX_DOWNLOAD_SIZE_BYTES:
                raise ValueError(
                    f"Descarga rechazada: Content-Length {size:,} bytes "
                    f"supera el límite de {settings.MAX_DOWNLOAD_SIZE_BYTES:,} bytes."
                )
        downloaded = 0
        try:
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    downloaded += len(chunk)
                    if downloaded > settings.MAX_DOWNLOAD_SIZE_BYTES:
                        raise ValueError(
                            f"Descarga abortada: tamaño real supera {settings.MAX_DOWNLOAD_SIZE_BYTES:,} bytes."
                        )
                    f.write(chunk)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    tmp.replace(dest)
    log.info("bulk_download_ok", url=url, bytes=downloaded)
    return dest


class CircuitOpenError(RuntimeError):
    """El circuit breaker está abierto — PLACSP está caído."""


def download_month(year: int, month: int, force: bool = False) -> Path | None:
    """Descarga el ZIP mensual. Devuelve la ruta o None si no existe."""
    if not (1 <= month <= 12):
        raise ValueError(f"month must be 1-12, got {month}")
    if year < 2000:
        raise ValueError(f"year must be >= 2000, got {year}")
    ensure_data_dirs()
    assert settings.DOWNLOADS_DIR is not None  # garantizado por ensure_data_dirs()
    url = BULK_URL_TEMPLATE.format(year=year, month=month)
    dest = settings.DOWNLOADS_DIR / f"placsp_{year}{month:02d}.zip"

    if dest.exists() and not force:
        if zipfile.is_zipfile(dest):
            log.info("bulk_cache_hit", dest=dest.name)
            return dest
        log.warning("bulk_cache_corrupt", dest=dest.name)
        dest.unlink()

    try:
        time.sleep(settings.REQUEST_DELAY_SECONDS)
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
                if info.file_size > settings.MAX_XML_SIZE_BYTES:
                    log.warning(
                        "zip_member_too_large",
                        name=name,
                        file_size=info.file_size,
                        limit=settings.MAX_XML_SIZE_BYTES,
                    )
                    continue
                with zf.open(name) as f:
                    yield name, f.read()
