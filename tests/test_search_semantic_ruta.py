"""O0.6a (D15) — la ruta deriva ``source`` del camino que ejecutó, sin BD.

``tests/test_search_semantic_source.py`` comprueba piezas sueltas (los pesos de
la fusión, el adaptador de hits, el acuerdo con la UI) y
``tests/test_search_semantic_hybrid.py`` ejecuta el SQL de verdad contra
pgvector, pero exige Postgres. Falta el escalón de en medio, que es justo donde
viven los criterios 2 y 4 del ítem: **ejecutar la ruta entera** y afirmar qué
``source`` sale por cada camino.

``semantic_search`` es una corrutina normal —se puede llamar sin servidor ni
middleware— y las funciones del motor se sustituyen por dobles: lo que se prueba
aquí es la DERIVACIÓN de la fuente y el viaje de ``alpha``, no el SQL.
"""

from __future__ import annotations

from typing import Any

import pytest

from api.routes.search import (
    SEARCH_SOURCES,
    SOURCE_FILTROS,
    SOURCE_FTS,
    SOURCE_LIKE,
    SOURCE_RRF,
    SemanticSearchResponse,
)


def _doc(id_externo: str, rrf: float) -> dict[str, Any]:
    """Un documento tal como lo devuelve ``hybrid_search_docs``."""
    return {
        "id_externo": id_externo,
        "titulo": f"Licitación {id_externo}",
        "organo_contratacion": "AEAT",
        "importe": 1000.0,
        "descripcion": "texto",
        "url": None,
        "fecha_publicacion": "2026-01-01",
        "ccaa": "Madrid",
        "estado": "PUB",
        "tecnologia": "SAP",
        "rrf_score": rrf,
        "chunks": [],
    }


def _hit(id_externo: str, **extra: Any) -> dict[str, Any]:
    """Un resultado tal como lo devuelve ``services.investigador.busqueda``."""
    return {
        "id_externo": id_externo,
        "titulo": f"Licitación {id_externo}",
        "organo_contratacion": "AEAT",
        "importe": 1000.0,
        "descripcion": "texto",
        "url": None,
        "fecha_publicacion": "2026-01-01",
        "fecha_limite": None,
        "ccaa": "Madrid",
        "estado": "PUB",
        "tecnologia": "SAP",
        "score": 1.0,
        "coincide_en": ["anuncio"],
        "terminos_ausentes": [],
        "titulo_tramos": [],
        "extracto": [],
        "pasaje": None,
        # Solo para /ask: la ruta no puede dejarlo salir.
        "chunks": [],
        **extra,
    }


class _MotorFalso:
    """Doble de los dos caminos que orquesta la ruta: la fusión y el texto.

    Registra el orden en que se intentan, el ``alpha`` y los filtros con los
    que se llamó a la fusión, y la consulta y el ámbito que recibió el motor de
    texto: que el deslizador y la frase entendida lleguen al motor es
    comprobable sin BD.
    """

    def __init__(
        self,
        *,
        fused: list[dict[str, Any]] | None = None,
        texto: list[dict[str, Any]] | None = None,
        fuente: str = SOURCE_FTS,
    ) -> None:
        self._fused = fused or []
        self._texto = texto or []
        self._fuente = fuente
        self.alpha_recibido: float | None = None
        self.filtros_de_la_fusion: dict[str, Any] | None = None
        self.pregunta_de_la_fusion: str | None = None
        self.consulta: Any = None
        self.ambito: Any = None
        self.llamadas: list[str] = []

    def hybrid_search(
        self,
        question: str,
        top_k: int,
        *,
        alpha: float | None = None,
        filtros: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.llamadas.append("hybrid")
        self.alpha_recibido = alpha
        self.filtros_de_la_fusion = dict(filtros or {})
        self.pregunta_de_la_fusion = question
        return list(self._fused)

    def buscar_por_texto(self, consulta: Any, ambito: Any, top_k: int, **_: Any) -> Any:
        from services.investigador.busqueda import Resultado

        self.llamadas.append("texto")
        self.consulta = consulta
        self.ambito = ambito
        return Resultado(list(self._texto)[:top_k], self._fuente)

    def instalar(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.investigador.busqueda as busqueda
        import services.investigador.search_engine as motor

        monkeypatch.setattr(motor, "hybrid_search", self.hybrid_search)
        monkeypatch.setattr(busqueda, "buscar_por_texto", self.buscar_por_texto)


def _buscar(q: str = "sap", **body: Any) -> SemanticSearchResponse:
    """Ejecuta la ruta con el motor ya sustituido y devuelve su respuesta."""
    import anyio

    from api.routes.search import SemanticSearchRequest, semantic_search

    peticion = SemanticSearchRequest(q=q, **body)
    # ``ctx`` es lo que inyectaría ``require_any_auth``; la ruta solo lee de él
    # ``user_id``, para el log.
    return anyio.run(semantic_search, peticion, {"user_id": "test"})


class TestFuenteDerivadaDelCamino:
    """Criterios 2 y 4 de O0.6a, ejecutados aquí."""

    def test_con_fusion_la_fuente_es_rrf(self, monkeypatch: pytest.MonkeyPatch) -> None:
        motor = _MotorFalso(fused=[_doc("A", 0.03)], texto=[_hit("Z")])
        motor.instalar(monkeypatch)
        resp = _buscar()
        assert resp.source == SOURCE_RRF
        assert [h.id_externo for h in resp.hits] == ["A"]
        # Y no ejecutó el camino de texto: la fuente no es una etiqueta puesta
        # encima de otro resultado.
        assert motor.llamadas == ["hybrid"]

    def test_sin_chunks_embebidos_la_fuente_es_fts_y_no_hay_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Criterio 4: sin embeddings ``hybrid_search`` devuelve ``[]``, la ruta
        sigue al texto y responde con la fuente que ese motor declare."""
        motor = _MotorFalso(fused=[], texto=[_hit("B"), _hit("C", score=0.5)])
        motor.instalar(monkeypatch)
        resp = _buscar()
        assert resp.source == SOURCE_FTS
        assert [h.id_externo for h in resp.hits] == ["B", "C"]
        assert motor.llamadas == ["hybrid", "texto"]

    def test_la_fuente_del_motor_de_texto_no_se_reetiqueta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Si el texto tuvo que degradar a subcadena, la respuesta dice ``like``."""
        motor = _MotorFalso(fused=[], texto=[_hit("D", score=0.5)], fuente=SOURCE_LIKE)
        motor.instalar(monkeypatch)
        resp = _buscar()
        assert resp.source == SOURCE_LIKE
        assert [h.id_externo for h in resp.hits] == ["D"]

    @pytest.mark.parametrize(
        "motor",
        [
            _MotorFalso(fused=[_doc("A", 0.03)]),
            _MotorFalso(texto=[_hit("B")]),
            _MotorFalso(texto=[_hit("D")], fuente=SOURCE_LIKE),
            _MotorFalso(texto=[_hit("E", score=0.0)], fuente=SOURCE_FILTROS),
            _MotorFalso(),  # ningún camino encuentra nada
        ],
        ids=["rrf", "fts", "like", "filtros", "vacio"],
    )
    def test_la_fuente_es_siempre_una_del_catalogo(
        self, motor: _MotorFalso, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        motor.instalar(monkeypatch)
        assert _buscar().source in SEARCH_SOURCES

    def test_el_top_k_del_cuerpo_recorta_la_fusion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        motor = _MotorFalso(fused=[_doc("A", 0.03), _doc("B", 0.02), _doc("C", 0.01)])
        motor.instalar(monkeypatch)
        resp = _buscar(top_k=2)
        assert [h.id_externo for h in resp.hits] == ["A", "B"]

    def test_la_fusion_normaliza_el_score_al_mejor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Lo que promete la descripción del campo para ``source=rrf``."""
        motor = _MotorFalso(fused=[_doc("A", 0.04), _doc("B", 0.02)])
        motor.instalar(monkeypatch)
        resp = _buscar()
        assert [h.score for h in resp.hits] == [1.0, 0.5]

    def test_los_campos_internos_del_motor_no_salen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``chunks`` es el fragmento entero, para que ``/ask`` lo cite; la
        lista de resultados enseña el pasaje troceado, no eso."""
        motor = _MotorFalso(texto=[_hit("B", chunks=[{"texto": "fragmento entero"}])])
        motor.instalar(monkeypatch)
        (hit,) = _buscar().hits
        assert "chunks" not in hit.model_dump()


class TestLaFraseEntendida:
    """Los filtros que dice la frase llegan al motor y vuelven en la respuesta."""

    def test_la_comunidad_de_la_frase_acota_y_se_declara(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        motor = _MotorFalso(texto=[_hit("B")])
        motor.instalar(monkeypatch)
        resp = _buscar("mantenimiento SAP en Andalucía")

        assert motor.consulta.terminos == ("mantenimiento", "sap")
        assert motor.ambito.ccaa_del_texto == ("Andalucía",)
        assert resp.interpretacion is not None
        assert resp.interpretacion.ccaa == ["Andalucía"]
        assert resp.interpretacion.texto == "mantenimiento sap"

    def test_la_fusion_recibe_el_texto_limpio_y_el_ambito(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Hasta 2026-10 la fusión buscaba sin ámbito y la ruta filtraba
        después, contra un conjunto de ids con tope."""
        motor = _MotorFalso(fused=[_doc("A", 0.03)])
        motor.instalar(monkeypatch)
        _buscar("soporte SAP en Madrid de más de 500K", tecnologia=["SAP"])

        assert motor.pregunta_de_la_fusion == "soporte sap"
        assert motor.filtros_de_la_fusion == {
            "ccaa": ["Madrid"],
            "tecnologia": ["SAP"],
            "importe_min": 500000.0,
        }

    def test_el_ambito_explicito_manda_sobre_la_frase(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Con Madrid marcado en la barra, «en Andalucía» no cambia el ámbito,
        y lo entendido no declara una comunidad que no se aplicó."""
        motor = _MotorFalso(texto=[_hit("B")])
        motor.instalar(monkeypatch)
        resp = _buscar("sap en Andalucía", ccaa=["Madrid"])

        assert motor.ambito.ccaa == ("Madrid",)
        assert motor.ambito.ccaa_del_texto == ()
        assert resp.interpretacion is not None
        assert resp.interpretacion.ccaa == []

    def test_interpretar_false_busca_el_texto_tal_cual(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        motor = _MotorFalso(texto=[_hit("B")])
        motor.instalar(monkeypatch)
        resp = _buscar("sap en Andalucía", interpretar=False)

        assert motor.ambito.vacio
        assert motor.consulta.terminos == ("sap", "andalucía")
        assert resp.interpretacion is not None
        assert resp.interpretacion.ccaa == []

    def test_una_frase_que_son_solo_filtros_no_intenta_la_fusion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sin texto no hay nada que codificar ni que fusionar."""
        motor = _MotorFalso(texto=[_hit("E", score=0.0)], fuente=SOURCE_FILTROS)
        motor.instalar(monkeypatch)
        resp = _buscar("abiertas en Madrid")

        assert motor.llamadas == ["texto"]
        assert resp.source == SOURCE_FILTROS
        assert motor.ambito.solo_abiertas is True


class TestElDeslizadorLlegaAlMotor:
    """Criterio 6: ``alpha`` deja de morir en el DTO."""

    def test_alpha_del_cuerpo_viaja_a_la_fusion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        motor = _MotorFalso(fused=[_doc("A", 0.03)])
        motor.instalar(monkeypatch)
        _buscar(alpha=0.15)
        assert motor.alpha_recibido == pytest.approx(0.15)

    def test_sin_alpha_viaja_el_default_publicado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """El default del DTO (0.70) es el que gobierna la ruta. NO se hereda
        el ``None`` del RAG: son dos consumidores con dos comportamientos."""
        motor = _MotorFalso(fused=[_doc("A", 0.03)])
        motor.instalar(monkeypatch)
        _buscar()
        assert motor.alpha_recibido == pytest.approx(0.70)


class TestDisponibilidadDeEmbeddings:
    """``document_embeddings_available`` es lo que separa «fusioné» de «llamé a
    la fusión y me devolvió el orden del FTS»."""

    @staticmethod
    def _responde(monkeypatch: pytest.MonkeyPatch, fila: object) -> bool:
        import contextlib
        from collections.abc import Iterator

        import db.database as database

        class _Conn:
            def execute(self, sql: str, params: object = None) -> _Conn:
                assert "documento_chunks" in sql
                assert "embedding IS NOT NULL" in sql
                return self

            def fetchone(self) -> object:
                return fila

        @contextlib.contextmanager
        def _fake() -> Iterator[_Conn]:
            yield _Conn()

        monkeypatch.setattr(database, "connect_read", _fake)
        from db.search_backend import document_embeddings_available

        return document_embeddings_available()

    def test_con_un_chunk_embebido_dice_que_si(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._responde(monkeypatch, (1,)) is True

    def test_con_la_tabla_vacia_dice_que_no(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._responde(monkeypatch, None) is False

    def test_si_la_bd_falla_dice_que_no(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fail-closed: sin poder mirar, lo honesto es degradar a FTS y no
        etiquetar como ``rrf`` una fusión que quizá no ocurrió."""
        import db.database as database

        def _revienta() -> object:
            raise RuntimeError("sin BD")

        monkeypatch.setattr(database, "connect_read", _revienta)
        from db.search_backend import document_embeddings_available

        assert document_embeddings_available() is False


class TestPuertasDeLaFusion:
    """``hybrid_search`` devuelve ``[]`` en cada uno de los motivos por los que
    el camino RRF no existe hoy — y por eso el llamador puede degradar."""

    @staticmethod
    def _hybrid(
        monkeypatch: pytest.MonkeyPatch,
        *,
        modelo: bool = True,
        corpus: bool = True,
        encode_revienta: bool = False,
    ) -> list[dict[str, Any]]:
        import numpy as np

        import db.search_backend as backend
        import services.embeddings as emb
        from services.investigador.search_engine import hybrid_search

        monkeypatch.setattr(emb, "embeddings_available", lambda: modelo)

        def _encode(textos: list[str], **kw: Any) -> Any:
            if encode_revienta:
                raise RuntimeError("modelo roto")
            return np.zeros((1, 384))

        monkeypatch.setattr(emb, "encode_texts", _encode)
        monkeypatch.setattr(backend, "document_embeddings_available", lambda: corpus)
        monkeypatch.setattr(
            backend,
            "hybrid_search_docs",
            lambda *a, **k: [{"id_externo": "A", "rrf_score": 0.1}],
        )
        return hybrid_search("sap", 10, alpha=0.7)

    def test_sin_modelo_no_hay_fusion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._hybrid(monkeypatch, modelo=False) == []

    def test_sin_corpus_embebido_no_hay_fusion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._hybrid(monkeypatch, corpus=False) == []

    def test_si_no_se_puede_codificar_la_consulta_no_hay_fusion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self._hybrid(monkeypatch, encode_revienta=True) == []

    def test_con_modelo_y_corpus_si_hay_fusion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._hybrid(monkeypatch) == [{"id_externo": "A", "rrf_score": 0.1}]

    def test_los_filtros_del_ambito_viajan_a_la_consulta_de_fusion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import numpy as np

        import db.search_backend as backend
        import services.embeddings as emb
        from services.investigador.search_engine import hybrid_search

        recibido: dict[str, Any] = {}

        def _fusion(*_a: Any, **kwargs: Any) -> list[dict[str, Any]]:
            recibido.update(kwargs)
            return []

        monkeypatch.setattr(emb, "embeddings_available", lambda: True)
        monkeypatch.setattr(emb, "encode_texts", lambda textos, **kw: np.zeros((1, 384)))
        monkeypatch.setattr(backend, "document_embeddings_available", lambda: True)
        monkeypatch.setattr(backend, "hybrid_search_docs", _fusion)

        hybrid_search("sap", 10, filtros={"ccaa": ["Madrid"], "solo_abiertas": True})

        assert recibido["ccaa"] == ["Madrid"]
        assert recibido["solo_abiertas"] is True


class TestEscalaDelScorePublicada:
    """ADR-014 sobre el contrato público: la descripción de ``score`` no puede
    prometer una escala que alguna de las fuentes no cumple."""

    def test_la_descripcion_distingue_la_escala_de_cada_fuente(self) -> None:
        from api.routes.search import SemanticHit

        desc = SemanticHit.model_fields["score"].description or ""
        assert all(s in desc for s in SEARCH_SOURCES), "no nombra todas las fuentes"
        # Con ``filtros`` no hubo texto que casar: prometer ahí una relevancia
        # sería inventarla.
        assert "filtros vale 0" in desc
