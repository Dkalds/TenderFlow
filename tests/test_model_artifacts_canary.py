"""Tests del canary de artefactos de modelo (scheduler/jobs/model_artifacts_canary).

El incidente que cubre: el 2026-09-29 el paso semanal ``sap_active_learning``
reentrenó dentro de un runner de ``scrape-daily`` y dejó **activa** en
``model_versions`` una versión cuyo ``.pkl`` solo existió en el disco de ese
runner. Desde la pasada siguiente, ``ml_scoring`` bajaba el
``sap_classifier.pkl`` de la Release —el de mayo—, su sha256 no era el
registrado y ``ModelArtifactMismatch`` dejó ``scrape-daily`` en rojo catorce
runs seguidos.

El canary compara lo registrado con lo publicado sin descargar nada: la API de
Releases ya trae el sha256 de cada asset.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

_API = "https://api.github.com/repos/Dkalds/TenderFlow/releases"

# Los dos hashes del incidente, tal como salieron en el log del run 37147352339,
# el de la v1 que el gate rechazó y uno de relleno para un predictivo. Son
# sha256 de artefactos, no credenciales: el pragma es para detect-secrets, y
# cada literal vive aquí una sola vez para que no haga falta repetirlo.
_SHA_REGISTRADO = (
    "c45898eea9f30793907ddc5847c056cac30a4024384f8f56141f23ccff675279"  # pragma: allowlist secret
)
_SHA_PUBLICADO = (
    "5ddcc0eecd07b6985a8033e21c070fd7fbd255f7b2297d0c64dd77f26eab2252"  # pragma: allowlist secret
)
_SHA_V1 = (
    "00098b449a8d9ef979335c72edfbcd2090ce77675bbecb28bdf5d04674e5fcfa"  # pragma: allowlist secret
)
_SHA_BAJA = "0fdb397d651e" + "0" * 52  # pragma: allowlist secret


class _Respuesta:
    """Doble mínimo de ``PinnedHttpsResponse``."""

    def __init__(self, status_code: int = 200, body: bytes = b"") -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self._body = body

    def raise_for_status(self) -> None:
        if self.status_code >= 300:
            raise RuntimeError(f"Pinned HTTPS response status {self.status_code}")

    def iter_content(self, chunk_size: int = 8192) -> Any:
        yield self._body

    def __enter__(self) -> _Respuesta:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _GitHubFalso:
    """``pinned_https_request`` que responde por URL; lo no configurado es 404."""

    def __init__(self, rutas: dict[str, object]) -> None:
        self.rutas = rutas
        self.urls: list[str] = []

    def __call__(self, _method: str, url: str, **_kwargs: object) -> _Respuesta:
        self.urls.append(url)
        respuesta = self.rutas.get(url)
        if respuesta is None:
            return _Respuesta(status_code=404)
        return _Respuesta(body=json.dumps(respuesta).encode())


def _asset(nombre: str, asset_id: int, sha256: str | None) -> dict[str, object]:
    return {
        "name": nombre,
        "id": asset_id,
        "digest": f"sha256:{sha256}" if sha256 else None,
    }


def _releases_de_produccion(*, sap: str | None = _SHA_PUBLICADO) -> dict[str, object]:
    """Las dos Releases del repo el día del incidente.

    ``ml-models`` (tag fijo) con los predictivos por contenido, y
    ``v1.0.0-models`` (*latest*) con el ``sap_classifier.pkl`` de mayo.
    """
    fija = {
        "id": 1,
        "tag_name": "ml-models",
        "assets": [_asset("baja_model-0fdb397d651e.pkl", 11, _SHA_BAJA)],
    }
    latest = {
        "id": 2,
        "tag_name": "v1.0.0-models",
        "assets": [_asset("sap_classifier.pkl", 21, sap)],
    }
    return {
        f"{_API}/tags/ml-models": fija,
        f"{_API}/latest": latest,
        f"{_API}?per_page=30": [fija, latest],
    }


def _correr(activas: list[dict[str, Any]], github: Any) -> dict[str, Any]:
    from scheduler.jobs.model_artifacts_canary import run

    with (
        patch("db.model_registry.list_active", return_value=activas),
        patch("shared.release_assets.pinned_https_request", side_effect=github),
    ):
        return run()


def _fila(name: str, version: int, path: str, sha256: str) -> dict[str, Any]:
    return {"name": name, "version": version, "path": path, "sha256": sha256}


# ---------------------------------------------------------------------------
# El job
# ---------------------------------------------------------------------------


def test_el_incidente_del_29_de_septiembre_se_detecta() -> None:
    """Registro y Release divergen: es exactamente el hallazgo que se busca."""
    activa = _fila("sap_classifier", 2, "data/models/sap_classifier.pkl", _SHA_REGISTRADO)

    result = _correr([activa], _GitHubFalso(_releases_de_produccion()))

    assert result["checked"] == 1
    assert result["error"] is None
    assert result["sin_publicar"] == []
    assert result["divergentes"] == [
        {
            "name": "sap_classifier",
            "version": 2,
            "asset": "sap_classifier.pkl",
            "registrado": _SHA_REGISTRADO,
            "publicado": _SHA_PUBLICADO,
            "release": "v1.0.0-models",
        }
    ]


def test_registro_y_release_coinciden() -> None:
    activas = [
        _fila("sap_classifier", 3, "data/models/sap_classifier.pkl", _SHA_PUBLICADO),
        _fila(
            "baja_model",
            4,
            "/home/runner/work/TenderFlow/TenderFlow/data/models/baja_model-0fdb397d651e.pkl",
            _SHA_BAJA,
        ),
    ]

    result = _correr(activas, _GitHubFalso(_releases_de_produccion()))

    assert result == {"checked": 2, "divergentes": [], "sin_publicar": [], "error": None}


def test_una_version_activa_sin_asset_publicado_es_un_hallazgo() -> None:
    """El caso de activar una fila que registró el artefacto versionado.

    ``sap_classifier_v1.pkl`` no viaja a ninguna Release: quien resuelva esa
    versión cae al artefacto de nombre fijo, sin verificar, mientras el
    registro dice otra cosa.
    """
    activa = _fila(
        "sap_classifier",
        1,
        "/home/runner/work/TenderFlow/TenderFlow/data/models/sap_classifier_v1.pkl",
        _SHA_V1,
    )

    result = _correr([activa], _GitHubFalso(_releases_de_produccion()))

    assert result["divergentes"] == []
    assert [h["asset"] for h in result["sin_publicar"]] == ["sap_classifier_v1.pkl"]
    assert result["sin_publicar"][0]["publicado"] is None


def test_sin_versiones_activas_no_sale_a_la_red() -> None:
    """El caso normal de una BD recién creada: nada que comparar, nada que pedir."""

    def _prohibido(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("el canary salió a la red sin nada que comprobar")

    result = _correr([], _prohibido)

    assert result == {"checked": 0, "divergentes": [], "sin_publicar": [], "error": None}


def test_un_fallo_de_red_no_es_un_hallazgo() -> None:
    """Fail-open: sin Releases legibles no se puede afirmar que algo falte."""
    activa = _fila("sap_classifier", 2, "data/models/sap_classifier.pkl", _SHA_REGISTRADO)

    def _caido(*_args: object, **_kwargs: object) -> None:
        raise OSError("DNS caído")

    result = _correr([activa], _caido)

    assert result["divergentes"] == []
    assert result["sin_publicar"] == []
    assert result["error"]


def test_un_asset_sin_digest_no_se_da_por_divergente() -> None:
    """Sin hash publicado no hay nada que comparar; lo decide la descarga."""
    activa = _fila("sap_classifier", 2, "data/models/sap_classifier.pkl", _SHA_REGISTRADO)

    result = _correr([activa], _GitHubFalso(_releases_de_produccion(sap=None)))

    assert result["checked"] == 1
    assert result["divergentes"] == []
    assert result["sin_publicar"] == []


def test_una_fila_sin_sha256_no_se_compara() -> None:
    activa = _fila("sap_classifier", 2, "data/models/sap_classifier.pkl", "")

    result = _correr([activa], _GitHubFalso(_releases_de_produccion()))

    assert result["divergentes"] == []
    assert result["sin_publicar"] == []


def test_mira_la_misma_release_que_el_resolvedor() -> None:
    """Dos Releases publican el mismo nombre: cuenta la que bajaría un runner.

    ``resolve_active_artifact`` se queda con la primera en el orden tag fijo →
    *latest* → recientes. Si el canary mirase otra, daría por buena una versión
    que ningún proceso puede servir.
    """
    rutas = _releases_de_produccion()
    fija = rutas[f"{_API}/tags/ml-models"]
    assert isinstance(fija, dict)
    fija["assets"].append(_asset("sap_classifier.pkl", 12, _SHA_REGISTRADO))
    activa = _fila("sap_classifier", 2, "data/models/sap_classifier.pkl", _SHA_REGISTRADO)

    result = _correr([activa], _GitHubFalso(rutas))

    assert result["divergentes"] == []


# ---------------------------------------------------------------------------
# El paso canónico
# ---------------------------------------------------------------------------


def _sin_ventana(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ejecuta el paso sin ``db.job_locks``: la cadencia no es lo que se prueba."""
    import scheduler.pipeline_runs as pr

    def _directo(_name: str, _ttl: int, fn: Any) -> str:
        fn()
        return "ok"

    monkeypatch.setattr(pr, "_run_periodic", _directo)


def test_el_paso_lanza_con_los_dos_hashes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un hallazgo sale como fallo del paso: así llega el email, no solo el log."""
    import scheduler.pipeline_runs as pr

    _sin_ventana(monkeypatch)
    activa = _fila("sap_classifier", 2, "data/models/sap_classifier.pkl", _SHA_REGISTRADO)

    with (
        patch("db.model_registry.list_active", return_value=[activa]),
        patch(
            "shared.release_assets.pinned_https_request",
            side_effect=_GitHubFalso(_releases_de_produccion()),
        ),
        pytest.raises(RuntimeError) as exc,
    ):
        pr._run_model_artifacts_canary()

    mensaje = str(exc.value)
    assert "sap_classifier v2" in mensaje
    assert _SHA_REGISTRADO[:12] in mensaje
    assert _SHA_PUBLICADO[:12] in mensaje
    assert "v1.0.0-models" in mensaje


def test_el_paso_no_lanza_por_un_fallo_de_red(monkeypatch: pytest.MonkeyPatch) -> None:
    import scheduler.pipeline_runs as pr

    _sin_ventana(monkeypatch)
    activa = _fila("sap_classifier", 2, "data/models/sap_classifier.pkl", _SHA_REGISTRADO)

    def _caido(*_args: object, **_kwargs: object) -> None:
        raise OSError("DNS caído")

    with (
        patch("db.model_registry.list_active", return_value=[activa]),
        patch("shared.release_assets.pinned_https_request", side_effect=_caido),
    ):
        assert pr._run_model_artifacts_canary() == "ok"


def test_es_paso_canonico_y_advisory() -> None:
    """Avisa, no entrega nada: no puede poner la pasada en rojo por sí solo."""
    from scheduler.pipeline_runs import CANONICAL_STEPS, STEP_TIER

    assert "model_artifacts_canary" in CANONICAL_STEPS
    assert STEP_TIER["model_artifacts_canary"] == "advisory"
