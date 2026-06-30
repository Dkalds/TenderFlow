"""Tests del pin out-of-band ML_MODEL_SHA256 en SAPClassifier.load/ensure_downloaded."""

from __future__ import annotations

import hashlib

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
