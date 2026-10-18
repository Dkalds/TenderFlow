"""El gate de ``deploy.yml`` verifica la instancia que acaba de desplegar.

Motivación
----------
Hasta el 2026-10-17 la espera de ``deploy.yml`` daba la API por lista con el
primer 200 de ``/health/ready``. Render despliega sin corte, así que ese 200 lo
daba la instancia anterior: en el run 38766484577 la espera salió al primer
intento (16:08:53), schema y smoke terminaron a las 16:09:05 y el deploy
encolado no quedó vivo hasta las 16:09:32. Con ``autoDeploy`` apagado, un
deploy que no arranca habría salido verde.

Se fija aquí:

- que ``/health/ready`` publica el commit que sirve (``commit``);
- que ``scripts/esperar_deploy.py`` no acepta un 200 de otra versión, ni de la
  anterior a este gate (sin el campo);
- que ``deploy.yml`` espera a ``github.sha`` y que el gate de schema lee el
  payload verificado en vez de volver a preguntar.

Sin red ni base de datos: el sondeo se sustituye por dobles.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from api.routes import health
from scripts import esperar_deploy

# SHAs de commits reales del repo (#471 y #465), no credenciales.
_SHA = "e8889a0c6eed6f6cbf721aa964a0aa3ef7fb18e5"  # pragma: allowlist secret
_SHA_ANTERIOR = "9ed4d69acdf7af388f948e35737980ec46ba3855"  # pragma: allowlist secret
_DEPLOY_YML = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "deploy.yml"


# ---------------------------------------------------------------------------
# El endpoint dice qué commit sirve
# ---------------------------------------------------------------------------


@pytest.fixture
def _sin_variables_de_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    for nombre in health._VARIABLES_DE_COMMIT:
        monkeypatch.delenv(nombre, raising=False)


@pytest.mark.usefixtures("_sin_variables_de_commit")
def test_el_commit_sale_de_render_git_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_GIT_COMMIT", f" {_SHA}\n")
    assert health._commit_desplegado() == _SHA


@pytest.mark.usefixtures("_sin_variables_de_commit")
def test_render_manda_sobre_git_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    """``RENDER_GIT_COMMIT`` lo pone Render en cada deploy; ``GIT_SHA`` puede quedar viejo."""
    monkeypatch.setenv("GIT_SHA", _SHA_ANTERIOR)
    monkeypatch.setenv("RENDER_GIT_COMMIT", _SHA)
    assert health._commit_desplegado() == _SHA


@pytest.mark.usefixtures("_sin_variables_de_commit")
def test_sin_variables_el_commit_es_unknown() -> None:
    assert health._commit_desplegado() == "unknown"


@pytest.mark.usefixtures("_sin_variables_de_commit")
def test_readiness_publica_el_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_GIT_COMMIT", _SHA)
    monkeypatch.setattr(health, "_check_db", lambda: "ok")
    monkeypatch.setattr(health, "_check_redis", lambda: "unconfigured")
    monkeypatch.setattr(health, "_check_disk", lambda: "ok")
    monkeypatch.setattr(health, "_check_schema", lambda: "unconfigured")

    respuesta = asyncio.run(health.readiness())

    assert respuesta.status_code == 200
    assert json.loads(respuesta.body)["commit"] == _SHA


def test_el_payload_declara_el_campo_commit() -> None:
    """En el modelo, para que el contrato OpenAPI y el cliente tipado lo vean."""
    assert "commit" in health.HealthResponse.model_fields
    modelo = health.HealthResponse(
        status="ok", db="ok", redis="ok", disk="ok", timestamp="2026-10-17T00:00:00+00:00"
    )
    assert modelo.commit == "unknown"


# ---------------------------------------------------------------------------
# La espera no acepta un 200 de otra versión
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("servido", "esperado", "igual"),
    [
        (_SHA, _SHA, True),
        (_SHA.upper(), _SHA, True),
        (_SHA, _SHA[:12], True),
        (_SHA[:7], _SHA, True),
        (_SHA[:6], _SHA, False),
        (_SHA_ANTERIOR, _SHA, False),
        ("unknown", _SHA, False),
        ("", _SHA, False),
    ],
)
def test_mismo_commit(servido: str, esperado: str, igual: bool) -> None:
    assert esperar_deploy.mismo_commit(servido, esperado) is igual


@pytest.mark.parametrize(
    ("estado", "payload", "fragmento"),
    [
        (503, {"commit": _SHA}, "HTTP 503"),
        (200, {"status": "ok"}, "anterior a este gate"),
        (200, None, "anterior a este gate"),
        (200, {"commit": "unknown"}, "RENDER_GIT_COMMIT"),
        (200, {"commit": _SHA_ANTERIOR}, f"sirve {_SHA_ANTERIOR[:12]}"),
    ],
)
def test_evaluar_explica_por_que_no_es_la_version_nueva(
    estado: int, payload: Any, fragmento: str
) -> None:
    motivo = esperar_deploy.evaluar(estado, payload, _SHA)
    assert motivo is not None
    assert fragmento in motivo


def test_evaluar_acepta_el_commit_esperado_con_200() -> None:
    assert esperar_deploy.evaluar(200, {"commit": _SHA, "status": "ok"}, _SHA) is None


def test_espera_mientras_responde_la_instancia_vieja() -> None:
    """El caso del 2026-10-15: la vieja da 200 y la nueva llega después."""
    respuestas: list[tuple[int, Any]] = [
        (200, {"status": "ok"}),  # versión anterior a este gate, sin campo
        (200, {"commit": _SHA_ANTERIOR}),
        (200, {"commit": _SHA, "schema_revision": "ok (v149)"}),
    ]
    pausas: list[float] = []

    payload, motivo = esperar_deploy.esperar(
        "https://api.example.com",
        _SHA,
        intentos=5,
        pausa=15,
        leer_fn=lambda _base: respuestas.pop(0),
        dormir=pausas.append,
    )

    assert motivo is None
    assert payload == {"commit": _SHA, "schema_revision": "ok (v149)"}
    assert pausas == [15, 15]


def test_vence_con_el_motivo_del_ultimo_intento() -> None:
    pausas: list[float] = []

    payload, motivo = esperar_deploy.esperar(
        "https://api.example.com",
        _SHA,
        intentos=3,
        pausa=15,
        leer_fn=lambda _base: (200, {"commit": _SHA_ANTERIOR}),
        dormir=pausas.append,
    )

    assert payload is None
    assert motivo == f"sirve {_SHA_ANTERIOR[:12]}, no {_SHA[:12]}"
    assert len(pausas) == 2  # no se duerme después del último intento


def test_commit_unknown_corta_la_espera_al_primer_intento() -> None:
    """Sin RENDER_GIT_COMMIT no hay nada que esperar: reintentar no lo arregla."""
    pausas: list[float] = []

    payload, motivo = esperar_deploy.esperar(
        "https://api.example.com",
        _SHA,
        intentos=60,
        pausa=15,
        leer_fn=lambda _base: (200, {"commit": "unknown"}),
        dormir=pausas.append,
    )

    assert payload is None
    assert motivo == esperar_deploy.MOTIVO_SIN_COMMIT
    assert pausas == []


def test_main_explica_el_commit_unknown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SMOKE_BASE_URL", "https://api.example.com")
    monkeypatch.setattr(esperar_deploy, "leer", lambda _base: (200, {"commit": "unknown"}))

    assert esperar_deploy.main(["--commit", _SHA, "--pausa", "0"]) == 1
    assert "::error title=La API no dice qué commit sirve::" in capsys.readouterr().out


def test_un_fallo_de_red_se_reintenta() -> None:
    def _leer(_base: str) -> tuple[int, Any]:
        if not llamadas:
            llamadas.append(1)
            raise TimeoutError("timed out")
        return 200, {"commit": _SHA}

    llamadas: list[int] = []

    payload, motivo = esperar_deploy.esperar(
        "https://api.example.com", _SHA, intentos=2, pausa=0, leer_fn=_leer, dormir=lambda _s: None
    )

    assert motivo is None
    assert payload == {"commit": _SHA}


def test_main_deja_el_payload_verificado(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SMOKE_BASE_URL", "https://api.example.com")
    monkeypatch.setattr(
        esperar_deploy, "leer", lambda _base: (200, {"commit": _SHA, "schema_revision": "ok"})
    )
    salida = tmp_path / "ready.json"

    codigo = esperar_deploy.main(["--commit", _SHA, "--salida", str(salida), "--pausa", "0"])

    assert codigo == 0
    assert json.loads(salida.read_text(encoding="utf-8"))["schema_revision"] == "ok"


def test_main_falla_si_nunca_responde_el_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SMOKE_BASE_URL", "https://api.example.com")
    monkeypatch.setattr(esperar_deploy, "leer", lambda _base: (200, {"commit": _SHA_ANTERIOR}))
    salida = tmp_path / "ready.json"

    codigo = esperar_deploy.main(
        ["--commit", _SHA, "--salida", str(salida), "--intentos", "2", "--pausa", "0"]
    )

    assert codigo == 1
    assert not salida.exists()
    assert "::error title=La versión nueva no llegó a responder::" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("base", "commit"),
    [
        ("", _SHA),
        ("http://api.example.com", _SHA),  # http contra un host remoto
        ("https://api.example.com", "e888"),  # SHA demasiado corto
    ],
)
def test_main_rechaza_la_configuracion_invalida_sin_sondear(
    monkeypatch: pytest.MonkeyPatch, base: str, commit: str
) -> None:
    monkeypatch.setenv("SMOKE_BASE_URL", base)

    def _no_debe_sondear(_base: str) -> tuple[int, Any]:
        raise AssertionError("no tenía que llegar a sondear")

    monkeypatch.setattr(esperar_deploy, "leer", _no_debe_sondear)

    assert esperar_deploy.main(["--commit", commit, "--pausa", "0"]) == 2


# ---------------------------------------------------------------------------
# El workflow usa la espera y el payload verificado
# ---------------------------------------------------------------------------


def test_deploy_yml_espera_a_github_sha_y_el_schema_lee_lo_verificado() -> None:
    texto = _DEPLOY_YML.read_text(encoding="utf-8")

    assert "COMMIT_SHA: ${{ github.sha }}" in texto
    assert (
        'python scripts/esperar_deploy.py --commit "$COMMIT_SHA" '
        '--salida "$RUNNER_TEMP/health-ready.json"'
    ) in texto
    # El gate de schema no vuelve a preguntar: la respuesta nueva podría venir
    # de otra instancia.
    assert 'cat "$RUNNER_TEMP/health-ready.json"' in texto
    assert 'curl -sS --max-time 30 "$SMOKE_BASE_URL/api/v1/health/ready"' not in texto
