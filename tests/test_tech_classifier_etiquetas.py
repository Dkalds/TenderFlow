"""Etiquetas no circulares del clasificador multi-tecnología (S6.2).

``licitaciones.tecnologia`` la escriben los conectores llamando a
``matches_technology()`` sobre el mismo título y descripción que después ve el
modelo. Entrenar contra ella mide cuánto **imita** el modelo al regex.

Esta suite fija tres cosas:

1. Con etiquetas humanas suficientes NO se emite ``circular_labels``.
2. Con unas pocas etiquetas humanas sobre un corpus de keywords SÍ se emite:
   el aviso desaparece cuando las independientes son *suficientes*, no cuando
   hay una. Con las 33 de producción y ~1.400 filas de keywords, el flag decía
   que no era circular sobre un modelo que es el regex con un redondeo encima.
3. El conteo por origen queda en ``label_sources`` y llega al registro.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd

from scraper.tech_classifier import (
    TechnologyClassifier,
    _es_circular,
    _resolver_label_column,
    registrar_entrenamiento,
)


def _df(n: int, *, humanas: int = 0, llm: int = 0, tecnologia: str = "META4") -> pd.DataFrame:
    """Corpus mínimo donde ninguna etiqueta llega al tier ML.

    Con esto ``train()`` recorre la resolución de etiquetas sin ajustar un solo
    modelo: los tests corren en milisegundos.
    """
    return pd.DataFrame(
        {
            "titulo": [f"contrato de servicios {i}" for i in range(n)],
            "descripcion": ["objeto del contrato"] * n,
            "tecnologia": [tecnologia] * n,
            "tecnologia_humana": ["ORACLE"] * humanas + [None] * (n - humanas),
            "tecnologia_llm": [None] * (n - llm) + ["SAP:0.91"] * llm,
        }
    )


class TestSuficienciaDeEtiquetas:
    def test_sin_ninguna_fila_de_keywords_no_es_circular(self) -> None:
        """Un dataset pequeño pero enteramente humano es pequeño, no circular.
        Confundir las dos cosas haría saltar el aviso justo cuando el etiquetado
        va bien."""
        assert _es_circular({"human": 3, "llm": 0, "keywords": 0, "sin_etiqueta": 0}) is False

    def test_pocas_independientes_sobre_un_corpus_de_keywords_es_circular(self) -> None:
        # El caso de producción del 2026-09-03: 33 humanas, ~1.400 keywords.
        assert _es_circular({"human": 33, "llm": 0, "keywords": 1405, "sin_etiqueta": 0}) is True

    def test_con_independientes_suficientes_deja_de_serlo(self) -> None:
        assert _es_circular({"human": 60, "llm": 0, "keywords": 1405, "sin_etiqueta": 0}) is False

    def test_el_suelo_es_el_del_tier_ml_ready(self) -> None:
        """No es un umbral nuevo: por debajo de ``ML_TECH_MIN_POS_READY``
        ninguna tecnología puede llegar al tier con filas independientes."""
        from scraper.tech_classifier import _suelo_etiquetas_independientes

        with patch("scraper.tech_classifier.settings") as mock_settings:
            mock_settings.ML_TECH_MIN_POS_READY = 7
            assert _suelo_etiquetas_independientes() == 7
            assert _es_circular({"human": 7, "llm": 0, "keywords": 10}) is False
            assert _es_circular({"human": 6, "llm": 0, "keywords": 10}) is True


class TestAvisoDeCircularidad:
    def test_con_etiquetas_humanas_suficientes_no_avisa(self) -> None:
        """El criterio de aceptación de S6.2, en una línea."""
        df = _df(80, humanas=80)
        with patch("scraper.tech_classifier.log") as mock_log:
            resolucion = _resolver_label_column(df)
        avisos = [c[0][0] for c in mock_log.warning.call_args_list]
        assert "tech_classifier.circular_labels" not in avisos
        assert resolucion.circular is False
        assert resolucion.counts["human"] == 80

    def test_train_no_avisa_con_etiquetas_humanas_suficientes(self) -> None:
        df = _df(80, humanas=80)
        with patch("scraper.tech_classifier.log") as mock_log:
            metrics = TechnologyClassifier().train(df)
        avisos = [c[0][0] for c in mock_log.warning.call_args_list]
        assert "tech_classifier.circular_labels" not in avisos
        assert metrics["labels_circulares"] is False
        # Y la etiqueta que decide es la humana, no las keywords.
        assert metrics["per_tech"]["ORACLE"]["n_positive"] == 80
        assert metrics["per_tech"]["META4"]["n_positive"] == 0

    def test_train_avisa_cuando_las_humanas_no_llegan_al_suelo(self) -> None:
        df = _df(80, humanas=2)
        with patch("scraper.tech_classifier.log") as mock_log:
            metrics = TechnologyClassifier().train(df)
        avisos = [c[0][0] for c in mock_log.warning.call_args_list]
        assert "tech_classifier.circular_labels" in avisos
        assert metrics["labels_circulares"] is True

    def test_la_senal_llm_tambien_cuenta_como_independiente(self) -> None:
        df = _df(80, llm=80)
        with patch("scraper.tech_classifier.log") as mock_log:
            resolucion = _resolver_label_column(df)
        avisos = [c[0][0] for c in mock_log.warning.call_args_list]
        assert "tech_classifier.circular_labels" not in avisos
        assert resolucion.counts["llm"] == 80


class TestLabelSources:
    def test_las_metricas_llevan_el_conteo_por_origen(self) -> None:
        metrics = TechnologyClassifier().train(_df(80, humanas=60))
        assert metrics["label_sources"] == {
            "human": 60,
            "llm": 0,
            "keywords": 20,
            "sin_etiqueta": 0,
        }
        # El gate de publicación lee el nombre viejo; los dos son el mismo dato.
        assert metrics["label_source_counts"] == metrics["label_sources"]

    def test_el_registro_guarda_label_sources(self, tmp_path: Path) -> None:
        destino = tmp_path / "tech_registry.json"
        metrics: dict[str, Any] = {
            "label_sources": {"human": 60, "llm": 5, "keywords": 20, "sin_etiqueta": 0},
            "label_column": "tecnologia_resuelta",
            "labels_circulares": False,
            "n_samples": 85,
            "n_models": 1,
            "macro_f1_all_labels": 0.71,
        }
        registrar_entrenamiento(metrics, path=destino)
        entradas = json.loads(destino.read_text(encoding="utf-8"))
        assert entradas[-1]["label_sources"] == metrics["label_sources"]
        assert entradas[-1]["modelo"] == "tech_classifier"
        assert entradas[-1]["trained_at"]

    def test_el_registro_es_append_only(self, tmp_path: Path) -> None:
        destino = tmp_path / "tech_registry.json"
        registrar_entrenamiento({"label_sources": {"human": 1}}, path=destino)
        registrar_entrenamiento({"label_sources": {"human": 2}}, path=destino)
        entradas = json.loads(destino.read_text(encoding="utf-8"))
        assert [e["label_sources"] for e in entradas] == [{"human": 1}, {"human": 2}]

    def test_tambien_registra_el_entrenamiento_rechazado(self, tmp_path: Path) -> None:
        """Un rechazo sin conteo no informa: lo que hay que mirar es justo con
        qué etiquetas se intentó."""
        destino = tmp_path / "tech_registry.json"
        registrar_entrenamiento(
            {"error": "no_ml_techs", "label_sources": {"human": 0, "keywords": 900}},
            path=destino,
        )
        entrada = json.loads(destino.read_text(encoding="utf-8"))[-1]
        assert entrada["error"] == "no_ml_techs"
        assert entrada["label_sources"]["keywords"] == 900


class TestTrainFromDb:
    """El SQL vive en ``db/`` (ADR-022): aquí se sustituyen sus funciones."""

    def test_lee_la_poblacion_acotada_y_las_etiquetas_no_circulares(self) -> None:
        filas = [
            {
                "id_externo": "PLACSP-1",
                "titulo": "Mantenimiento del ERP",
                "descripcion": "soporte",
                "cpv": "72000000",
                "importe": 1000.0,
                "fecha_publicacion": "2026-01-01",
                "tecnologia": "SAP",
                "raw_keywords": "SAP",
            }
        ]
        repo = MagicMock()
        repo.return_value.etiquetas_tecnologia_no_circulares.return_value = {
            "PLACSP-1": {"tecnologia_humana": "ORACLE", "tecnologia_llm": None}
        }
        clf = MagicMock()
        clf.train.return_value = {"error": "insufficient_data", "label_sources": {"human": 1}}

        with (
            patch(
                "db.repositories.ml_dataset.filas_entrenamiento_tecnologia", return_value=filas
            ) as mock_filas,
            patch("db.repositories.licitaciones.LicitacionRepository", repo),
            patch("scraper.tech_classifier.TechnologyClassifier", return_value=clf),
            patch("scraper.tech_classifier.registrar_entrenamiento") as mock_registro,
        ):
            from scraper.tech_classifier import train_from_db

            train_from_db()

        mock_filas.assert_called_once()
        df = clf.train.call_args[0][0]
        assert df.loc[0, "tecnologia_humana"] == "ORACLE"
        # El registro se escribe siempre, también cuando el entrenamiento falla.
        mock_registro.assert_called_once()
        clf.save.assert_not_called()
