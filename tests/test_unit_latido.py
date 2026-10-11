"""Latido externo del healthcheck (``scheduler/latido.py``).

Sin red: ``pinned_https_request`` se sustituye por un doble que apunta las
llamadas. Lo que se fija es cuándo late, cuándo calla y que nunca lanza.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import requests
from pydantic import SecretStr

from scheduler import healthcheck, latido

URL = "https://hc-ping.test/0f1e2d3c-identificador-del-check"


class _Respuesta:
    def __init__(self, status: int) -> None:
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 300:
            raise requests.HTTPError(f"status {self.status_code}")

    def __enter__(self) -> _Respuesta:
        return self

    def __exit__(self, *_: object) -> None:
        return None


@pytest.fixture
def llamadas(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Activa la URL del latido y recoge cada petición que se intenta."""
    monkeypatch.setattr(
        "config.settings", SimpleNamespace(HEALTHCHECK_HEARTBEAT_URL=SecretStr(URL))
    )
    hechas: list[dict[str, Any]] = []

    def _peticion(method: str, url: str, **kwargs: Any) -> _Respuesta:
        hechas.append({"method": method, "url": url, **kwargs})
        return _Respuesta(200)

    monkeypatch.setattr(latido, "pinned_https_request", _peticion)
    return hechas


def test_sin_url_no_hace_ninguna_peticion(
    llamadas: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("config.settings", SimpleNamespace(HEALTHCHECK_HEARTBEAT_URL=SecretStr("")))
    assert latido.enviar_latido({"status": "healthy"}) is False
    assert llamadas == []


@pytest.mark.parametrize("estado", ["healthy", "degraded"])
def test_late_si_el_chequeo_no_es_critico(llamadas: list[dict[str, Any]], estado: str) -> None:
    assert latido.enviar_latido({"status": estado}) is True
    (llamada,) = llamadas
    assert llamada["method"] == "GET"
    assert llamada["url"] == URL
    # La allowlist es el host de la propia URL: ni redirecciones ni otro destino.
    assert llamada["allowed_hosts"] == frozenset({"hc-ping.test"})


def test_un_estado_critico_no_late(llamadas: list[dict[str, Any]]) -> None:
    """Un crítico sostenido tiene que disparar el interruptor, no alimentarlo."""
    assert latido.enviar_latido({"status": "critical"}) is False
    assert llamadas == []


@pytest.mark.parametrize(
    "fallo",
    [
        requests.RequestException("Pinned HTTPS request failed"),
        ValueError("Host resuelve a una dirección no global"),
        OSError("red caída"),
    ],
)
def test_un_fallo_de_red_se_reintenta_una_vez_y_no_lanza(
    monkeypatch: pytest.MonkeyPatch, llamadas: list[dict[str, Any]], fallo: Exception
) -> None:
    intentos: list[str] = []

    def _rota(method: str, url: str, **_: Any) -> _Respuesta:
        intentos.append(url)
        raise fallo

    monkeypatch.setattr(latido, "pinned_https_request", _rota)
    assert latido.enviar_latido({"status": "healthy"}) is False
    assert len(intentos) == 2


def test_una_respuesta_de_error_no_cuenta_como_latido(
    monkeypatch: pytest.MonkeyPatch, llamadas: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(latido, "pinned_https_request", lambda *_a, **_k: _Respuesta(404))
    assert latido.enviar_latido({"status": "healthy"}) is False


def test_la_url_no_llega_a_los_logs(
    llamadas: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """La URL identifica el check y vale como credencial: al log va solo el host."""
    eventos: list[dict[str, Any]] = []
    registro = SimpleNamespace(
        info=lambda evento, **campos: eventos.append({"evento": evento, **campos}),
        warning=lambda evento, **campos: eventos.append({"evento": evento, **campos}),
    )
    monkeypatch.setattr(latido, "log", registro)

    latido.enviar_latido({"status": "healthy"})
    monkeypatch.setattr(
        latido,
        "pinned_https_request",
        lambda *_a, **_k: (_ for _ in ()).throw(requests.RequestException(URL)),
    )
    latido.enviar_latido({"status": "healthy"})

    assert [e["evento"] for e in eventos] == ["latido_enviado", "latido_fallido", "latido_fallido"]
    assert "identificador-del-check" not in repr(eventos)


def test_el_chequeo_post_pasada_termina_con_el_latido(monkeypatch: pytest.MonkeyPatch) -> None:
    """El camino del worker (``daily_atom``) late igual que la CLI con ``--alert``."""
    orden: list[str] = []
    resultado = {"status": "degraded", "warnings": ["dlq_above_threshold:53"], "errors": []}
    monkeypatch.setattr(healthcheck, "run_check", lambda: resultado)
    monkeypatch.setattr(healthcheck, "alertar", lambda r: orden.append("alerta"))
    monkeypatch.setattr(
        healthcheck, "enviar_latido", lambda r: orden.append(f"latido:{r['status']}")
    )

    assert healthcheck.comprobar_y_alertar() is resultado
    assert orden == ["alerta", "latido:degraded"]


@pytest.mark.parametrize(("argv", "late"), [(["--alert"], True), ([], False)])
def test_la_cli_solo_late_con_alert(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str], late: bool
) -> None:
    latidos: list[str] = []
    resultado = {"status": "healthy", "warnings": [], "errors": [], "info": {}, "checks": []}
    monkeypatch.setattr(healthcheck, "run_check", lambda *_a: resultado)
    monkeypatch.setattr(healthcheck, "configure_logging", lambda: None)
    monkeypatch.setattr(healthcheck, "alertar", lambda r: None)
    monkeypatch.setattr(healthcheck, "enviar_latido", lambda r: latidos.append(r["status"]))
    monkeypatch.setattr("sys.argv", ["healthcheck", *argv])

    assert healthcheck.main() == 0
    capsys.readouterr()
    assert latidos == (["healthy"] if late else [])
