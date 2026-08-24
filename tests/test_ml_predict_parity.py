"""Los tres caminos de predicción tienen que dar la misma probabilidad.

``SAPClassifier`` expone ``predict``, ``predict_batch`` y ``predict_proba``.
Los dos primeros aplican ``_augment_text`` —que inyecta los tokens
estructurales (``CPV_TI``, ``CPV2_72``, ``IMPORTE_M``…) con los que el modelo
se entrenó— y el tercero no lo hacía.

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

from scraper.ml_classifier import SAPClassifier

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
    def test_predict_batch_coincide_con_predict(
        self, clasificador: SAPClassifier, texto: str, cpv: str, importe: float
    ) -> None:
        _, proba_predict = clasificador.predict(texto, cpv=cpv, importe=importe)
        ((_, proba_batch),) = clasificador.predict_batch([texto], cpvs=[cpv], importes=[importe])
        assert proba_batch == pytest.approx(proba_predict, abs=1e-9)

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
