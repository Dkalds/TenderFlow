"""Los tres caminos de predicción tienen que dar la misma probabilidad.

``SAPClassifier`` expone ``predict``, ``predict_proba`` y ``explain``.
``predict`` aplica ``_augment_text`` —que inyecta los tokens estructurales
(``CPV_TI``, ``CPV2_72``, ``IMPORTE_M``…) con los que el modelo se entrenó— y
``predict_proba`` no lo hacía.

Como ``predict_proba`` es el que puntúa la cola de active learning
(``api/routes/feedback.py``), el conjunto de licitaciones que un humano llegaba
a etiquetar —y por tanto todo el feedback que realimenta el modelo— se ordenaba
con una probabilidad calculada sin las señales más discriminantes. Además
contradecía el ``ml_proba`` guardado en BD para la misma licitación, así que la
UI mostraba dos confianzas distintas del mismo modelo.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from services.ml.sap_classifier import SAPClassifier

_SAP = "Implantacion de SAP S/4HANA modulo financiero"
_NO_SAP = "Suministro de material de oficina para dependencias"
_VARIANTES = ["central", "autonomico", "provincial", "municipal", "consorcio", "portuario"]


@pytest.fixture(scope="module")
def clasificador() -> SAPClassifier:
    """Un clasificador realmente entrenado sobre un histórico sintético."""
    filas: list[dict[str, object]] = []
    d0 = date(2024, 1, 1)
    for i in range(240):
        es_pos = i % 3 == 0
        variante = " ".join(
            _VARIANTES[(i // len(_VARIANTES) ** k) % len(_VARIANTES)] for k in range(3)
        )
        filas.append(
            {
                "titulo": f"{_SAP if es_pos else _NO_SAP} {variante}",
                "descripcion": "",
                "raw_keywords": "SAP" if es_pos else None,
                "cpv": "72000000" if es_pos else "30000000",
                "importe": 250_000.0,
                "fecha_publicacion": (d0 + timedelta(days=i)).isoformat(),
            }
        )
    clf = SAPClassifier()
    metrics = clf.train(pd.DataFrame(filas))
    assert "error" not in metrics, metrics
    return clf


_CASOS = [
    ("Servicio de soporte del ERP corporativo", "72000000", 500_000.0),
    ("Suministro de sillas de oficina", "39000000", 12_000.0),
    ("Migracion de entorno HANA de gestion economica", "48000000", 1_500_000.0),
]


class TestParidadEntreCaminos:
    @pytest.mark.parametrize(("texto", "cpv", "importe"), _CASOS)
    def test_predict_proba_coincide_con_predict(
        self, clasificador: SAPClassifier, texto: str, cpv: str, importe: float
    ) -> None:
        _, proba_predict = clasificador.predict(texto, cpv=cpv, importe=importe)
        matriz = clasificador.predict_proba([texto], cpvs=[cpv], importes=[importe])
        assert matriz[0][1] == pytest.approx(proba_predict, abs=1e-9)

    @pytest.mark.parametrize(("texto", "cpv", "importe"), _CASOS)
    def test_explain_coincide_con_predict(
        self, clasificador: SAPClassifier, texto: str, cpv: str, importe: float
    ) -> None:
        """``/explain`` enseñaba otra confianza que el ``ml_proba`` de la misma licitación."""
        es_sap, proba_predict = clasificador.predict(texto, cpv=cpv, importe=importe)
        explicacion = clasificador.explain(texto, cpv=cpv, importe=importe)
        assert explicacion["confidence"] == pytest.approx(proba_predict, abs=1e-9)
        assert explicacion["prediction"] is es_sap

    def test_explain_contribuye_sobre_las_features_escaladas(
        self, clasificador: SAPClassifier
    ) -> None:
        """La contribución es lo que entra al clasificador: tras el ``MaxAbsScaler``."""
        from services.ml.classifier_pipeline import _augment_text

        texto, cpv, importe = _CASOS[0]
        explicacion = clasificador.explain(texto, cpv=cpv, importe=importe, top_k=20)
        nombres = list(clasificador.pipeline.named_steps["features"].get_feature_names_out())
        escaladas = clasificador.pipeline[:-1].transform(
            [_augment_text(texto, cpv=cpv, importe=importe)]
        )
        assert explicacion["top_features"]
        for f in explicacion["top_features"]:
            valor = escaladas[0, nombres.index(f["term"])]
            assert f["contribution"] == pytest.approx(valor * f["weight"], abs=1e-9)
        assert any("cpv_ti" in f["term"] for f in explicacion["top_features"]), (
            "los tokens estructurales no llegan a la explicación"
        )

    def test_los_tokens_estructurales_cambian_la_probabilidad(
        self, clasificador: SAPClassifier
    ) -> None:
        """Si pasar el CPV no cambiara nada, el test de paridad sería vacío."""
        texto = "Servicio de soporte del ERP corporativo"
        sin_cpv = clasificador.predict_proba([texto])[0][1]
        con_cpv = clasificador.predict_proba([texto], cpvs=["72000000"])[0][1]
        assert sin_cpv != pytest.approx(con_cpv, abs=1e-6), (
            "los tokens estructurales no influyen: el modelo no los aprendió "
            "y la paridad entre caminos no demuestra nada"
        )
