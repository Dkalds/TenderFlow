"""Frontera services↔db de ``services/licitaciones.py`` (ratchet TID251, F5).

El módulo abría conexión por su cuenta en dos sitios —el retrieval híbrido de
``/ask`` y la carga full-table para índices— y era por eso una entrada del
ratchet. Ambas consultas viven ahora en ``db/`` y estos tests fijan que el
servicio solo delega, sin volver a abrir conexión.

``tests/test_search_for_ask_hybrid.py`` cubre el *gating* del flag y los
fallbacks; lo que se fija aquí es el traslado en sí.
"""

from __future__ import annotations

import ast
import pathlib
from unittest.mock import MagicMock, patch

import pandas as pd

import services.licitaciones as svc

_SERVICE_SRC = pathlib.Path(svc.__file__)


class TestNoAbreConexion:
    """El invariante del ratchet, verificado sobre el AST del propio módulo."""

    def test_no_importa_connect_ni_connect_read(self):
        tree = ast.parse(_SERVICE_SRC.read_text(encoding="utf-8"))
        importados: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("db."):
                importados.update(alias.name for alias in node.names)

        assert "connect" not in importados
        assert "connect_read" not in importados


class TestHybridSearchDelegado:
    def test_delega_en_db_search_backend_con_los_mismos_argumentos(self):
        fake_row = type("Row", (), {"tolist": lambda self: [0.1, 0.2]})()

        class _FakeArr(list):
            def __getitem__(self, idx):
                return fake_row if idx == 0 else super().__getitem__(idx)

        with (
            patch("services.embeddings.embeddings_available", return_value=True),
            patch("services.embeddings.encode_texts", return_value=_FakeArr([None])),
            patch(
                "db.search_backend.hybrid_search_docs", return_value=[{"id_externo": "X"}]
            ) as mock_hybrid,
        ):
            docs = svc._try_hybrid_search("pregunta", 5, ccaa="Madrid", tecnologia="SAP")

        assert docs == [{"id_externo": "X"}]
        args, kwargs = mock_hybrid.call_args
        assert args[0] == "pregunta"
        assert args[1] == [0.1, 0.2]
        assert kwargs == {"ccaa": "Madrid", "tecnologia": "SAP", "limit": 5}

    def test_error_de_conexion_degrada_a_none(self):
        """Si abrir la conexión falla, ``search_for_ask`` debe poder caer a FTS."""
        fake_row = type("Row", (), {"tolist": lambda self: [0.1]})()

        class _FakeArr(list):
            def __getitem__(self, idx):
                return fake_row if idx == 0 else super().__getitem__(idx)

        with (
            patch("services.embeddings.embeddings_available", return_value=True),
            patch("services.embeddings.encode_texts", return_value=_FakeArr([None])),
            patch("db.search_backend.hybrid_search_docs", side_effect=RuntimeError("pg down")),
        ):
            assert svc._try_hybrid_search("q", 5, ccaa=None, tecnologia=None) is None

    def test_resultado_vacio_degrada_a_none(self):
        fake_row = type("Row", (), {"tolist": lambda self: [0.1]})()

        class _FakeArr(list):
            def __getitem__(self, idx):
                return fake_row if idx == 0 else super().__getitem__(idx)

        with (
            patch("services.embeddings.embeddings_available", return_value=True),
            patch("services.embeddings.encode_texts", return_value=_FakeArr([None])),
            patch("db.search_backend.hybrid_search_docs", return_value=[]),
        ):
            assert svc._try_hybrid_search("q", 5, ccaa=None, tecnologia=None) is None


class TestDbSearchBackendAbreLaConexion:
    """La conexión se abre ahora dentro de ``db/`` — ahí sí está permitido."""

    def test_abre_connect_read_y_pasa_la_conexion_al_backend(self):
        from db.search_backend import hybrid_search_docs

        conn = MagicMock(name="conn")
        cm = MagicMock()
        cm.__enter__.return_value = conn

        with (
            patch("db.database.connect_read", return_value=cm) as mock_connect,
            patch("db.search_backend.PgTsBackend") as mock_backend_cls,
        ):
            mock_backend_cls.return_value.hybrid_search_docs.return_value = [{"id_externo": "Y"}]
            docs = hybrid_search_docs("q", [0.1, 0.2], ccaa="Madrid", limit=7)

        mock_connect.assert_called_once_with()
        assert docs == [{"id_externo": "Y"}]
        args, kwargs = mock_backend_cls.return_value.hybrid_search_docs.call_args
        assert args[0] is conn
        assert kwargs["ccaa"] == "Madrid"
        assert kwargs["tecnologia"] is None
        assert kwargs["limit"] == 7


class TestLoadForIndexDelegado:
    def test_delega_en_el_repository(self):
        df = pd.DataFrame({"id_externo": ["A"], "titulo": ["t"], "descripcion": ["d"]})
        with patch.object(svc._repo, "load_for_index", return_value=df) as mock_load:
            out = svc.load_licitaciones_for_index()

        mock_load.assert_called_once_with()
        assert out is df

    def test_repository_conserva_las_columnas_con_tabla_vacia(self):
        """Las columnas salen de ``cursor.description``, no de las filas."""
        from db.repositories.licitaciones import LicitacionRepository

        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.description = [("id_externo",), ("titulo",), ("descripcion",)]
        conn = MagicMock()
        conn.execute.return_value = cursor
        cm = MagicMock()
        cm.__enter__.return_value = conn

        with (
            patch("db.database.init_db"),
            patch("db.database.connect", return_value=cm),
        ):
            out = LicitacionRepository().load_for_index()

        assert list(out.columns) == ["id_externo", "titulo", "descripcion"]
        assert out.empty
