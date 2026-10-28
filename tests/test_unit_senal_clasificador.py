"""D55: sin versión activa que haya pasado el gate, ``ml_proba`` no es señal.

El ``sap_classifier`` servido (el asset de mayo, sin versión activa en
``model_versions``) da ``ml_proba ≥ 0,69`` al 60 % de su población. Mientras
no haya una versión validada, su probabilidad:

- no ordena ni puntúa el Radar (que la proyección del scoring no la lee y que
  cambiarla no mueve ni un punto);
- no aparece en ningún contrato de la API ni en la tarjeta de la cola de
  etiquetado, que lo declara con ``senal_clasificador``.

La definición de «validada» vive en ``services/ml/senal_clasificador.py``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from services.ml import senal_clasificador as senal
from services.ml.senal_clasificador import EstadoSenal, evaluar_version_activa

_RAIZ = Path(__file__).resolve().parents[1]
_SHA = "a" * 64

_METRICAS_QUE_PASAN: dict[str, Any] = {
    "metrics_reliable": True,
    "split_strategy": "temporal",
    "golden_holdout_n": 80,
    "golden_holdout_n_positive": 30,
    "golden_holdout_n_negative": 50,
    "golden_holdout_threshold": 0.5,
    "golden_holdout_accuracy": 0.9,
    "golden_holdout_precision": 0.9,
    "golden_holdout_recall": 0.8,
    "golden_holdout_f1": 0.85,
    "golden_holdout_fbeta": 0.85,
    "golden_holdout_beta": 1.0,
    "golden_holdout_recall_no_keyword": 0.4,
    "golden_holdout_n_no_keyword_positive": 10,
    "golden_holdout_n_no_keyword_caught": 4,
}


def _activa(**cambios: Any) -> dict[str, Any]:
    fila: dict[str, Any] = {
        "version": 3,
        "path": f"/runner/data/models/sap_classifier-{_SHA[:12]}.pkl",
        "sha256": _SHA,
        "metrics": dict(_METRICAS_QUE_PASAN),
    }
    fila.update(cambios)
    return fila


# ── La regla: qué cuenta como versión validada ──────────────────────────────


def test_sin_version_activa_la_senal_no_esta_validada() -> None:
    estado = evaluar_version_activa(None)

    assert estado.validada is False
    assert estado.motivo == senal.MOTIVO_SIN_VERSION_ACTIVA


def test_una_version_publicada_por_el_gate_y_que_lo_pasa_esta_validada() -> None:
    estado = evaluar_version_activa(_activa())

    assert estado == EstadoSenal(validada=True, version=3)


@pytest.mark.parametrize(
    "path",
    [
        # Las anteriores a 2026-10 (la v2 del incidente del 29/09).
        "data/models/sap_classifier.pkl",
        # Un candidato rechazado se registra con su nombre versionado.
        "/runner/data/models/sap_classifier_v1.pkl",
        # Nombre por contenido, pero de otro contenido.
        "/runner/data/models/sap_classifier-ffffffffffff.pkl",
    ],
)
def test_activar_a_mano_un_artefacto_que_el_gate_no_publico_no_la_valida(path: str) -> None:
    estado = evaluar_version_activa(_activa(path=path))

    assert estado.validada is False
    assert estado.motivo == senal.MOTIVO_ARTEFACTO_SIN_GATE


def test_el_golden_de_hoy_no_alcanza_el_holdout_minimo() -> None:
    """27 etiquetados frente a ≥ 60 en el holdout (D55, 2026-10-25)."""
    metricas = {**_METRICAS_QUE_PASAN, "golden_holdout_n": 27}

    estado = evaluar_version_activa(_activa(metrics=metricas))

    assert estado.validada is False
    assert estado.motivo == senal.MOTIVO_NO_PASA_EL_GATE
    assert any("27" in motivo for motivo in estado.detalle)


@pytest.mark.parametrize(
    "cambio",
    [
        {"metrics_reliable": False},
        {"split_strategy": "random"},
        {"golden_holdout_recall_no_keyword": 0.0},
        {"golden_holdout_n_no_keyword_positive": 0},
        {"golden_holdout_n": None},
    ],
)
def test_unas_metricas_que_no_pasan_el_gate_no_validan(cambio: dict[str, Any]) -> None:
    estado = evaluar_version_activa(_activa(metrics={**_METRICAS_QUE_PASAN, **cambio}))

    assert estado.validada is False
    assert estado.motivo == senal.MOTIVO_NO_PASA_EL_GATE


def test_un_registro_ilegible_esconde_la_senal(monkeypatch: pytest.MonkeyPatch) -> None:
    import db.model_registry as registro

    def roto(_name: str) -> dict[str, Any] | None:
        raise RuntimeError("sin conexión")

    monkeypatch.setattr(registro, "get_active", roto)

    estado = senal.estado_senal_sap()

    assert estado.validada is False
    assert estado.motivo == senal.MOTIVO_REGISTRY_ILEGIBLE


def test_lee_la_version_activa_del_sap_classifier(monkeypatch: pytest.MonkeyPatch) -> None:
    import db.model_registry as registro

    pedidos: list[str] = []

    def get_active(name: str) -> dict[str, Any] | None:
        pedidos.append(name)
        return None

    monkeypatch.setattr(registro, "get_active", get_active)

    assert senal.estado_senal_sap() == senal.NO_VALIDADA_SIN_VERSION
    assert pedidos == ["sap_classifier"]


# ── El Radar: la probabilidad no ordena ni puntúa ───────────────────────────

#: Los módulos por los que pasa el Radar: la ruta, el scoring y sus señales,
#: la proyección SQL y los predicados de universo.
_MODULOS_DEL_RADAR = (
    "api/routes/radar.py",
    "api/routes/analytics.py",
    "db/repositories/aggregates.py",
    "db/sql_fragments.py",
    "services/sql_fragments.py",
    *sorted(p.relative_to(_RAIZ).as_posix() for p in (_RAIZ / "services/analytics").glob("*.py")),
)

#: ``ml_proba`` como palabra: no casa con ``ml_proba_max``, que deriva el
#: clasificador multi-etiqueta, el LLM y el pliego (ADR-026), no el binario.
_ML_PROBA = re.compile(r"\bml_proba\b")


def test_ningun_modulo_del_radar_lee_ml_proba() -> None:
    lectores = [
        ruta
        for ruta in _MODULOS_DEL_RADAR
        if (_RAIZ / ruta).exists() and _ML_PROBA.search((_RAIZ / ruta).read_text(encoding="utf-8"))
    ]

    assert lectores == [], (
        "D55: la probabilidad del sap_classifier no ordena ni puntúa el Radar mientras "
        "no tenga versión activa validada (services/ml/senal_clasificador.py)."
    )


def test_la_proyeccion_del_scoring_no_trae_ml_proba() -> None:
    from db.repositories.aggregates import AggregateRepository

    columnas = {c.strip() for c in AggregateRepository._SCORING_COLS.split(",")}

    assert "ml_proba" not in columnas


def test_cambiar_ml_proba_no_mueve_el_score_ni_el_orden() -> None:
    from services.analytics.scoring import _puntuar, _ScoringContext
    from services.analytics.scoring_signals import CompetenciaStats, MargenStats

    ahora = pd.Timestamp("2026-10-26T10:00:00Z")
    base = pd.DataFrame(
        {
            "id_externo": ["A", "B", "C"],
            "titulo": ["Soporte SAP", "Licencias", "Mantenimiento ERP"],
            "cpv": ["72267000", "48000000", "72000000"],
            "importe": [50_000.0, 200_000.0, 900_000.0],
            "organo_contratacion": ["Ayto. A", "Ayto. B", "Ayto. C"],
            "fecha_limite_dt": [ahora + pd.Timedelta(days=d) for d in (5, 20, 40)],
        }
    )
    ctx = _ScoringContext(
        imp_p10=10_000.0,
        imp_p90=1_000_000.0,
        weights={
            "importe": 20,
            "plazo": 15,
            "competencia": 20,
            "margen": 20,
            "afinidad": 15,
            "senal_tecnica": 10,
        },
        keywords=[],
        affinity_scores={"A": 0.2, "B": 0.5},
        affinity_method="keyword_cpv_fallback",
        competencia_stats=CompetenciaStats(media_global=3.0, status="ok"),
        margen_stats=MargenStats(baja_media_global=0.15, status="ok"),
        tech_signal={"A": 0.4, "C": 0.9},
        now=ahora,
    )

    sin_columna = _puntuar(base, ctx)
    sesgada_a = _puntuar(base.assign(ml_proba=[0.99, 0.01, 0.01]), ctx)
    sesgada_c = _puntuar(base.assign(ml_proba=[0.01, 0.01, 0.99]), ctx)

    for otra in (sesgada_a, sesgada_c):
        assert otra.ids == sin_columna.ids
        np.testing.assert_array_equal(otra.score, sin_columna.score)
        assert otra.bandas == sin_columna.bandas


# ── Ninguna pantalla la enseña ──────────────────────────────────────────────


def test_ningun_contrato_de_la_api_expone_ml_proba() -> None:
    """La web solo ve lo que el OpenAPI describe (invariante 8)."""
    from api.app import app

    esquemas = app.openapi()["components"]["schemas"]
    con_ml_proba = sorted(
        nombre
        for nombre, esquema in esquemas.items()
        if "ml_proba" in (esquema.get("properties") or {})
    )

    assert con_ml_proba == []


_CANDIDATO_DESACUERDO: dict[str, Any] = {
    "id_externo": "EXP-9",
    "titulo": "Manteniment del gestor documental",
    "descripcion": "",
    "cpv": "72267000-4",
    "importe": 1000.0,
    "organo_contratacion": "Ajuntament",
    "ccaa": "Cataluña",
    "fecha_publicacion": "2026-09-20",
    "url": None,
    "tecnologia": None,
    "ml_tecnologias": None,
    "ml_proba_max": None,
    "ml_tech_principal": None,
    "ml_proba": 0.97,
    "motivo": "llm_si_reglas_no",
    "llm_es_ti": True,
    "llm_confianza_es_ti": 0.7,
    "llm_familias": [],
    "llm_sin_evidencia": False,
}


@pytest.fixture
def cola(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """La cola de etiquetado sin BD y con el registro sin versión activa."""
    import api.routes.feedback as rutas
    import db.repositories.revision_ti as revision
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    monkeypatch.setattr(
        revision, "candidatos_desacuerdo", lambda limit: [dict(_CANDIDATO_DESACUERDO)]
    )
    monkeypatch.setattr(rutas, "_cargar_tech_classifier", lambda: None)
    monkeypatch.setattr(rutas, "_senal_clasificador", lambda: senal.NO_VALIDADA_SIN_VERSION)
    app.dependency_overrides[require_any_auth] = lambda: {"user_id": 1, "is_admin": True}
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


def test_sin_version_activa_la_cola_por_desacuerdo_no_ensena_la_confianza(
    cola: TestClient,
) -> None:
    cuerpo = cola.get("/api/v1/feedback/queue?strategy=desacuerdo&limit=5").json()

    item = cuerpo["items"][0]
    assert item["sin_confianza"] is True
    assert item["confidence"] == pytest.approx(0.5)
    assert item["uncertainty"] == pytest.approx(0.0)
    assert cuerpo["senal_clasificador"] == {
        "validada": False,
        "motivo": "sin_version_activa",
        "version": None,
    }


def test_sin_version_activa_la_cola_por_incertidumbre_no_ensena_la_confianza(
    cola: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La cola sigue eligiendo candidatos con el modelo —es muestreo para
    etiquetar, no una señal—, pero ninguna tarjeta lleva su probabilidad."""
    from unittest.mock import MagicMock

    import api.model_cache as cache
    import api.routes.feedback as rutas

    candidatos = [
        {"id_externo": "A", "titulo": "SAP", "descripcion": "", "cpv": None, "importe": None},
        {"id_externo": "B", "titulo": "Otro", "descripcion": "", "cpv": None, "importe": None},
    ]
    repo = MagicMock()
    repo.get_unlabelled_candidates.return_value = candidatos
    monkeypatch.setattr(rutas, "_lic_repo", repo)
    clf = MagicMock()
    clf.predict_proba.return_value = np.array([[0.1, 0.9], [0.45, 0.55]])
    monkeypatch.setattr(cache, "get_classifier", lambda: clf)

    cuerpo = cola.get("/api/v1/feedback/queue?strategy=uncertainty&limit=5").json()

    assert cuerpo["strategy"] == "uncertainty"
    assert [i["id_externo"] for i in cuerpo["items"]] == ["B", "A"]
    assert all(i["sin_confianza"] for i in cuerpo["items"])
    assert {i["confidence"] for i in cuerpo["items"]} == {0.5}
    assert cuerpo["senal_clasificador"]["validada"] is False


def test_con_version_validada_la_cola_ensena_la_confianza(
    cola: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import api.routes.feedback as rutas

    monkeypatch.setattr(rutas, "_senal_clasificador", lambda: EstadoSenal(validada=True, version=3))

    cuerpo = cola.get("/api/v1/feedback/queue?strategy=desacuerdo&limit=5").json()

    assert cuerpo["items"][0]["confidence"] == pytest.approx(0.97)
    assert cuerpo["items"][0]["sin_confianza"] is False
    assert cuerpo["senal_clasificador"] == {"validada": True, "motivo": None, "version": 3}


def test_explain_declara_que_la_probabilidad_no_es_senal(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from api.routes.licitaciones import analitica

    async def fake_run_db(fn: Any, *args: Any, **kwargs: Any) -> Any:
        if fn is analitica.estado_senal_sap:
            return senal.NO_VALIDADA_SIN_VERSION
        return ("Implantación SAP S/4HANA", "Migración", "SAP")

    async def fake_run_ml(fn: Any, *args: Any, **kwargs: Any) -> Any:
        return fn(*args, **kwargs)

    class _Clf:
        def explain(self, _text: str, *, top_k: int) -> dict[str, Any]:
            return {"prediction": True, "confidence": 0.93, "top_features": []}

    monkeypatch.setattr(analitica, "run_db", fake_run_db)
    monkeypatch.setattr(analitica, "run_ml", fake_run_ml)
    monkeypatch.setattr(analitica, "_get_classifier", _Clf)

    # Desde la fase B de identidad el id llega resuelto por la dependencia
    # `resolver_id_externo`, no como parámetro de ruta posicional.
    resultado = asyncio.run(analitica.explain_licitacion(top_k=5, _ctx={}, id_externo="X-1"))

    assert resultado.senal_clasificador is not None
    assert resultado.senal_clasificador.validada is False
    assert resultado.senal_clasificador.motivo == "sin_version_activa"
    assert resultado.warning == analitica.AVISO_SENAL_NO_VALIDADA
