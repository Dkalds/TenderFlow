"""TED, RSS regionales y TACRC reintentan un fallo HTTP transitorio.

Hasta 2026-11 pedían con su sesión a pelo: un timeout o un 503 suelto tumbaba
la pasada. Ahora van por ``scraper.resilience.pedir_con_reintentos`` (el
``http_retry`` de PSCP, ATOM y bulk). Sin red: sesiones de mentira, y las
esperas de tenacity anuladas.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

from scraper.resilience import pedir_con_reintentos


class _Respuesta:
    def __init__(self, estado: int, *, payload: Any = None, content: bytes = b"") -> None:
        self.status_code = estado
        self._payload = payload
        self.content = content
        self.text = content.decode()
        self.url = "https://ejemplo.invalid/"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error", response=self)  # type: ignore[arg-type]

    def json(self) -> Any:
        return self._payload


class _Sesion:
    """Devuelve las respuestas en orden; una excepción de la lista se lanza."""

    def __init__(self, *respuestas: _Respuesta | Exception) -> None:
        self.respuestas = list(respuestas)
        self.llamadas = 0

    def _siguiente(self) -> _Respuesta:
        self.llamadas += 1
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def get(self, url: str, **kw: object) -> _Respuesta:
        return self._siguiente()

    def post(self, url: str, **kw: object) -> _Respuesta:
        return self._siguiente()


@pytest.fixture(autouse=True)
def _sin_esperas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pedir_con_reintentos.retry, "sleep", lambda _s: None)  # type: ignore[attr-defined]


def test_ted_reintenta_un_503_de_la_api() -> None:
    from scraper.connectors.ted import TedConnector

    sesion = _Sesion(
        _Respuesta(503),
        _Respuesta(200, payload={"notices": [], "totalNoticeCount": 0}),
    )
    conector = TedConnector(session=sesion)  # type: ignore[arg-type]

    assert list(conector.fetch(None)) == []
    assert sesion.llamadas == 2


def test_rss_regional_reintenta_un_timeout() -> None:
    from scraper.connectors.galicia import GaliciaRssConnector

    rss = b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
    sesion = _Sesion(requests.Timeout("lento"), _Respuesta(200, content=rss))
    conector = GaliciaRssConnector(session=sesion)  # type: ignore[arg-type]

    assert list(conector.fetch(None)) == []
    assert sesion.llamadas == 2


def test_tacrc_reintenta_un_corte_a_medias() -> None:
    from scraper.connectors import tacrc

    sesion = _Sesion(
        requests.exceptions.ChunkedEncodingError("cortado"),
        _Respuesta(200, content=b"<html></html>"),
    )

    assert tacrc.fetch_index("https://tribunal.example/index.html", session=sesion) == (  # type: ignore[arg-type]
        "<html></html>"
    )
    assert sesion.llamadas == 2


def test_tacrc_no_reintenta_un_404() -> None:
    """Un año sin carpeta responde 404: no es transitorio y ``run`` lo trata aparte."""
    from scraper.connectors import tacrc

    sesion = _Sesion(_Respuesta(404), _Respuesta(200))

    with pytest.raises(requests.HTTPError):
        tacrc.fetch_index("https://tribunal.example/index.html", session=sesion)  # type: ignore[arg-type]
    assert sesion.llamadas == 1
