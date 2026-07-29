"""Tests del pin out-of-band ML_MODEL_SHA256 en SAPClassifier.load/ensure_downloaded."""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest

from config import settings
from scraper.ml_classifier import SAPClassifier


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
    """El repositorio no puede inyectar rutas ni consultas en la GitHub API."""
    with patch("scraper.ml_classifier.pinned_https_request") as request:
        downloaded = SAPClassifier.ensure_downloaded(
            path=tmp_path / "model.pkl",
            repo="Dkalds/TenderFlow?redirect=https://internal.example",
        )

    assert downloaded is False
    request.assert_not_called()
