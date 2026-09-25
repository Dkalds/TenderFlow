"""Modelo de baja por lote (backlog P2, v140) — sin base de datos.

Lo que fijan estos tests:

- **el default no se mueve**: el batch agregado escribe siempre la fila del
  expediente (``lote_numero`` NULL) aunque la fila de features traiga lote, y el
  batch por lote solo corre con ``ML_BAJA_POR_LOTE``;
- **el upsert usa los árbitros de v140**: dos únicos parciales, dos
  sentencias, cada una con el predicado de su índice;
- **el desglose es aditivo**: la respuesta del expediente solo gana ``lotes``
  si hay filas propias de lote, y nunca se rellena con la cifra agregada;
- **la comparación no se engaña**: el backtest solo recomienda sustituir si el
  delta pareado supera su propio ruido.

Los caminos con SQL real están en ``tests/test_ml_calibration_lote.py``
(Postgres).
"""

from __future__ import annotations

import asyncio
import random
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import services.ml.scoring as scoring
from services.ml.baja_model import Prediccion
from services.ml.features import CATEGORICAL_COLUMNS, FEATURE_COLUMNS, FilaDataset, _como_lote

# ---------------------------------------------------------------------------
# Batch de scoring
# ---------------------------------------------------------------------------


def _fila(lic: str, lote: str | None) -> FilaDataset:
    return FilaDataset(licitacion_id=lic, fecha="2026-09-01", features={}, lote_numero=lote)


class _RepoCaptura:
    def __init__(self) -> None:
        self.filas: list[tuple[Any, ...]] = []

    def guardar_baja(self, filas: list[tuple[Any, ...]]) -> int:
        self.filas.extend(filas)
        return len(filas)


def _correr_batch(monkeypatch: pytest.MonkeyPatch, *, por_lote: bool) -> _RepoCaptura:
    """Batch sin modelo activo (baseline), con features y repo de mentira."""
    llamadas: dict[str, Any] = {}

    def features(**kwargs: Any) -> list[FilaDataset]:
        llamadas["features"] = kwargs
        return (
            [_fila("E1", "1"), _fila("E1", "2")] if kwargs.get("por_lote") else [_fila("E1", None)]
        )

    repo = _RepoCaptura()
    monkeypatch.setattr(scoring, "features_licitaciones_abiertas", features)
    monkeypatch.setattr(scoring, "PrediccionesRepository", lambda: repo)
    monkeypatch.setattr(scoring, "_media_global_baja", lambda **kw: 0.2)
    monkeypatch.setattr(scoring, "_offset_baseline", lambda **kw: 0.0)
    monkeypatch.setattr("db.model_registry.get_active", lambda _nombre: None)
    resultado = (
        scoring.score_predicciones_baja_por_lote()
        if por_lote
        else scoring.score_predicciones_baja()
    )
    assert resultado["granularidad"] == ("lote" if por_lote else "expediente")
    assert llamadas["features"].get("por_lote", False) is por_lote
    return repo


def test_el_batch_agregado_escribe_solo_la_fila_del_expediente(monkeypatch):
    repo = _correr_batch(monkeypatch, por_lote=False)
    assert [(f[0], f[1]) for f in repo.filas] == [("E1", None)]


def test_el_batch_por_lote_escribe_una_fila_por_lote(monkeypatch):
    repo = _correr_batch(monkeypatch, por_lote=True)
    assert [(f[0], f[1]) for f in repo.filas] == [("E1", "1"), ("E1", "2")]
    # Sin modelo activo: baseline, `model_version` NULL.
    assert all(f[5] is None for f in repo.filas)


def test_el_batch_agregado_nunca_hereda_el_lote_de_la_fila(monkeypatch):
    """Una fila con lote en el camino agregado rompería la unicidad agregada."""
    repo = _RepoCaptura()
    monkeypatch.setattr(scoring, "features_licitaciones_abiertas", lambda **kw: [_fila("E1", "7")])
    monkeypatch.setattr(scoring, "PrediccionesRepository", lambda: repo)
    monkeypatch.setattr(scoring, "_media_global_baja", lambda **kw: 0.2)
    monkeypatch.setattr(scoring, "_offset_baseline", lambda **kw: 0.0)
    monkeypatch.setattr("db.model_registry.get_active", lambda _nombre: None)
    scoring.score_predicciones_baja()
    assert repo.filas[0][1] is None


def test_el_batch_por_lote_busca_su_propio_modelo(monkeypatch):
    pedidos: list[str] = []
    monkeypatch.setattr(scoring, "features_licitaciones_abiertas", lambda **kw: [_fila("E1", "1")])
    monkeypatch.setattr(scoring, "PrediccionesRepository", _RepoCaptura)
    monkeypatch.setattr(scoring, "_media_global_baja", lambda **kw: 0.2)
    monkeypatch.setattr(scoring, "_offset_baseline", lambda **kw: 0.0)
    monkeypatch.setattr(
        "db.model_registry.get_active", lambda nombre: pedidos.append(nombre) or None
    )
    scoring.score_predicciones_baja_por_lote()
    assert pedidos == ["baja_model_lote"]


def test_el_job_no_corre_el_batch_por_lote_por_defecto(monkeypatch):
    from config import settings
    from scheduler.jobs import ml_predicciones

    monkeypatch.setattr(settings, "ML_BAJA_POR_LOTE", False)
    with patch("services.ml.scoring.score_predicciones_baja_por_lote") as batch:
        assert ml_predicciones._score_baja_por_lote_si_activo() == {"status": "desactivado"}
    batch.assert_not_called()


def test_el_job_aisla_un_fallo_del_batch_por_lote(monkeypatch):
    from config import settings
    from scheduler.jobs import ml_predicciones

    monkeypatch.setattr(settings, "ML_BAJA_POR_LOTE", True)
    with patch(
        "services.ml.scoring.score_predicciones_baja_por_lote", side_effect=RuntimeError("x")
    ):
        assert ml_predicciones._score_baja_por_lote_si_activo()["status"] == "error"


# ---------------------------------------------------------------------------
# Upsert con los árbitros de v140
# ---------------------------------------------------------------------------


def test_guardar_baja_usa_un_arbitro_por_indice_parcial():
    from db.repositories import predicciones as mod

    conexion = MagicMock()
    ctx = MagicMock()
    ctx.__enter__.return_value = conexion
    with patch.object(mod, "connect", return_value=ctx):
        mod.PrediccionesRepository().guardar_baja(
            [
                ("E1", None, 0.1, 0.2, 0.3, None, "t"),
                ("E1", "1", 0.1, 0.2, 0.3, None, "t"),
                ("E1", "2", 0.1, 0.2, 0.3, None, "t"),
            ]
        )

    sentencias = [
        (llamada.args[0], llamada.args[1]) for llamada in conexion.executemany.call_args_list
    ]
    assert len(sentencias) == 2
    (sql_agregado, filas_agregado), (sql_lote, filas_lote) = sentencias
    assert "ON CONFLICT (licitacion_id) WHERE lote_numero IS NULL" in sql_agregado
    assert [f[1] for f in filas_agregado] == [None]
    assert "ON CONFLICT (licitacion_id, lote_numero) WHERE lote_numero IS NOT NULL" in sql_lote
    assert [f[1] for f in filas_lote] == ["1", "2"]


# ---------------------------------------------------------------------------
# Features por lote
# ---------------------------------------------------------------------------


def test_la_fila_por_lote_toma_el_importe_del_lote():
    fila = {"importe": 1_000_000.0, "importe_lote": 40_000.0}
    assert _como_lote(fila)["importe"] == 40_000.0


def test_sin_importe_de_lote_se_queda_el_del_expediente():
    assert _como_lote({"importe": 90_000.0, "importe_lote": None})["importe"] == 90_000.0
    assert _como_lote({"importe": 90_000.0, "importe_lote": 0})["importe"] == 90_000.0


def test_la_prediccion_conserva_el_lote_de_su_fila():
    from services.ml.baja_model import predecir_baseline

    [pred] = predecir_baseline([_fila("E1", "3")], 0.2)
    assert pred.lote_numero == "3"
    assert isinstance(pred, Prediccion)


# ---------------------------------------------------------------------------
# Desglose por lote en la respuesta del expediente
# ---------------------------------------------------------------------------


class _RepoLectura:
    def __init__(self, desglose: list[dict[str, Any]]) -> None:
        self.desglose = desglose

    def prediccion_materializada(
        self, licitacion_id: str, lote_numero: str | None = None
    ) -> dict[str, Any] | None:
        assert lote_numero is None, "el expediente pide explícitamente la fila agregada"
        return {
            "p10": 0.1,
            "p50": 0.2,
            "p90": 0.3,
            "model_version": 3,
            "computed_at": "2026-09-18T03:00:00+00:00",
        }

    def predicciones_por_lote(self, licitacion_id: str) -> list[dict[str, Any]]:
        return self.desglose


def _prediccion_expediente(desglose: list[dict[str, Any]]) -> dict[str, Any] | None:
    with (
        patch.object(scoring, "PrediccionesRepository", return_value=_RepoLectura(desglose)),
        patch.object(scoring, "_baja_real", return_value=None),
    ):
        return scoring.prediccion_baja("E1")


def test_sin_filas_por_lote_la_respuesta_del_expediente_no_cambia():
    from api.routes.predicciones import PrediccionBajaResult

    data = _prediccion_expediente([])
    assert data is not None
    assert "lotes" not in data
    # `exclude_unset`: la clave ni siquiera aparece serializada.
    assert "lotes" not in PrediccionBajaResult(**data).model_dump(exclude_unset=True)


def test_el_desglose_por_lote_viaja_junto_a_la_cifra_agregada():
    from api.routes.predicciones import PrediccionBajaResult

    data = _prediccion_expediente(
        [
            {
                "lote_id": 11,
                "lote_numero": "1",
                "p10": 0.05,
                "p50": 0.15,
                "p90": 0.25,
                "model_version": None,
                "computed_at": "2026-09-18T03:00:00+00:00",
            }
        ]
    )
    assert data is not None
    assert data["p50"] == 0.2  # la cifra servida sigue siendo la agregada
    dto = PrediccionBajaResult(**data)
    assert dto.lotes is not None
    [lote] = dto.lotes
    assert (lote.lote_id, lote.lote_numero, lote.p50, lote.serving) == (11, "1", 0.15, "baseline")


def test_la_ruta_sirve_el_desglose():
    from api.routes.predicciones import get_prediccion_baja

    data = {
        "licitacion_id": "E1",
        "p50": 0.2,
        "lotes": [
            {
                "lote_id": 11,
                "lote_numero": "1",
                "p10": 0.05,
                "p50": 0.15,
                "p90": 0.25,
                "model_version": 2,
                "computed_at": None,
                "serving": "modelo",
            }
        ],
    }
    with patch("api.routes.predicciones.prediccion_baja", return_value=data):
        servido = asyncio.run(get_prediccion_baja("E1", _ctx={}))
    assert servido.lotes is not None and servido.lotes[0].model_version == 2


# ---------------------------------------------------------------------------
# Comparación por lote vs agregado
# ---------------------------------------------------------------------------


def test_metricas_recomienda_sustituir_solo_si_el_delta_supera_su_ruido():
    from services.ml.comparacion_lote import _metricas

    # El lote acierta siempre; el agregado falla 0.05 en cada par.
    claro = _metricas([(0.20, 0.25, 0.20)] * 40 + [(0.10, 0.05, 0.10)] * 40)
    assert claro["delta_mae_p50"] == pytest.approx(-0.05)
    assert claro["recomendacion"] == "candidato_a_sustituir"

    # Mejora media minúscula con mucho ruido: no basta con que sea negativa.
    rng = random.Random(7)
    ruidoso = _metricas(
        [(0.2, 0.2 + rng.uniform(-0.1, 0.1), 0.2 + rng.uniform(-0.1, 0.1)) for _ in range(40)]
    )
    if ruidoso["delta_mae_p50"] < 0:
        assert ruidoso["recomendacion"] == "mantener_agregado"


def test_metricas_con_pocos_pares_no_recomienda_nada():
    from services.ml.comparacion_lote import _metricas

    assert _metricas([(0.2, 0.3, 0.2)] * 5)["recomendacion"] == "sin_datos_suficientes"
    assert _metricas([])["recomendacion"] == "sin_datos_suficientes"


def test_si_el_lote_empeora_se_mantiene_el_agregado():
    from services.ml.comparacion_lote import _metricas

    peor = _metricas([(0.20, 0.20, 0.30)] * 40)
    assert peor["delta_mae_p50"] > 0
    assert peor["recomendacion"] == "mantener_agregado"


def test_comparar_sobre_pares_sin_train_suficiente():
    from services.ml.comparacion_lote import comparar_sobre_pares

    res = comparar_sobre_pares(train_expediente=[], train_lote=[], eval_expediente=[], eval_lote=[])
    assert res["status"] == "datos_insuficientes"


def _fila_sintetica(lic: str, lote: str | None, cpv4: str, baja: float, mes: int) -> FilaDataset:
    features: dict[str, Any] = {
        col: ("na" if col in CATEGORICAL_COLUMNS else None) for col in FEATURE_COLUMNS
    }
    features["cpv4"] = cpv4
    features["log_importe"] = 11.0
    return FilaDataset(
        licitacion_id=lic,
        fecha=f"2025-{mes:02d}-15",
        features=features,
        baja=baja,
        lote_numero=lote,
    )


def test_el_backtest_detecta_un_lote_que_el_agregado_promedia():
    """Dos lotes con bajas opuestas: el agregado solo puede dar la media.

    El lote de CPV A baja un 30 % y el de CPV B un 5 %; el expediente (CPV
    mixto) promedia 17,5 %. El modelo por lote ve el CPV de cada lote y los
    separa; el agregado no puede. Es el caso que justifica el ítem, en pequeño.
    """
    pytest.importorskip("sklearn")
    from services.ml.comparacion_lote import comparar_sobre_pares

    def bloque(desde: int, n: int, mes: int) -> tuple[list[FilaDataset], list[FilaDataset]]:
        exp, lotes = [], []
        for i in range(desde, desde + n):
            lic = f"X{i}"
            exp.append(_fila_sintetica(lic, None, "mix", 0.175, mes))
            lotes.append(_fila_sintetica(lic, "1", "A", 0.30, mes))
            lotes.append(_fila_sintetica(lic, "2", "B", 0.05, mes))
        return exp, lotes

    train_exp, train_lote = bloque(0, 220, 1)
    eval_exp, eval_lote = bloque(1000, 40, 9)
    res = comparar_sobre_pares(
        train_expediente=train_exp,
        train_lote=train_lote,
        eval_expediente=eval_exp,
        eval_lote=eval_lote,
        halflife=0.0,
    )
    assert res["status"] == "ok"
    assert res["todos"]["n"] == 80
    assert res["todos"]["mae_p50_lote"] < res["todos"]["mae_p50_agregado"]
    assert res["recomendacion"] == "candidato_a_sustituir"
