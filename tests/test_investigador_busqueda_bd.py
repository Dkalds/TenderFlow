"""El motor de texto del Investigador, ejecutado contra Postgres.

``tests/test_investigador_busqueda.py`` fija la orquestación con el repositorio
sustituido; aquí corre el SQL de ``db/repositories/investigador.py`` de verdad,
que es donde vivían los fallos medidos el 2026-10-09 contra producción:

- una pregunta normal no casaba con nada (todas las palabras a la vez) y caía a
  un ``ILIKE`` del primer token de la consulta cruda;
- el ámbito se aplicaba después, contra un conjunto de ids con tope;
- la búsqueda miraba el anuncio y nunca el pliego.

Requiere Postgres (fixture ``tmp_db``): ``search_vector`` es una columna
generada con el diccionario español y no tiene equivalente fuera.
"""

from __future__ import annotations

from typing import Any

import pytest

from services.investigador.busqueda import (
    FUENTE_FILTROS,
    FUENTE_LITERAL,
    FUENTE_TEXTO,
    Resultado,
    buscar_por_texto,
    preparar,
)


def _sembrar(*filas: dict[str, Any]) -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones([Licitacion(**fila) for fila in filas])


def _sembrar_pasaje(licitacion_id: str, texto: str, *, pagina: int = 3) -> int:
    """Un pliego extraído con un fragmento (SQL directo: es un fixture de datos,
    no código de producción — ``tests/*`` está fuera del TID251)."""
    from db.database import connect

    with connect() as c:
        fila = c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri, filename, status, texto) "
            "VALUES (%s, 'legal', %s, 'PCAP.pdf', 'extracted', %s) RETURNING id",
            (licitacion_id, f"https://example.com/{licitacion_id}.pdf", texto),
        ).fetchone()
        documento_id = int(fila[0])
        c.execute(
            "INSERT INTO documento_chunks (documento_id, chunk_index, texto, page_number) "
            "VALUES (%s, 0, %s, %s)",
            (documento_id, texto, pagina),
        )
    return documento_id


def _buscar(q: str, top_k: int = 10, **filtros: Any) -> Resultado:
    consulta, ambito = preparar(q, **filtros)
    return buscar_por_texto(consulta, ambito, top_k)


def _ids(resultado: Resultado) -> list[str]:
    return [str(h["id_externo"]) for h in resultado.hits]


@pytest.fixture()
def corpus(tmp_db):
    _sembrar(
        {
            "id_externo": "A-COMPLETO",
            "titulo": "Mantenimiento de licencias SAP",
            "descripcion": "Renovación y mantenimiento de las licencias SAP del organismo.",
            "ccaa": "Andalucía",
            "estado": "PUB",
            "importe": 800_000.0,
            "fecha_publicacion": "2026-03-10",
        },
        {
            "id_externo": "B-ASCENSORES",
            "titulo": "Mantenimiento de ascensores",
            "descripcion": "Servicio de mantenimiento de los ascensores de la sede.",
            "ccaa": "Madrid",
            "estado": "ADJ",
            "importe": 40_000.0,
            "fecha_publicacion": "2025-06-01",
        },
        {
            "id_externo": "C-ORACLE",
            "titulo": "Licencias de base de datos Oracle",
            "descripcion": "Suministro de licencias Oracle Database.",
            "ccaa": "Madrid",
            "estado": "PUB",
            "importe": 300_000.0,
            "fecha_publicacion": "2026-05-20",
        },
        {
            "id_externo": "D-XUNTA",
            "titulo": "Soporte SAP para la Xunta de Galicia",
            "descripcion": "Soporte funcional SAP.",
            # Sin comunidad informada: la nombra el texto.
            "estado": "PUB",
            "fecha_publicacion": "2026-01-15",
        },
        {
            "id_externo": "E-LIMPIEZA",
            "titulo": "Servicio de limpieza de edificios",
            "descripcion": "Limpieza de oficinas.",
            "ccaa": "Madrid",
            "estado": "PUB",
            "fecha_publicacion": "2026-06-01",
        },
    )


class TestCasaConAlgunoYOrdenaPorLoQueCasa:
    def test_el_que_casa_con_todos_va_primero_y_el_resto_dice_que_le_falta(self, corpus):
        resultado = _buscar("mantenimiento sap")

        assert resultado.fuente == FUENTE_TEXTO
        ids = _ids(resultado)
        assert ids[0] == "A-COMPLETO"
        assert set(ids) == {"A-COMPLETO", "B-ASCENSORES", "D-XUNTA"}
        por_id = {h["id_externo"]: h for h in resultado.hits}
        assert por_id["A-COMPLETO"]["terminos_ausentes"] == []
        assert por_id["A-COMPLETO"]["score"] == 1.0
        assert por_id["B-ASCENSORES"]["terminos_ausentes"] == ["sap"]
        assert por_id["D-XUNTA"]["terminos_ausentes"] == ["mantenimiento"]
        assert por_id["B-ASCENSORES"]["score"] == 0.5

    def test_una_pregunta_hablada_encuentra_lo_que_nombra(self, corpus):
        """La búsqueda real del 2026-10-04 que devolvió cero resultados."""
        resultado = _buscar("Puedes mirar licitaciones relacionadas con licencia")

        assert resultado.fuente == FUENTE_TEXTO
        assert set(_ids(resultado)) == {"A-COMPLETO", "C-ORACLE"}

    def test_dos_formas_de_la_misma_palabra_cuentan_como_una(self, corpus):
        """«licencia» y «licencias» son el mismo lexema: no hay un término que
        falte por haberlo escrito dos veces."""
        resultado = _buscar("licencia licencias")

        assert all(h["terminos_ausentes"] == [] for h in resultado.hits)
        assert all(h["score"] == 1.0 for h in resultado.hits)

    def test_el_titulo_y_el_extracto_marcan_lo_que_casa(self, corpus):
        (hit,) = (h for h in _buscar("licencias sap").hits if h["id_externo"] == "A-COMPLETO")

        resaltado = {t["texto"].lower() for t in hit["titulo_tramos"] if t["resaltado"]}
        assert resaltado == {"licencias", "sap"}
        assert "".join(t["texto"] for t in hit["titulo_tramos"]) == hit["titulo"]
        assert any(t["resaltado"] for t in hit["extracto"])

    def test_el_orden_es_estable(self, corpus):
        assert _ids(_buscar("mantenimiento sap")) == _ids(_buscar("mantenimiento sap"))

    def test_top_k_recorta(self, corpus):
        assert len(_buscar("mantenimiento sap licencias", top_k=2).hits) == 2


class TestElAmbitoVaEnLaConsulta:
    def test_la_comunidad_explicita_acota(self, corpus):
        assert set(_ids(_buscar("mantenimiento", ccaa=["Madrid"]))) == {"B-ASCENSORES"}

    def test_la_comunidad_de_la_frase_acota(self, corpus):
        resultado = _buscar("mantenimiento SAP en Andalucía")

        assert _ids(resultado) == ["A-COMPLETO"]

    def test_la_comunidad_de_la_frase_no_esconde_la_fila_sin_comunidad_que_la_nombra(self, corpus):
        """«en Galicia» sobre un expediente de la Xunta al que le falta la columna."""
        assert _ids(_buscar("soporte SAP en Galicia")) == ["D-XUNTA"]

    def test_la_comunidad_explicita_si_es_estricta(self, corpus):
        """La de la barra de ámbito no hace excepciones: es un filtro declarado."""
        assert _ids(_buscar("soporte SAP", ccaa=["Galicia"])) == []

    def test_importe_de_la_frase(self, corpus):
        assert _ids(_buscar("licencias de más de 500K")) == ["A-COMPLETO"]
        assert _ids(_buscar("licencias de menos de 500.000 €")) == ["C-ORACLE"]

    def test_abiertas_descarta_las_adjudicadas(self, corpus):
        assert "B-ASCENSORES" in _ids(_buscar("mantenimiento"))
        assert "B-ASCENSORES" not in _ids(_buscar("mantenimiento abiertas"))

    def test_fechas_de_la_frase(self, corpus):
        assert set(_ids(_buscar("licencias desde 2026 hasta 2026"))) == {"A-COMPLETO", "C-ORACLE"}
        assert _ids(_buscar("licencias hasta 2025")) == []
        assert _ids(_buscar("mantenimiento en 2025")) == ["B-ASCENSORES"]

    def test_interpretar_false_busca_la_palabra(self, corpus):
        """Sin interpretar, «Galicia» es un término más y casa con el título."""
        resultado = _buscar("Galicia", interpretar_filtros=False)

        assert _ids(resultado) == ["D-XUNTA"]


class TestSoloFiltros:
    def test_una_frase_que_son_solo_filtros_devuelve_lo_reciente_del_ambito(self, corpus):
        resultado = _buscar("licitaciones abiertas en Madrid")

        assert resultado.fuente == FUENTE_FILTROS
        # Publicación descendente; la adjudicada no entra.
        assert _ids(resultado) == ["E-LIMPIEZA", "C-ORACLE"]
        assert all(h["score"] == 0.0 and h["coincide_en"] == [] for h in resultado.hits)

    def test_las_mas_recientes_sin_ambito(self, corpus):
        resultado = _buscar("¿Cuáles son las licitaciones más recientes?", top_k=2)

        assert resultado.fuente == FUENTE_FILTROS
        assert _ids(resultado) == ["E-LIMPIEZA", "C-ORACLE"]

    def test_recientes_con_texto_ordena_por_fecha(self, corpus):
        resultado = _buscar("últimas licitaciones de licencias")

        assert resultado.fuente == FUENTE_TEXTO
        assert _ids(resultado) == ["C-ORACLE", "A-COMPLETO"]

    def test_sin_texto_ni_ambito_no_devuelve_el_corpus(self, corpus):
        resultado = _buscar("de la")

        assert resultado.hits == []


class TestPliegos:
    def test_un_pasaje_del_pliego_trae_el_expediente_aunque_el_anuncio_no_lo_diga(self, corpus):
        documento_id = _sembrar_pasaje(
            "E-LIMPIEZA",
            "Se considerará baja temeraria la oferta cuyo porcentaje de baja supere "
            "en 25 unidades la media de las ofertas presentadas.",
            pagina=14,
        )

        resultado = _buscar("bajada temeraria")

        assert resultado.fuente == FUENTE_TEXTO
        (hit,) = resultado.hits
        assert hit["id_externo"] == "E-LIMPIEZA"
        assert hit["coincide_en"] == ["pliego"]
        assert hit["terminos_ausentes"] == []
        assert hit["score"] == 1.0
        pasaje = hit["pasaje"]
        assert pasaje["documento_id"] == documento_id
        assert (pasaje["tipo"], pasaje["filename"], pasaje["page_number"]) == (
            "legal",
            "PCAP.pdf",
            14,
        )
        assert {t["texto"].lower() for t in pasaje["tramos"] if t["resaltado"]} >= {"temeraria"}
        # Lo que cita /ask: el fragmento entero, con su documento.
        assert hit["chunks"][0]["documento_id"] == documento_id
        assert "25 unidades" in hit["chunks"][0]["texto"]

    def test_el_anuncio_completo_va_antes_que_el_que_solo_casa_en_el_pliego(self, corpus):
        _sembrar_pasaje("E-LIMPIEZA", "Mantenimiento de las licencias SAP del adjudicatario.")

        ids = _ids(_buscar("mantenimiento licencias sap"))

        assert ids[:2] == ["A-COMPLETO", "E-LIMPIEZA"]

    def test_un_pasaje_que_solo_tiene_parte_no_cuenta(self, corpus):
        _sembrar_pasaje("E-LIMPIEZA", "Criterios de valoración y bajas desproporcionadas.")

        assert _ids(_buscar("baja temeraria")) == []

    def test_el_ambito_acota_tambien_los_pliegos(self, corpus):
        _sembrar_pasaje("E-LIMPIEZA", "Se considerará baja temeraria la oferta inferior.")

        assert _ids(_buscar("baja temeraria", ccaa=["Andalucía"])) == []
        assert _ids(_buscar("baja temeraria", ccaa=["Madrid"])) == ["E-LIMPIEZA"]


class TestExpresionYUltimoRecurso:
    def test_las_comillas_piden_la_frase_exacta(self, corpus):
        assert _ids(_buscar('"licencias sap"')) == ["A-COMPLETO"]
        assert _ids(_buscar('"sap licencias"')) == []

    def test_la_exclusion_quita_lo_excluido(self, corpus):
        assert set(_ids(_buscar("licencias -oracle"))) == {"A-COMPLETO"}

    def test_una_palabra_a_medias_cae_a_subcadena(self, corpus):
        resultado = _buscar("ascensor ofici")

        # «ascensor» sí es un lexema («ascensores»): responde el texto.
        assert resultado.fuente == FUENTE_TEXTO

        resultado = _buscar("scensore")

        assert resultado.fuente == FUENTE_LITERAL
        assert _ids(resultado) == ["B-ASCENSORES"]

    def test_la_subcadena_no_distingue_tildes(self, corpus):
        resultado = _buscar("enovacio")

        assert resultado.fuente == FUENTE_LITERAL
        assert _ids(resultado) == ["A-COMPLETO"]


class TestContextoDeAsk:
    def test_search_for_ask_usa_el_mismo_motor_y_trae_el_pasaje(self, corpus):
        from services.licitaciones import search_for_ask

        _sembrar_pasaje("E-LIMPIEZA", "Se considerará baja temeraria la oferta inferior.")

        docs = search_for_ask("¿Qué licitaciones hablan de baja temeraria?", 5)

        assert [d["id_externo"] for d in docs] == ["E-LIMPIEZA"]
        assert docs[0]["chunks"][0]["texto"].startswith("Se considerará baja temeraria")
        # Los campos de presentación de la lista no viajan al modelo.
        assert "titulo_tramos" not in docs[0]
        assert "score" not in docs[0]

    def test_la_pregunta_acota_el_contexto_como_la_lista(self, corpus):
        from services.licitaciones import search_for_ask

        docs = search_for_ask("mantenimiento SAP en Andalucía", 5)

        assert [d["id_externo"] for d in docs] == ["A-COMPLETO"]


class TestRutaDePuntaAPunta:
    def test_la_respuesta_declara_lo_entendido_y_donde_casa(self, corpus, api_key):
        from fastapi.testclient import TestClient

        from api.app import app

        cliente = TestClient(app, raise_server_exceptions=False)
        resp = cliente.post(
            "/api/v1/search/semantic",
            json={"q": "mantenimiento SAP en Andalucía"},
            headers={"X-API-Key": api_key},
        )

        assert resp.status_code == 200, resp.text
        datos = resp.json()
        assert datos["source"] == "fts"
        assert datos["interpretacion"]["ccaa"] == ["Andalucía"]
        assert datos["interpretacion"]["terminos"] == ["mantenimiento", "sap"]
        (hit,) = datos["hits"]
        assert hit["id_externo"] == "A-COMPLETO"
        assert hit["coincide_en"] == ["anuncio"]
        assert hit["estado"] == "PUB"
        assert "chunks" not in hit
