"""``services/investigador/busqueda.py`` y la forma de su SQL, sin BD.

Dos cosas se fijan aquí:

- **La orquestación**: los tres escalones del orden (anuncio completo, pasaje de
  pliego, anuncio parcial), qué dice cada resultado de sí mismo, y que un fallo
  en los pliegos no tumba la búsqueda en los anuncios. El repositorio se
  sustituye por un doble.
- **La forma de las consultas** de ``db/repositories/investigador.py``: que el
  ámbito va en el ``WHERE`` y que cada marcador tiene su parámetro, en orden.
  Con una conexión que captura el SQL, igual que ``tests/test_ask_filtros.py``.

Que ese SQL sea válido y devuelva lo que debe lo prueba, contra Postgres,
``tests/test_investigador_busqueda_bd.py``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

import services.investigador.busqueda as busqueda
from db.repositories import investigador as repo
from db.repositories.investigador import MARCA_FIN, MARCA_INICIO, Ambito
from services.investigador.busqueda import (
    FUENTE_FILTROS,
    FUENTE_LITERAL,
    FUENTE_TEXTO,
    buscar_por_texto,
    documentos_de_contexto,
    filtros_de_fusion,
    preparar,
    tramos,
)


def _m(texto: str) -> str:
    """``texto`` con ``[[x]]`` convertido en las marcas de ``ts_headline``."""
    return texto.replace("[[", MARCA_INICIO).replace("]]", MARCA_FIN)


def _anuncio(id_externo: str, *, cobertura: int = 2, n: int = 2, **extra: Any) -> dict[str, Any]:
    """Una fila de ``anuncios_por_terminos``."""
    return {
        "id_externo": id_externo,
        "titulo": f"Título {id_externo}",
        "organo_contratacion": "Órgano",
        "importe": 1000.0,
        "descripcion": "Descripción",
        "url": None,
        "fecha_publicacion": "2026-01-01",
        "fecha_limite": "2026-02-01",
        "ccaa": "Madrid",
        "estado": "PUB",
        "tecnologia": "SAP",
        "puntos": 1.0,
        "rank": 0.5,
        "cobertura": cobertura,
        "n_terminos": n,
        "ausentes": [],
        "titulo_marcado": _m(f"Título [[{id_externo}]]"),
        "extracto": _m("una [[coincidencia]] en la descripción"),
        **extra,
    }


def _fragmento(licitacion_id: str) -> dict[str, Any]:
    """Una fila de ``mejores_pasajes``."""
    return {
        "licitacion_id": licitacion_id,
        "documento_id": 7,
        "tipo": "legal",
        "filename": "PCAP.pdf",
        "chunk_index": 3,
        "page_number": 14,
        "texto": "texto entero del fragmento",
        "extracto": _m("se considerará [[baja]] [[temeraria]]"),
    }


class _Repo:
    """Doble de ``db.repositories.investigador`` con las llamadas grabadas."""

    def __init__(self) -> None:
        self.anuncios: list[dict[str, Any]] = []
        self.pasajes: list[tuple[str, int]] = []
        self.mejores: dict[str, dict[str, Any]] = {}
        self.por_id: dict[str, dict[str, Any]] = {}
        self.literales: list[dict[str, Any]] = []
        self.del_ambito: list[dict[str, Any]] = []
        self.pasajes_revienta = False
        self.mejores_revienta = False
        self.llamadas: list[tuple[str, dict[str, Any]]] = []

    def anuncios_por_terminos(
        self, terminos: Any, ambito: Ambito, *, limit: int, recientes: bool = False
    ) -> list[dict[str, Any]]:
        self.llamadas.append(
            ("terminos", {"terminos": tuple(terminos), "ambito": ambito, "recientes": recientes})
        )
        return list(self.anuncios)[:limit]

    def anuncios_por_expresion(
        self, expresion: str, ambito: Ambito, *, limit: int, recientes: bool = False
    ) -> list[dict[str, Any]]:
        self.llamadas.append(("expresion", {"expresion": expresion, "ambito": ambito}))
        return list(self.anuncios)[:limit]

    def licitaciones_con_pasaje(
        self, texto: str, ambito: Ambito, *, expresion: bool = False, limit: int = 50, **_: Any
    ) -> list[tuple[str, int]]:
        self.llamadas.append(("pasajes", {"texto": texto, "expresion": expresion}))
        if self.pasajes_revienta:
            raise RuntimeError("documento_chunks no existe")
        return list(self.pasajes)[:limit]

    def mejores_pasajes(
        self, ids: Any, texto: str, *, expresion: bool = False
    ) -> dict[str, dict[str, Any]]:
        self.llamadas.append(("mejores", {"ids": list(ids)}))
        if self.mejores_revienta:
            raise RuntimeError("timeout")
        return {i: self.mejores[i] for i in ids if i in self.mejores}

    def anuncios_por_id(self, ids: Any) -> dict[str, dict[str, Any]]:
        self.llamadas.append(("por_id", {"ids": list(ids)}))
        return {i: self.por_id[i] for i in ids if i in self.por_id}

    def anuncios_literales(
        self, terminos: Any, ambito: Ambito, *, limit: int
    ) -> list[dict[str, Any]]:
        self.llamadas.append(("literales", {"terminos": tuple(terminos)}))
        return list(self.literales)[:limit]

    def anuncios_del_ambito(self, ambito: Ambito, *, limit: int) -> list[dict[str, Any]]:
        self.llamadas.append(("ambito", {"ambito": ambito}))
        return list(self.del_ambito)[:limit]

    def nombres(self) -> list[str]:
        return [n for n, _ in self.llamadas]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> _Repo:
    doble = _Repo()
    monkeypatch.setattr(busqueda, "repo", doble)
    return doble


def _buscar(q: str, top_k: int = 10, **kw: Any) -> busqueda.Resultado:
    consulta, ambito = preparar(q, **kw)
    return buscar_por_texto(consulta, ambito, top_k)


# ── tramos ───────────────────────────────────────────────────────────────────


class TestTramos:
    def test_trocea_por_lo_que_casa(self) -> None:
        assert tramos(_m("antes [[casa]] después")) == [
            {"texto": "antes ", "resaltado": False},
            {"texto": "casa", "resaltado": True},
            {"texto": " después", "resaltado": False},
        ]

    def test_reconstruye_el_texto(self) -> None:
        marcado = _m("[[Mantenimiento]] de licencias [[SAP]]")

        assert "".join(t["texto"] for t in tramos(marcado)) == "Mantenimiento de licencias SAP"

    def test_colapsa_los_saltos_de_un_pdf(self) -> None:
        assert tramos(_m("criterios \n  \nde [[baja]]\n")) == [
            {"texto": "criterios de ", "resaltado": False},
            {"texto": "baja", "resaltado": True},
        ]

    def test_sin_marcas_es_un_solo_tramo(self) -> None:
        assert tramos("texto llano") == [{"texto": "texto llano", "resaltado": False}]

    @pytest.mark.parametrize("vacio", [None, "", "   "])
    def test_vacio(self, vacio: str | None) -> None:
        assert tramos(vacio) == []

    def test_una_marca_sin_cerrar_no_revienta(self) -> None:
        assert tramos(f"antes {MARCA_INICIO}resto") == [
            {"texto": "antes ", "resaltado": False},
            {"texto": "resto", "resaltado": True},
        ]

    def test_las_marcas_nunca_salen(self) -> None:
        for tramo in tramos(_m("a [[b]] c [[d]]")):
            assert MARCA_INICIO not in tramo["texto"]
            assert MARCA_FIN not in tramo["texto"]


# ── preparar ─────────────────────────────────────────────────────────────────


class TestPreparar:
    def test_la_frase_rellena_lo_que_la_barra_no_trae(self) -> None:
        consulta, ambito = preparar("sap abiertas en Madrid de más de 500K desde 2025")

        assert ambito == Ambito(
            ccaa_del_texto=("Madrid",),
            fecha_desde="2025-01-01",
            importe_min=500_000.0,
            solo_abiertas=True,
        )
        assert consulta.terminos == ("sap",)

    def test_la_comunidad_de_la_barra_manda(self) -> None:
        consulta, ambito = preparar("sap en Andalucía", ccaa=["Madrid", " "])

        assert ambito.ccaa == ("Madrid",)
        assert ambito.ccaa_del_texto == ()
        # Lo entendido no declara lo que no se aplicó.
        assert consulta.ccaa == ()

    def test_las_fechas_de_la_barra_mandan_enteras(self) -> None:
        """Con un «desde» en la barra, el «hasta» de la frase no se mezcla: el
        rango es uno."""
        consulta, ambito = preparar("sap hasta 2024", fecha_desde="2026-01-01")

        assert (ambito.fecha_desde, ambito.fecha_hasta) == ("2026-01-01", None)
        assert consulta.fecha_hasta is None

    def test_la_tecnologia_solo_viene_de_la_barra(self) -> None:
        _, ambito = preparar("sap", tecnologia=["SAP", ""])

        assert ambito.tecnologia == ("SAP",)

    def test_sin_interpretar_no_hay_ambito_de_la_frase(self) -> None:
        consulta, ambito = preparar("sap en Madrid", interpretar_filtros=False)

        assert ambito.vacio
        assert consulta.terminos == ("sap", "madrid")


class TestFiltrosDeFusion:
    def test_solo_lo_que_acota(self) -> None:
        assert filtros_de_fusion(Ambito()) == {}

    def test_junta_las_comunidades_de_la_barra_y_de_la_frase(self) -> None:
        ambito = Ambito(ccaa=("Madrid",), ccaa_del_texto=("Galicia",), solo_abiertas=True)

        assert filtros_de_fusion(ambito) == {"ccaa": ["Madrid", "Galicia"], "solo_abiertas": True}

    def test_son_argumentos_validos_de_la_fusion(self) -> None:
        """Lo que sale de aquí se pasa como ``**kwargs`` a ``hybrid_search_docs``."""
        import inspect

        from db.search_backend import hybrid_search_docs

        completo = Ambito(
            ccaa=("Madrid",),
            tecnologia=("SAP",),
            fecha_desde="2026-01-01",
            fecha_hasta="2026-12-31",
            importe_min=1.0,
            importe_max=2.0,
            solo_abiertas=True,
        )

        assert set(filtros_de_fusion(completo)) <= set(
            inspect.signature(hybrid_search_docs).parameters
        )


# ── escalones ────────────────────────────────────────────────────────────────


class TestEscalones:
    def test_completo_luego_pliego_luego_parcial(self, fake: _Repo) -> None:
        fake.anuncios = [
            _anuncio("COMPLETO"),
            _anuncio("PARCIAL", cobertura=1, ausentes=["temeraria"]),
        ]
        fake.pasajes = [("SOLO-PLIEGO", 3)]
        fake.por_id = {"SOLO-PLIEGO": {"id_externo": "SOLO-PLIEGO", "titulo": "Limpieza"}}
        fake.mejores = {"SOLO-PLIEGO": _fragmento("SOLO-PLIEGO")}

        resultado = _buscar("baja temeraria")

        assert resultado.fuente == FUENTE_TEXTO
        assert [h["id_externo"] for h in resultado.hits] == ["COMPLETO", "SOLO-PLIEGO", "PARCIAL"]
        completo, pliego, parcial = resultado.hits
        assert completo["coincide_en"] == ["anuncio"]
        assert pliego["coincide_en"] == ["pliego"]
        assert parcial["coincide_en"] == ["anuncio"]
        assert parcial["terminos_ausentes"] == ["temeraria"]
        assert (completo["score"], pliego["score"], parcial["score"]) == (1.0, 1.0, 0.5)

    def test_el_parcial_con_pasaje_sube_y_ya_no_le_falta_nada(self, fake: _Repo) -> None:
        """Lo que el anuncio no dice lo dice su pliego."""
        fake.anuncios = [
            _anuncio("A", cobertura=1, ausentes=["temeraria"]),
            _anuncio("B", cobertura=1, ausentes=["baja"]),
        ]
        fake.pasajes = [("B", 2)]
        fake.mejores = {"B": _fragmento("B")}

        resultado = _buscar("baja temeraria")

        assert [h["id_externo"] for h in resultado.hits] == ["B", "A"]
        b = resultado.hits[0]
        assert b["coincide_en"] == ["anuncio", "pliego"]
        assert b["terminos_ausentes"] == []
        assert b["score"] == 1.0
        assert "por_id" not in fake.nombres(), "ya tenía su fila de anuncio"

    def test_el_pasaje_viaja_troceado_y_el_fragmento_entero_aparte(self, fake: _Repo) -> None:
        fake.pasajes = [("P", 1)]
        fake.por_id = {"P": {"id_externo": "P", "titulo": "Limpieza"}}
        fake.mejores = {"P": _fragmento("P")}

        (hit,) = _buscar("baja temeraria").hits

        assert hit["pasaje"] == {
            "documento_id": 7,
            "tipo": "legal",
            "filename": "PCAP.pdf",
            "page_number": 14,
            "tramos": [
                {"texto": "se considerará ", "resaltado": False},
                {"texto": "baja", "resaltado": True},
                {"texto": " ", "resaltado": False},
                {"texto": "temeraria", "resaltado": True},
            ],
        }
        assert hit["chunks"] == [
            {
                "documento_id": 7,
                "chunk_index": 3,
                "page_number": 14,
                "tipo": "legal",
                "filename": "PCAP.pdf",
                "texto": "texto entero del fragmento",
            }
        ]

    def test_top_k_recorta_despues_de_ordenar(self, fake: _Repo) -> None:
        fake.anuncios = [_anuncio("A"), _anuncio("B", cobertura=1)]
        fake.pasajes = [("P", 1)]
        fake.por_id = {"P": {"id_externo": "P"}}

        assert [h["id_externo"] for h in _buscar("baja temeraria", top_k=2).hits] == ["A", "P"]

    def test_un_extracto_sin_coincidencia_no_se_ensena(self, fake: _Repo) -> None:
        """``ts_headline`` devuelve el arranque del texto si nada casa: en este
        corpus es «Id licitación: …; Órgano de Contratación: …», que no explica
        por qué salió el resultado."""
        fake.anuncios = [_anuncio("A", extracto="Id licitación: 5781; Órgano de Contratación")]

        (hit,) = _buscar("licencias sap").hits

        assert hit["extracto"] == []
        assert hit["titulo_tramos"], "el título sí se enseña marcado"

    def test_un_expediente_del_indice_que_ya_no_existe_no_se_inventa(self, fake: _Repo) -> None:
        fake.pasajes = [("FANTASMA", 1)]

        assert _buscar("baja temeraria").hits == []


class TestLosPliegosSumanNoSostienen:
    def test_si_la_consulta_de_pasajes_falla_responden_los_anuncios(self, fake: _Repo) -> None:
        fake.anuncios = [_anuncio("A")]
        fake.pasajes_revienta = True

        resultado = _buscar("licencias sap")

        assert resultado.fuente == FUENTE_TEXTO
        assert [h["id_externo"] for h in resultado.hits] == ["A"]

    def test_si_falla_el_extracto_del_pasaje_el_resultado_sigue(self, fake: _Repo) -> None:
        fake.pasajes = [("P", 1)]
        fake.por_id = {"P": {"id_externo": "P", "titulo": "Limpieza"}}
        fake.mejores_revienta = True

        (hit,) = _buscar("baja temeraria").hits

        assert hit["coincide_en"] == ["pliego"]
        assert hit["pasaje"] is None

    def test_un_fallo_en_los_anuncios_si_se_propaga(
        self, fake: _Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La ruta lo convierte en 503: una búsqueda rota no puede leerse como
        «sin resultados»."""

        def _revienta(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
            raise RuntimeError("bd caída")

        monkeypatch.setattr(fake, "anuncios_por_terminos", _revienta)

        with pytest.raises(RuntimeError):
            _buscar("licencias sap")


class TestCaminos:
    def test_con_operadores_va_la_expresion_entera(self, fake: _Repo) -> None:
        fake.anuncios = [_anuncio("A", cobertura=0, n=0, rank=0.3)]
        del fake.anuncios[0]["cobertura"]
        del fake.anuncios[0]["n_terminos"]

        resultado = _buscar('"gestión documental" -obra')

        assert fake.nombres()[:2] == ["expresion", "pasajes"]
        assert fake.llamadas[0][1]["expresion"] == '"gestión documental" -obra'
        assert fake.llamadas[1][1] == {"texto": '"gestión documental" -obra', "expresion": True}
        (hit,) = resultado.hits
        assert hit["coincide_en"] == ["anuncio"]
        assert hit["score"] == 1.0

    def test_una_expresion_sin_resultados_no_degrada_a_subcadena(self, fake: _Repo) -> None:
        """Quien escribe comillas pide exactamente eso."""
        resultado = _buscar('"frase exacta"')

        assert resultado.hits == []
        assert resultado.fuente == FUENTE_TEXTO
        assert "literales" not in fake.nombres()

    def test_sin_resultados_de_texto_cae_a_subcadena(self, fake: _Repo) -> None:
        fake.literales = [_anuncio("L", cobertura=1, n=2)]

        resultado = _buscar("scensore ofici")

        assert resultado.fuente == FUENTE_LITERAL
        (hit,) = resultado.hits
        assert hit["score"] == 0.5
        assert hit["titulo_tramos"] == []
        assert fake.llamadas[-1] == ("literales", {"terminos": ("scensore", "ofici")})

    def test_solo_filtros_devuelve_lo_reciente_del_ambito(self, fake: _Repo) -> None:
        fake.del_ambito = [_anuncio("R")]

        resultado = _buscar("licitaciones abiertas en Madrid")

        assert resultado.fuente == FUENTE_FILTROS
        assert fake.nombres() == ["ambito"]
        (hit,) = resultado.hits
        assert (hit["score"], hit["coincide_en"]) == (0.0, [])

    def test_las_mas_recientes_sin_ambito_tambien(self, fake: _Repo) -> None:
        fake.del_ambito = [_anuncio("R")]

        assert _buscar("las más recientes").fuente == FUENTE_FILTROS

    def test_sin_texto_ni_ambito_no_se_consulta_nada(self, fake: _Repo) -> None:
        resultado = _buscar("de la")

        assert resultado.hits == []
        assert fake.llamadas == []

    def test_recientes_llega_al_repositorio(self, fake: _Repo) -> None:
        _buscar("últimas de oracle")

        assert fake.llamadas[0] == (
            "terminos",
            {"terminos": ("oracle",), "ambito": Ambito(), "recientes": True},
        )

    def test_sin_pliegos_no_se_miran(self, fake: _Repo) -> None:
        fake.anuncios = [_anuncio("A")]
        consulta, ambito = preparar("licencias sap")

        buscar_por_texto(consulta, ambito, 5, con_pliegos=False)

        assert fake.nombres() == ["terminos"]


class TestDocumentosDeContexto:
    def test_solo_viaja_el_expediente_y_su_fragmento(self, fake: _Repo) -> None:
        fake.anuncios = [_anuncio("A")]
        fake.pasajes = [("A", 1)]
        fake.mejores = {"A": _fragmento("A")}

        (doc,) = documentos_de_contexto(_buscar("baja temeraria").hits)

        assert doc["id_externo"] == "A"
        assert doc["chunks"][0]["texto"] == "texto entero del fragmento"
        for presentacion in ("score", "coincide_en", "titulo_tramos", "extracto", "pasaje"):
            assert presentacion not in doc

    def test_sin_pasaje_no_hay_clave_chunks(self, fake: _Repo) -> None:
        """``_fuentes_documentos`` de ``/ask`` emite el evento si la clave tiene algo."""
        fake.anuncios = [_anuncio("A")]

        (doc,) = documentos_de_contexto(_buscar("licencias sap").hits)

        assert "chunks" not in doc


# ── forma del SQL ────────────────────────────────────────────────────────────


class _Cursor:
    description: tuple[tuple[str], ...] = ()

    def fetchall(self) -> list[tuple[Any, ...]]:
        return []


class _Conexion:
    def __init__(self) -> None:
        self.sql = ""
        self.params: list[Any] = []

    def execute(self, sql: str, params: list[Any]) -> _Cursor:
        self.sql = sql
        self.params = list(params)
        return _Cursor()


@pytest.fixture
def conexion(monkeypatch: pytest.MonkeyPatch) -> _Conexion:
    conn = _Conexion()

    @contextmanager
    def _connect_read() -> Any:
        yield conn

    monkeypatch.setattr(repo, "connect_read", _connect_read)
    return conn


_AMBITO = Ambito(
    ccaa=("Madrid", "Galicia"),
    ccaa_del_texto=("Andalucía",),
    tecnologia=("SAP",),
    fecha_desde="2026-01-01",
    fecha_hasta="2026-12-31",
    importe_min=1000.0,
    importe_max=9000.0,
    solo_abiertas=True,
)


class TestAmbitoSql:
    def test_vacio(self) -> None:
        assert Ambito().sql() == ([], [])
        assert Ambito().vacio

    def test_cada_marcador_tiene_su_parametro(self) -> None:
        clausulas, valores = _AMBITO.sql("l")

        assert sum(c.count("%s") for c in clausulas) == len(valores)
        assert not _AMBITO.vacio

    def test_la_comunidad_de_la_frase_admite_la_fila_sin_comunidad_que_la_nombra(self) -> None:
        clausulas, valores = Ambito(ccaa_del_texto=("Galicia", "Madrid")).sql("l")

        (clausula,) = clausulas
        assert clausula.count("l.ccaa = %s") == 2
        assert clausula.count("COALESCE(l.ccaa, '') = ''") == 2
        assert clausula.count("plainto_tsquery('spanish', %s)") == 2
        assert valores == ["Galicia", "Galicia", "Madrid", "Madrid"]

    def test_la_comunidad_de_la_barra_es_estricta(self) -> None:
        clausulas, valores = Ambito(ccaa=("Galicia",)).sql("l")

        assert clausulas == ["l.ccaa = %s"]
        assert valores == ["Galicia"]

    def test_importe_y_abiertas(self) -> None:
        from shared.estados import abierta_sql

        clausulas, valores = Ambito(importe_min=5.0, importe_max=9.0, solo_abiertas=True).sql("l")

        assert valores == [5.0, 9.0]
        assert clausulas[-1] == abierta_sql("l.estado")
        assert all("importe" in c for c in clausulas[:2])


class TestFormaDeLasConsultas:
    """Cada consulta lleva el ámbito en el WHERE y tantos parámetros como marcadores."""

    @staticmethod
    def _comprueba(conexion: _Conexion) -> None:
        assert conexion.sql.count("%s") == len(conexion.params), conexion.sql
        for clausula in _AMBITO.sql("l")[0]:
            assert clausula in conexion.sql

    def test_anuncios_por_terminos(self, conexion: _Conexion) -> None:
        repo.anuncios_por_terminos(["baja", "temeraria"], _AMBITO, limit=7)

        self._comprueba(conexion)
        assert conexion.params[0] == ["baja", "temeraria"]
        # Los pesos se calculan UNA vez. Sin `MATERIALIZED`, Postgres incrusta
        # una CTE que solo se usa en un sitio, y ese sitio es una subconsulta
        # por candidato: con 8.000 candidatos la consulta caducaba a los 30 s
        # (medido contra producción); materializada, 89 ms.
        for cte in ("terminos", "consulta", "cand", "frecuencia", "pesos"):
            assert f"{cte} AS MATERIALIZED (" in conexion.sql
        # Dentro de un ámbito ya acotado: nada de filtrar después.
        assert conexion.sql.index("l.ccaa IN") < conexion.sql.index("LIMIT")
        assert 7 in conexion.params

    def test_anuncios_por_terminos_recientes_ordena_por_fecha(self, conexion: _Conexion) -> None:
        repo.anuncios_por_terminos(["oracle"], Ambito(), limit=5, recientes=True)

        assert "fpub DESC NULLS LAST" in conexion.sql
        assert conexion.sql.count("%s") == len(conexion.params)

    def test_sin_terminos_no_se_consulta(self, conexion: _Conexion) -> None:
        assert repo.anuncios_por_terminos([], _AMBITO, limit=5) == []
        assert conexion.sql == ""

    def test_anuncios_por_expresion(self, conexion: _Conexion) -> None:
        repo.anuncios_por_expresion('"gestión documental"', _AMBITO, limit=7)

        self._comprueba(conexion)
        assert "websearch_to_tsquery" in conexion.sql
        assert conexion.params.count('"gestión documental"') == 4

    def test_licitaciones_con_pasaje(self, conexion: _Conexion) -> None:
        repo.licitaciones_con_pasaje("baja temeraria", _AMBITO, limit=9)

        self._comprueba(conexion)
        assert "JOIN licitaciones l" in conexion.sql
        assert "plainto_tsquery('spanish', %s)" in conexion.sql
        assert conexion.params[0] == "baja temeraria"
        assert conexion.params[-2:] == [2000, 9]

    def test_licitaciones_con_pasaje_sin_ambito_no_une_licitaciones(
        self, conexion: _Conexion
    ) -> None:
        repo.licitaciones_con_pasaje("baja temeraria", Ambito(), expresion=True)

        assert "JOIN licitaciones" not in conexion.sql
        assert "websearch_to_tsquery" in conexion.sql
        assert conexion.sql.count("%s") == len(conexion.params)

    def test_mejores_pasajes(self, conexion: _Conexion) -> None:
        repo.mejores_pasajes(["A", "B"], "baja temeraria")

        assert conexion.sql.count("%s") == len(conexion.params)
        assert conexion.params[0] == ["A", "B"]
        # El extracto se calcula fuera del DISTINCT ON, una vez por expediente.
        assert conexion.sql.index("DISTINCT ON") < conexion.sql.index("ts_headline")

    def test_mejores_pasajes_sin_ids_no_consulta(self, conexion: _Conexion) -> None:
        assert repo.mejores_pasajes([], "baja") == {}
        assert conexion.sql == ""

    def test_anuncios_literales(self, conexion: _Conexion) -> None:
        repo.anuncios_literales(["Renovación", "50%", "ab"], _AMBITO, limit=5)

        self._comprueba(conexion)
        # Plegado y con los comodines escapados; el de dos letras no entra,
        # porque un patrón tan corto no puede usar el índice trigram.
        assert "%renovacion%" in conexion.params
        assert "%50\\%%" in conexion.params
        assert "%ab%" not in conexion.params
        # La expresión del índice, carácter a carácter.
        from db.sql_fragments import fold_expr

        assert fold_expr("l.descripcion") in conexion.sql

    def test_anuncios_literales_sin_terminos_utiles_no_consulta(self, conexion: _Conexion) -> None:
        assert repo.anuncios_literales(["ab", "x"], Ambito(), limit=5) == []
        assert conexion.sql == ""

    def test_anuncios_del_ambito(self, conexion: _Conexion) -> None:
        repo.anuncios_del_ambito(_AMBITO, limit=5)

        self._comprueba(conexion)

    def test_anuncios_del_ambito_ordena_como_recorre_el_indice(self, conexion: _Conexion) -> None:
        """``DESC NULLS LAST`` no lo sirve ningún recorrido de ``idx_fecha_pub``:
        Postgres ordenaba la tabla entera (5,1 s contra producción). Con el
        ``IS NOT NULL`` y ``DESC`` a secas, el índice hacia atrás ya es el orden
        y corta en el LIMIT (5 ms)."""
        repo.anuncios_del_ambito(Ambito(), limit=5)

        assert "WHERE l.fecha_publicacion IS NOT NULL" in conexion.sql
        assert "ORDER BY l.fecha_publicacion DESC, l.id_externo" in conexion.sql
        assert "NULLS LAST" not in conexion.sql
        assert conexion.params == [5]

    def test_anuncios_por_id(self, conexion: _Conexion) -> None:
        repo.anuncios_por_id(["A"])

        assert conexion.params == [["A"]]
