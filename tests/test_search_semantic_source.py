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
    SOURCE_FILTROS,
    SOURCE_FTS,
    SOURCE_LIKE,
    SOURCE_RRF,
    SemanticSearchResponse,
)
from db.search_backend import fusion_weights
from services.investigador.busqueda import Resultado, combinar

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

        Después se llamó «Peso semántico» con su cifra, que seguía siendo el
        nombre del motor y no el de quien busca: hoy es «Tipo de coincidencia»,
        entre «Palabras exactas» y «Por significado» (y sigue mandando
        ``alpha``, ver ``test_la_pantalla_envia_alpha``).

        Se mira el código sin comentarios: la historia de por qué se renombró
        sí puede (y debe) citar el nombre viejo.
        """
        codigo = _sin_comentarios(_codigo_del_investigador())
        assert "FAISS" not in codigo
        assert "Tipo de coincidencia" in codigo

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
        # Extremo 1: la fuente se lee del `source` de la respuesta (desde
        # 2026-10 la búsqueda es una consulta de React Query, no estado local).
        assert "busqueda.data?.source" in codigo
        # Extremo 2: esa fuente se traduce con el catálogo compartido.
        assert "sourceLabel(" in codigo

    def test_la_pantalla_envia_alpha(self) -> None:
        assert "alpha: config.alpha" in _codigo_del_investigador()

    def test_el_deslizador_solo_se_ofrece_si_la_respuesta_combino(self) -> None:
        """«Tipo de coincidencia» gobierna ``alpha``, y ``alpha`` solo interviene
        con ``source=rrf``. Medido contra producción el 2026-10-09: la imagen de
        la API no trae el modelo con que codificar la consulta, la búsqueda
        respondía siempre ``fts`` o ``like`` y el deslizador llevaba ahí sin
        mover nada. Ahora la pantalla lo enseña cuando una respuesta ha llegado
        por la fusión, y no antes.
        """
        codigo = _sin_comentarios(_codigo_del_investigador())
        # La fuente con la que se compara es la de la fusión…
        assert f'FUENTE_CON_SIGNIFICADO = "{SOURCE_RRF}"' in codigo
        assert "searchSource === FUENTE_CON_SIGNIFICADO" in codigo
        # …y el control está detrás de esa condición.
        assert "{fusionDisponible && (" in codigo


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


class TestCombinarTextoYFusion:
    """La fusión completa la lista del texto; ya no la sustituye.

    Hasta 2026-10 una instalación con embeddings respondía solo con la fusión
    y perdía dónde casa cada resultado, el pasaje del pliego y el plazo.
    """

    @staticmethod
    def _doc(id_externo: str, rrf: float, texto: str = "fragmento del pliego") -> dict[str, object]:
        return {
            "id_externo": id_externo,
            "titulo": f"Licitación {id_externo}",
            "rrf_score": rrf,
            "chunks": [{"chunk_id": 1, "chunk_index": 0, "texto": texto}],
        }

    @staticmethod
    def _hit(id_externo: str, *, ausentes: tuple[str, ...] = ()) -> dict[str, object]:
        return {
            "id_externo": id_externo,
            "titulo": f"Licitación {id_externo}",
            "fecha_limite": "2026-11-30T14:00:00",
            "coincide_en": ["anuncio"],
            "terminos_ausentes": list(ausentes),
            "score": 0.5 if ausentes else 1.0,
            "pasaje": None,
        }

    @staticmethod
    def _filas(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
        """``anuncios_por_id`` sin BD: la fila completa, con su plazo."""
        import services.investigador.busqueda as busqueda

        pedidas: list[list[str]] = []

        def _por_id(ids: list[str]) -> dict[str, dict[str, object]]:
            pedidas.append(list(ids))
            return {
                i: {"id_externo": i, "titulo": f"Licitación {i}", "fecha_limite": "2026-12-01"}
                for i in ids
            }

        monkeypatch.setattr(busqueda.repo, "anuncios_por_id", _por_id)
        return pedidas

    def _combinar(
        self, texto: list[dict[str, object]], fusion: list[dict[str, object]], fuente: str = "fts"
    ) -> Resultado:
        return combinar(Resultado(texto, fuente), fusion, 10)

    def test_sin_fusion_la_lista_del_texto_queda_igual(self) -> None:
        original = Resultado([self._hit("A")], SOURCE_FTS)
        assert combinar(original, [], 10) is original

    def test_lo_nuevo_va_entre_lo_completo_y_lo_parcial(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._filas(monkeypatch)
        res = self._combinar(
            [self._hit("A"), self._hit("P", ausentes=("sap",))],
            [self._doc("N", 0.03)],
        )
        assert [h["id_externo"] for h in res.hits] == ["A", "N", "P"]
        assert res.fuente == SOURCE_RRF

    def test_lo_que_solo_trae_la_fusion_dice_por_que_y_trae_su_plazo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._filas(monkeypatch)
        (hit,) = self._combinar([], [self._doc("N", 0.03, "  mantenimiento\n del ERP  ")]).hits
        assert hit["coincide_en"] == ["significado"]
        assert hit["fecha_limite"] == "2026-12-01"
        assert hit["pasaje"]["tramos"] == [{"texto": "mantenimiento del ERP", "resaltado": False}]
        assert "rrf_score" not in hit and hit["chunks"] == []

    def test_lo_que_casa_por_texto_y_por_significado_lo_dice_sin_moverse(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pedidas = self._filas(monkeypatch)
        res = self._combinar([self._hit("A"), self._hit("B")], [self._doc("B", 0.03)])
        assert [h["id_externo"] for h in res.hits] == ["A", "B"]
        assert res.hits[1]["coincide_en"] == ["anuncio", "significado"]
        assert res.hits[1]["fecha_limite"] == "2026-11-30T14:00:00"
        assert pedidas == []  # nada nuevo que leer de la BD
        assert res.fuente == SOURCE_RRF

    def test_el_score_de_lo_nuevo_se_escala_al_mejor_de_la_fusion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._filas(monkeypatch)
        res = self._combinar([], [self._doc("A", 0.04), self._doc("B", 0.02)])
        assert [h["score"] for h in res.hits] == [1.0, 0.5]

    def test_lo_que_la_fusion_trajo_solo_por_su_lado_lexico_no_es_significado(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sin fragmento no vino de la lista vectorial: lo léxico lo ordena el
        motor de texto, y llamarlo «parecido» sería mentir."""
        pedidas = self._filas(monkeypatch)
        lexico = {"id_externo": "X", "rrf_score": 0.03, "chunks": []}
        original = Resultado([self._hit("A")], SOURCE_FTS)
        assert combinar(original, [lexico, {**lexico, "id_externo": "A"}], 10) is original
        assert pedidas == []

    def test_todos_a_cero_no_divide_por_cero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._filas(monkeypatch)
        res = self._combinar([], [self._doc("A", 0.0)])
        assert res.hits[0]["score"] == 0.0

    def test_con_subcadena_lo_parecido_va_delante(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Una coincidencia por subcadena es más débil que un parecido."""
        self._filas(monkeypatch)
        res = self._combinar([self._hit("L")], [self._doc("N", 0.03)], fuente=SOURCE_LIKE)
        assert [h["id_externo"] for h in res.hits] == ["N", "L"]

    def test_un_id_que_ya_no_existe_no_se_inventa(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.investigador.busqueda as busqueda

        monkeypatch.setattr(busqueda.repo, "anuncios_por_id", lambda ids: {})
        res = self._combinar([self._hit("A")], [self._doc("X", 0.03)])
        assert [h["id_externo"] for h in res.hits] == ["A"]
        assert res.fuente == SOURCE_FTS

    def test_la_respuesta_valida_con_lo_que_trae_la_fusion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Contrato: un resultado por significado encaja en el DTO publicado."""
        import services.investigador.busqueda as busqueda
        from api.routes.search import Interpretacion
        from services.investigador.consulta import interpretar

        monkeypatch.setattr(
            busqueda.repo,
            "anuncios_por_id",
            lambda ids: {
                i: {
                    "id_externo": i,
                    "titulo": "T",
                    "organo_contratacion": None,
                    "importe": None,
                    "descripcion": None,
                    "url": None,
                    "fecha_publicacion": None,
                    "fecha_limite": None,
                    "ccaa": None,
                    "estado": None,
                    "tecnologia": None,
                }
                for i in ids
            },
        )
        hits = combinar(Resultado([], SOURCE_FTS), [self._doc("A", 0.03)], 10).hits
        resp = SemanticSearchResponse(
            q="sap",
            top_k=10,
            source=SOURCE_RRF,
            hits=hits,
            elapsed_ms=1,
            interpretacion=Interpretacion.de(interpretar("sap")),
        )
        assert resp.hits[0].coincide_en == ["significado"]
        assert resp.hits[0].pasaje is not None
        assert 0.0 <= resp.hits[0].score <= 1.0


class TestCatalogoDeFuentes:
    def test_valores_en_minusculas_y_sin_duplicados(self) -> None:
        assert SEARCH_SOURCES == (SOURCE_RRF, SOURCE_FTS, SOURCE_LIKE, SOURCE_FILTROS)
        assert len(set(SEARCH_SOURCES)) == 4
        assert all(s == s.lower() for s in SEARCH_SOURCES)

    def test_openapi_describe_todos_los_valores(self) -> None:
        """El contrato público explica qué significa cada uno."""
        desc = SemanticSearchResponse.model_fields["source"].description or ""
        assert all(s in desc for s in SEARCH_SOURCES)
