"""Activación de un modelo predictivo desde ``operaciones-datos.yml`` (``activar-predictivo``).

Solo se activa lo que el scoring podría servir: versión promocionable,
artefacto resuelto con su sha256 y, en baja, el layout de features actual. Sin
``--aplicar`` no escribe nada.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import db.model_registry as registro
import scheduler.jobs.ml_predicciones as job
import services.ml.baja_model as baja_model_mod
import services.ml.model_artifacts as artefactos


def _version(version: int, *, promocionable: bool = True) -> dict[str, Any]:
    return {
        "version": version,
        "metrics": {
            "promocionable": promocionable,
            "promotion_reason": f"razón v{version}",
        },
        "notes": "",
    }


@pytest.fixture()
def entorno(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    pkl = tmp_path / "baja_model-abc123.pkl"
    estado: dict[str, Any] = {
        "versiones": [_version(6), _version(5, promocionable=False)],
        "activada": None,
        "artefacto": pkl,
        "modelo": MagicMock(),
    }
    monkeypatch.setattr(registro, "list_versions", lambda _n: estado["versiones"])
    monkeypatch.setattr(registro, "get_active", lambda _n: {"version": 4})

    def activar(nombre: str, version: int) -> bool:
        estado["activada"] = (nombre, version)
        return True

    monkeypatch.setattr(registro, "activate_version", activar)
    monkeypatch.setattr(artefactos, "resolve_version_artifact", lambda _n, _v: estado["artefacto"])
    monkeypatch.setattr(
        baja_model_mod.BajaModel, "load", classmethod(lambda _cls, *_a, **_k: estado["modelo"])
    )
    return estado


def test_sin_aplicar_comprueba_y_no_activa(entorno: dict[str, Any]) -> None:
    r = job.activar_predictivo("baja_model", 6, aplicar=False)
    assert r["activada"] is False and r["version_anterior"] == 4
    assert r["artefacto"] == "baja_model-abc123.pkl"
    assert entorno["activada"] is None
    entorno["modelo"].verificar_features.assert_called_once_with()


def test_con_aplicar_activa_la_version(entorno: dict[str, Any]) -> None:
    assert job.activar_predictivo("baja_model", 6, aplicar=True)["activada"] is True
    assert entorno["activada"] == ("baja_model", 6)


def test_rechaza_una_version_que_no_paso_el_gate(entorno: dict[str, Any]) -> None:
    with pytest.raises(job.ActivacionRechazada, match="no pasó el gate: razón v5"):
        job.activar_predictivo("baja_model", 5, aplicar=True)
    assert entorno["activada"] is None


def test_rechaza_un_artefacto_irresoluble(entorno: dict[str, Any]) -> None:
    entorno["artefacto"] = None
    with pytest.raises(job.ActivacionRechazada, match="no se puede resolver"):
        job.activar_predictivo("baja_model", 6, aplicar=True)
    assert entorno["activada"] is None


def test_rechaza_un_layout_de_features_distinto(entorno: dict[str, Any]) -> None:
    entorno["modelo"].verificar_features.side_effect = baja_model_mod.FeatureSchemaMismatch("x")
    with pytest.raises(job.ActivacionRechazada):
        job.activar_predictivo("baja_model", 6, aplicar=True)
    assert entorno["activada"] is None


@pytest.mark.parametrize(("nombre", "version"), [("sap_classifier", 6), ("baja_model", 99)])
def test_rechaza_modelos_y_versiones_que_no_existen(
    entorno: dict[str, Any], nombre: str, version: int
) -> None:
    with pytest.raises(job.ActivacionRechazada):
        job.activar_predictivo(nombre, version, aplicar=True)


def test_el_cli_devuelve_1_y_lo_resume_al_rechazar(
    entorno: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resumen = tmp_path / "resumen.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(resumen))
    assert job.activar_cli(["baja_model:5", "--aplicar"]) == 1
    assert "Versión NO activada" in resumen.read_text(encoding="utf-8")


def test_el_cli_exige_modelo_y_version(entorno: dict[str, Any]) -> None:
    assert job.activar_cli(["baja_model"]) == 2
