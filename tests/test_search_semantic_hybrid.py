"""O0.6a (D15) — /search/semantic sirve la fusión RRF que ya existía.

Tests de INTEGRACIÓN: exigen Postgres con pgvector (fixtures ``api_db`` /
``api_key``). Cubren lo que solo se puede afirmar ejecutando el SQL:

* con ``documento_chunks`` vacío el endpoint responde ``source=fts`` sin error;
* con chunks embebidos responde ``source=rrf``;
* ``alpha`` gobierna de verdad el peso de las dos listas de la fusión;
* el default de ``hybrid_search_docs`` (``alpha=None``) sigue produciendo el
  RRF sin ponderar que consume el RAG.

El modelo de embeddings se simula (``encode_texts``): lo que se prueba es la
fusión, no la calidad del modelo, y la suite no puede depender de que el extra
``[ml]`` esté instalado.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

_DIM = 384  # vector(384) en la migración v56


def _vec(pos: int) -> list[float]:
    """Vector unitario en el eje ``pos`` — distancia coseno 0 consigo mismo y
    1 con cualquier otro eje, que es todo lo que este test necesita ordenar."""
    v = [0.0] * _DIM
    v[pos] = 1.0
    return v


@pytest.fixture()
def search_client(api_db, api_key):
    from api.app import app

    c = TestClient(app, raise_server_exceptions=False)
    c.headers.update({"X-API-Key": api_key})
    return c


@pytest.fixture()
def embeddings_simulados(monkeypatch):
    """El modelo dice estar disponible y codifica cualquier consulta al eje 0."""
    import services.embeddings as emb

    monkeypatch.setattr(emb, "embeddings_available", lambda: True)
    monkeypatch.setattr(emb, "encode_texts", lambda texts, **kw: np.array([_vec(0)]))


def _seed_licitaciones() -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [
            # Casa por FTS con "sap"; no tiene pliego indexado.
            Licitacion(
                id_externo="L-FTS",
                titulo="Servicios SAP para la sede",
                descripcion="Mantenimiento SAP",
                ccaa="Madrid",
            ),
            # NO casa por FTS con "sap": solo llega por el lado vectorial.
            Licitacion(
                id_externo="L-VEC",
                titulo="Gestión documental corporativa",
                descripcion="Digitalización de archivo",
                ccaa="Madrid",
            ),
        ]
    )


def _seed_chunk(licitacion_id: str, embedding: list[float]) -> None:
    """Un documento extraído con un chunk embebido (SQL directo: es un fixture
    de datos, no código de producción — ``tests/*`` está fuera del TID251)."""
    from db.database import connect

    with connect() as c:
        row = c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri, status, texto) "
            "VALUES (%s, 'technical', %s, 'extracted', 'texto del pliego') "
            "RETURNING id",
            (licitacion_id, f"https://example.com/{licitacion_id}.pdf"),
        ).fetchone()
        documento_id = int(row[0])
        c.execute(
            "INSERT INTO documento_chunks (documento_id, chunk_index, texto, embedding) "
            "VALUES (%s, 0, 'fragmento del pliego', %s::vector)",
            (documento_id, "[" + ",".join(repr(x) for x in embedding) + "]"),
        )


def _buscar(client: TestClient, **body: Any) -> dict[str, Any]:
    resp = client.post("/api/v1/search/semantic", json={"q": "sap", **body})
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


class TestFuenteDerivadaDelCaminoEjecutado:
    def test_sin_chunks_responde_fts_sin_error(self, search_client, embeddings_simulados):
        """Criterio 4 de O0.6a: ``documento_chunks`` vacío → ``source=fts``.

        Con modelo de embeddings disponible pero sin nada que fusionar, llamar
        a esto «híbrido» sería declarar la fuente por configuración.
        """
        _seed_licitaciones()
        data = _buscar(search_client)
        assert data["source"] == "fts"
        assert [h["id_externo"] for h in data["hits"]] == ["L-FTS"]

    def test_sin_modelo_de_embeddings_responde_fts(self, search_client, monkeypatch):
        """Aunque haya chunks: sin modelo no hay vector de consulta."""
        import services.embeddings as emb

        monkeypatch.setattr(emb, "embeddings_available", lambda: False)
        _seed_licitaciones()
        _seed_chunk("L-VEC", _vec(0))
        assert _buscar(search_client)["source"] == "fts"

    def test_con_chunks_embebidos_responde_rrf(self, search_client, embeddings_simulados):
        _seed_licitaciones()
        _seed_chunk("L-VEC", _vec(0))
        data = _buscar(search_client)
        assert data["source"] == "rrf"
        ids = {h["id_externo"] for h in data["hits"]}
        assert ids == {"L-FTS", "L-VEC"}  # una lista aporta cada uno

    def test_sin_coincidencias_fts_cae_a_like(self, search_client, monkeypatch):
        """Sin fusión y con el FTS vacío, la fuente es ``like``."""
        import services.embeddings as emb

        monkeypatch.setattr(emb, "embeddings_available", lambda: False)
        _seed_licitaciones()
        monkeypatch.setattr("services.investigador.search_engine.fts5_search", lambda q, k: [])
        resp = search_client.post("/api/v1/search/semantic", json={"q": "documental"})
        assert resp.status_code == 200
        assert resp.json()["source"] == "like"

    def test_score_normalizado_en_la_fusion(self, search_client, embeddings_simulados):
        _seed_licitaciones()
        _seed_chunk("L-VEC", _vec(0))
        hits = _buscar(search_client)["hits"]
        assert max(h["score"] for h in hits) == pytest.approx(1.0)
        assert all(0.0 <= h["score"] <= 1.0 for h in hits)


class TestAlphaGobiernaLaFusion:
    """El deslizador del Investigador deja de ser decorativo."""

    def test_alpha_uno_deja_solo_el_lado_semantico(self, search_client, embeddings_simulados):
        _seed_licitaciones()
        _seed_chunk("L-VEC", _vec(0))
        data = _buscar(search_client, alpha=1.0)
        assert data["source"] == "rrf"
        # L-FTS solo aparece en la lista léxica, que pesa cero.
        assert [h["id_externo"] for h in data["hits"]] == ["L-VEC"]

    def test_alpha_cero_deja_solo_el_lado_lexico(self, search_client, embeddings_simulados):
        _seed_licitaciones()
        _seed_chunk("L-VEC", _vec(0))
        data = _buscar(search_client, alpha=0.0)
        assert data["source"] == "rrf"
        assert [h["id_externo"] for h in data["hits"]] == ["L-FTS"]

    def test_alpha_alto_ordena_antes_lo_semantico(self, search_client, embeddings_simulados):
        _seed_licitaciones()
        _seed_chunk("L-VEC", _vec(0))
        alto = _buscar(search_client, alpha=0.9)["hits"]
        bajo = _buscar(search_client, alpha=0.1)["hits"]
        assert alto[0]["id_externo"] == "L-VEC"
        assert bajo[0]["id_externo"] == "L-FTS"


class TestDefaultDelRag:
    """El RAG (services/licitaciones.py) llama sin ``alpha``: ese camino no
    puede cambiar de resultado por servir ahora también al Investigador."""

    def test_sin_alpha_los_pesos_son_los_de_siempre(self, api_db):
        from db.database import connect_read
        from db.search_backend import RRF_K, PgTsBackend

        _seed_licitaciones()
        _seed_chunk("L-VEC", _vec(0))

        with connect_read() as conn:
            docs = PgTsBackend().hybrid_search_docs(conn, "sap", _vec(0), limit=10)

        por_id = {d["id_externo"]: float(d["rrf_score"]) for d in docs}
        # Cada uno es primero en su única lista: 1/(k+1) sin ponderar.
        esperado = 1.0 / (RRF_K + 1)
        assert por_id["L-FTS"] == pytest.approx(esperado)
        assert por_id["L-VEC"] == pytest.approx(esperado)

    def test_alpha_medio_coincide_con_el_default(self, api_db):
        from db.database import connect_read
        from db.search_backend import PgTsBackend

        _seed_licitaciones()
        _seed_chunk("L-VEC", _vec(0))

        backend = PgTsBackend()
        with connect_read() as conn:
            default = backend.hybrid_search_docs(conn, "sap", _vec(0), limit=10)
            medio = backend.hybrid_search_docs(conn, "sap", _vec(0), limit=10, alpha=0.5)

        # El orden se compara exacto; los scores con tolerancia porque las dos
        # consultas no tienen el mismo TIPO en Postgres: sin ponderar la suma
        # es ``SUM(1.0/(k+rnk))`` (literal ``numeric``) y ponderada es
        # ``SUM(w/(k+rnk))`` con ``w`` en ``float8``. El valor es el mismo, la
        # aritmética que lo produce no, y exigir igualdad bit a bit entre
        # numeric y double sería un test frágil que no defiende nada.
        assert [d["id_externo"] for d in default] == [d["id_externo"] for d in medio]
        for d, m in zip(default, medio, strict=True):
            assert float(m["rrf_score"]) == pytest.approx(float(d["rrf_score"]))

    def test_los_chunks_siguen_viajando_para_las_citas(self, api_db):
        """``chunks`` es lo que /ask cita; la ruta de búsqueda no lo usa, pero
        el contrato del backend no cambia."""
        from db.database import connect_read
        from db.search_backend import PgTsBackend

        _seed_licitaciones()
        _seed_chunk("L-VEC", _vec(0))

        with connect_read() as conn:
            docs = PgTsBackend().hybrid_search_docs(conn, "sap", _vec(0), limit=10)

        por_id = {d["id_externo"]: d for d in docs}
        assert por_id["L-VEC"]["chunks"], "la licitación con pliego trae sus fragmentos"
        assert por_id["L-FTS"]["chunks"] == []


class TestFiltrosSobreLaFusion:
    def test_los_filtros_globales_acotan_tambien_el_rrf(self, search_client, embeddings_simulados):
        """El filtrado sigue siendo del backend (allowed_ids), también cuando
        los resultados vienen de la fusión."""
        from db.upsert import Licitacion, upsert_licitaciones

        _seed_licitaciones()
        upsert_licitaciones(
            [Licitacion(id_externo="L-OTRA", titulo="SAP en Galicia", ccaa="Galicia")]
        )
        _seed_chunk("L-VEC", _vec(0))

        data = _buscar(search_client, ccaa=["Galicia"])
        assert data["source"] == "rrf"
        assert [h["id_externo"] for h in data["hits"]] == ["L-OTRA"]
