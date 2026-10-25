"""Tests del pin out-of-band ML_MODEL_SHA256 en SAPClassifier.load/ensure_downloaded."""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest

from config import settings
from services.ml.sap_classifier import SAPClassifier


def _save_untrained(tmp_path):
    clf = SAPClassifier()
    model_path = tmp_path / "m.pkl"
    clf.save(model_path)  # escribe .pkl + .sha256 co-ubicado
    return model_path


def test_load_rejects_when_pin_mismatch(tmp_path, monkeypatch) -> None:
    model_path = _save_untrained(tmp_path)
    monkeypatch.setattr(settings, "ML_MODEL_SHA256", "de" * 32)  # 64 hex, no coincide
    with pytest.raises(RuntimeError, match="ML_MODEL_SHA256"):
        SAPClassifier.load(model_path)


def test_load_accepts_when_pin_matches(tmp_path, monkeypatch) -> None:
    model_path = _save_untrained(tmp_path)
    correct = hashlib.sha256(model_path.read_bytes()).hexdigest()
    monkeypatch.setattr(settings, "ML_MODEL_SHA256", correct)
    loaded = SAPClassifier.load(model_path)
    assert loaded is not None


def test_load_pin_is_case_insensitive(tmp_path, monkeypatch) -> None:
    model_path = _save_untrained(tmp_path)
    correct = hashlib.sha256(model_path.read_bytes()).hexdigest().upper()
    monkeypatch.setattr(settings, "ML_MODEL_SHA256", correct)
    assert SAPClassifier.load(model_path) is not None


def test_load_no_pin_uses_colocated_checksum(tmp_path, monkeypatch) -> None:
    model_path = _save_untrained(tmp_path)
    monkeypatch.setattr(settings, "ML_MODEL_SHA256", "")
    assert SAPClassifier.load(model_path) is not None


def test_load_pin_detects_tampered_model(tmp_path, monkeypatch) -> None:
    # Pin del modelo original; luego se manipula el .pkl y su .sha256 co-ubicado
    # (simula un release comprometido). El pin out-of-band debe detectarlo.
    model_path = _save_untrained(tmp_path)
    original_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    monkeypatch.setattr(settings, "ML_MODEL_SHA256", original_hash)

    # Manipular el modelo y regenerar el checksum co-ubicado (atacante).
    model_path.write_bytes(b"contenido manipulado")
    tampered_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    model_path.with_suffix(".sha256").write_text(tampered_hash, encoding="utf-8")

    with pytest.raises(RuntimeError, match="ML_MODEL_SHA256"):
        SAPClassifier.load(model_path)


def test_load_prod_without_pin_or_checksum_raises(tmp_path, monkeypatch) -> None:
    """En ENV=prod, sin pin ni checksum co-ubicado, load() debe fallar duro."""
    model_path = _save_untrained(tmp_path)
    model_path.with_suffix(".sha256").unlink()  # simula ausencia de checksum
    monkeypatch.setattr(settings, "ML_MODEL_SHA256", "")
    monkeypatch.setattr(settings, "ENV", "prod")
    with pytest.raises(RuntimeError, match="Sin verificación de integridad"):
        SAPClassifier.load(model_path)


def test_load_prod_with_colocated_checksum_is_allowed(tmp_path, monkeypatch) -> None:
    """En ENV=prod, un checksum co-ubicado válido basta (sin pin)."""
    model_path = _save_untrained(tmp_path)
    monkeypatch.setattr(settings, "ML_MODEL_SHA256", "")
    monkeypatch.setattr(settings, "ENV", "prod")
    assert SAPClassifier.load(model_path) is not None


def test_ensure_downloaded_rejects_non_github_repository(tmp_path) -> None:
    """El repositorio no puede inyectar rutas ni consultas en la GitHub API.

    La validación se mudó a ``shared.release_assets`` con el transporte; el
    contrato observable desde aquí no cambia.
    """
    with patch("shared.release_assets.pinned_https_request") as request:
        downloaded = SAPClassifier.ensure_downloaded(
            path=tmp_path / "model.pkl",
            repo="Dkalds/TenderFlow?redirect=https://internal.example",
        )

    assert downloaded is False
    request.assert_not_called()


def test_ensure_downloaded_baja_tambien_el_checksum_co_ubicado(tmp_path) -> None:
    """Sin el ``.sha256``, ``load()`` con ENV=prod rechaza el artefacto.

    Bajar solo el ``.pkl`` cambiaba ``no_model`` por ``load_failed``: el paso
    seguía sin puntuar nada, solo que por otro motivo.
    """
    from shared.release_assets import AssetLocalizado

    destino = tmp_path / "sap_classifier.pkl"
    release = {"id": 2, "tag_name": "v1.0.0-models", "assets": []}
    with (
        patch(
            "shared.release_assets.locate_release_asset",
            return_value=AssetLocalizado(release, 7),
        ),
        patch("shared.release_assets.download_asset", return_value=True) as descarga,
        patch("shared.release_assets.download_checksum_sidecar", return_value=True) as sidecar,
    ):
        assert SAPClassifier.ensure_downloaded(path=destino) is True

    assert descarga.call_args.args[2] == destino
    assert sidecar.call_args.args[2] == destino
    # El sidecar, de la MISMA Release que el `.pkl`.
    assert sidecar.call_args.args[1] is release


def test_ensure_downloaded_busca_el_nombre_fijo_como_el_resolvedor(tmp_path) -> None:
    """Release fija, *latest* y recientes, por el nombre fijo.

    Solo miraba *latest*: una Release de software marcada como *latest* dejaba
    fuera de alcance el ``sap_classifier.pkl`` de mayo (``v1.0.0-models``), que
    es lo que se sirve sin versión activa. Y busca el nombre FIJO: los de
    nombre por contenido son de versiones registradas, que resuelve
    ``resolve_active_artifact`` cotejando su sha256.
    """
    with patch("shared.release_assets.locate_release_asset", return_value=None) as localizar:
        assert SAPClassifier.ensure_downloaded(path=tmp_path / "sap_classifier.pkl") is False

    args, kwargs = localizar.call_args
    assert args == ("Dkalds/TenderFlow", "sap_classifier.pkl")
    assert kwargs["tag_fijo"] == "ml-models"


def test_ensure_downloaded_encuentra_el_asset_fuera_de_latest(tmp_path) -> None:
    """*latest* es una Release de software sin modelos; el asset está en otra."""
    from shared.release_assets import ML_MODELS_RELEASE_TAG

    api = "https://api.github.com/repos/Dkalds/TenderFlow/releases"
    fija = {"id": 1, "tag_name": ML_MODELS_RELEASE_TAG, "assets": []}
    software = {"id": 3, "tag_name": "v2.0.0", "assets": []}
    modelos = {
        "id": 2,
        "tag_name": "v1.0.0-models",
        "assets": [{"name": "sap_classifier.pkl", "id": 21, "digest": None}],
    }
    respuestas = {
        f"{api}/tags/{ML_MODELS_RELEASE_TAG}": fija,
        f"{api}/latest": software,
        f"{api}?per_page=30": [software, fija, modelos],
    }

    def _api(url: str, _repo: str, *, token: str) -> object | None:
        return respuestas.get(url)

    destino = tmp_path / "sap_classifier.pkl"
    with (
        patch("shared.release_assets._get_api_json", side_effect=_api),
        patch("shared.release_assets.download_asset", return_value=True) as descarga,
        patch("shared.release_assets.download_checksum_sidecar", return_value=True),
    ):
        assert SAPClassifier.ensure_downloaded(path=destino) is True

    assert descarga.call_args.args[1] == 21


# ── Tercer canal: la Release por nombre, sin pasar por el registro ──────────
#
# `resolve_servable_artifact` (#264) mira `model_versions` y, si no hay versión
# activa, cae al fichero local. En un runner efímero ninguno de los dos existe:
# `model_versions` no tiene fila de `sap_classifier` y `data/models/` está en
# `.gitignore`. Sin un tercer canal el paso seguiría en `no_model` con el
# artefacto publicado en la Release desde el 2026-05-22.


def test_resolve_artifact_prefiere_el_registro_y_no_descarga(tmp_path) -> None:
    with (
        patch(
            "services.ml.model_artifacts.resolve_servable_artifact",
            return_value=tmp_path / "del_registro.pkl",
        ),
        patch.object(SAPClassifier, "ensure_downloaded") as descarga,
    ):
        assert SAPClassifier.resolve_artifact() == tmp_path / "del_registro.pkl"

    descarga.assert_not_called()


def test_resolve_artifact_cae_a_la_release_cuando_no_hay_ni_registro_ni_local() -> None:
    """El caso de producción: sin fila en `model_versions` y sin fichero local."""
    with (
        patch("services.ml.model_artifacts.resolve_servable_artifact", return_value=None),
        patch.object(SAPClassifier, "ensure_downloaded", return_value=True) as descarga,
    ):
        resuelto = SAPClassifier.resolve_artifact()

    descarga.assert_called_once()
    assert resuelto is not None
    assert resuelto.name == "sap_classifier.pkl"


def test_resolve_artifact_devuelve_none_si_la_release_tampoco_lo_tiene() -> None:
    with (
        patch("services.ml.model_artifacts.resolve_servable_artifact", return_value=None),
        patch.object(SAPClassifier, "ensure_downloaded", return_value=False),
    ):
        assert SAPClassifier.resolve_artifact() is None


def test_tech_resolve_artifact_tambien_cae_a_la_release() -> None:
    """Gemelo del SAP: hoy no encuentra nada porque `train-tech.yml` aún no publica."""
    from services.ml.tech_classifier import TechnologyClassifier

    with (
        patch("services.ml.model_artifacts.resolve_servable_artifact", return_value=None),
        patch.object(TechnologyClassifier, "ensure_downloaded", return_value=True) as descarga,
    ):
        resuelto = TechnologyClassifier.resolve_artifact()

    descarga.assert_called_once()
    assert resuelto is not None
    assert resuelto.name == "tech_classifier.pkl"
