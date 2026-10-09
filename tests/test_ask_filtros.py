"""Filtros de corpus de ``/ask``: el mismo contrato que ``/search/semantic``, sin BD.

El Investigador manda **un solo** objeto de filtros a sus dos modos
(``web/src/app/(dashboard)/investigador/_hooks/use-investigador.ts``): ``ccaa``
y ``tecnologia`` como listas, más ``fecha_desde``/``fecha_hasta``. La búsqueda
lo aceptaba; ``AskRequest`` declaraba ``ccaa``/``tecnologia`` como ``str |
None`` —con una CCAA o una tecnología marcadas, preguntar daba 422— y no tenía
fechas, así que el rango del chip se ignoraba en silencio.

Aquí se fija el contrato y que los cuatro filtros lleguen, iguales, a los tres
caminos del retrieval (híbrido, FTS y LIKE). Que el SQL resultante sea válido y
acote de verdad —también el lado vectorial de la fusión— lo prueban
``tests/test_search_backend_hybrid.py`` (texto) y
``tests/test_search_semantic_hybrid.py`` (Postgres).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from api.routes.ask import AskRequest, _prepare_ask_context
from api.routes.search import SemanticSearchRequest
from db.repositories.base import ambito_busqueda_sql
from db.sql_fragments import tecnologia_en_csv_sql

#: Lo que manda el Investigador con los filtros globales activos.
_FILTROS: dict[str, Any] = {
    "ccaa": ["Galicia", "Madrid"],
    "tecnologia": ["SAP"],
    "fecha_desde": "2026-01-01",
    "fecha_hasta": "2026-06-30",
}


class TestContrato:
    def test_acepta_los_filtros_que_manda_el_investigador(self):
        req = AskRequest.model_validate({"question": "soporte sap", **_FILTROS})

        assert req.ccaa == ["Galicia", "Madrid"]
        assert req.tecnologia == ["SAP"]
        assert req.fecha_desde == "2026-01-01"
        assert req.fecha_hasta == "2026-06-30"

    def test_el_mismo_cuerpo_vale_para_buscar_y_para_preguntar(self):
        """Un solo objeto de filtros para los dos modos de la pantalla."""
        busqueda = SemanticSearchRequest.model_validate({"q": "soporte sap", **_FILTROS})
        pregunta = AskRequest.model_validate({"question": "soporte sap", **_FILTROS})

        for campo in _FILTROS:
            assert getattr(pregunta, campo) == getattr(busqueda, campo), campo

    def test_sin_filtros_no_acota_nada(self):
        req = AskRequest(question="soporte sap")

        assert req.ccaa == []
        assert req.tecnologia == []
        assert req.fecha_desde is None
        assert req.fecha_hasta is None

    @pytest.mark.parametrize(
        ("bruto", "esperado"),
        [("SAP", ["SAP"]), ("SAP, ORACLE", ["SAP", "ORACLE"]), (None, [])],
    )
    def test_la_forma_anterior_del_contrato_sigue_valiendo(self, bruto, esperado):
        """El OpenAPI publicaba ``str | None``: un cliente con API key que manda
        una cadena (o ``null``) no puede empezar a recibir 422. La cadena se lee
        como CSV, la codificación multi-valor del resto de la API."""
        req = AskRequest.model_validate(
            {"question": "soporte sap", "ccaa": bruto, "tecnologia": bruto}
        )

        assert req.ccaa == esperado
        assert req.tecnologia == esperado

    def test_un_tipo_que_no_es_texto_sigue_siendo_invalido(self):
        with pytest.raises(ValidationError):
            AskRequest.model_validate({"question": "soporte sap", "tecnologia": 5})
        with pytest.raises(ValidationError):
            AskRequest.model_validate({"question": "soporte sap", "ccaa": [{"x": 1}]})


class TestLosFiltrosLleganAlRetrieval:
    def test_el_modo_general_pasa_los_cuatro_filtros(self):
        req = AskRequest.model_validate({"question": "soporte sap", **_FILTROS})

        with patch("services.licitaciones.search_for_ask", return_value=[]) as buscar:
            _prepare_ask_context(req)

        args, kwargs = buscar.call_args
        assert args == ("soporte sap", req.top_k)
        assert kwargs == {**_FILTROS, "interpretar": True}

    def test_interpretar_false_llega_al_retrieval(self):
        """«Buscar el texto tal cual» vale también para el contexto del asistente."""
        req = AskRequest.model_validate({"question": "soporte sap en Madrid", "interpretar": False})

        with patch("services.licitaciones.search_for_ask", return_value=[]) as buscar:
            _prepare_ask_context(req)

        assert buscar.call_args.kwargs["interpretar"] is False

    def test_el_hibrido_y_el_motor_de_texto_reciben_los_mismos_filtros(self, monkeypatch):
        """El que responda, acota igual."""
        from config import settings
        from services.licitaciones import search_for_ask

        monkeypatch.setattr(settings, "RAG_HYBRID_ENABLED", True, raising=False)
        with (
            patch("services.licitaciones._try_hybrid_search", return_value=None) as hibrido,
            patch("services.licitaciones._contexto_por_texto", return_value=[]) as texto,
        ):
            search_for_ask("soporte sap", 5, **_FILTROS)

        hibrido.assert_called_once_with("soporte sap", 5, **_FILTROS)
        texto.assert_called_once_with("soporte sap", 5, **_FILTROS, interpretar=True)

    def test_si_el_motor_de_texto_falla_la_red_recibe_los_mismos_filtros(self, monkeypatch):
        """El camino anterior (FTS estricto y LIKE) queda de red para cuando el
        motor de texto **falla**, y acota igual que él."""
        from config import settings
        from services.licitaciones import _repo, search_for_ask

        monkeypatch.setattr(settings, "RAG_HYBRID_ENABLED", False, raising=False)
        with (
            patch("services.licitaciones._contexto_por_texto", side_effect=RuntimeError("bd")),
            patch.object(_repo, "search_fts_docs", return_value=[]) as fts,
            patch.object(_repo, "search_like_for_ask", return_value=[]) as like,
        ):
            search_for_ask("soporte sap", 5, **_FILTROS)

        fts.assert_called_once_with("soporte sap", limit=5, **_FILTROS)
        like.assert_called_once_with("soporte sap", limit=5, **_FILTROS)

    def test_sin_resultados_no_se_cae_a_la_red(self, monkeypatch):
        """Que el motor de texto no encuentre nada no es un fallo: la pregunta
        llega al modelo sin contexto, y no con el de un LIKE sin orden."""
        from config import settings
        from services.licitaciones import _repo, search_for_ask

        monkeypatch.setattr(settings, "RAG_HYBRID_ENABLED", False, raising=False)
        with (
            patch("services.licitaciones._contexto_por_texto", return_value=[]),
            patch.object(_repo, "search_fts_docs") as fts,
            patch.object(_repo, "search_like_for_ask") as like,
        ):
            assert search_for_ask("soporte sap", 5) == []

        fts.assert_not_called()
        like.assert_not_called()

    def test_el_motor_de_texto_recibe_la_pregunta_entendida(self):
        """Los filtros que dice la pregunta acotan el contexto del asistente
        igual que la lista de resultados, y los explícitos mandan."""
        from services.investigador.busqueda import Resultado
        from services.licitaciones import _contexto_por_texto

        with patch(
            "services.investigador.busqueda.buscar_por_texto", return_value=Resultado([], "fts")
        ) as buscar:
            _contexto_por_texto(
                "soporte SAP abiertas en Andalucía", 5, ccaa=None, tecnologia="SAP, ORACLE"
            )

        consulta, ambito, top_k = buscar.call_args.args
        assert top_k == 5
        assert consulta.terminos == ("soporte", "sap")
        assert ambito.ccaa_del_texto == ("Andalucía",)
        assert ambito.tecnologia == ("SAP", "ORACLE")
        assert ambito.solo_abiertas is True

    def test_el_hibrido_pasa_los_filtros_a_la_fusion(self):
        fila = type("Row", (), {"tolist": lambda self: [0.1, 0.2]})()

        class _Matriz(list):
            def __getitem__(self, idx):
                return fila if idx == 0 else super().__getitem__(idx)

        from services.licitaciones import _try_hybrid_search

        with (
            patch("services.embeddings.embeddings_available", return_value=True),
            patch("services.embeddings.encode_texts", return_value=_Matriz([None])),
            patch("db.search_backend.hybrid_search_docs", return_value=[]) as fusion,
        ):
            _try_hybrid_search("soporte sap", 5, **_FILTROS)

        _, kwargs = fusion.call_args
        assert kwargs == {**_FILTROS, "limit": 5}


class TestAmbitoBusquedaSql:
    """Las cláusulas que comparten los tres caminos de ``/ask``."""

    def test_sin_filtros_no_anade_nada(self):
        assert ambito_busqueda_sql("l") == ([], [])

    def test_una_lista_y_un_csv_son_el_mismo_filtro(self):
        assert ambito_busqueda_sql("l", tecnologia=["SAP", "ORACLE"]) == ambito_busqueda_sql(
            "l", tecnologia="SAP, ORACLE"
        )
        assert ambito_busqueda_sql("l", ccaa=["Galicia"]) == ambito_busqueda_sql(
            "l", ccaa="Galicia"
        )

    def test_una_ccaa_es_igualdad_y_varias_un_in(self):
        assert ambito_busqueda_sql("l", ccaa=["Madrid"]) == (["l.ccaa = %s"], ["Madrid"])
        assert ambito_busqueda_sql("l", ccaa=["Galicia", "Madrid"]) == (
            ["l.ccaa IN (%s, %s)"],
            ["Galicia", "Madrid"],
        )

    def test_la_tecnologia_se_busca_en_el_csv_de_la_fila(self):
        """«ERP,SAP» también es SAP: nunca igualdad contra la columna."""
        assert ambito_busqueda_sql("l", tecnologia=["SAP", "ORACLE"]) == (
            [tecnologia_en_csv_sql("l.tecnologia", n=2)],
            ["SAP", "ORACLE"],
        )

    def test_los_valores_en_blanco_no_filtran(self):
        """Un ``""`` colado sería un filtro que no casa con nada: respuesta sin
        contexto y sin error."""
        assert ambito_busqueda_sql("l", ccaa=["", "  "], tecnologia=" , ") == ([], [])
        assert ambito_busqueda_sql("l", ccaa=[" Madrid "]) == (["l.ccaa = %s"], ["Madrid"])

    def test_las_fechas_acotan_la_publicacion(self):
        assert ambito_busqueda_sql("l", fecha_desde="2026-01-01", fecha_hasta="2026-06-30") == (
            ["l.fecha_publicacion >= %s", "l.fecha_publicacion <= %s"],
            ["2026-01-01", "2026-06-30"],
        )

    def test_una_fecha_mal_formada_se_ignora_como_en_la_busqueda(self):
        """Mismo criterio que ``ids_for_filters`` (``/search/semantic``)."""
        assert ambito_busqueda_sql("l", fecha_desde="ayer", fecha_hasta="2026-13") == ([], [])

    def test_los_parametros_siguen_el_orden_de_las_clausulas(self):
        clausulas, params = ambito_busqueda_sql(
            "l", ccaa=["Madrid"], tecnologia=["SAP"], fecha_desde="2026-01-01"
        )

        assert params == ["Madrid", "SAP", "2026-01-01"]
        assert sum(c.count("%s") for c in clausulas) == len(params)


class _Cursor:
    description: tuple[tuple[str], ...] = ()

    def fetchall(self) -> list[tuple[Any, ...]]:
        return []


class _Conexion:
    """Captura la SQL y los parámetros de la única consulta que se ejecuta."""

    def __init__(self) -> None:
        self.sql = ""
        self.params: list[Any] = []

    def execute(self, sql: str, params: list[Any]) -> _Cursor:
        self.sql = sql
        self.params = list(params)
        return _Cursor()


@pytest.fixture()
def conexion():
    conn = _Conexion()

    @contextmanager
    def _connect_read():
        yield conn

    with patch("db.repositories.licitaciones.connect_read", _connect_read):
        yield conn


class TestConsultasDelRepositorio:
    def test_el_fts_aplica_los_cuatro_filtros(self, conexion):
        from db.repositories.licitaciones import LicitacionRepository

        LicitacionRepository().search_fts_docs("soporte sap", limit=5, **_FILTROS)

        clausulas, valores = ambito_busqueda_sql("l", **_FILTROS)
        for clausula in clausulas:
            assert clausula in conexion.sql
        assert conexion.params == ["soporte sap", *valores, "soporte sap", 5]
        assert conexion.sql.count("%s") == len(conexion.params)

    def test_el_like_ya_no_ignora_la_tecnologia_ni_las_fechas(self, conexion):
        """El último recurso de ``/ask`` solo miraba la CCAA: si el FTS no
        encontraba nada, el contexto podía traer cualquier tecnología."""
        from db.repositories.licitaciones import LicitacionRepository

        LicitacionRepository().search_like_for_ask("soporte mantenimiento", limit=5, **_FILTROS)

        clausulas, valores = ambito_busqueda_sql("l", **_FILTROS)
        for clausula in clausulas:
            assert clausula in conexion.sql
        assert conexion.params[-(len(valores) + 1) :] == [*valores, 5]
        assert conexion.sql.count("%s") == len(conexion.params)
