"""Pin fuera de banda de los modelos ``.pkl`` y avisos cuando falta (deserializacion-ejecucion-1, cicd-2).

El ``.pkl`` y su ``.sha256`` salen de la misma Release: quien la controle
sustituye los dos. Solo ``ML_*_SHA256`` (en el entorno del proceso) lo impide. El
pin ya se exigía; lo que se fija aquí es que **gane** al checksum co-ubicado en
los dos cargadores y que su ausencia, con solo el checksum, deje un aviso.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config import settings
from services.ml import sap_classifier, tech_classifier
from shared import model_integrity
from shared.model_integrity import verify_model_integrity, write_checksum


@pytest.fixture
def modelo(tmp_path: Path) -> Path:
    """Un ``.pkl`` con su ``.sha256`` co-ubicado, como lo deja ``save()``."""
    destino = tmp_path / "modelo.pkl"
    destino.write_bytes(b"contenido del artefacto")
    write_checksum(destino)
    return destino


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _verificar(ruta: Path, *, pin: str, env: str) -> str:
    return verify_model_integrity(
        ruta, pinned_sha256=pin, pin_setting_name="ML_X_SHA256", model_label="x", env=env
    )


def _eventos_de_aviso(registro: MagicMock) -> list[str]:
    return [llamada.args[0] for llamada in registro.warning.call_args_list]


@pytest.mark.parametrize("env", ["prod", "staging"])
def test_solo_con_el_checksum_co_ubicado_avisa_en_prod_y_staging(
    modelo: Path, monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    registro = MagicMock()
    monkeypatch.setattr(model_integrity, "log", registro)
    assert _verificar(modelo, pin="", env=env) == _sha(modelo)  # carga igual: no es un fallo
    assert _eventos_de_aviso(registro) == ["model_integrity.sin_pin_fuera_de_banda"]
    assert registro.warning.call_args.kwargs["pin"] == "ML_X_SHA256"


def test_en_dev_o_con_pin_no_avisa(modelo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registro = MagicMock()
    monkeypatch.setattr(model_integrity, "log", registro)
    _verificar(modelo, pin="", env="dev")
    _verificar(modelo, pin=_sha(modelo), env="prod")
    assert _eventos_de_aviso(registro) == []


def test_el_pin_gana_aunque_el_checksum_co_ubicado_cuadre(modelo: Path) -> None:
    """Release comprometida: el atacante sustituye el ``.pkl`` y regenera su ``.sha256``."""
    pin = _sha(modelo)
    modelo.write_bytes(b"codigo del atacante")
    write_checksum(modelo)  # el .sha256 ahora cuadra con el .pkl falso
    with pytest.raises(RuntimeError, match="ML_X_SHA256"):
        _verificar(modelo, pin=pin, env="prod")


def test_tech_classifier_honra_ml_tech_model_sha256(
    modelo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", "prod")
    monkeypatch.setattr(settings, "ML_TECH_MODEL_SHA256", "de" * 32)
    with pytest.raises(RuntimeError, match="ML_TECH_MODEL_SHA256"):
        tech_classifier.TechnologyClassifier.load(modelo)


# ── ensure_downloaded: el pin se comprueba al bajar, el aviso si falta ─────


def _descarga_que_escribe(contenido: bytes):
    def _descargar(*args: object, **_: object) -> bool:
        destino = args[2]
        assert isinstance(destino, Path)
        destino.write_bytes(contenido)
        return True

    return _descargar


def _bajar_tech(destino: Path, *, sidecar: bool) -> bool:
    release = {"id": 1, "tag_name": "v1", "assets": []}
    with (
        patch("shared.release_assets.fetch_latest_release", return_value=release),
        patch("shared.release_assets.find_asset_id", return_value=7),
        patch(
            "shared.release_assets.download_asset",
            side_effect=_descarga_que_escribe(b"pkl descargado"),
        ),
        patch("shared.release_assets.download_checksum_sidecar", return_value=sidecar),
    ):
        return tech_classifier.TechnologyClassifier.ensure_downloaded(path=destino)


def _bajar_sap(destino: Path, *, sidecar: bool) -> bool:
    from shared.release_assets import AssetLocalizado

    release = {"id": 1, "tag_name": "v1", "assets": []}
    with (
        patch(
            "shared.release_assets.locate_release_asset",
            return_value=AssetLocalizado(release, 7),
        ),
        patch(
            "shared.release_assets.download_asset",
            side_effect=_descarga_que_escribe(b"pkl descargado"),
        ),
        patch("shared.release_assets.download_checksum_sidecar", return_value=sidecar),
    ):
        return sap_classifier.SAPClassifier.ensure_downloaded(path=destino)


_CARGADORES = [
    pytest.param(
        _bajar_tech, tech_classifier, "ML_TECH_MODEL_SHA256", "tech_classifier", id="tech"
    ),
    pytest.param(_bajar_sap, sap_classifier, "ML_MODEL_SHA256", "ml_classifier", id="sap"),
]


@pytest.mark.parametrize(("bajar", "modulo", "ajuste", "prefijo"), _CARGADORES)
def test_descarga_con_pin_que_no_coincide_se_borra_y_no_se_sirve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bajar, modulo, ajuste: str, prefijo: str
) -> None:
    monkeypatch.setattr(settings, ajuste, "de" * 32)
    destino = tmp_path / "descargado.pkl"
    assert bajar(destino, sidecar=True) is False
    assert not destino.exists()


@pytest.mark.parametrize(("bajar", "modulo", "ajuste", "prefijo"), _CARGADORES)
def test_descarga_con_pin_correcto_no_avisa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bajar, modulo, ajuste: str, prefijo: str
) -> None:
    registro = MagicMock()
    monkeypatch.setattr(modulo, "log", registro)
    monkeypatch.setattr(settings, ajuste, hashlib.sha256(b"pkl descargado").hexdigest())
    assert bajar(tmp_path / "descargado.pkl", sidecar=True) is True
    assert _eventos_de_aviso(registro) == []


@pytest.mark.parametrize(("bajar", "modulo", "ajuste", "prefijo"), _CARGADORES)
def test_descarga_sin_pin_y_con_sidecar_avisa_de_la_verificacion_circular(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bajar, modulo, ajuste: str, prefijo: str
) -> None:
    registro = MagicMock()
    monkeypatch.setattr(modulo, "log", registro)
    monkeypatch.setattr(settings, ajuste, "")
    assert bajar(tmp_path / "descargado.pkl", sidecar=True) is True
    assert _eventos_de_aviso(registro) == [f"{prefijo}.verificacion_circular"]


@pytest.mark.parametrize(("bajar", "modulo", "ajuste", "prefijo"), _CARGADORES)
def test_descarga_sin_pin_ni_sidecar_conserva_su_aviso(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bajar, modulo, ajuste: str, prefijo: str
) -> None:
    registro = MagicMock()
    monkeypatch.setattr(modulo, "log", registro)
    monkeypatch.setattr(settings, ajuste, "")
    assert bajar(tmp_path / "descargado.pkl", sidecar=False) is True
    assert _eventos_de_aviso(registro) == [f"{prefijo}.sin_verificacion_de_integridad"]
