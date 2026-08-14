"""Tests de shared/model_artifacts — resolución verificada por sha256.

Cierra el ítem del backlog «db/model_registry.py no verifica el sha256 del
modelo servido contra el registrado»: registrar una versión, mutar el fichero
en disco y confirmar que la discrepancia se detecta.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from shared.model_artifacts import ModelArtifactMismatch, resolve_active_artifact


def _register(name: str, path: Path, sha256: str) -> None:
    from db.model_registry import register_version

    register_version(name=name, path=str(path), sha256=sha256, activate=True)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_sin_version_activa_devuelve_none(tmp_db):
    assert resolve_active_artifact("modelo-inexistente") is None


def test_happy_path_artefacto_verificado(tmp_db, tmp_path):
    artefacto = tmp_path / "baja_model.pkl"
    artefacto.write_bytes(b"modelo-serializado")
    _register("baja", artefacto, _sha(b"modelo-serializado"))

    assert resolve_active_artifact("baja") == artefacto


def test_mutacion_del_artefacto_se_detecta(tmp_db, tmp_path):
    """Registrar → mutar el fichero → la resolución falla con mismatch."""
    artefacto = tmp_path / "baja_model.pkl"
    artefacto.write_bytes(b"modelo-original")
    _register("baja", artefacto, _sha(b"modelo-original"))

    artefacto.write_bytes(b"modelo-sustituido")

    with pytest.raises(ModelArtifactMismatch):
        resolve_active_artifact("baja")


def test_fichero_ausente_sin_sha_devuelve_none(tmp_db, tmp_path):
    artefacto = tmp_path / "no-existe.pkl"
    _register("baja", artefacto, "")

    assert resolve_active_artifact("baja") is None


def test_fichero_ausente_con_sha_intenta_descarga(tmp_db, tmp_path):
    """Runner efímero: sin fichero local se intenta el asset de la Release."""
    artefacto = tmp_path / "baja_model.pkl"
    contenido = b"modelo-desde-release"
    _register("baja", artefacto, _sha(contenido))

    def _fake_download(asset_name: str, dest: Path) -> bool:
        assert asset_name == "baja_model.pkl"
        dest.write_bytes(contenido)
        return True

    with patch("shared.model_artifacts._download_release_asset", side_effect=_fake_download):
        resolved = resolve_active_artifact("baja")

    assert resolved == artefacto
    assert artefacto.read_bytes() == contenido


def test_descarga_deja_el_checksum_colocado(tmp_db, tmp_path):
    """El asset de la Release llega solo, sin su ``.sha256``.

    ``shared.model_integrity.verify_model_integrity`` —el paso previo a
    ``joblib.load``— aborta en ENV=prod si no hay ni pin ni checksum
    co-ubicado, así que sin escribirlo aquí resolver el artefacto cambiaría el
    fallback a baseline por un RuntimeError a mitad del batch.
    """
    artefacto = tmp_path / "baja_model.pkl"
    contenido = b"modelo-desde-release"
    _register("baja", artefacto, _sha(contenido))

    def _fake_download(_asset_name: str, dest: Path) -> bool:
        dest.write_bytes(contenido)
        return True

    with patch("shared.model_artifacts._download_release_asset", side_effect=_fake_download):
        resolve_active_artifact("baja")

    sidecar = tmp_path / "baja_model.sha256"
    assert sidecar.read_text(encoding="utf-8").strip() == _sha(contenido)


def test_no_pisa_un_checksum_colocado_existente(tmp_db, tmp_path):
    """Si el sidecar ya existe se respeta: detectar una discrepancia entre él y
    el artefacto es justo el trabajo de verify_model_integrity."""
    artefacto = tmp_path / "baja_model.pkl"
    artefacto.write_bytes(b"modelo-serializado")
    sidecar = tmp_path / "baja_model.sha256"
    sidecar.write_text("un-hash-que-no-cuadra", encoding="utf-8")
    _register("baja", artefacto, _sha(b"modelo-serializado"))

    assert resolve_active_artifact("baja") == artefacto
    assert sidecar.read_text(encoding="utf-8") == "un-hash-que-no-cuadra"


def test_descarga_con_sha_incorrecto_falla(tmp_db, tmp_path):
    artefacto = tmp_path / "baja_model.pkl"
    _register("baja", artefacto, _sha(b"lo-esperado"))

    def _fake_download(asset_name: str, dest: Path) -> bool:
        dest.write_bytes(b"otra-cosa")
        return True

    with (
        patch("shared.model_artifacts._download_release_asset", side_effect=_fake_download),
        pytest.raises(ModelArtifactMismatch),
    ):
        resolve_active_artifact("baja")


def test_sap_active_learning_es_paso_canonico():
    from scheduler.pipeline_runs import CANONICAL_STEPS

    assert "sap_active_learning" in CANONICAL_STEPS


def test_sap_active_learning_invoca_maybe_retrain(tmp_db, monkeypatch):
    """El paso ejecuta maybe_retrain_classifier bajo la ventana periódica."""
    import scheduler.pipeline_runs as pr

    called: list[bool] = []

    def _fake_retrain(**_kw):
        called.append(True)
        return {"triggered": False, "feedbacks_new": 0}

    monkeypatch.setattr("scheduler.concept_drift.maybe_retrain_classifier", _fake_retrain)

    assert pr._run_sap_active_learning() == "ok"
    assert called == [True]
    # Segunda pasada dentro de la ventana semanal → skipped (lock retenido).
    assert pr._run_sap_active_learning() == "skipped"
    assert called == [True]
