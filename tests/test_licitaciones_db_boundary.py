"""Frontera services↔db de ``services/licitaciones.py`` (ratchet TID251, F5).

El módulo abría conexión por su cuenta en dos sitios —el retrieval híbrido de
``/ask`` y la carga full-table para índices— y era por eso una entrada del
ratchet. Ambas consultas viven ahora en ``db/`` (el retrieval de ``/ask`` es
desde 2026-11 la búsqueda del Investigador) y estos tests fijan que el
servicio no vuelve a abrir conexión.
"""

from __future__ import annotations

import ast
import pathlib
from unittest.mock import MagicMock, patch

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
