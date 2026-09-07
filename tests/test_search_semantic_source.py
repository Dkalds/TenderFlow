"""O0.6a (D15) — el campo ``source`` de /search/semantic no miente.

Estos tests NO necesitan Postgres: cubren la derivación de la fuente, la
ponderación de la fusión y el acuerdo entre la etiqueta que pinta el
Investigador y los valores que el backend puede devolver. Lo que sí necesita
BD (la fusión ejecutándose de verdad sobre ``documento_chunks``) vive en
``tests/test_search_semantic_hybrid.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from api.routes.search import (
    SEARCH_SOURCES,
    SOURCE_FTS,
    SOURCE_LIKE,
    SOURCE_RRF,
    SemanticSearchResponse,
    _hits_from_fused,
)
from db.search_backend import fusion_weights

_REPO_ROOT = Path(__file__).resolve().parents[1]
_INVESTIGADOR = _REPO_ROOT / "web" / "src" / "app" / "(dashboard)" / "investigador"
_SOURCE_LABEL_TS = _INVESTIGADOR / "_lib" / "source-label.ts"
_PAGE_TSX = _INVESTIGADOR / "page.tsx"


def _codigo_del_investigador() -> str:
    """Todo el código TS/TSX de la pantalla del Investigador, concatenado.

    Se mira el subárbol entero y no ``page.tsx`` a secas porque la pantalla
    está partida en ``_hooks/`` y ``_components/`` (S7.1 del plan): el
    deslizador vive hoy en ``_components/investigador-config-panel.tsx`` y el
    estado en ``_hooks/use-investigador.ts``. Lo que estos tests fijan es un
    acuerdo entre el backend y **la pantalla**, no entre el backend y un
    fichero concreto; atarlo a una ruta convertía cada troceado en un fallo
    rojo que no significaba nada.
    """
    return "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(_INVESTIGADOR.rglob("*.ts*"))
        if "__tests__" not in p.parts
    )


def _sin_comentarios(source: str) -> str:
    """Quita comentarios de bloque y de línea de un fichero TS/TSX.

    Aproximación deliberada (no es un parser): basta para distinguir lo que la
    UI *pinta* de lo que sus comentarios *explican*.
    """
    sin_bloques = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", sin_bloques, flags=re.MULTILINE)


def _ts_record_keys(source: str, const_name: str) -> set[str]:
    """Claves de un ``export const X: Record<string, string> = { ... }``.

    Se parsea con una regex y no importando TypeScript porque el test tiene
    que correr en la suite de Python: lo que se comprueba es un contrato de
    dos lados, y el lado que puede quedarse atrás es el que no tiene tests
    unitarios de tipos.
    """
    match = re.search(rf"export const {const_name}[^=]*=\s*{{(.*?)}};", source, re.DOTALL)
    assert match, f"No se encontró {const_name} en source-label.ts"
    return set(re.findall(r"^\s*([a-z_]+):", match.group(1), re.MULTILINE))


class TestEtiquetaDelInvestigador:
    """Criterio 5 de O0.6a: la etiqueta que pinta el Investigador coincide con
    ``source``. El acuerdo se verifica sobre el fichero real de la UI."""

    def test_la_ui_etiqueta_exactamente_las_fuentes_del_backend(self) -> None:
        ts = _SOURCE_LABEL_TS.read_text(encoding="utf-8")
        assert _ts_record_keys(ts, "SOURCE_LABELS") == set(SEARCH_SOURCES)

    def test_cada_fuente_tiene_explicacion(self) -> None:
        ts = _SOURCE_LABEL_TS.read_text(encoding="utf-8")
        assert _ts_record_keys(ts, "SOURCE_HINTS") == set(SEARCH_SOURCES)

    def test_el_deslizador_no_cita_motores_retirados(self) -> None:
        """FAISS (2026-07) y FTS5 de SQLite (ADR-021) están retirados; el
        deslizador seguía nombrándolos en su etiqueta visible.

        Se mira el código sin comentarios: la historia de por qué se renombró
        sí puede (y debe) citar el nombre viejo.
        """
        codigo = _sin_comentarios(_codigo_del_investigador())
        assert "FAISS" not in codigo
        assert "Peso semántico" in codigo

    def test_la_pantalla_pinta_la_fuente_de_la_respuesta(self) -> None:
        """La cadena entera: la fuente sale del cuerpo de la respuesta, se
        guarda en estado y se pinta con la etiqueta del catálogo.

        El bug que este test cierra era leer un campo `source` **por hit** que
        la API nunca ha devuelto, así que la etiqueta no aparecía nunca. Se
        comprueban los dos extremos y no el literal de la llamada intermedia:
        con la pantalla partida en `_hooks/` y `_components/`, el nombre de la
        variable que viaja entre ellos es un detalle del troceado.
        """
        codigo = _codigo_del_investigador()
        # Extremo 1: el estado se alimenta del `source` de la respuesta.
        assert "setSearchSource(data.source" in codigo
        # Extremo 2: ese estado se traduce con el catálogo compartido.
        assert "sourceLabel(" in codigo

    def test_la_pantalla_envia_alpha(self) -> None:
        assert "alpha: config.alpha" in _codigo_del_investigador()


class TestFusionWeights:
    """``alpha`` gobierna el peso de la fusión sin cambiar el RAG."""

    def test_default_reproduce_el_comportamiento_actual(self) -> None:
        """``None`` es la fusión sin ponderar: multiplicar por 1.0 es exacto,
        así que el ranking de /ask no se mueve ni un ULP."""
        assert fusion_weights(None) == (1.0, 1.0)

    def test_alpha_medio_equivale_al_default(self) -> None:
        assert fusion_weights(0.5) == (1.0, 1.0)

    def test_alpha_cero_anula_el_lado_semantico(self) -> None:
        w_fts, w_vec = fusion_weights(0.0)
        assert w_vec == 0.0
        assert w_fts > 0

    def test_alpha_uno_anula_el_lado_lexico(self) -> None:
        w_fts, w_vec = fusion_weights(1.0)
        assert w_fts == 0.0
        assert w_vec > 0

    def test_alpha_alto_pesa_mas_lo_semantico(self) -> None:
        w_fts, w_vec = fusion_weights(0.7)
        assert w_vec > w_fts

    @pytest.mark.parametrize("alpha", [-0.1, 1.1, 2.0])
    def test_alpha_fuera_de_rango_es_error(self, alpha: float) -> None:
        with pytest.raises(ValueError):
            fusion_weights(alpha)


class _FakeConn:
    """Conexión que captura SQL y parámetros sin BD (mismo patrón que
    ``tests/test_search_backend_hybrid.py``)."""

    def __init__(self) -> None:
        self.sql: str = ""
        self.params: list[object] = []

    def execute(self, sql: str, params: object = None) -> _FakeConn:
        self.sql = sql
        self.params = list(params or [])
        return self

    def fetchall(self) -> list[object]:
        return []


class TestElRagNoCambia:
    """La consulta por defecto (la del RAG) no gana ni una columna ni un
    parámetro por servir ahora también al Investigador."""

    @staticmethod
    def _sql(alpha: float | None = None) -> _FakeConn:
        from db.search_backend import PgTsBackend

        conn = _FakeConn()
        PgTsBackend().hybrid_search_docs(conn, "sap", [0.1, 0.2], alpha=alpha)
        return conn

    def test_sin_alpha_no_hay_columna_de_peso(self) -> None:
        conn = self._sql()
        assert "AS w" not in conn.sql
        assert "SUM(1.0 / (%s + rnk))" in conn.sql

    def test_sin_alpha_no_hay_parametros_de_mas(self) -> None:
        """8 parámetros: los mismos de siempre (query, query, k, vec, vec, k,
        RRF_K, limit)."""
        assert len(self._sql().params) == 8

    def test_con_alpha_la_suma_es_ponderada(self) -> None:
        conn = self._sql(alpha=0.9)
        assert "SUM(w / (%s + rnk))" in conn.sql
        assert conn.params[0] == pytest.approx(0.2)  # peso léxico
        assert conn.params[4] == pytest.approx(1.8)  # peso semántico

    def test_con_alpha_se_descartan_los_de_score_cero(self) -> None:
        """En los extremos del deslizador una lista pesa 0; sus documentos
        exclusivos no deben ocupar plazas del LIMIT."""
        assert "WHERE f.rrf_score > 0" in self._sql(alpha=0.0).sql
        assert "WHERE f.rrf_score > 0" not in self._sql().sql


class TestHitsDeLaFusion:
    """La adaptación de los docs de RRF a ``SemanticHit``."""

    @staticmethod
    def _doc(id_externo: str, rrf: float) -> dict[str, object]:
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
            "chunks": [{"chunk_id": 1, "chunk_index": 0, "texto": "..."}],
        }

    def test_score_normalizado_a_uno_en_el_mejor(self) -> None:
        hits = _hits_from_fused([self._doc("A", 0.03), self._doc("B", 0.015)], None, 10)
        assert [h["score"] for h in hits] == [1.0, 0.5]

    def test_no_arrastra_campos_internos(self) -> None:
        """``chunks`` y ``rrf_score`` son del RAG, no del contrato de esta ruta."""
        (hit,) = _hits_from_fused([self._doc("A", 0.03)], None, 10)
        assert "chunks" not in hit
        assert "rrf_score" not in hit
        assert "tecnologia" not in hit

    def test_respeta_allowed_ids_y_top_k(self) -> None:
        docs = [self._doc("A", 0.03), self._doc("B", 0.02), self._doc("C", 0.01)]
        hits = _hits_from_fused(docs, {"B", "C"}, 1)
        assert [h["id_externo"] for h in hits] == ["B"]

    def test_todos_a_cero_no_divide_por_cero(self) -> None:
        hits = _hits_from_fused([self._doc("A", 0.0)], None, 10)
        assert hits[0]["score"] == 0.0

    def test_la_respuesta_valida_con_los_hits_de_la_fusion(self) -> None:
        """Contrato: lo que produce la fusión encaja en el DTO publicado."""
        hits = _hits_from_fused([self._doc("A", 0.03)], None, 10)
        resp = SemanticSearchResponse(q="sap", top_k=10, source=SOURCE_RRF, hits=hits, elapsed_ms=1)
        assert resp.hits[0].id_externo == "A"
        assert 0.0 <= resp.hits[0].score <= 1.0


class TestCatalogoDeFuentes:
    def test_valores_en_minusculas_y_sin_duplicados(self) -> None:
        assert SEARCH_SOURCES == (SOURCE_RRF, SOURCE_FTS, SOURCE_LIKE)
        assert len(set(SEARCH_SOURCES)) == 3
        assert all(s == s.lower() for s in SEARCH_SOURCES)

    def test_openapi_describe_los_tres_valores(self) -> None:
        """El contrato público explica qué significa cada uno."""
        desc = SemanticSearchResponse.model_fields["source"].description or ""
        assert all(s in desc for s in SEARCH_SOURCES)
