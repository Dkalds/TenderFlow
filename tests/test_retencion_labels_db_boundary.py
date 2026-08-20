"""Caracterización de la frontera services↔db de ``services/ml/retencion_labels.py``.

Escrito ANTES de mover el SQL a ``db/`` (ratchet TID251, F5 del backlog): fija
el comportamiento de la lógica de emparejamiento **con los datos inyectados**,
para que el traslado de las dos consultas (adjudicaciones y contrato_eventos)
no pueda cambiarlo en silencio.

`tests/test_ml_retencion.py` ya cubre el camino end-to-end contra Postgres; lo
que aquí falta y ese no da es un test que corra **sin Postgres** y que fije
exactamente qué consume ``construir_pares`` de la capa de datos — que es lo
único que el traslado toca.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Any
from unittest.mock import MagicMock, patch

import services.ml.retencion_labels as rl


def _adj(
    lic_id: str,
    *,
    empresa_id: int,
    fecha_adj: str,
    fecha_fin: str | None = None,
    organo: str = "Ayuntamiento de Madrid",
    cpv: str = "72000000",
    importe: float = 100_000.0,
    adjudicado: float = 90_000.0,
) -> dict[str, Any]:
    """Fila tal y como la devuelve la consulta de adjudicaciones."""
    return {
        "licitacion_id": lic_id,
        "empresa_id": empresa_id,
        "nombre": f"Empresa {empresa_id}",
        "fecha_adjudicacion": fecha_adj,
        "importe_adjudicado": adjudicado,
        "organo": organo,
        "cpv": cpv,
        "ccaa": "Madrid",
        "importe": importe,
        "titulo": f"Servicio {lic_id}",
        "fecha_fin_efectiva": fecha_fin,
    }


def _fake_conn(rows: list[tuple[Any, ...]], cols: tuple[str, ...]) -> tuple[Any, Any]:
    """Conexión de mentira que devuelve ``rows`` con las columnas dadas."""
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    cursor.description = [(c,) for c in cols]
    conn = MagicMock()
    conn.execute.return_value = cursor
    cm = MagicMock()
    cm.__enter__.return_value = conn
    return conn, cm


class TestNoAbreConexion:
    """El invariante del ratchet TID251, sobre el AST del propio módulo."""

    def test_no_importa_connect_ni_connect_read(self):
        tree = ast.parse(pathlib.Path(rl.__file__).read_text(encoding="utf-8"))
        importados: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("db."):
                importados.update(alias.name for alias in node.names)

        assert "connect" not in importados
        assert "connect_read" not in importados


class TestSqlEnDb:
    """Las dos consultas movidas conservan lo que el etiquetado da por hecho."""

    def test_load_para_retencion_ordena_ascendente_y_excluye_duplicados(self):
        from db.repositories.adjudicaciones import AdjudicacionRepository

        conn, cm = _fake_conn([], ("licitacion_id",))
        with patch("db.repositories.adjudicaciones.connect_read", return_value=cm):
            AdjudicacionRepository().load_para_retencion()

        sql = conn.execute.call_args[0][0]
        # El orden ascendente es contractual: `previos[0]` es el primer
        # contrato de la relación órgano-empresa en las features anti-fuga.
        assert "ORDER BY a.fecha_adjudicacion ASC" in sql
        assert "licitaciones_duplicados" in sql
        assert "fecha_fin_efectiva" in sql
        assert "a.fecha_adjudicacion IS NOT NULL" in sql

    def test_contar_por_licitacion_y_tipo_agrupa_y_parametriza_los_tipos(self):
        from db.contrato_eventos import contar_por_licitacion_y_tipo

        conn, cm = _fake_conn(
            [("LIC-1", "modificacion", 2), ("LIC-1", "prorroga", 1)],
            ("licitacion_id", "tipo", "n"),
        )
        with patch("db.contrato_eventos.connect_read", return_value=cm):
            out = contar_por_licitacion_y_tipo()

        sql, params = conn.execute.call_args[0]
        assert "GROUP BY licitacion_id, tipo" in sql
        # Los tipos viajan como parámetros, no interpolados en el SQL.
        assert "modificacion" not in sql
        assert tuple(params) == ("modificacion", "prorroga")
        assert out == {"LIC-1": {"modificacion": 2, "prorroga": 1}}

    def test_licitacion_sin_eventos_no_aparece_en_el_resultado(self):
        from db.contrato_eventos import contar_por_licitacion_y_tipo

        _, cm = _fake_conn([], ("licitacion_id", "tipo", "n"))
        with patch("db.contrato_eventos.connect_read", return_value=cm):
            assert contar_por_licitacion_y_tipo() == {}


class TestSeamDeDatos:
    """``construir_pares`` se alimenta de dos —y solo dos— fuentes de datos."""

    def test_usa_las_dos_consultas_y_nada_mas(self):
        with (
            patch.object(rl, "_cargar_adjudicaciones", return_value=[]) as mock_adj,
            patch.object(rl, "_eventos_por_licitacion", return_value={}) as mock_ev,
        ):
            assert rl.construir_pares() == []

        mock_adj.assert_called_once_with()
        mock_ev.assert_called_once_with()

    def test_features_para_vencimientos_usa_las_mismas_dos_consultas(self):
        with (
            patch.object(rl, "_cargar_adjudicaciones", return_value=[]) as mock_adj,
            patch.object(rl, "_eventos_por_licitacion", return_value={}) as mock_ev,
        ):
            assert rl.features_para_vencimientos() == []

        mock_adj.assert_called_once_with()
        mock_ev.assert_called_once_with()


class TestEtiquetadoConDatosInyectados:
    def test_retencion_positiva_cuando_el_incumbente_repite(self):
        adjudicaciones = [
            _adj("LIC-1", empresa_id=7, fecha_adj="2023-01-10", fecha_fin="2024-01-10"),
            _adj("LIC-2", empresa_id=7, fecha_adj="2024-02-01"),
        ]
        with (
            patch.object(rl, "_cargar_adjudicaciones", return_value=adjudicaciones),
            patch.object(rl, "_eventos_por_licitacion", return_value={}),
        ):
            pares = rl.construir_pares()

        assert len(pares) == 1
        assert pares[0].licitacion_id == "LIC-1"
        assert pares[0].sucesor_id == "LIC-2"
        assert pares[0].label == 1

    def test_retencion_negativa_cuando_gana_otra_empresa(self):
        adjudicaciones = [
            _adj("LIC-1", empresa_id=7, fecha_adj="2023-01-10", fecha_fin="2024-01-10"),
            _adj("LIC-2", empresa_id=99, fecha_adj="2024-02-01"),
        ]
        with (
            patch.object(rl, "_cargar_adjudicaciones", return_value=adjudicaciones),
            patch.object(rl, "_eventos_por_licitacion", return_value={}),
        ):
            pares = rl.construir_pares()

        assert len(pares) == 1
        assert pares[0].label == 0

    def test_sucesor_fuera_de_ventana_no_genera_par(self):
        adjudicaciones = [
            _adj("LIC-1", empresa_id=7, fecha_adj="2023-01-10", fecha_fin="2024-01-10"),
            # +18 meses sobre el vencimiento con margen: fuera de la ventana.
            _adj("LIC-2", empresa_id=7, fecha_adj="2026-06-01"),
        ]
        with (
            patch.object(rl, "_cargar_adjudicaciones", return_value=adjudicaciones),
            patch.object(rl, "_eventos_por_licitacion", return_value={}),
        ):
            assert rl.construir_pares() == []

    def test_eventos_alimentan_las_features_de_satisfaccion(self):
        """El dict de ``contrato_eventos`` entra tal cual en las features."""
        adjudicaciones = [
            _adj("LIC-1", empresa_id=7, fecha_adj="2023-01-10", fecha_fin="2024-01-10"),
            _adj("LIC-2", empresa_id=7, fecha_adj="2024-02-01"),
        ]
        eventos = {"LIC-1": {"modificacion": 2, "prorroga": 1}}
        with (
            patch.object(rl, "_cargar_adjudicaciones", return_value=adjudicaciones),
            patch.object(rl, "_eventos_por_licitacion", return_value=eventos),
        ):
            pares = rl.construir_pares()

        assert pares[0].features["n_modificaciones"] == 2.0
        assert pares[0].features["n_prorrogas"] == 1.0

    def test_baja_original_se_calcula_sobre_importe_e_importe_adjudicado(self):
        adjudicaciones = [
            _adj(
                "LIC-1",
                empresa_id=7,
                fecha_adj="2023-01-10",
                fecha_fin="2024-01-10",
                importe=100_000.0,
                adjudicado=80_000.0,
            ),
            _adj("LIC-2", empresa_id=7, fecha_adj="2024-02-01"),
        ]
        with (
            patch.object(rl, "_cargar_adjudicaciones", return_value=adjudicaciones),
            patch.object(rl, "_eventos_por_licitacion", return_value={}),
        ):
            pares = rl.construir_pares()

        assert pares[0].features["baja_original"] == 0.2

    def test_muestra_auditoria_proyecta_los_pares(self):
        adjudicaciones = [
            _adj("LIC-1", empresa_id=7, fecha_adj="2023-01-10", fecha_fin="2024-01-10"),
            _adj("LIC-2", empresa_id=7, fecha_adj="2024-02-01"),
        ]
        with (
            patch.object(rl, "_cargar_adjudicaciones", return_value=adjudicaciones),
            patch.object(rl, "_eventos_por_licitacion", return_value={}),
        ):
            muestra = rl.muestra_auditoria(10)

        assert muestra == [
            {
                "original": "LIC-1",
                "titulo_original": "Servicio LIC-1",
                "empresa_original": "Empresa 7",
                "sucesor": "LIC-2",
                "titulo_sucesor": "Servicio LIC-2",
                "empresa_sucesora": "Empresa 7",
                "fecha_fin": "2024-01-10",
                "fecha_sucesor": "2024-02-01",
                "label": 1,
            }
        ]
