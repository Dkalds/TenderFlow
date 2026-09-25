"""Monitor de drift del modelo de baja: con qué filas mide y a quién avisa.

Lo que fijan estos tests, sin base de datos:

- **con las filas del batch no reconstruye nada**: el job nocturno le pasa las
  abiertas que acaba de puntuar, y construirlas otra vez era ~1 min tirado;
- **solo alerta si lo servido es el modelo**: con el baseline mide y lo deja en
  el log, pero no manda correo. El run de ``ml-scoring.yml`` del 2026-09-24
  mandó un ERROR con los dos modelos sirviendo el baseline, como cada día;
- **la alerta va deduplicada** por monitor y severidad, así que una escalada
  cambia de clave;
- **sin régimen lo resuelve** con ``regimen_servido()``, y si no puede alerta
  como siempre (fail-open).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import observability.alerts as alerts_mod
import services.ml.drift as drift_mod
import services.ml.features as features_mod
from services.ml.features import CATEGORICAL_COLUMNS, FEATURE_COLUMNS, FilaDataset


def _fila(**numericas: float | None) -> FilaDataset:
    """Fila con el layout canónico: categóricas a ``"x"``, numéricas a 1.0."""
    features: dict[str, Any] = dict.fromkeys(FEATURE_COLUMNS, 1.0)
    features.update(dict.fromkeys(CATEGORICAL_COLUMNS, "x"))
    features.update(numericas)
    return FilaDataset(licitacion_id="L", fecha="2026-01-01", features=features)


def _sin_deriva() -> list[FilaDataset]:
    return [_fila() for _ in range(50)]


def _deriva_crit() -> list[FilaDataset]:
    """``log_importe`` presente al entrenar y ausente en todo el scoring."""
    return [_fila(log_importe=None) for _ in range(50)]


def _deriva_warn() -> list[FilaDataset]:
    """Ausente en el 30%: delta de nulos entre el umbral de aviso y el crítico."""
    return [_fila(log_importe=None if i < 15 else 1.0) for i in range(50)]


class _Canal:
    """``notify`` de mentira: apunta cada llamada y devuelve lo que se le diga."""

    def __init__(self, resultado: str = "enviada") -> None:
        self.resultado = resultado
        self.llamadas: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> str:
        self.llamadas.append((args, kwargs))
        return self.resultado


@pytest.fixture()
def canal(monkeypatch: pytest.MonkeyPatch) -> _Canal:
    doble = _Canal()
    monkeypatch.setattr(alerts_mod, "notify", doble)
    return doble


@pytest.fixture()
def construidas(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Qué construye el monitor por su cuenta, en orden."""
    llamadas: list[str] = []

    def construir_dataset_baja() -> tuple[list[FilaDataset], None]:
        llamadas.append("entrenamiento")
        return _sin_deriva(), None

    def features_licitaciones_abiertas() -> list[FilaDataset]:
        llamadas.append("abiertas")
        return _deriva_crit()

    monkeypatch.setattr(features_mod, "construir_dataset_baja", construir_dataset_baja)
    monkeypatch.setattr(
        features_mod, "features_licitaciones_abiertas", features_licitaciones_abiertas
    )
    return llamadas


# ---------------------------------------------------------------------------
# Con qué filas mide
# ---------------------------------------------------------------------------


def test_con_las_filas_del_batch_no_reconstruye_las_abiertas(canal, construidas):
    resultado = drift_mod.comprobar_drift_baja(scoring=_deriva_crit(), regimen="modelo")

    assert construidas == ["entrenamiento"]
    assert resultado["status"] == "crit"
    assert resultado["n_scoring"] == 50


def test_sin_filas_las_construye_como_siempre(canal, construidas):
    resultado = drift_mod.comprobar_drift_baja(regimen="modelo")

    assert construidas == ["abiertas", "entrenamiento"]
    assert resultado["status"] == "crit"


def test_sin_abiertas_ni_construye_el_dataset_de_entrenamiento(canal, construidas):
    resultado = drift_mod.comprobar_drift_baja(scoring=[], regimen="modelo")

    assert construidas == []
    assert resultado == {"status": "sin_datos", "regimen_servido": "modelo", "alerta": "no_aplica"}
    assert canal.llamadas == []


# ---------------------------------------------------------------------------
# A quién avisa
# ---------------------------------------------------------------------------


def test_con_el_baseline_servido_mide_pero_no_manda_correo(canal, construidas, monkeypatch):
    log = MagicMock()
    monkeypatch.setattr(drift_mod, "log", log)

    resultado = drift_mod.comprobar_drift_baja(scoring=_deriva_crit(), regimen="baseline")

    assert canal.llamadas == []
    # La medida es la misma que con el modelo: solo cambia a quién se le cuenta.
    assert resultado["status"] == "crit"
    assert resultado["missing_delta"]["log_importe"] == pytest.approx(1.0)
    assert resultado["regimen_servido"] == "baseline"
    assert resultado["alerta"] == "suprimida_regimen"
    assert log.info.call_args.args[0] == "ml_drift_detected_no_servido"
    assert log.info.call_args.kwargs["regimen_servido"] == "baseline"
    log.warning.assert_not_called()


def test_con_el_modelo_servido_alerta_con_clave_y_ventana(canal, construidas):
    resultado = drift_mod.comprobar_drift_baja(scoring=_deriva_crit(), regimen="modelo")

    [(args, kwargs)] = canal.llamadas
    assert args[0] == "error"
    assert kwargs["dedup_key"] == "ml_drift_baja:crit"
    assert kwargs["cooldown_s"] == alerts_mod.COOLDOWN_MONITOR_DIARIO_S
    assert resultado["regimen_servido"] == "modelo"
    assert resultado["alerta"] == "enviada"


def test_una_escalada_cambia_de_clave(canal, construidas):
    """warn y crit no comparten ventana: la escalada avisa al momento."""
    drift_mod.comprobar_drift_baja(scoring=_deriva_warn(), regimen="modelo")
    drift_mod.comprobar_drift_baja(scoring=_deriva_crit(), regimen="modelo")

    enviadas = [(args[0], kwargs["dedup_key"]) for args, kwargs in canal.llamadas]
    assert enviadas == [("warn", "ml_drift_baja:warn"), ("error", "ml_drift_baja:crit")]


def test_publica_lo_que_hizo_el_canal(monkeypatch, construidas):
    monkeypatch.setattr(alerts_mod, "notify", _Canal("suprimida_cooldown"))

    resultado = drift_mod.comprobar_drift_baja(scoring=_deriva_crit(), regimen="modelo")

    assert resultado["alerta"] == "suprimida_cooldown"


def test_sin_deriva_no_hay_nada_que_alertar(canal, construidas):
    resultado = drift_mod.comprobar_drift_baja(scoring=_sin_deriva(), regimen="modelo")

    assert resultado["status"] == "ok"
    assert resultado["alerta"] == "no_aplica"
    assert canal.llamadas == []


# ---------------------------------------------------------------------------
# Llamador que no sabe qué se sirve
# ---------------------------------------------------------------------------


class _RepoBaseline:
    def regimen_servido(self) -> str | None:
        return "baseline"


class _RepoQueRevienta:
    def regimen_servido(self) -> str | None:
        raise RuntimeError("db caída")


def test_sin_regimen_lo_resuelve_con_el_repositorio(canal, construidas, monkeypatch):
    import db.repositories.ml_dataset as ml_dataset

    monkeypatch.setattr(ml_dataset, "MlDatasetRepository", _RepoBaseline)

    resultado = drift_mod.comprobar_drift_baja(scoring=_deriva_crit())

    assert resultado["regimen_servido"] == "baseline"
    assert resultado["alerta"] == "suprimida_regimen"
    assert canal.llamadas == []


def test_si_no_puede_resolver_el_regimen_alerta_como_siempre(canal, construidas, monkeypatch):
    """Fail-open: callar el monitor por no saber qué se sirve perdería la alerta."""
    import db.repositories.ml_dataset as ml_dataset

    monkeypatch.setattr(ml_dataset, "MlDatasetRepository", _RepoQueRevienta)

    resultado = drift_mod.comprobar_drift_baja(scoring=_deriva_crit())

    assert resultado["regimen_servido"] is None
    assert resultado["alerta"] == "enviada"
    assert len(canal.llamadas) == 1
