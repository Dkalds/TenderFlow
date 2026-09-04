"""Tests para scraper/ml_training.py — registro de entrenamientos y precómputo ML."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
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
    @patch("db.database.connect")
    @patch("db.database.init_db")
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_train_success_saves(
        self, mock_clf_cls: MagicMock, mock_init: MagicMock, mock_connect: MagicMock
    ) -> None:
        # train_from_db emite dos SELECT: licitaciones (con id_externo/tecnologia)
        # y ml_feedback. Se mockean por separado con side_effect.
        lic_cursor = MagicMock()
        lic_cursor.fetchall.return_value = [
            ("LIC-1", "t1", "d1", "SAP", "48000000", 1000, "2024-01-01", "SAP"),
        ]
        lic_cursor.description = [
            ("id_externo",),
            ("titulo",),
            ("descripcion",),
            ("raw_keywords",),
            ("cpv",),
            ("importe",),
            ("fecha_publicacion",),
            ("tecnologia",),
        ]
        fb_cursor = MagicMock()
        fb_cursor.fetchall.return_value = []
        fb_cursor.description = [("expediente",), ("relevante",)]
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [lic_cursor, fb_cursor]
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_clf = MagicMock()
        mock_clf.train.return_value = {"f1": 0.9}
        mock_clf_cls.return_value = mock_clf

        from scraper.ml_training import train_from_db

        # El artefacto de producción ya no se sobrescribe a ciegas: este camino
        # —el que genera el asset de la Release que sirven API y runners— pasa
        # por el mismo gate que el reentrenamiento semanal. Antes guardaba si
        # `train()` no devolvía `error`, sin gate ni versión registrada.
        with patch("services.ml.promotion.promote_if_better") as mock_promote:
            mock_promote.return_value = SimpleNamespace(
                activada=True,
                version=3,
                motivos_rechazo=[],
                as_dict=lambda: {"activada": True, "version": 3},
            )
            metrics = train_from_db()

        mock_clf.train.assert_called_once()
        mock_promote.assert_called_once()
        assert metrics["promotion"]["activada"] is True

    @patch("db.database.connect")
    @patch("db.database.init_db")
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_train_no_promociona_si_el_gate_rechaza(
        self, mock_clf_cls: MagicMock, mock_init: MagicMock, mock_connect: MagicMock
    ) -> None:
        lic_cursor = MagicMock()
        lic_cursor.fetchall.return_value = [
            ("LIC-1", "t1", "d1", "SAP", "48000000", 1000, "2024-01-01", "SAP"),
        ]
        lic_cursor.description = [
            ("id_externo",),
            ("titulo",),
            ("descripcion",),
            ("raw_keywords",),
            ("cpv",),
            ("importe",),
            ("fecha_publicacion",),
            ("tecnologia",),
        ]
        fb_cursor = MagicMock()
        fb_cursor.fetchall.return_value = []
        fb_cursor.description = [("expediente",), ("relevante",)]
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [lic_cursor, fb_cursor]
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_clf = MagicMock()
        mock_clf.train.return_value = {"f1": 0.1}
        mock_clf_cls.return_value = mock_clf

        from scraper.ml_training import train_from_db

        with patch("services.ml.promotion.promote_if_better") as mock_promote:
            mock_promote.return_value = SimpleNamespace(
                activada=False,
                version=4,
                motivos_rechazo=["recall_no_keyword 0.0000 < 0.05"],
                as_dict=lambda: {"activada": False, "version": 4},
            )
            metrics = train_from_db()

        assert metrics["promotion"]["activada"] is False

    @patch("db.database.connect")
    @patch("db.database.init_db")
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_train_error_no_save(
        self, mock_clf_cls: MagicMock, mock_init: MagicMock, mock_connect: MagicMock
    ) -> None:
        # Sin licitaciones: train recibe un DataFrame vacío, devuelve error y no
        # se guarda. Se mockean las dos queries (licitaciones + ml_feedback).
        lic_cursor = MagicMock()
        lic_cursor.fetchall.return_value = []
        lic_cursor.description = [
            ("id_externo",),
            ("titulo",),
            ("descripcion",),
            ("raw_keywords",),
            ("cpv",),
            ("importe",),
            ("fecha_publicacion",),
            ("tecnologia",),
        ]
        fb_cursor = MagicMock()
        fb_cursor.fetchall.return_value = []
        fb_cursor.description = [("expediente",), ("relevante",)]
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [lic_cursor, fb_cursor]
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_clf = MagicMock()
        mock_clf.train.return_value = {"error": "no data"}
        mock_clf_cls.return_value = mock_clf

        from scraper.ml_training import train_from_db

        result = train_from_db()
        mock_clf.save.assert_not_called()
        assert "error" in result


class TestPrecomputeMlProba:
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_no_model_available(self, mock_cls: MagicMock) -> None:
        """Sin artefacto el desenlace es ``sin_modelo``, nunca ``ok``.

        S3.1 añadió la clave ``status`` al contrato: el orquestador necesitaba
        distinguir «no había modelo» de «hecho», porque antes ambos casos
        devolvían ``updated: 0`` y el paso de la pipeline salía en verde aunque
        no se hubiera puntuado ni una fila. Se compara el dict COMPLETO a
        propósito: ``scheduler/pipeline_runs.py`` sigue leyendo
        ``skipped_no_model``, así que esa clave de compatibilidad tiene que
        seguir presente y concordar con ``status``.
        """
        mock_cls.ensure_downloaded.return_value = False
        mock_cls.is_available.return_value = False
        from scraper.ml_training import precompute_ml_proba

        result = precompute_ml_proba()
        assert result == {"status": "sin_modelo", "updated": 0, "skipped_no_model": True}

    @patch("scraper.ml_classifier.SAPClassifier")
    def test_intenta_descargar_antes_de_comprobar_disponibilidad(self, mock_cls: MagicMock) -> None:
        """``ensure_downloaded()`` va ANTES de ``is_available()`` (S3.1).

        Incidente: ``is_available()`` es un ``Path.exists()`` sobre
        ``data/models/``, que no está versionado ni entra en la imagen. El
        precómputo solo acertaba por efecto colateral de que la fase de ingesta
        previa, en el MISMO runner, ya había bajado el artefacto
        (``scraper/pipeline.py`` era el único sitio del repo que llamaba a
        ``ensure_downloaded``). El CLI, un job aislado o un contenedor nuevo
        veían «no hay modelo» con la Release llena de artefactos.

        Sin esta comprobación de orden el invariante queda invisible: al
        mockear la clase entera ``ensure_downloaded()`` devuelve un MagicMock
        veraz, así que borrar esa llamada del código de producción dejaría el
        resto de la suite en verde.
        """
        mock_cls.ensure_downloaded.return_value = True
        mock_cls.is_available.return_value = False

        from scraper.ml_training import precompute_ml_proba

        precompute_ml_proba()

        mock_cls.ensure_downloaded.assert_called_once_with()
        llamadas = [nombre for nombre, _, _ in mock_cls.mock_calls]
        assert llamadas.index("ensure_downloaded") < llamadas.index("is_available")

    @patch("db.database.connect")
    @patch("scraper.ml_pipeline._augment_text", side_effect=lambda t, **kw: t)
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_updates_rows(
        self, mock_cls: MagicMock, mock_aug: MagicMock, mock_connect: MagicMock
    ) -> None:
        mock_cls.is_available.return_value = True
        mock_clf = MagicMock()
        mock_cls.load.return_value = mock_clf

        import numpy as np

        mock_clf.pipeline.predict_proba.return_value = np.array([[0.2, 0.8]])

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("ext1", "titulo", "desc", "48000000", 1000),
        ]
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scraper.ml_training import precompute_ml_proba

        result = precompute_ml_proba(batch_size=10, force=True)
        assert result["updated"] == 1
        assert result["skipped_no_model"] is False

    @patch("db.database.connect")
    @patch("scraper.ml_pipeline._augment_text", side_effect=lambda t, **kw: t)
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_no_rows_to_update(
        self, mock_cls: MagicMock, mock_aug: MagicMock, mock_connect: MagicMock
    ) -> None:
        """Con modelo y sin filas pendientes el desenlace es ``ok``: está hecho.

        Es la mitad del contrato que S3.1 vino a separar. ``updated: 0`` ya no
        alcanza para decidir nada — aquí significa «no había nada que puntuar»,
        y el paso de la pipeline debe salir en verde; en
        ``test_no_model_available`` el mismo ``updated: 0`` significa lo
        contrario.
        """
        mock_cls.ensure_downloaded.return_value = True
        mock_cls.is_available.return_value = True
        mock_cls.load.return_value = MagicMock()

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scraper.ml_training import precompute_ml_proba

        result = precompute_ml_proba()
        assert result == {"status": "ok", "updated": 0, "skipped_no_model": False}

    @patch("db.database.connect")
    @patch("scraper.ml_pipeline._augment_text", side_effect=lambda t, **kw: t)
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_descarga_fallida_no_impide_usar_el_modelo_local(
        self, mock_cls: MagicMock, mock_aug: MagicMock, mock_connect: MagicMock
    ) -> None:
        """Que la descarga falle degrada, no aborta.

        La llamada nueva a ``ensure_downloaded()`` toca la red y un GitHub
        Release: sin ``GITHUB_TOKEN``, con la Release caída o sin salida a
        internet devuelve False. Si el ``.pkl`` ya está en el disco del runner
        —el caso normal cuando la ingesta corrió antes— el precómputo tiene que
        seguir puntuando igual. S3.1 no puede haber convertido un fallo de red
        en «no hay modelo».
        """
        mock_cls.ensure_downloaded.return_value = False
        mock_cls.is_available.return_value = True
        mock_clf = MagicMock()
        mock_cls.load.return_value = mock_clf

        import numpy as np

        mock_clf.pipeline.predict_proba.return_value = np.array([[0.2, 0.8]])

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("ext1", "titulo", "desc", "48000000", 1000),
        ]
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scraper.ml_training import precompute_ml_proba

        result = precompute_ml_proba(batch_size=10, force=True)
        assert result == {"status": "ok", "updated": 1, "skipped_no_model": False}

    @patch("scraper.ml_classifier.SAPClassifier")
    def test_load_fails(self, mock_cls: MagicMock) -> None:
        """Un modelo corrupto degrada el job; no lo tumba con una excepción.

        INVARIANTE: ``precompute_ml_proba`` es un paso de la pipeline nocturna.
        Si ``load()`` revienta (pickle truncado, descarga a medias, versión de
        scikit-learn incompatible) la función tiene que ATRAPAR el error y
        devolver el desenlace ``sin_modelo``, no propagar. La llamada se hace
        fuera de ``pytest.raises`` justamente para que una regresión que deje
        escapar la excepción rompa este test.
        """
        mock_cls.ensure_downloaded.return_value = True
        mock_cls.is_available.return_value = True
        mock_cls.load.side_effect = RuntimeError("corrupt")

        from scraper.ml_training import precompute_ml_proba

        result = precompute_ml_proba()
        assert result == {"status": "sin_modelo", "updated": 0, "skipped_no_model": True}

    @patch("db.database.connect")
    @patch("scraper.ml_pipeline._augment_text", side_effect=lambda t, **kw: t)
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_predict_failure_continues(
        self, mock_cls: MagicMock, mock_aug: MagicMock, mock_connect: MagicMock
    ) -> None:
        mock_cls.is_available.return_value = True
        mock_clf = MagicMock()
        mock_cls.load.return_value = mock_clf
        mock_clf.pipeline.predict_proba.side_effect = RuntimeError("boom")

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("ext1", "titulo", "desc", "48000000", 1000),
        ]
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scraper.ml_training import precompute_ml_proba

        result = precompute_ml_proba()
        assert result["updated"] == 0


class TestPrecomputeMlTecnologias:
    @patch("scraper.tech_classifier.TechnologyClassifier")
    def test_no_model(self, mock_cls: MagicMock) -> None:
        """Sin artefacto multi-tecnología: ``sin_modelo`` y nada tocado.

        Este es el caso que motivó S3.1: ``ML_TECH_ENABLED`` lleva en True
        desde el principio y el ``tech_classifier`` no llegó nunca a
        producción, así que cada corrida devolvía ``skipped_no_model`` mientras
        el paso salía en verde y la ausencia total del modelo era invisible
        desde fuera.
        """
        mock_cls.ensure_downloaded.return_value = False
        mock_cls.is_available.return_value = False
        from scraper.ml_training import precompute_ml_tecnologias

        result = precompute_ml_tecnologias()
        assert result["skipped_no_model"] is True
        assert result["status"] == "sin_modelo"

    @patch("scraper.tech_classifier.TechnologyClassifier")
    def test_intenta_descargar_antes_de_comprobar_disponibilidad(self, mock_cls: MagicMock) -> None:
        """Mismo orden que en ``precompute_ml_proba`` (S3.1).

        Ver el razonamiento en el test homónimo de ``TestPrecomputeMlProba``:
        con la clase mockeada entera, quitar la llamada a ``ensure_downloaded``
        no rompería ningún otro test.
        """
        mock_cls.ensure_downloaded.return_value = True
        mock_cls.is_available.return_value = False

        from scraper.ml_training import precompute_ml_tecnologias

        precompute_ml_tecnologias()

        mock_cls.ensure_downloaded.assert_called_once_with()
        llamadas = [nombre for nombre, _, _ in mock_cls.mock_calls]
        assert llamadas.index("ensure_downloaded") < llamadas.index("is_available")

    @patch("scraper.tech_classifier.TechnologyClassifier")
    def test_load_fails(self, mock_cls: MagicMock) -> None:
        """Un modelo corrupto degrada el job; no lo tumba con una excepción."""
        mock_cls.ensure_downloaded.return_value = True
        mock_cls.is_available.return_value = True
        mock_cls.load.side_effect = RuntimeError("corrupt")
        from scraper.ml_training import precompute_ml_tecnologias

        result = precompute_ml_tecnologias()
        assert result["skipped_no_model"] is True
        assert result["status"] == "sin_modelo"

    @patch("db.database.connect")
    @patch("scraper.tech_classifier.TechnologyClassifier")
    def test_no_rows(self, mock_cls: MagicMock, mock_connect: MagicMock) -> None:
        """Con modelo y sin filas pendientes: ``ok``, no ``sin_modelo``."""
        mock_cls.ensure_downloaded.return_value = True
        mock_cls.is_available.return_value = True
        mock_cls.load.return_value = MagicMock()

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scraper.ml_training import precompute_ml_tecnologias

        result = precompute_ml_tecnologias()
        assert result == {
            "status": "ok",
            "updated": 0,
            "scores_inserted": 0,
            "skipped_no_model": False,
        }

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
