"""Artefactos de modelo con el sha256 en el nombre (2026-09).

Toda versión de ``baja_model``/``retencion_model`` se guardaba como
``data/models/baja_model.pkl`` y ``train-predictivos.yml`` la subía a la
Release con ``--clobber``. Con vN activa, el reentrenamiento mensual registra
vN+1 SIN activarla y pisaba su asset: ``ml-scoring`` bajaba vN+1 para la fila
vN, el sha256 no cuadraba y ``ModelArtifactMismatch`` tumbaba el scoring cada
día hasta que alguien activara la nueva.

Estos tests fijan el contrato que lo cierra: ``entrenar`` publica
``<stem>-<sha256[:12]>.pkl`` con su ``.sha256`` al lado, registra esa ruta en
``model_versions`` y el CLI del workflow sube exactamente esos dos ficheros.
Sin BD: el registro se sustituye por un doble que captura lo que se
registraría.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shared.model_artifacts import rename_to_content_address
from shared.model_integrity import verify_model_integrity


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _guardado(path: Path, contenido: bytes) -> Path:
    """Lo que deja ``save()``: el ``.pkl`` y su ``.sha256`` con el nombre base."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contenido)
    path.with_suffix(".sha256").write_text(_sha(contenido), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# rename_to_content_address
# ---------------------------------------------------------------------------


def test_el_nombre_lleva_el_prefijo_del_sha256(tmp_path):
    ruta, sha256 = rename_to_content_address(_guardado(tmp_path / "baja_model.pkl", b"modelo"))

    assert sha256 == _sha(b"modelo")
    assert ruta == tmp_path / f"baja_model-{sha256[:12]}.pkl"
    assert ruta.read_bytes() == b"modelo"


def test_el_sidecar_viaja_con_el_nombre_nuevo(tmp_path):
    """``verify_model_integrity`` busca el ``.sha256`` junto al ``.pkl``; el del
    nombre base describiría un fichero que ya no existe."""
    base = _guardado(tmp_path / "baja_model.pkl", b"modelo")

    ruta, sha256 = rename_to_content_address(base)

    assert ruta.with_suffix(".sha256").read_text(encoding="utf-8") == sha256
    assert not base.exists()
    assert not base.with_suffix(".sha256").exists()
    # El invariante de verdad: lo publicado se puede cargar en ENV=prod.
    verify_model_integrity(
        ruta,
        pinned_sha256="",
        pin_setting_name="ML_BAJA_MODEL_SHA256",
        model_label="baja_model",
        env="prod",
    )


def test_publicar_la_version_nueva_no_pisa_la_activa(tmp_path):
    """El incidente: vN+1 sobrescribía el artefacto de vN. Ahora conviven."""
    activa, _ = rename_to_content_address(_guardado(tmp_path / "baja_model.pkl", b"modelo-vN"))
    nueva, _ = rename_to_content_address(_guardado(tmp_path / "baja_model.pkl", b"modelo-vN+1"))

    assert activa != nueva
    assert activa.read_bytes() == b"modelo-vN"
    assert activa.with_suffix(".sha256").read_text(encoding="utf-8") == _sha(b"modelo-vN")
    assert nueva.read_bytes() == b"modelo-vN+1"


def test_mismo_contenido_mismo_nombre(tmp_path):
    """Por eso ``--clobber`` ya es inocuo: solo puede reescribir los mismos bytes."""
    primera, _ = rename_to_content_address(_guardado(tmp_path / "baja_model.pkl", b"igual"))
    segunda, _ = rename_to_content_address(_guardado(tmp_path / "baja_model.pkl", b"igual"))

    assert primera == segunda
    assert segunda.read_bytes() == b"igual"


def test_es_idempotente(tmp_path):
    """Un ``path`` que ya lleva su prefijo no acumula un segundo sufijo."""
    ruta, sha256 = rename_to_content_address(_guardado(tmp_path / "baja_model.pkl", b"modelo"))

    assert rename_to_content_address(ruta) == (ruta, sha256)
    assert ruta.exists()


# ---------------------------------------------------------------------------
# entrenar(): lo registrado es el nombre por contenido
# ---------------------------------------------------------------------------


@pytest.fixture
def registro(monkeypatch):
    """``register_version`` de mentira: captura lo que se registraría."""
    falso = MagicMock(return_value=7)
    monkeypatch.setattr("db.model_registry.register_version", falso)
    return falso


def _comprobar_publicado(resumen: dict[str, Any], registro: MagicMock, base: Path) -> Path:
    """La ruta del resumen, la registrada y la del disco son la misma, por contenido."""
    ruta = Path(resumen["path"])
    registrado = registro.call_args.kwargs
    assert registrado["path"] == str(ruta)
    assert registrado["sha256"] == _sha(ruta.read_bytes())
    assert ruta.name == f"{base.stem}-{registrado['sha256'][:12]}.pkl"
    assert ruta.with_suffix(".sha256").read_text(encoding="utf-8") == registrado["sha256"]
    # Nada queda con el nombre base: es el que compartían todas las versiones.
    assert not base.exists()
    assert not base.with_suffix(".sha256").exists()
    return ruta


def _filas_baja() -> list[Any]:
    """Tres años de filas ordenadas por fecha: da para los folds por defecto."""
    from services.ml.features import CATEGORICAL_COLUMNS, FilaDataset

    inicio = date(2022, 1, 1)
    return [
        FilaDataset(
            licitacion_id=f"L-{i}",
            fecha=(inicio + timedelta(days=3 * i)).isoformat(),
            features={
                **{col: f"{col}-{i % 3}" for col in CATEGORICAL_COLUMNS},
                "log_importe": 10.0 + i % 7,
            },
            baja=0.05 + 0.01 * (i % 20),
        )
        for i in range(360)
    ]


def test_entrenar_baja_registra_el_nombre_por_contenido(tmp_path, monkeypatch, registro):
    from sklearn.dummy import DummyRegressor

    import services.ml.baja_model as baja_model
    from config import settings

    def _ajuste_rapido(q, X, y, _pesos, _cat_mask, _hiper):
        # Lo que se prueba es el artefacto, no la calidad del ajuste: un
        # DummyRegressor se serializa igual y cuesta milisegundos.
        return DummyRegressor(strategy="quantile", quantile=q).fit(X, y)

    monkeypatch.setattr(baja_model, "MIN_TRAIN_SAMPLES", 40)
    monkeypatch.setattr(baja_model, "construir_dataset_baja", lambda **_kw: (_filas_baja(), None))
    monkeypatch.setattr(baja_model, "_fechas_adjudicacion", lambda *_a, **_kw: {})
    monkeypatch.setattr(baja_model, "_fit_quantil", _ajuste_rapido)
    monkeypatch.setattr(settings, "ML_BAJA_SEARCH_COMBOS", 0, raising=False)

    base = tmp_path / "baja_model.pkl"
    resumen = baja_model.entrenar(activar=False, model_path=base)

    assert resumen["status"] == "ok"
    ruta = _comprobar_publicado(resumen, registro, base)
    assert isinstance(baja_model.BajaModel.load(ruta), baja_model.BajaModel)


def _pares_retencion() -> list[Any]:
    from services.ml.retencion_labels import FEATURE_COLUMNS_RETENCION, ParRetencion

    inicio = date(2020, 1, 1)
    pares = []
    for i in range(200):
        retiene = int(i % 3 != 0)
        pares.append(
            ParRetencion(
                licitacion_id=f"P-{i}",
                sucesor_id=f"S-{i}",
                empresa_id=i % 7,
                organo="Organo",
                fecha_fin=(inicio + timedelta(days=5 * i)).isoformat(),
                # `entrenar` asume el orden por fecha de sucesor.
                fecha_sucesor=(inicio + timedelta(days=5 * i + 30)).isoformat(),
                label=retiene,
                features={
                    col: float((i + j) % 5) + retiene
                    for j, col in enumerate(FEATURE_COLUMNS_RETENCION)
                },
            )
        )
    return pares


def test_entrenar_retencion_registra_el_nombre_por_contenido(tmp_path, monkeypatch, registro):
    import services.ml.retencion_model as retencion_model

    monkeypatch.setattr("services.ml.retencion_labels.construir_pares", _pares_retencion)

    base = tmp_path / "retencion_model.pkl"
    resumen = retencion_model.entrenar(activar=False, model_path=base)

    assert resumen["status"] == "ok"
    ruta = _comprobar_publicado(resumen, registro, base)
    assert isinstance(retencion_model.RetencionModel.load(ruta), retencion_model.RetencionModel)


# ---------------------------------------------------------------------------
# El CLI del workflow sube lo registrado, sin cambios en el CLI
# ---------------------------------------------------------------------------


def test_el_cli_del_workflow_sube_el_pkl_y_su_sidecar_por_contenido(tmp_path, monkeypatch):
    """``run_retrain_cli`` deriva el sidecar con ``with_suffix(".sha256")``: con
    el hash en el stem sigue saliendo el ``.sha256`` que escribió ``entrenar``."""
    from scheduler.jobs import ml_predicciones

    ruta, sha256 = rename_to_content_address(_guardado(tmp_path / "baja_model.pkl", b"modelo"))
    salida = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(salida))
    resultados = {
        "baja": {"status": "ok", "version": 4, "path": str(ruta)},
        "retencion": {"status": "datos_insuficientes", "n": 3},
    }
    with (
        patch.object(ml_predicciones, "run_retrain", return_value=resultados),
        patch("db.database.init_db"),
    ):
        assert ml_predicciones.run_retrain_cli() == 0

    linea = salida.read_text(encoding="utf-8").strip()
    assert linea.startswith("artefactos=")
    nombres = [Path(p).name for p in linea.removeprefix("artefactos=").split()]
    assert nombres == [f"baja_model-{sha256[:12]}.pkl", f"baja_model-{sha256[:12]}.sha256"]
