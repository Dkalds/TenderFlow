"""Tests para scraper/ml_training.py — registro de entrenamientos y precómputo ML."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch


class TestAppendToRegistry:
    def test_creates_file_when_missing(self, tmp_path: Path) -> None:
        from scraper.ml_training import _append_to_registry

        target = tmp_path / "sub" / "registry.json"
        _append_to_registry({"run": 1}, path=target)
        assert target.exists()
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data == [{"run": 1}]

    def test_appends_to_existing(self, tmp_path: Path) -> None:
        from scraper.ml_training import _append_to_registry

        target = tmp_path / "registry.json"
        target.write_text('[{"run": 1}]', encoding="utf-8")
        _append_to_registry({"run": 2}, path=target)
        data = json.loads(target.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[1]["run"] == 2

    def test_handles_corrupt_json(self, tmp_path: Path) -> None:
        from scraper.ml_training import _append_to_registry

        target = tmp_path / "registry.json"
        target.write_text("NOT JSON", encoding="utf-8")
        _append_to_registry({"run": 1}, path=target)
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data == [{"run": 1}]

    def test_handles_non_list_json(self, tmp_path: Path) -> None:
        from scraper.ml_training import _append_to_registry

        target = tmp_path / "registry.json"
        target.write_text('{"not": "a list"}', encoding="utf-8")
        _append_to_registry({"run": 1}, path=target)
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data == [{"run": 1}]

    def test_handles_empty_file(self, tmp_path: Path) -> None:
        from scraper.ml_training import _append_to_registry

        target = tmp_path / "registry.json"
        target.write_text("", encoding="utf-8")
        _append_to_registry({"run": 1}, path=target)
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data == [{"run": 1}]


class TestReadRegistry:
    def test_missing_file(self, tmp_path: Path) -> None:
        from scraper.ml_training import read_registry

        assert read_registry(path=tmp_path / "nope.json") == []

    def test_corrupt_json(self, tmp_path: Path) -> None:
        from scraper.ml_training import read_registry

        f = tmp_path / "reg.json"
        f.write_text("BAD", encoding="utf-8")
        assert read_registry(path=f) == []

    def test_non_list(self, tmp_path: Path) -> None:
        from scraper.ml_training import read_registry

        f = tmp_path / "reg.json"
        f.write_text('{"x":1}', encoding="utf-8")
        assert read_registry(path=f) == []

    def test_valid(self, tmp_path: Path) -> None:
        from scraper.ml_training import read_registry

        f = tmp_path / "reg.json"
        f.write_text('[{"a":1}]', encoding="utf-8")
        assert read_registry(path=f) == [{"a": 1}]


class TestTrainFromDb:
    """El camino que produce el asset de la Release.

    Estos tests ya no mockean ``db.database.connect``: desde S6.1 el SQL vive
    en ``db/repositories/ml_dataset.py`` (ADR-022) y lo que se sustituye son
    sus funciones. Es también lo que los mantiene ``unit``: ninguno abre
    Postgres.
    """

    @staticmethod
    def _filas(n_positivos: int, n_negativos: int) -> list[dict[str, Any]]:
        """Dataset con la proporción de positivos que se quiera medir."""
        filas: list[dict[str, Any]] = []
        for i in range(n_positivos):
            filas.append(
                {
                    "id_externo": f"POS-{i}",
                    "titulo": f"Mantenimiento SAP S/4HANA {i}",
                    "descripcion": "Servicios de soporte del ERP corporativo",
                    "raw_keywords": "SAP",
                    "cpv": "72000000",
                    "importe": 100000.0,
                    "fecha_publicacion": "2026-01-01",
                    "tecnologia": "SAP",
                }
            )
        for i in range(n_negativos):
            filas.append(
                {
                    "id_externo": f"NEG-{i}",
                    "titulo": f"Suministro de material de laboratorio {i}",
                    "descripcion": "Reactivos y consumibles",
                    "raw_keywords": None,
                    "cpv": "33000000",
                    "importe": 50000.0,
                    "fecha_publicacion": "2026-01-01",
                    "tecnologia": None,
                }
            )
        return filas

    @staticmethod
    def _dataset(filas: list[dict[str, Any]], feedback: list[dict[str, Any]] | None = None):
        """Sustituye las dos lecturas del dataset por listas en memoria."""
        return (
            patch("db.database.init_db"),
            patch("db.repositories.ml_dataset.filas_entrenamiento_sap", return_value=filas),
            patch(
                "db.repositories.ml_dataset.feedback_humano_sap",
                return_value=list(feedback or []),
            ),
        )

    def test_train_success_saves(self) -> None:
        lecturas = self._dataset(self._filas(n_positivos=30, n_negativos=70))
        mock_clf = MagicMock()
        mock_clf.train.return_value = {"f1": 0.9}

        # El artefacto de producción no se sobrescribe a ciegas: este camino
        # —el que genera el asset de la Release que sirven API y runners— pasa
        # por el mismo gate que el reentrenamiento semanal.
        with (
            lecturas[0],
            lecturas[1],
            lecturas[2],
            patch("scraper.ml_classifier.SAPClassifier", return_value=mock_clf),
            patch("services.ml.promotion.promote_if_better") as mock_promote,
        ):
            mock_promote.return_value = SimpleNamespace(
                activada=True,
                version=3,
                motivos_rechazo=[],
                as_dict=lambda: {"activada": True, "version": 3},
            )
            from scraper.ml_training import train_from_db

            metrics = train_from_db()

        mock_clf.train.assert_called_once()
        mock_promote.assert_called_once()
        assert metrics["promotion"]["activada"] is True

    def test_registra_la_poblacion_de_entrenamiento(self) -> None:
        """Sin ``train_population``, dos versiones entrenadas sobre poblaciones
        distintas son indistinguibles en el registro."""
        lecturas = self._dataset(self._filas(n_positivos=30, n_negativos=70))
        mock_clf = MagicMock()
        mock_clf.train.return_value = {"f1": 0.9}

        with (
            lecturas[0],
            lecturas[1],
            lecturas[2],
            patch("scraper.ml_classifier.SAPClassifier", return_value=mock_clf),
            patch("services.ml.promotion.promote_if_better") as mock_promote,
        ):
            mock_promote.return_value = SimpleNamespace(
                activada=True, version=1, motivos_rechazo=[], as_dict=lambda: {"activada": True}
            )
            from scraper.ml_training import train_from_db

            metrics = train_from_db()

        poblacion = metrics["train_population"]
        assert poblacion["n_filas"] == 100
        assert poblacion["n_positivos"] == 30
        assert poblacion["pct_positivos"] == 30.0
        assert poblacion["nombre"] == "universos_filtrados_en_ingesta"
        # Y llega al registro: `promote_if_better` vuelca `metrics` en la fila.
        assert "train_population" in mock_promote.call_args[0][1]

    def test_dataset_ahogado_no_entrena(self) -> None:
        """El caso del backlog P2: 1% de clase minoritaria.

        ``validate_training_data`` es la puerta que abortó el run 33855421538 y
        ahora se ejecuta también en este camino. Con el corpus de PSCP dentro,
        el entrenamiento no debe llegar a ``train()``.
        """
        lecturas = self._dataset(self._filas(n_positivos=1, n_negativos=99))
        mock_clf = MagicMock()

        with (
            lecturas[0],
            lecturas[1],
            lecturas[2],
            patch("scraper.ml_classifier.SAPClassifier", return_value=mock_clf),
        ):
            from scraper.ml_training import train_from_db

            metrics = train_from_db()

        assert metrics["error"] == "dataset_invalido"
        assert "Minority class" in metrics["detalle"]
        assert metrics["train_population"]["pct_positivos"] == 1.0
        mock_clf.train.assert_not_called()

    def test_poblacion_acotada_pasa_el_validador(self) -> None:
        """22,4% de positivos (PLACSP + bulk + TED) supera el suelo del 5%."""
        import pandas as pd

        from scraper.ml_pipeline import validate_training_data
        from scraper.ml_training import etiquetar_dataset_sap

        df = etiquetar_dataset_sap(pd.DataFrame(self._filas(224, 776)), [])
        # No lanza: es el criterio de aceptación de S6.1.
        assert len(validate_training_data(df)) == 1000

    def test_feedback_humano_sobrescribe_la_etiqueta_base(self) -> None:
        import pandas as pd

        from scraper.ml_training import etiquetar_dataset_sap

        df = etiquetar_dataset_sap(
            pd.DataFrame(self._filas(1, 1)),
            [{"expediente": "NEG-0", "relevante": 1}, {"expediente": "POS-0", "relevante": 0}],
        )
        assert dict(zip(df["id_externo"], df["es_relevante"], strict=False)) == {
            "POS-0": 0,
            "NEG-0": 1,
        }

    def test_train_no_promociona_si_el_gate_rechaza(self) -> None:
        lecturas = self._dataset(self._filas(n_positivos=30, n_negativos=70))
        mock_clf = MagicMock()
        mock_clf.train.return_value = {"f1": 0.1}

        with (
            lecturas[0],
            lecturas[1],
            lecturas[2],
            patch("scraper.ml_classifier.SAPClassifier", return_value=mock_clf),
            patch("services.ml.promotion.promote_if_better") as mock_promote,
        ):
            mock_promote.return_value = SimpleNamespace(
                activada=False,
                version=4,
                motivos_rechazo=["recall_no_keyword 0.0000 < 0.05"],
                as_dict=lambda: {"activada": False, "version": 4},
            )
            from scraper.ml_training import train_from_db

            metrics = train_from_db()

        assert metrics["promotion"]["activada"] is False

    def test_sin_filas_no_entrena(self) -> None:
        lecturas = self._dataset([])
        mock_clf = MagicMock()

        with (
            lecturas[0],
            lecturas[1],
            lecturas[2],
            patch("scraper.ml_classifier.SAPClassifier", return_value=mock_clf),
        ):
            from scraper.ml_training import train_from_db

            result = train_from_db()

        mock_clf.save.assert_not_called()
        assert result["error"] == "insufficient_data"


class TestPrecomputeMlProba:
    @staticmethod
    def _fila(ident: str = "ext1") -> dict[str, Any]:
        return {
            "id_externo": ident,
            "titulo": "titulo",
            "descripcion": "desc",
            "cpv": "48000000",
            "importe": 1000,
            "organo_contratacion": "Organo",
        }

    @patch("scraper.ml_classifier.SAPClassifier")
    def test_no_model_available(self, mock_cls: MagicMock) -> None:
        # `resolve_artifact` y no `is_available`: el paso ya no se rinde por lo
        # que haya en disco (`data/models/` viene vacío en el runner), sino por
        # lo que devuelve el canal de artefactos.
        mock_cls.resolve_artifact.return_value = None
        from scraper.ml_training import precompute_ml_proba

        result = precompute_ml_proba()
        assert result["skipped_no_model"] is True
        assert result["updated"] == 0

    @patch("scraper.ml_pipeline._augment_text", side_effect=lambda t, **kw: t)
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_updates_rows(self, mock_cls: MagicMock, mock_aug: MagicMock) -> None:
        import numpy as np

        mock_clf = MagicMock()
        mock_cls.load.return_value = mock_clf
        mock_clf.pipeline.predict_proba.return_value = np.array([[0.2, 0.8]])

        with (
            patch(
                "db.repositories.ml_dataset.filas_pendientes_ml_proba",
                return_value=[self._fila()],
            ),
            patch("db.repositories.ml_dataset.limpiar_ml_proba_fuera_de_poblacion", return_value=0),
            patch("db.repositories.ml_dataset.guardar_ml_proba", return_value=1) as mock_guardar,
        ):
            from scraper.ml_training import precompute_ml_proba

            result = precompute_ml_proba(batch_size=10, force=True)

        assert result["updated"] == 1
        assert result["skipped_no_model"] is False
        assert mock_guardar.call_args[0][0] == [(0.8, "ext1")]

    @patch("scraper.ml_pipeline._augment_text", side_effect=lambda t, **kw: t)
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_limpia_los_scores_fuera_de_la_poblacion(
        self, mock_cls: MagicMock, mock_aug: MagicMock
    ) -> None:
        """Acotar la población sin borrar los scores heredados no cambiaría
        nada de lo que se ve: las filas de PSCP seguirían marcadas por un
        modelo que ya no las puntúa (S6.1)."""
        mock_cls.load.return_value = MagicMock()

        with (
            patch("db.repositories.ml_dataset.filas_pendientes_ml_proba", return_value=[]),
            patch(
                "db.repositories.ml_dataset.limpiar_ml_proba_fuera_de_poblacion",
                return_value=683_076,
            ) as mock_limpiar,
        ):
            from scraper.ml_training import precompute_ml_proba

            result = precompute_ml_proba()

        mock_limpiar.assert_called_once()
        assert result["limpiadas_fuera_de_poblacion"] == 683_076
        assert result["updated"] == 0

    @patch("scraper.ml_classifier.SAPClassifier")
    def test_load_fails(self, mock_cls: MagicMock) -> None:
        mock_cls.load.side_effect = RuntimeError("corrupt")

        from scraper.ml_training import precompute_ml_proba

        result = precompute_ml_proba()
        assert result["skipped_no_model"] is True
        assert result["updated"] == 0

    @patch("scraper.ml_pipeline._augment_text", side_effect=lambda t, **kw: t)
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_predict_failure_continues(self, mock_cls: MagicMock, mock_aug: MagicMock) -> None:
        mock_clf = MagicMock()
        mock_cls.load.return_value = mock_clf
        mock_clf.pipeline.predict_proba.side_effect = RuntimeError("boom")

        with (
            patch(
                "db.repositories.ml_dataset.filas_pendientes_ml_proba",
                return_value=[self._fila()],
            ),
            patch("db.repositories.ml_dataset.limpiar_ml_proba_fuera_de_poblacion", return_value=0),
            patch("db.repositories.ml_dataset.guardar_ml_proba", return_value=0),
        ):
            from scraper.ml_training import precompute_ml_proba

            result = precompute_ml_proba()

        assert result["updated"] == 0


class TestPrecomputeMlTecnologias:
    @patch("scraper.tech_classifier.TechnologyClassifier")
    def test_no_model(self, mock_cls: MagicMock) -> None:
        mock_cls.resolve_artifact.return_value = None
        from scraper.ml_training import precompute_ml_tecnologias

        result = precompute_ml_tecnologias()
        assert result["skipped_no_model"] is True

    @patch("scraper.tech_classifier.TechnologyClassifier")
    def test_load_fails(self, mock_cls: MagicMock) -> None:
        mock_cls.is_available.return_value = True
        mock_cls.load.side_effect = RuntimeError("corrupt")
        from scraper.ml_training import precompute_ml_tecnologias

        result = precompute_ml_tecnologias()
        assert result["skipped_no_model"] is True

    @patch("db.database.connect")
    @patch("scraper.tech_classifier.TechnologyClassifier")
    def test_no_rows(self, mock_cls: MagicMock, mock_connect: MagicMock) -> None:
        mock_cls.is_available.return_value = True
        mock_cls.load.return_value = MagicMock()

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scraper.ml_training import precompute_ml_tecnologias

        result = precompute_ml_tecnologias()
        assert result == {"updated": 0, "scores_inserted": 0, "skipped_no_model": False}

    @patch("db.database.connect")
    @patch("scraper.tech_classifier.TechnologyClassifier")
    def test_updates_rows_force(self, mock_cls: MagicMock, mock_connect: MagicMock) -> None:
        mock_cls.is_available.return_value = True
        mock_clf = MagicMock()
        mock_cls.load.return_value = mock_clf

        mock_clf.predict_batch.return_value = [
            {
                "predicted": ["SAP", "ORACLE"],
                "max_proba": 0.9,
                "principal": "SAP",
                "scores": {"SAP": 0.9, "ORACLE": 0.7},
                "thresholds": {"SAP": 0.5, "ORACLE": 0.5},
            }
        ]

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("ext1", "titulo", "desc", "48000000", 1000),
        ]
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scraper.ml_training import precompute_ml_tecnologias

        result = precompute_ml_tecnologias(force=True, batch_size=10)
        assert result["updated"] == 1
        assert result["scores_inserted"] == 2

    @patch("db.database.connect")
    @patch("scraper.tech_classifier.TechnologyClassifier")
    def test_predict_batch_failure(self, mock_cls: MagicMock, mock_connect: MagicMock) -> None:
        mock_cls.is_available.return_value = True
        mock_clf = MagicMock()
        mock_cls.load.return_value = mock_clf
        mock_clf.predict_batch.side_effect = RuntimeError("boom")

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("ext1", "titulo", "desc", "48000000", 1000),
        ]
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scraper.ml_training import precompute_ml_tecnologias

        result = precompute_ml_tecnologias()
        assert result["updated"] == 0
