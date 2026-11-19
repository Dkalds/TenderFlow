"""Documentos de TED y PSCP, que su feed no trae (``scraper.documentos_plataforma``).

Dos caminos: el PDF del anuncio TED y la ficha JSON de la PSCP (el expediente
de PLACSP que enlaza un aviso TED lo ingiere el propio conector:
``tests/test_placsp_esperadas_por_ted.py``). El JSON de ``tests/fixtures/pscp/detall_publicacio_expedient.json`` es un
recorte real (expediente 2026/6150/1428 de Esplugues, 2026-10-02), con el
anuncio TED 675385-2026 que cita. ``fase_formalitzacio.json`` y
``fase_anunci.json`` son otros dos (expediente SER_NSP_2026_0002, resuelto,
2026-11-09): la publicación de su última fase, que es la que guarda
``licitaciones.url``, y la del anuncio que enlaza su ``navegacioFases``.
``fixtures/andalucia/expediente_1036313.json`` es la respuesta real del buscador
del Perfil de Contratante de la Junta para EXPT26-00040 (SANDETEL, 2026-11-09),
recortada a lo que se lee.

Los tests unitarios doblan red y BD. Los ``test_integration_*`` del final
corren contra Postgres.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pybreaker
import pytest

import scraper.documentos_plataforma as dp
from db.upsert import DocumentoReferencia
from scraper.documentos_plataforma import (
    numero_publicacion_ted,
    numeros_ted_citados,
    parse_detalle_pscp,
    referencia_anuncio_ted,
    url_api_pscp,
)
from services.dedupe import ReferenciaCruzada, RepublicacionesTed

_FIXTURE_PSCP = Path(__file__).parent / "fixtures" / "pscp" / "detall_publicacio_expedient.json"
_FICHA_PSCP = (
    "https://contractaciopublica.cat/ca/detall-publicacio/"
    "fcd0edf9-2bd9-4f2e-9924-24b8627a96de/300885821"
)
_DEEPLINK = "https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl="
_FIXTURE_FORMALITZACIO = _FIXTURE_PSCP.with_name("fase_formalitzacio.json")
_FIXTURE_ANUNCI = _FIXTURE_PSCP.with_name("fase_anunci.json")
_FICHA_CERRADA = (
    "https://contractaciopublica.cat/ca/detall-publicacio/"
    "5f414a80-c061-48ab-b865-8cc23e05e3af/300751065"
)
_API_EXPEDIENTE_CERRADO = (
    "https://contractaciopublica.cat/portal-api/detall-publicacio-expedient/"
    "5f414a80-c061-48ab-b865-8cc23e05e3af"
)


def _detalle_pscp() -> Any:
    return json.loads(_FIXTURE_PSCP.read_text(encoding="utf-8"))


def _formalitzacio() -> Any:
    return json.loads(_FIXTURE_FORMALITZACIO.read_text(encoding="utf-8"))


def _portal(por_publicacion: dict[str, Any], pedidas: list[str]) -> Any:
    """Un ``obtener`` que sirve el JSON de cada publicación del expediente cerrado."""

    def obtener(url: str) -> bytes:
        pedidas.append(url)
        return json.dumps(por_publicacion[url.rsplit("/", 1)[-1]]).encode()

    return obtener


# ── Anuncio TED ──────────────────────────────────────────────────────────────


def test_anuncio_ted_es_el_pdf_del_aviso_con_identidad_estable():
    ref = referencia_anuncio_ted("ted:678766-2026")

    assert ref == DocumentoReferencia(
        tipo="additional",
        uri="https://ted.europa.eu/es/notice/678766-2026/pdf",
        filename="Anuncio TED 678766-2026.pdf",
        source_hash="ted-678766-2026",
    )


@pytest.mark.parametrize(
    "id_externo", ["2026/ABC", "pscp:2026/1", "ted:", "ted:678766", "ted:../../x-2026"]
)
def test_sin_numero_de_publicacion_valido_no_hay_anuncio(id_externo):
    assert numero_publicacion_ted(id_externo) is None
    assert referencia_anuncio_ted(id_externo) is None


def test_el_source_hash_del_anuncio_es_un_token_valido_para_el_almacen():
    """La clave del binario es ``documentos/{source_hash}`` si el hash es un token seguro."""
    from shared.object_store import document_blob_key

    ref = referencia_anuncio_ted("ted:678766-2026")
    assert ref is not None
    assert document_blob_key(ref.source_hash, fallback="sha") == "documentos/ted-678766-2026"


def test_numeros_ted_citados_en_cualquier_forma_de_enlace_y_sin_repetir():
    nodo = {
        "publicacionsOficials": [
            {"url": "https://ted.europa.eu/en/notice/-/detail/675385-2026"},
            {"url": "https://ted.europa.eu/es/notice/675385-2026/pdf"},
        ],
        "lots": [{"altres": "https://ted.europa.eu/es/notice/-/detail/12-2026"}],
        "boe": "https://www.boe.es/notice/1-2026",
    }

    assert numeros_ted_citados(nodo) == ["675385-2026", "12-2026"]


# ── PSCP ─────────────────────────────────────────────────────────────────────


def test_url_api_de_la_ficha_de_una_publicacion():
    assert url_api_pscp(_FICHA_PSCP) == (
        "https://contractaciopublica.cat/portal-api/detall-publicacio-expedient/"
        "fcd0edf9-2bd9-4f2e-9924-24b8627a96de/300885821"
    )


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        # El BT-15 de los avisos TED catalanes: el perfil del comprador, no el expediente.
        "https://contractaciopublica.cat/ca/perfils-contractant/detall/5281352",
        "https://contractaciopublica.gencat.cat/perfil/TB",
        "https://evil.example/ca/detall-publicacio/fcd0edf9-2bd9-4f2e-9924-24b8627a96de/1",
    ],
)
def test_sin_ficha_de_publicacion_no_hay_url_de_api(url):
    assert url_api_pscp(url) is None


def test_detalle_pscp_mapea_los_apartados_a_tipos_y_usa_el_hash_como_identidad():
    detalle = parse_detalle_pscp(_detalle_pscp())

    por_nombre = {d.filename: d for d in detalle.documentos}
    assert por_nombre["PCAP.pdf"].tipo == "legal"
    assert por_nombre["PPT.pdf"].tipo == "technical"
    assert por_nombre["Informe de necessitat.pdf"].tipo == "additional"
    assert por_nombre["PPT.pdf"].uri == (
        "https://contractaciopublica.cat/portal-api/descarrega-document/"
        "302602166/BED412D30394A796A1E7F7C62352C981"
    )
    # Hash de contenido del PPT que publica el portal, no un secreto.
    huella = "BED412D30394A796A1E7F7C62352C981"  # pragma: allowlist secret
    assert por_nombre["PPT.pdf"].source_hash == huella
    assert len(detalle.documentos) == 5
    assert detalle.anuncios_ted == ["675385-2026"]


def test_detalle_pscp_descarta_documentos_con_id_o_hash_que_compondrian_otra_ruta():
    datos = {
        "dades": {
            "publicacio": {
                "dadesPublicacio": {
                    "altresDocuments": {
                        "docs": [
                            {"id": "1/../../x", "hash": "ABCDEF0123456789", "titol": "a"},
                            {"id": 7, "hash": "AB/CD", "titol": "b"},
                            {"id": 8, "hash": "ABCDEF0123456789", "titol": "  "},
                        ]
                    }
                }
            }
        }
    }

    detalle = parse_detalle_pscp(datos)

    assert [(d.uri.rsplit("/", 2)[-2], d.filename) for d in detalle.documentos] == [("8", None)]


def test_detalle_pscp_sin_publicacion_no_falla():
    assert parse_detalle_pscp({}) == dp.DetallePscp(documentos=[], anuncios_ted=[])
    assert parse_detalle_pscp([]) == dp.DetallePscp(documentos=[], anuncios_ted=[])


def test_documentos_de_pscp_pide_el_json_de_la_ficha():
    pedidas: list[str] = []

    def obtener(url: str) -> bytes:
        pedidas.append(url)
        return _FIXTURE_PSCP.read_bytes()

    detalle = dp.documentos_de_pscp(_FICHA_PSCP, obtener=obtener)

    assert pedidas == [url_api_pscp(_FICHA_PSCP)]
    assert detalle is not None and len(detalle.documentos) == 5


def test_documentos_de_pscp_no_pide_nada_si_la_url_no_es_una_ficha():
    def obtener(url: str) -> bytes:
        raise AssertionError("no debería pedir nada")

    assert (
        dp.documentos_de_pscp("https://contractaciopublica.cat/ca/inici", obtener=obtener) is None
    )


def test_los_documentos_de_otra_fase_no_entran_como_pliego():
    """El contrato firmado de la formalización, como ``additional``, iría al RAG y a la ficha."""
    assert parse_detalle_pscp(_formalitzacio()).documentos == []


def test_un_expediente_cerrado_lee_los_pliegos_de_su_anuncio():
    pedidas: list[str] = []
    anunci = json.loads(_FIXTURE_ANUNCI.read_text(encoding="utf-8"))
    portal = _portal({"300751065": _formalitzacio(), "300719618": anunci}, pedidas)

    detalle = dp.documentos_de_pscp(_FICHA_CERRADA, obtener=portal)

    assert pedidas == [
        f"{_API_EXPEDIENTE_CERRADO}/300751065",
        f"{_API_EXPEDIENTE_CERRADO}/300719618",
    ]
    assert detalle is not None
    assert [(d.tipo, d.filename) for d in detalle.documentos] == [
        ("legal", "SER_NSP_2026_0002-PCAP_diligenciat.pdf"),
        ("technical", "SER_NSP_2026_0002-PPT-diligenciat.pdf"),
        ("additional", "SER_NSP_2026_0002-Informe previ.pdf"),
        ("additional", "SER_NSP_2026_0002-Decret aprovar Plecs_CA.pdf"),
    ]


def test_solo_vale_el_aviso_ted_que_cita_la_ficha_del_anuncio():
    """El de otra fase podría ser el del acuerdo marco, y se marcaría ``confirmed``."""

    def citando(datos: Any, numero: str) -> Any:
        datos["dades"]["publicacio"]["publicacionsOficials"] = [
            {"tipus": {"text": "DOUE"}, "url": f"https://ted.europa.eu/en/notice/-/detail/{numero}"}
        ]
        return datos

    anunci = json.loads(_FIXTURE_ANUNCI.read_text(encoding="utf-8"))
    portal = _portal(
        {
            "300751065": citando(_formalitzacio(), "111111-2026"),
            "300719618": citando(anunci, "222222-2026"),
        },
        [],
    )

    detalle = dp.documentos_de_pscp(_FICHA_CERRADA, obtener=portal)

    assert detalle is not None and detalle.anuncios_ted == ["222222-2026"]


def test_sin_anuncio_en_la_plataforma_no_hay_nada_mas_que_pedir():
    """Un negociado sin publicidad o un contrato basado en un acuerdo marco no lo tuvo."""
    datos = _formalitzacio()
    datos["navegacioFases"] = [f for f in datos["navegacioFases"] if f["fase"] != 1000040]
    pedidas: list[str] = []

    detalle = dp.documentos_de_pscp(_FICHA_CERRADA, obtener=_portal({"300751065": datos}, pedidas))

    assert pedidas == [f"{_API_EXPEDIENTE_CERRADO}/300751065"]
    assert detalle == dp.DetallePscp(documentos=[], anuncios_ted=[])


@pytest.mark.parametrize("publicacion", ["1/../../x", "300719618?a=1", "", None, 12345678901234])
def test_un_id_de_publicacion_que_compondria_otra_ruta_no_se_pide(publicacion):
    datos = _formalitzacio()
    datos["navegacioFases"] = [{"fase": 1000040, "publicacioId": publicacion}]
    pedidas: list[str] = []

    dp.documentos_de_pscp(_FICHA_CERRADA, obtener=_portal({"300751065": datos}, pedidas))

    assert pedidas == [f"{_API_EXPEDIENTE_CERRADO}/300751065"]


_FIXTURE_ANDALUCIA = Path(__file__).parent / "fixtures" / "andalucia" / "expediente_1036313.json"
_FICHA_ANDALUCIA = (
    "https://www.juntadeandalucia.es/haciendayadministracionpublica/apl/pdc_sirec/"
    "perfiles-licitaciones/detalle-licitacion.jsf?idExpediente=1036313"
)
_DESCARGA_JUNTA = (
    "https://www.juntadeandalucia.es/haciendayadministracionpublica/apl/"
    "pdc_sirec_documentacion/rest/descargar/documento/"
)


@pytest.mark.parametrize(
    "url",
    [
        _FICHA_ANDALUCIA,
        # La ficha nueva, a la que la web redirige la vieja.
        "https://www.juntadeandalucia.es/haciendayadministracionpublica/apl/pdc-front-publico/"
        "perfiles-licitaciones/detalle-licitacion?idExpediente=1036313",
    ],
)
def test_id_expediente_de_la_ficha_vieja_y_de_la_nueva(url):
    assert dp.id_expediente_andalucia(url) == "1036313"


@pytest.mark.parametrize(
    "url",
    [
        None,
        "https://www.juntadeandalucia.es/temas/contratacion-publica.html",
        "https://www.juntadeandalucia.es/x/detalle-licitacion.jsf?idExpediente=1036313/../1",
        "https://www.juntadeandalucia.es/x/detalle-licitacion.jsf?idExpediente=1&idExpediente=2",
        "https://evil.example/x/detalle-licitacion.jsf?idExpediente=1036313",
    ],
)
def test_sin_ficha_de_la_junta_no_hay_expediente(url):
    assert dp.id_expediente_andalucia(url) is None


def test_detalle_andalucia_mapea_las_categorias_y_usa_el_sha256_como_identidad():
    crudo = json.loads(_FIXTURE_ANDALUCIA.read_text("utf-8"))
    documentos = dp.parse_detalle_andalucia(crudo)

    assert [(d.tipo, d.uri, d.filename) for d in documentos] == [
        (
            "legal",
            f"{_DESCARGA_JUNTA}441311",
            "PCAP - Pliegos de Cláusulas Administrativas Particulares",
        ),
        ("technical", f"{_DESCARGA_JUNTA}441224", "PPT - Pliego de prescripciones técnicas"),
        ("legal", f"{_DESCARGA_JUNTA}441227", "DEUC"),
    ]
    publicados = crudo["hits"]["hits"][0]["_source"]["documentos"]
    assert [d.source_hash for d in documentos] == [doc["sha256"] for doc in publicados]


def test_detalle_andalucia_solo_trae_pliegos_activos_con_forma_valida():
    """Ni versiones sustituidas, ni actas ni adjudicación, ni un id o hash que compondría otra ruta."""
    huella = "a" * 64

    def doc(**campos: Any) -> dict[str, Any]:
        return {"id": 7, "categoria": "Documento adicional", "nombre": "Anexo I", "sha256": huella,
                "estado": "Activo", **campos}  # fmt: skip

    datos = {"hits": {"hits": [{"_source": {"documentos": [
        doc(),
        doc(id=8, estado="Inactivo"),
        doc(id=9, categoria="Acta de la mesa de contratación"),
        doc(id=10, categoria="Resolución de adjudicación"),
        doc(id="11/../12"),
        doc(id=13, sha256="no-es-un-hash"),
        doc(),  # repetido: un solo documento
    ]}}]}}  # fmt: skip

    assert [(d.tipo, d.uri) for d in dp.parse_detalle_andalucia(datos)] == [
        ("additional", f"{_DESCARGA_JUNTA}7")
    ]


@pytest.mark.parametrize("datos", [{}, {"hits": {"hits": []}}, {"hits": {"hits": [{}, {}]}}, None])
def test_detalle_andalucia_sin_un_expediente_no_falla(datos):
    assert dp.parse_detalle_andalucia(datos) == []


def test_documentos_de_andalucia_pide_el_expediente_como_lo_pide_su_web():
    pedidas: list[tuple[str, Any]] = []

    def obtener(url: str, cuerpo: bytes) -> bytes:
        pedidas.append((url, json.loads(cuerpo)))
        return _FIXTURE_ANDALUCIA.read_bytes()

    documentos = dp.documentos_de_andalucia(_FICHA_ANDALUCIA, obtener=obtener)

    assert pedidas == [(dp._API_ANDALUCIA, {"query": {"match": {"_id": "1036313"}}})]
    assert documentos is not None and len(documentos) == 3


def test_documentos_de_andalucia_no_pide_nada_si_la_url_no_es_su_ficha():
    def obtener(url: str, cuerpo: bytes) -> bytes:
        raise AssertionError("no debía pedir nada")

    assert dp.documentos_de_andalucia("https://ted.europa.eu/x", obtener=obtener) is None


# ── Del aviso TED al portal de origen ────────────────────────────────────────

_FIXTURE_BUSQUEDA_ANDALUCIA = _FIXTURE_ANDALUCIA.with_name("busqueda_contr_2026_185738.json")
_COD_NAVARRA = "2611161058079F239BBD"  # pragma: allowlist secret -- código público del anuncio
_FICHA_NAVARRA = (
    f"https://hacienda.navarra.es/sicpportal/mtoAnunciosModalidad.aspx?cod={_COD_NAVARRA}"
)
_FIXTURE_NAVARRA = Path(__file__).parent / "fixtures" / "navarra" / f"anuncio_{_COD_NAVARRA}.html"
_DESCARGA_NAVARRA = (
    f"https://hacienda.navarra.es/sicpportal/mtoGeneraDocumento.aspx?DOA={_COD_NAVARRA}&DOL="
)
_PERFIL_JUNTA = (
    "https://www.juntadeandalucia.es/haciendayadministracionpublica/apl/pdc_sirec/"
    "perfiles-licitaciones/detalle-perfil.jsf?perfilContratante=EICE13&organismo=CEHYFE"
)


def _busqueda_andalucia(*expedientes: dict[str, Any]) -> bytes:
    """La respuesta del buscador con esos expedientes (``_source``)."""
    return json.dumps({"hits": {"hits": [{"_source": e} for e in expedientes]}}).encode()


def _expediente_junta(**campos: Any) -> dict[str, Any]:
    pliego = {"id": 7, "categoria": "PPT", "nombre": "PPT.pdf", "sha256": "a" * 64}
    return {
        "numeroExpediente": "CONTR 2026 0000185738",
        "estado": {"codigo": "PUB"},
        "perfilContratante": {"codigo": "EICE13"},
        "documentos": [{**pliego, "estado": "Activo"}],
        **campos,
    }


def test_andalucia_por_expediente_encuentra_el_que_ted_teclea_sin_ceros():
    """Recorte real: el DOUE publica «CONTR 2026 185738» y la Junta «CONTR 2026 0000185738»."""
    pedidas: list[tuple[str, Any]] = []

    def obtener(url: str, cuerpo: bytes) -> bytes:
        pedidas.append((url, json.loads(cuerpo)))
        return _FIXTURE_BUSQUEDA_ANDALUCIA.read_bytes()

    documentos = dp.documentos_de_andalucia_por_expediente(
        "CONTR 2026 185738", perfil="EICE13", obtener=obtener
    )

    # El buscador solo admite `match`: el número va también relleno a diez cifras.
    assert pedidas == [
        (
            dp._API_ANDALUCIA,
            {"query": {"match": {"numeroExpediente": "CONTR 2026 185738 0000185738"}}, "size": 10},
        )
    ]
    # Solo el expediente que casa, no los otros tres que devuelve la búsqueda.
    assert [(d.tipo, d.uri) for d in documentos] == [
        ("legal", f"{_DESCARGA_JUNTA}435839"),
        ("technical", f"{_DESCARGA_JUNTA}435838"),
        ("additional", f"{_DESCARGA_JUNTA}443804"),
    ]


@pytest.mark.parametrize("expediente", ["contr 2026 / 185738", "CONTR-2026-0000185738"])
def test_andalucia_por_expediente_compara_sin_separadores_ni_mayusculas(expediente):
    respuesta = _busqueda_andalucia(_expediente_junta())

    documentos = dp.documentos_de_andalucia_por_expediente(
        expediente, obtener=lambda url, cuerpo: respuesta
    )

    assert [d.uri for d in documentos] == [f"{_DESCARGA_JUNTA}7"]


@pytest.mark.parametrize(
    ("encontrados", "perfil"),
    [
        pytest.param(
            [_expediente_junta(numeroExpediente="CONTR 2025 0000185738")], None, id="otro"
        ),
        pytest.param([_expediente_junta(estado={"codigo": "RES"})], None, id="ya-resuelto"),
        pytest.param([_expediente_junta()], "COED02", id="de-otro-perfil"),
        pytest.param([_expediente_junta(), _expediente_junta()], None, id="dos-candidatos"),
        pytest.param([], None, id="ninguno"),
    ],
)
def test_andalucia_por_expediente_no_da_los_pliegos_de_otro_contrato(encontrados, perfil):
    respuesta = _busqueda_andalucia(*encontrados)

    documentos = dp.documentos_de_andalucia_por_expediente(
        "CONTR 2026 185738", perfil=perfil, obtener=lambda url, cuerpo: respuesta
    )

    assert documentos == []


def test_andalucia_por_expediente_no_busca_un_expediente_sin_numero():
    """«Contrato de Suministro» casaría con medio índice: ni se pide."""

    def obtener(url: str, cuerpo: bytes) -> bytes:
        raise AssertionError("no debía pedir nada")

    assert (
        dp.documentos_de_andalucia_por_expediente("Contrato de Suministro", obtener=obtener) == []
    )


def test_andalucia_sin_perfil_solo_busca_la_numeracion_corporativa():
    """«3/2026» lo tiene cada órgano: sin perfil, el único publicado podría ser de otro."""
    del_organo = _expediente_junta(numeroExpediente="3/2026", perfilContratante={"codigo": "X"})
    pedidas = 0

    def obtener(url: str, cuerpo: bytes) -> bytes:
        nonlocal pedidas
        pedidas += 1
        return _busqueda_andalucia(del_organo)

    assert dp.documentos_de_andalucia_por_expediente("3/2026", obtener=obtener) == []
    assert pedidas == 0
    # Con el perfil del aviso sí: el número es de ese órgano.
    assert len(dp.documentos_de_andalucia_por_expediente("3/2026", perfil="X", obtener=obtener))


@pytest.mark.parametrize(
    ("urls", "perfil"),
    [
        ([_PERFIL_JUNTA], "EICE13"),
        (
            [
                "https://www.ceh.junta-andalucia.es/haciendayadministracionpublica/apl/"
                "pdc-front-publico/perfiles-contratantes/detalle?code=capadr02&codeOrganismo=CAPADR"
            ],
            "CAPADR02",
        ),
        (["https://juntadeandalucia.es/temas/perfiles-contratante/detalle/COED02.html"], "COED02"),
        (["https://sirecbkdexp.chap.junta-andalucia.es/liciElec/web/"], None),
        # Un `code=` de otro sitio no es un perfil, ni tapa el de la Junta que va detrás.
        (["https://ted.europa.eu/x?code=abc"], None),
        (["https://ted.europa.eu/x?code=abc", _PERFIL_JUNTA], "EICE13"),
        (["https://www.ajuntadeandalucia.es/detalle?code=abc"], None),
    ],
)
def test_perfil_andalucia_del_enlace_del_aviso(urls, perfil):
    assert dp._perfil_andalucia(urls) == perfil


def test_codigo_del_anuncio_de_navarra():
    assert dp.codigo_anuncio_navarra(_FICHA_NAVARRA) == _COD_NAVARRA


@pytest.mark.parametrize(
    "url",
    [
        None,
        "www.contrataciones.navarra.es",
        "https://hacienda.navarra.es/sicpportal/mtoAnunciosModalidad.aspx",
        "https://hacienda.navarra.es/sicpportal/mtoAnunciosModalidad.aspx?cod=../../x",
        "https://hacienda.navarra.es/sicpportal/mtoFichaEntidad.aspx?Cod=8379",
        f"https://otro.example/sicpportal/mtoAnunciosModalidad.aspx?cod={_COD_NAVARRA}",
    ],
)
def test_sin_ficha_del_portal_navarro_no_hay_anuncio(url):
    assert dp.codigo_anuncio_navarra(url) is None


def test_detalle_navarra_lee_la_tabla_de_pliegos():
    """Recorte real del anuncio 0005-CP01-2026-000125 (2026-11-19), en su ISO-8859."""
    documentos = dp.parse_detalle_navarra(_FIXTURE_NAVARRA.read_bytes(), _COD_NAVARRA)

    assert documentos == [
        DocumentoReferencia(
            tipo="legal",
            uri=f"{_DESCARGA_NAVARRA}1",
            filename="Pliego regulador_20261112111731_CSV.pdf",
            source_hash=f"navarra-{_COD_NAVARRA}-1",
        ),
        DocumentoReferencia(
            tipo="additional",
            uri=f"{_DESCARGA_NAVARRA}2",
            filename="espd-request.zip",
            source_hash=f"navarra-{_COD_NAVARRA}-2",
        ),
    ]


def test_detalle_navarra_solo_toma_las_descargas_de_su_anuncio():
    """Ni el adjunto de otro anuncio, ni un enlace con otra forma, ni lo de fuera de la tabla."""
    otro = "9" * 20
    pagina = f"""<html><body>
      <a href='mtoGeneraDocumento.aspx?DOA={_COD_NAVARRA}&DOL=9' name='Acta.pdf'>fuera</a>
      <table id='tblPliegos'>
        <tr><td><a href='mtoGeneraDocumento.aspx?DOA={_COD_NAVARRA}&DOL=1'
                   name='SDC_2025_PCT_csv.pdf'>SDC_2025_P(...)</a></td></tr>
        <tr><td><a href='mtoGeneraDocumento.aspx?DOA={otro}&DOL=1' name='Pliego.pdf'>x</a></td></tr>
        <tr><td><a href='mtoGeneraDocumento.aspx?DOA={_COD_NAVARRA}&DOL=2&x=../y'>x</a></td></tr>
        <tr><td><a href='https://otro.example/pliego.pdf'>x</a></td></tr>
      </table></body></html>""".encode()

    documentos = dp.parse_detalle_navarra(pagina, _COD_NAVARRA)

    # El nombre entero sale de `name`: el texto del enlace llega cortado.
    assert [(d.tipo, d.uri, d.filename) for d in documentos] == [
        ("technical", f"{_DESCARGA_NAVARRA}1", "SDC_2025_PCT_csv.pdf")
    ]


def test_detalle_navarra_clasifica_por_el_nombre_y_no_por_la_carpeta():
    """En ISO-8859, como lo sirve el portal, y con el `cod` en minúsculas en el enlace."""
    cod = _COD_NAVARRA.lower()
    pagina = f"""<html><head>
      <meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1"></head><body>
      <table id='tblPliegos'>
        <tr><td><a href='mtoGeneraDocumento.aspx?DOA={cod}&DOL=1'
                   name='Pliego/Anexo I modelo de oferta económica.docx'>x</a></td></tr>
        <tr><td><a href='mtoGeneraDocumento.aspx?DOA={cod}&DOL=2'
                   name='Otros/Prescripciones técnicas.pdf'>x</a></td></tr>
        <tr><td><a href='mtoGeneraDocumento.aspx?DOA={cod}&DOL=3'
                   name='Pliego/Pliego regulador.pdf'>x</a></td></tr>
      </table></body></html>""".encode("iso-8859-15")

    documentos = dp.parse_detalle_navarra(pagina, _COD_NAVARRA)

    assert [(d.tipo, d.filename) for d in documentos] == [
        ("additional", "Anexo I modelo de oferta económica.docx"),
        ("technical", "Prescripciones técnicas.pdf"),
        ("legal", "Pliego regulador.pdf"),
    ]


def test_el_portal_se_reconoce_por_el_enlace_al_expediente_o_por_el_host_de_la_junta():
    sin_esquema = _FICHA_NAVARRA.removeprefix("https://")

    def portal(urls: list[str], expediente: str | None = "CONTR 2026 185738") -> str | None:
        encontrado = dp._buscar_en_origen(urls, expediente)
        return encontrado[0] if encontrado else None

    assert portal([sin_esquema]) == "navarra"  # BT-15 llega a veces sin esquema
    assert portal([_FICHA_ANDALUCIA], None) == "andalucia"  # la ficha no necesita BT-22
    assert portal([_PERFIL_JUNTA]) == "andalucia"
    assert portal([_PERFIL_JUNTA], None) is None  # el perfil sin número no identifica nada
    assert portal(["https://www.ajuntadeandalucia.es/perfil"]) is None
    assert portal(["https://www.contratacion.euskadi.eus"]) is None


def test_la_ficha_de_la_junta_que_enlaza_el_aviso_se_pide_por_su_id():
    encontrado = dp._buscar_en_origen([_FICHA_ANDALUCIA], None)
    assert encontrado is not None
    pedidas: list[tuple[str, Any]] = []

    def pedir(url: str, cuerpo: bytes | None) -> bytes:
        pedidas.append((url, json.loads(cuerpo or b"null")))
        return _FIXTURE_ANDALUCIA.read_bytes()

    documentos = encontrado[1](pedir)

    assert pedidas == [(dp._API_ANDALUCIA, {"query": {"match": {"_id": "1036313"}}})]
    assert documentos is not None and len(documentos) == 3


def test_cada_peticion_al_origen_va_al_host_de_su_portal(monkeypatch):
    hosts: list[str] = []

    def obtener(
        url: str, *, host: str, timeout_s: float | None = None, cuerpo: Any = None
    ) -> bytes:
        hosts.append(host)
        return b""

    monkeypatch.setattr(dp, "_obtener", obtener)
    pedir = dp._obtener_origen_con_tope(lambda: 30.0)

    pedir(_FICHA_NAVARRA, None)
    pedir(dp._API_ANDALUCIA, b"{}")

    assert hosts == ["hacienda.navarra.es", "www.juntadeandalucia.es"]


def test_documentos_de_navarra_pide_la_ficha_del_anuncio():
    pedidas: list[str] = []

    def obtener(url: str) -> bytes:
        pedidas.append(url)
        return _FIXTURE_NAVARRA.read_bytes()

    documentos = dp.documentos_de_navarra(_FICHA_NAVARRA, obtener=obtener)

    assert pedidas == [_FICHA_NAVARRA]
    assert documentos is not None and len(documentos) == 2


def test_documentos_de_navarra_no_pide_nada_si_la_url_no_es_su_ficha():
    def obtener(url: str) -> bytes:
        raise AssertionError("no debía pedir nada")

    assert dp.documentos_de_navarra("www.contrataciones.navarra.es", obtener=obtener) is None


def _portal_de_origen(pedidas: list[str]) -> dp.PedirAlOrigen:
    """Navarra y la Junta contestando sus recortes reales."""

    def pedir(url: str, cuerpo: bytes | None) -> bytes:
        pedidas.append(url)
        if url == dp._API_ANDALUCIA:
            return _FIXTURE_BUSQUEDA_ANDALUCIA.read_bytes()
        assert (url, cuerpo) == (_FICHA_NAVARRA, None)
        return _FIXTURE_NAVARRA.read_bytes()

    return pedir


def _fila_ted(numero: str, **campos: Any) -> Any:
    return {
        "id_externo": f"ted:{numero}",
        "url": f"https://ted.europa.eu/es/notice/{numero}/pdf",
        "destino": f"ted:{numero}",
        "url_destino": None,
        **campos,
    }


def test_los_pliegos_de_un_aviso_ted_salen_del_portal_de_origen(repo_falso):
    """Navarra por la ficha de su pareja; la Junta por el BT-22; el resto no gasta nada."""
    repo = repo_falso([])
    agregada = "placsp_agregadas:S7138185I:8379_0005-CP01-2026-000125"
    filas = [
        _fila_ted("797899-2026", destino=agregada, url_destino=_FICHA_NAVARRA),
        _fila_ted("723357-2026", url=_PERFIL_JUNTA),
        _fila_ted("803365-2026"),  # Euskadi: el aviso solo enlaza la portada
    ]
    origenes = {
        "ted:797899-2026": dp.OrigenTed(
            "0005-CP01-2026-000125", ("www.contrataciones.navarra.es",)
        ),
        "ted:723357-2026": dp.OrigenTed("CONTR 2026 185738", (_PERFIL_JUNTA,)),
        "ted:803365-2026": dp.OrigenTed("2026KOES0032", ("https://www.contratacion.euskadi.eus",)),
    }
    pedidas: list[str] = []

    resumen = dp.completar_pliegos_ted_en_origen(
        filas, origenes, pausa_s=0, obtener=_portal_de_origen(pedidas)
    )

    assert pedidas == [_FICHA_NAVARRA, dp._API_ANDALUCIA]
    # Se escriben en la fila que lee la ficha: la canónica si la hay.
    assert {lic: len(refs) for lic, refs in repo.escritos.items()} == {
        agregada: 2,
        "ted:723357-2026": 3,
    }
    assert (resumen.candidatas, resumen.con_documentos, resumen.referencias) == (2, 2, 5)


def test_dos_avisos_con_la_misma_canonica_piden_el_portal_una_vez(repo_falso):
    repo_falso([])
    filas = [
        _fila_ted(numero, destino="placsp_agregadas:X:1", url_destino=_FICHA_NAVARRA)
        for numero in ("775188-2026", "773412-2026")
    ]
    pedidas: list[str] = []

    dp.completar_pliegos_ted_en_origen(filas, {}, pausa_s=0, obtener=_portal_de_origen(pedidas))

    assert pedidas == [_FICHA_NAVARRA]


def test_un_portal_caido_no_deja_sin_leer_el_otro(repo_falso):
    repo = repo_falso([])
    filas = [
        *(_fila_ted(f"{i}-2026", url=_PERFIL_JUNTA) for i in range(1, 8)),
        _fila_ted("797644-2026", url=_FICHA_NAVARRA),
    ]
    origenes = {
        f["id_externo"]: dp.OrigenTed(f"CONTR 2026 {i}0000", ()) for i, f in enumerate(filas)
    }
    pedidas: list[str] = []

    def pedir(url: str, cuerpo: bytes | None) -> bytes:
        pedidas.append(url)
        if url == dp._API_ANDALUCIA:
            raise ConnectionError("la Junta no contesta")
        return _FIXTURE_NAVARRA.read_bytes()

    resumen = dp.completar_pliegos_ted_en_origen(filas, origenes, pausa_s=0, obtener=pedir)

    assert pedidas == [dp._API_ANDALUCIA] * 5 + [_FICHA_NAVARRA]
    assert set(repo.escritos) == {"ted:797644-2026"}
    assert (resumen.fallidas, resumen.con_documentos) == (5, 1)


def test_los_pliegos_en_origen_no_pasan_de_su_presupuesto(repo_falso, monkeypatch):
    repo_falso([])
    filas = [_fila_ted(f"{i}-2026", url=_FICHA_NAVARRA, destino=f"d{i}") for i in range(3)]
    instantes = iter([100.0, 100.0, 100.0, 108.0, 108.0, 111.0])
    topes: list[tuple[str, float]] = []

    def obtener(
        url: str, *, host: str, timeout_s: float | None = None, cuerpo: Any = None
    ) -> bytes:
        topes.append((host, float(timeout_s or 0)))
        return _FIXTURE_NAVARRA.read_bytes()

    monkeypatch.setattr(dp, "_obtener", obtener)

    resumen = dp.completar_pliegos_ted_en_origen(
        filas, {}, presupuesto_s=10, pausa_s=0, reloj=lambda: next(instantes)
    )

    # Cada petición con lo que queda; la tercera fila ya no se pide.
    assert topes == [("hacienda.navarra.es", 10.0), ("hacienda.navarra.es", 2.0)]
    assert (resumen.candidatas, resumen.sin_presupuesto) == (2, True)
    # Lo que se descarga después: las filas escritas, que no son un contador del log.
    assert resumen.escritas == ["d0", "d1"]
    assert "escritas" not in resumen.as_dict()


class _RepoDeDescargas:
    """Los pendientes de unas licitaciones y lo que se devuelve a la cola."""

    def __init__(self, pendientes: list[dict[str, Any]]) -> None:
        self.pendientes = pendientes
        self.pedidas: list[tuple[list[str], int]] = []
        self.reencolados: list[int] = []

    def list_pendientes_de(self, licitacion_ids: Any, limit: int = 60) -> list[dict[str, Any]]:
        self.pedidas.append((list(licitacion_ids), limit))
        return self.pendientes

    def reencolar_escaneado(self, documento_id: int) -> None:
        self.reencolados.append(documento_id)


@pytest.fixture()
def descargas(monkeypatch):
    def instalar(n: int, *, ocr: str | None = None) -> _RepoDeDescargas:
        repo = _RepoDeDescargas([{"id": i, "uri": f"https://x/{i}"} for i in range(1, n + 1)])
        monkeypatch.setattr("db.repositories.documentos.DocumentosRepository", lambda: repo)
        monkeypatch.setattr("scraper.document_fetcher.ocr_binario", lambda: ocr)
        return repo

    return instalar


def test_los_pliegos_recien_registrados_se_descargan_en_la_misma_pasada(descargas):
    repo = descargas(3)
    estados = iter(["extracted", "error", "unsupported"])
    bajados: list[int] = []

    def descargar(documento: Any) -> str:
        bajados.append(documento["id"])
        return next(estados)

    resultado = dp.descargar_pliegos(["ted:1-2026", "agregada:2"], descargar=descargar)

    assert repo.pedidas == [(["ted:1-2026", "agregada:2"], 60)]
    assert bajados == [1, 2, 3]
    assert resultado == {"extracted": 1, "error": 1, "unsupported": 1}


def test_sin_pliegos_nuevos_no_se_descarga_ni_se_consulta(descargas):
    repo = descargas(2)

    assert dp.descargar_pliegos([], descargar=lambda documento: "extracted") == {}
    assert repo.pedidas == []


def test_un_escaneado_sin_ocr_en_la_ingesta_vuelve_a_la_cola_de_la_noche(descargas):
    """``sin_texto`` es terminal, y aquí nadie ha intentado leerlo: no hay OCR."""
    repo = descargas(1)

    resultado = dp.descargar_pliegos(["ted:1-2026"], descargar=lambda documento: "sin_texto")

    assert repo.reencolados == [1]
    assert resultado == {"escaneado_para_la_noche": 1}


def test_sin_ocr_un_zip_se_deja_entero_para_la_noche(descargas):
    """El extractor se salta las entradas escaneadas de un ZIP y lo da por ``extracted``:
    leído aquí a medias, el lote nocturno ya no lo abriría con OCR."""
    repo = descargas(0)
    repo.pendientes = [
        {"id": 1, "uri": "https://x/descarga?DOL=1", "filename": "DOUE/DEUC/espd-request.ZIP"},
        {"id": 2, "uri": "https://x/pliegos.zip?v=2", "filename": None},
        {"id": 3, "uri": "https://x/descarga?DOL=3", "filename": "Pliego.pdf"},
    ]
    bajados: list[int] = []

    resultado = dp.descargar_pliegos(
        ["ted:1-2026"], descargar=lambda d: (bajados.append(d["id"]), "extracted")[1]
    )

    assert bajados == [3]
    assert resultado == {"zip_para_la_noche": 2, "extracted": 1}


def test_con_ocr_el_zip_se_lee_en_la_misma_pasada(descargas):
    repo = descargas(0, ocr="/usr/bin/ocrmypdf")
    repo.pendientes = [{"id": 1, "uri": "https://x/pliegos.zip", "filename": None}]

    assert dp.descargar_pliegos(["ted:1-2026"], descargar=lambda d: "extracted") == {"extracted": 1}


def test_si_no_se_puede_reencolar_el_escaneado_el_resto_sigue(descargas):
    repo = descargas(2)

    def roto(documento_id: int) -> None:
        raise RuntimeError("BD caída")

    repo.reencolar_escaneado = roto
    estados = iter(["sin_texto", "extracted"])

    resultado = dp.descargar_pliegos(["ted:1-2026"], descargar=lambda d: next(estados))

    assert resultado == {"fallo_inesperado": 1, "extracted": 1}


def test_un_escaneado_que_el_ocr_no_pudo_leer_se_queda_sin_texto(descargas):
    repo = descargas(1, ocr="/usr/bin/ocrmypdf")

    resultado = dp.descargar_pliegos(["ted:1-2026"], descargar=lambda documento: "sin_texto")

    assert repo.reencolados == []
    assert resultado == {"sin_texto": 1}


def test_la_descarga_no_pasa_de_su_presupuesto_y_un_fallo_no_corta_el_resto(descargas):
    descargas(4)
    # El inicio y, por documento, el instante en que se mira el presupuesto y el de después.
    instantes = iter([0.0, 0.0, 5.0, 50.0, 55.0, 130.0, 130.0])
    bajados: list[int] = []

    def descargar(documento: Any) -> str:
        bajados.append(documento["id"])
        if documento["id"] == 1:
            raise RuntimeError("PDF que tumba al extractor")
        return "extracted"

    resultado = dp.descargar_pliegos(
        ["ted:1-2026"], presupuesto_s=120, descargar=descargar, reloj=lambda: next(instantes)
    )

    # El primero falla sin clasificar y sigue `pending`; los dos últimos no caben.
    assert bajados == [1, 2]
    assert resultado == {"fallo_inesperado": 1, "extracted": 1, "sin_presupuesto": 2}


def test_un_portal_que_tarda_deja_sus_documentos_para_el_final(descargas):
    """Pasada del 2026-11-19: los reintentos de Navarra se llevaron el presupuesto
    entero y no se llegó a pedir ningún documento de Andalucía."""
    repo = descargas(0)
    navarra, andalucia = "https://hacienda.navarra.es/doc", "https://www.juntadeandalucia.es/doc"
    repo.pendientes = [  # como los da `list_pendientes_de`: los pliegos delante de los anexos
        {"id": 1, "tipo": "legal", "uri": f"{navarra}/1"},
        {"id": 2, "tipo": "technical", "uri": f"{navarra}/2"},
        {"id": 3, "tipo": "legal", "uri": f"{andalucia}/3"},
        {"id": 4, "tipo": "additional", "uri": f"{navarra}/4"},
        {"id": 5, "tipo": "additional", "uri": f"{andalucia}/5"},
        {"id": 6, "tipo": "additional", "uri": f"{navarra}/6"},
    ]
    ahora = [0.0]
    bajados: list[int] = []

    def descargar(documento: Any) -> str:
        bajados.append(documento["id"])
        ahora[0] += 40.0 if documento["uri"].startswith(navarra) else 4.0
        return "extracted"

    resultado = dp.descargar_pliegos(
        ["ted:1-2026"], presupuesto_s=120, descargar=descargar, reloj=lambda: ahora[0]
    )

    # Navarra cede el turno dentro de cada clase: su pliego 2 va tras el 3 de Andalucía y
    # antes que ningún anexo; su anexo 4, tras el 5; para el 6 ya no queda presupuesto.
    assert bajados == [1, 3, 2, 5, 4]
    assert resultado == {"extracted": 5, "sin_presupuesto": 1}


class _RepoFalso:
    def __init__(self, filas: list[dict[str, Any]]) -> None:
        self.filas = filas
        self.escritos: dict[str, list[DocumentoReferencia]] = {}
        #: Llamadas a ``upsert_meta_batch``; las filas de ``fallan`` no se escriben.
        self.lotes = 0
        self.fallan: set[str] = set()

    def pscp_para_documentos(
        self, limit: int = 200, *, dias_cambio: int | None = 7
    ) -> list[dict[str, Any]]:
        return self.filas[:limit]

    def ted_vigentes_sin_documentos(self, limit: int = 300) -> list[str]:
        return [f["id_externo"] for f in self.filas][:limit]

    def andalucia_para_documentos(self, limit: int = 60) -> list[dict[str, Any]]:
        return self.filas[:limit]

    def upsert_meta(self, licitacion_id: str, refs: list[DocumentoReferencia]) -> int:
        self.escritos[licitacion_id] = refs
        return len(refs)

    def upsert_meta_batch(
        self, docs_por_lic: dict[str, list[DocumentoReferencia]]
    ) -> dict[str, Exception]:
        self.lotes += 1
        for lic, refs in docs_por_lic.items():
            if lic not in self.fallan:
                self.escritos[lic] = refs
        return {lic: RuntimeError("roto") for lic in docs_por_lic if lic in self.fallan}


@pytest.fixture()
def repo_falso(monkeypatch):
    def instalar(filas: list[dict[str, Any]]) -> _RepoFalso:
        repo = _RepoFalso(filas)
        monkeypatch.setattr("db.repositories.documentos.DocumentosRepository", lambda: repo)
        return repo

    return instalar


def test_completar_pscp_escribe_pliegos_y_empareja_el_anuncio_ted(repo_falso, monkeypatch):
    repo = repo_falso([{"id_externo": "pscp:2026/6150/1428", "url": _FICHA_PSCP}])
    marcadas: list[tuple[str, list[str]]] = []

    def marcar(canonica: str, numeros: list[str]) -> RepublicacionesTed:
        marcadas.append((canonica, list(numeros)))
        return RepublicacionesTed(marcadas=[f"ted:{n}" for n in numeros])

    monkeypatch.setattr("services.dedupe.marcar_republicaciones_ted", marcar)

    resumen = dp.completar_documentos_pscp(
        pausa_s=0, obtener=lambda url: _FIXTURE_PSCP.read_bytes()
    )

    assert len(repo.escritos["pscp:2026/6150/1428"]) == 5
    assert marcadas == [("pscp:2026/6150/1428", ["675385-2026"])]
    assert (resumen.candidatas, resumen.con_documentos, resumen.emparejadas) == (1, 1, 1)


def test_si_la_ficha_pscp_no_se_publica_sus_pliegos_van_al_anuncio_ted(repo_falso, monkeypatch):
    """PSCP guarda sin etiqueta lo que entra solo por CPV; TED lo publica igual."""
    repo = repo_falso([{"id_externo": "pscp:2026/6150/1428", "url": _FICHA_PSCP}])
    monkeypatch.setattr(
        "services.dedupe.marcar_republicaciones_ted",
        lambda canonica, numeros: RepublicacionesTed(sin_canonica_visible=["ted:675385-2026"]),
    )

    resumen = dp.completar_documentos_pscp(
        pausa_s=0, obtener=lambda url: _FIXTURE_PSCP.read_bytes()
    )

    assert repo.escritos["ted:675385-2026"] == repo.escritos["pscp:2026/6150/1428"]
    assert len(repo.escritos["ted:675385-2026"]) == 5
    assert (resumen.con_documentos, resumen.emparejadas) == (2, 0)


def test_completar_pscp_corta_tras_cinco_fallos_seguidos(repo_falso, monkeypatch):
    filas = [{"id_externo": f"pscp:{i}", "url": _FICHA_PSCP} for i in range(20)]
    repo_falso(filas)
    monkeypatch.setattr(
        "services.dedupe.marcar_republicaciones_ted", lambda *a: RepublicacionesTed()
    )
    pedidas = 0

    def caida(url: str) -> bytes:
        nonlocal pedidas
        pedidas += 1
        raise ConnectionError("plataforma caída")

    resumen = dp.completar_documentos_pscp(pausa_s=0, obtener=caida)

    assert pedidas == 5
    assert resumen.fallidas == 5
    assert len(resumen.as_dict()["errores"]) == 5


def test_si_no_llega_la_ficha_del_anuncio_cuenta_como_fallo_y_no_escribe(repo_falso):
    repo = repo_falso([{"id_externo": "pscp:cerrada", "url": _FICHA_CERRADA}])

    def obtener(url: str) -> bytes:
        if url.endswith("/300719618"):
            raise ConnectionError("plataforma caída")
        return _FIXTURE_FORMALITZACIO.read_bytes()

    resumen = dp.completar_documentos_pscp(pausa_s=0, obtener=obtener)

    assert (resumen.candidatas, resumen.fallidas, repo.escritos) == (1, 1, {})


def test_completar_pscp_respeta_el_presupuesto(repo_falso, monkeypatch):
    repo_falso([{"id_externo": f"pscp:{i}", "url": _FICHA_PSCP} for i in range(3)])
    monkeypatch.setattr(
        "services.dedupe.marcar_republicaciones_ted", lambda *a: RepublicacionesTed()
    )

    resumen = dp.completar_documentos_pscp(
        presupuesto_s=-1, pausa_s=0, obtener=lambda url: _FIXTURE_PSCP.read_bytes()
    )

    assert resumen.sin_presupuesto
    assert resumen.candidatas == 0


def test_completar_ted_da_el_anuncio_a_cada_candidata(repo_falso):
    repo = repo_falso([{"id_externo": "ted:1-2026"}, {"id_externo": "ted:2-2026"}])

    resumen = dp.completar_documentos_ted()

    assert [r.uri for r in repo.escritos["ted:1-2026"]] == [
        "https://ted.europa.eu/es/notice/1-2026/pdf"
    ]
    assert set(repo.escritos) == {"ted:1-2026", "ted:2-2026"}
    assert resumen.con_documentos == 2
    assert repo.lotes == 1  # una escritura para todas, no una por fila


def test_completar_ted_cuenta_la_fila_que_no_se_pudo_escribir(repo_falso):
    repo = repo_falso([{"id_externo": "ted:1-2026"}, {"id_externo": "ted:2-2026"}])
    repo.fallan = {"ted:2-2026"}

    resumen = dp.completar_documentos_ted()

    assert set(repo.escritos) == {"ted:1-2026"}
    assert (resumen.con_documentos, resumen.referencias, resumen.fallidas) == (1, 1, 1)
    assert resumen.errores == ["ted:2-2026: roto"]


def test_completar_andalucia_escribe_los_pliegos_de_cada_vigente(repo_falso):
    repo = repo_falso(
        [
            {"id_externo": "placsp_agregadas:EICE21:EXPT26-00040", "url": _FICHA_ANDALUCIA},
            {"id_externo": "placsp_agregadas:X:sin-ficha", "url": "https://otra.example/"},
        ]
    )

    resumen = dp.completar_documentos_andalucia(
        pausa_s=0, obtener=lambda url, cuerpo: _FIXTURE_ANDALUCIA.read_bytes()
    )

    assert len(repo.escritos["placsp_agregadas:EICE21:EXPT26-00040"]) == 3
    assert set(repo.escritos) == {"placsp_agregadas:EICE21:EXPT26-00040"}
    assert (resumen.candidatas, resumen.con_documentos, resumen.referencias) == (2, 1, 3)


def test_completar_andalucia_corta_tras_cinco_fallos_seguidos(repo_falso):
    repo_falso([{"id_externo": f"a:{i}", "url": _FICHA_ANDALUCIA} for i in range(20)])
    pedidas = 0

    def caida(url: str, cuerpo: bytes) -> bytes:
        nonlocal pedidas
        pedidas += 1
        raise ConnectionError("plataforma caída")

    resumen = dp.completar_documentos_andalucia(pausa_s=0, obtener=caida)

    assert (pedidas, resumen.fallidas) == (5, 5)


def test_completar_andalucia_no_deja_que_una_peticion_pase_del_presupuesto(repo_falso, monkeypatch):
    repo_falso([{"id_externo": f"a:{i}", "url": _FICHA_ANDALUCIA} for i in range(2)])
    instantes = iter([100.0, 100.0, 100.0, 108.0, 108.0])
    topes: list[float] = []

    def obtener(
        url: str, *, host: str, timeout_s: float | None = None, cuerpo: Any = None
    ) -> bytes:
        assert (host, json.loads(cuerpo)) == (
            "www.juntadeandalucia.es",
            {"query": {"match": {"_id": "1036313"}}},
        )
        topes.append(float(timeout_s or 0))
        return _FIXTURE_ANDALUCIA.read_bytes()

    monkeypatch.setattr(dp, "_obtener", obtener)

    resumen = dp.completar_documentos_andalucia(
        presupuesto_s=10, pausa_s=0, reloj=lambda: next(instantes)
    )

    assert resumen.candidatas == 2
    assert topes == [10.0, 2.0]


# ── Conectores y runner ──────────────────────────────────────────────────────


def test_ted_reempareja_antes_de_dar_anuncios_y_un_fallo_no_salta_el_otro(monkeypatch):
    from scraper.connectors.ted import TedConnector

    orden: list[str] = []

    def reemparejar() -> Any:
        orden.append("reemparejar")
        raise RuntimeError("BD caída")

    def vigentes(self: TedConnector) -> Any:
        orden.append("vigentes")
        raise ConnectionError("API de TED caída")

    def en_origen(self: TedConnector) -> Any:
        orden.append("origen")
        raise ConnectionError("portal caído")

    def completar() -> dp.ResumenDocumentos:
        orden.append("anuncios")
        return dp.ResumenDocumentos()

    monkeypatch.setattr("services.dedupe.reemparejar_ted_por_id_evl", reemparejar)
    monkeypatch.setattr(TedConnector, "reemparejar_vigentes", vigentes)
    monkeypatch.setattr(TedConnector, "pliegos_en_origen", en_origen)
    monkeypatch.setattr("scraper.documentos_plataforma.completar_documentos_ted", completar)

    TedConnector().completar_documentos()

    # Los pliegos del portal van tras emparejar (se escriben en la canónica) y
    # antes del anuncio, que es solo para quien se queda sin nada.
    assert orden == ["reemparejar", "vigentes", "origen", "anuncios"]


def test_ted_apunta_los_pliegos_registrados_y_no_los_descarga_en_el_cierre(monkeypatch):
    """``completar_documentos`` corre delante de los eventos de contrato y del registro
    de la pasada: la descarga, que es lo más largo, no va ahí."""
    from scraper.connectors.ted import TedConnector

    orden: list[Any] = []

    def paso(nombre: str, resumen: Any) -> Any:
        return lambda *a, **kw: (orden.append(nombre), resumen)[1]

    registrados = dp.ResumenDocumentos(escritas=["placsp_agregadas:NA:1", "ted:2-2026"])
    monkeypatch.setattr(
        "services.dedupe.reemparejar_ted_por_id_evl", paso("reemparejar", dp.ResumenDocumentos())
    )
    monkeypatch.setattr(
        TedConnector, "reemparejar_vigentes", paso("vigentes", dp.ResumenDocumentos())
    )
    monkeypatch.setattr(TedConnector, "pliegos_en_origen", paso("origen", registrados))
    monkeypatch.setattr(dp, "completar_documentos_ted", paso("anuncios", dp.ResumenDocumentos()))
    monkeypatch.setattr(dp, "descargar_pliegos", paso("descarga", {}))
    conector = TedConnector()

    conector.completar_documentos()

    assert orden == ["reemparejar", "vigentes", "origen", "anuncios"]
    assert conector._con_pliegos == ["placsp_agregadas:NA:1", "ted:2-2026"]


def test_ted_descarga_los_pliegos_con_la_pasada_ya_cerrada(monkeypatch):
    """Si el step se corta en la descarga, el cursor, los eventos y la salud ya están escritos."""
    from scraper.connectors import base, ted

    orden: list[Any] = []

    def run_connector(connector: Any) -> str:
        connector._con_pliegos = ["placsp_agregadas:NA:1"]  # lo que deja el cierre del lote
        orden.append("pasada cerrada")
        return "resultado"

    def descargar(licitaciones: Any) -> dict[str, int]:
        orden.append(list(licitaciones))
        raise ConnectionError("portal caído")  # fail-open: la pasada ya está hecha

    class Repo:
        """Lo que otra pasada registró y no bajó; una de ellas se ha vuelto a escribir en esta."""

        def ted_con_pliegos_en_cola(self, prefijos_uri: Any) -> list[str]:
            assert prefijos_uri == dp.DESCARGAS_EN_ORIGEN
            return ["placsp_agregadas:NA:1", "ted:7-2026"]

    monkeypatch.setattr(base, "run_connector", run_connector)
    monkeypatch.setattr(dp, "descargar_pliegos", descargar)
    monkeypatch.setattr("db.repositories.documentos.DocumentosRepository", Repo)

    assert ted.ejecutar() == "resultado"
    assert orden == ["pasada cerrada", ["placsp_agregadas:NA:1", "ted:7-2026"]]


class _RespuestaTed:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _ApiTedReferencias:
    """API de TED que contesta ``publication-number IN (…)`` con los avisos que tiene."""

    def __init__(self, avisos: dict[str, dict[str, Any]]) -> None:
        self.avisos = avisos
        self.pedidos: list[list[str]] = []

    def post(self, url: str, json: dict[str, Any], timeout: float) -> _RespuestaTed:
        numeros = json["query"].removeprefix("publication-number IN (").removesuffix(")").split()
        self.pedidos.append(numeros)
        return _RespuestaTed({"notices": [self.avisos[n] for n in numeros if n in self.avisos]})


def test_ted_reempareja_las_vigentes_releyendo_sus_referencias(monkeypatch):
    """BT-22 y BT-04 no se guardan: se le piden de nuevo a la API, por lotes."""
    from scraper.connectors import ted

    monkeypatch.setattr(ted, "_PAGE_SIZE", 2)
    monkeypatch.setattr(ted, "_PAGE_PAUSE_S", 0)
    excluidas: list[list[str]] = []

    def vigentes(limit: int, *, excluir: list[str]) -> list[str]:
        excluidas.append(list(excluir))
        todas = ["ted:111-2026", "ted:222-2026", "ted:333-2026", "ted:mal", "ted:999-2026"]
        return [i for i in todas if i not in excluir]

    monkeypatch.setattr("db.repositories.dedupe.ted_vigentes_sin_pareja", vigentes)
    api = _ApiTedReferencias(
        {
            "111-2026": {"publication-number": "111-2026", "internal-identifier-proc": "EJIE-1"},
            "222-2026": {"publication-number": "222-2026"},
            "333-2026": {"publication-number": "333-2026", "procedure-identifier": "AB-CD"},
        }
    )
    recibidas: dict[str, ReferenciaCruzada] = {}

    def detectar(*, fuente: str, referencias: dict[str, ReferenciaCruzada]) -> Any:
        assert fuente == "ted"
        recibidas.update(referencias)
        return dp.ResumenDocumentos()

    monkeypatch.setattr("services.dedupe.detect_duplicados_por_referencia", detectar)
    connector = ted.TedConnector(session=api)
    # La pasada ya releyó 999: su referencia se evaluó en el cierre del lote.
    connector._referencias["ted:999-2026"] = ReferenciaCruzada(expediente="X")

    connector.reemparejar_vigentes()

    # Lo ya evaluado se quita en la consulta, antes de su LIMIT, no después.
    assert excluidas == [["ted:999-2026"]]
    assert api.pedidos == [["111-2026", "222-2026"], ["333-2026"]]
    assert recibidas == {
        "ted:111-2026": ReferenciaCruzada(expediente="EJIE-1"),
        "ted:333-2026": ReferenciaCruzada(procedimiento="ab-cd"),
    }


def test_ted_reemparejo_no_pasa_de_su_presupuesto(monkeypatch):
    """Corre dentro del cierre del lote: lo que no pide esta pasada lo pide la siguiente."""
    from scraper.connectors import ted

    monkeypatch.setattr(ted, "_PAGE_SIZE", 1)
    monkeypatch.setattr(ted, "_PAGE_PAUSE_S", 0)
    monkeypatch.setattr(
        "db.repositories.dedupe.ted_vigentes_sin_pareja",
        lambda limit, excluir: ["ted:111-2026", "ted:222-2026"],
    )
    monkeypatch.setattr(
        "services.dedupe.detect_duplicados_por_referencia", lambda **kw: dp.ResumenDocumentos()
    )
    api = _ApiTedReferencias({})
    instantes = iter([0.0, 0.0, 61.0])

    ted.TedConnector(session=api).reemparejar_vigentes(reloj=lambda: next(instantes))

    assert api.pedidos == [["111-2026"]]


@pytest.fixture()
def en_origen(repo_falso, monkeypatch):
    """Conector TED con dos convocatorias sin pliegos; devuelve lo que recibe el paso."""
    from scraper.connectors import ted

    repo = repo_falso([_fila_ted("111-2026"), _fila_ted("222-2026", url=_FICHA_NAVARRA)])
    repo.ted_vigentes_sin_pliegos = lambda limit: repo.filas[:limit]
    recibido: dict[str, Any] = {}

    def completar(filas: Any, origenes: Any) -> dp.ResumenDocumentos:
        recibido.update(filas=filas, origenes=origenes)
        return dp.ResumenDocumentos(candidatas=len(filas))

    monkeypatch.setattr(ted, "_PAGE_PAUSE_S", 0)
    monkeypatch.setattr(dp, "completar_pliegos_ted_en_origen", completar)
    return recibido


def test_ted_relee_del_aviso_el_expediente_y_los_enlaces_al_portal(en_origen):
    """Ni el BT-22 ni el perfil del comprador se guardan: salen de la API en la misma pasada."""
    from scraper.connectors import ted

    api = _ApiTedReferencias(
        {
            "111-2026": {
                "publication-number": "111-2026",
                "internal-identifier-proc": "CONTR 2026 185738",
                "document-url-lot": [_PERFIL_JUNTA, _PERFIL_JUNTA],
                "buyer-profile": "https://juntadeandalucia.es/perfil",
            }
        }
    )

    resumen = ted.TedConnector(session=api).pliegos_en_origen()

    assert api.pedidos == [["111-2026", "222-2026"]]
    assert en_origen["origenes"] == {
        "ted:111-2026": dp.OrigenTed(
            "CONTR 2026 185738", (_PERFIL_JUNTA, "https://juntadeandalucia.es/perfil")
        )
    }
    assert [f["id_externo"] for f in en_origen["filas"]] == ["ted:111-2026", "ted:222-2026"]
    assert resumen.candidatas == 2


def test_sin_la_api_de_ted_el_portal_se_pide_con_lo_que_hay_en_la_bd(en_origen):
    """La ficha de Navarra sale de la ``url`` guardada: no depende de releer el aviso."""
    from scraper.connectors import ted

    class _ApiCaida:
        def post(self, url: str, json: Any, timeout: float) -> Any:
            raise ConnectionError("API de TED caída")

    ted.TedConnector(session=_ApiCaida()).pliegos_en_origen()

    assert en_origen["origenes"] == {}
    assert len(en_origen["filas"]) == 2


def test_post_ingestion_completa_documentos_tras_el_dedupe_y_es_fail_open(monkeypatch):
    from scraper.connectors import base

    orden: list[str] = []
    monkeypatch.setattr(
        "services.entity_resolution.resolve_all_unlinked", lambda **kw: orden.append("empresas")
    )
    monkeypatch.setattr("services.dedupe.detect_duplicates", lambda **kw: orden.append("dedupe"))
    monkeypatch.setattr(
        "services.dedupe.detect_duplicados_por_referencia",
        lambda **kw: orden.append("referencias"),
    )
    monkeypatch.setattr(
        "services.contract_events.derive_new_events", lambda: orden.append("eventos")
    )
    monkeypatch.setattr("db.cache_signal.signal_cache_invalidation", lambda: orden.append("cache"))

    def completar() -> None:
        orden.append("documentos")
        raise RuntimeError("plataforma caída")

    base._post_ingestion(
        "ted",
        referencias={"ted:1-2026": ReferenciaCruzada(id_evl="CEGLc1/kxg/E6P/uLemXRw==")},
        completar_documentos=completar,
    )

    assert orden == ["empresas", "dedupe", "referencias", "documentos", "eventos", "cache"]


def test_completar_documentos_es_opt_in_por_atributo():
    from scraper.connectors.base import _completar_documentos_de
    from scraper.connectors.pscp import PscpConnector
    from scraper.connectors.ted import TedConnector

    class _Sin:
        source_id = "x"

    assert _completar_documentos_de(_Sin()) is None  # type: ignore[arg-type]
    assert _completar_documentos_de(TedConnector()) is not None
    assert _completar_documentos_de(PscpConnector()) is not None


class _ConectorSinFilas:
    """La pasada habitual de PSCP: el dataset no trae nada nuevo desde el cursor."""

    source_id = "pscp"

    def __init__(self, completar: Any) -> None:
        self._completar = completar

    def fetch(self, cursor: Any) -> Any:
        return iter(())

    def parse(self, raw: Any) -> Any:
        raise AssertionError("no hay nada que parsear")

    def new_cursor(self) -> None:
        return None

    def completar_documentos(self) -> None:
        self._completar()


@pytest.fixture()
def runner_sin_bd(monkeypatch):
    """``run_connector`` sin Postgres: el cursor y la salud de la fuente, doblados."""
    from scraper.connectors import base

    monkeypatch.setattr(base, "get_cursor", lambda source_id: None)
    monkeypatch.setattr(base, "record_source_started", lambda source_id: None)
    monkeypatch.setattr(base, "_record_source_completed", lambda result: None)
    return base


def test_sin_filas_nuevas_el_runner_completa_documentos_igual(runner_sin_bd, monkeypatch):
    """El paso lee de la BD las convocatorias vigentes: no depende del lote.

    Hasta el 2026-10-03 colgaba solo de ``_post_ingestion``, que el runner se
    salta cuando no parsea nada. PSCP actualiza su dataset una vez al día, así
    que casi todas sus pasadas son de cero filas: en producción no llegó a leer
    ni una ficha (0 filas PSCP con documentos tras la primera pasada de #395).
    """
    completadas: list[str] = []
    cierres: list[str] = []
    monkeypatch.setattr(runner_sin_bd, "_post_ingestion", lambda *a, **k: cierres.append("x"))

    resultado = runner_sin_bd.run_connector(_ConectorSinFilas(lambda: completadas.append("x")))

    assert (resultado.fetched, resultado.parsed) == (0, 0)
    assert completadas == ["x"]
    # Sin lote no hay empresas que resolver ni filas que deduplicar.
    assert cierres == []


def test_sin_filas_un_completar_roto_no_tumba_la_pasada(runner_sin_bd):
    def roto() -> None:
        raise RuntimeError("plataforma caída")

    resultado = runner_sin_bd.run_connector(_ConectorSinFilas(roto))

    assert resultado.errores == 0
    assert not resultado.fetch_failed


# ── Con lote: el paso de PSCP no espera al cierre del lote ───────────────────


class _CorteDelStep(BaseException):
    """El ``timeout-minutes`` del step: mata el proceso, no es una ``Exception``.

    Hereda de ``BaseException`` a propósito, como ``SystemExit``: nada del
    runner la atrapa, igual que nada sobrevive a que Actions mate el proceso.
    """


class _ConectorConLote:
    """Una pasada con una fila: la que de verdad ocurría el 2026-10-03."""

    def __init__(self, source_id: str, completar: Any, *, primero: bool) -> None:
        self.source_id = source_id
        self._completar = completar
        if primero:
            self.completar_documentos_primero = True

    def fetch(self, cursor: Any) -> Any:
        from scraper.connectors.base import RawNotice

        yield RawNotice(natural_id="1", payload={})

    def parse(self, raw: Any) -> Any:
        from db.upsert import Licitacion
        from scraper.connectors.base import ParsedTender

        return ParsedTender(
            licitacion=Licitacion(
                id_externo=f"{self.source_id}:1",
                titulo="Llicències de programari de gestió documental",
                fuente=self.source_id,
            )
        )

    def new_cursor(self) -> None:
        return None

    def completar_documentos(self) -> None:
        self._completar()


@pytest.fixture()
def runner_con_lote(runner_sin_bd, monkeypatch):
    """``run_connector`` con lote y sin BD: el upsert devuelve una fila nueva."""
    from db.upsert import UpsertResult

    monkeypatch.setattr(
        runner_sin_bd,
        "upsert_licitaciones_with_history",
        lambda lics, source: UpsertResult(
            inserted=[lic.id_externo for lic in lics], modified=[], unchanged=[]
        ),
    )
    return runner_sin_bd


def test_con_lote_pscp_lee_las_fichas_antes_de_que_el_step_corte_el_cierre(
    runner_con_lote, monkeypatch
):
    """La segunda causa del backlog: con filas, el corte llegaba antes que el paso.

    El 2026-10-03 (run 37126368765) el cursor quedó escrito 3 s después de la
    última página y el step murió a los 10 minutos dentro de la resolución de
    empresas, que va primero en ``_post_ingestion``: el paso de documentos,
    detrás de ella y de los dos dedupes, no llegó a correr. El paso no lee nada
    de lo que esos pasos escriben, así que PSCP lo pide **antes**.
    """
    orden: list[str] = []

    def empresas(**kw: Any) -> None:
        orden.append("empresas")
        raise _CorteDelStep

    monkeypatch.setattr("services.entity_resolution.resolve_all_unlinked", empresas)

    conector = _ConectorConLote("pscp", lambda: orden.append("documentos"), primero=True)
    with pytest.raises(_CorteDelStep):
        runner_con_lote.run_connector(conector)

    assert orden == ["documentos", "empresas"]


def test_con_lote_el_paso_primero_no_se_repite_dentro_del_cierre(runner_con_lote, monkeypatch):
    llamadas: list[str] = []
    for paso in (
        "services.entity_resolution.resolve_all_unlinked",
        "services.dedupe.detect_duplicates",
    ):
        monkeypatch.setattr(paso, lambda **kw: None)
    monkeypatch.setattr("services.contract_events.derive_new_events", lambda: None)
    monkeypatch.setattr("db.cache_signal.signal_cache_invalidation", lambda: None)

    conector = _ConectorConLote("pscp", lambda: llamadas.append("x"), primero=True)
    resultado = runner_con_lote.run_connector(conector)

    assert resultado.parsed == 1
    assert llamadas == ["x"]


def test_sin_declararlo_el_paso_sigue_detras_de_los_dedupes(runner_con_lote, monkeypatch):
    """TED y PLACSP no cambian: su paso necesita las marcas que deja el dedupe.

    Un aviso TED recién emparejado lee los pliegos de su canónica, y el paso lo
    sabe por la marca que el dedupe acaba de escribir.
    """
    orden: list[str] = []
    monkeypatch.setattr(
        "services.entity_resolution.resolve_all_unlinked", lambda **kw: orden.append("empresas")
    )
    monkeypatch.setattr("services.dedupe.detect_duplicates", lambda **kw: orden.append("dedupe"))
    monkeypatch.setattr("services.contract_events.derive_new_events", lambda: None)
    monkeypatch.setattr("db.cache_signal.signal_cache_invalidation", lambda: None)

    conector = _ConectorConLote("ted", lambda: orden.append("documentos"), primero=False)
    runner_con_lote.run_connector(conector)

    assert orden == ["empresas", "dedupe", "documentos"]


def test_pscp_y_agregadas_piden_el_paso_de_documentos_antes_del_cierre():
    from scraper.connectors.placsp import PlacspAtomConnector, PlacspBulkConnector
    from scraper.connectors.placsp_agregadas import (
        URL_SINDICACION_1044,
        PlacspAgregadasConnector,
    )
    from scraper.connectors.pscp import PscpConnector
    from scraper.connectors.ted import TedConnector

    for primero in (PscpConnector(), PlacspAgregadasConnector(URL_SINDICACION_1044)):
        assert getattr(primero, "completar_documentos_primero", False) is True
    for otro in (TedConnector(), PlacspAtomConnector(), PlacspBulkConnector(2026, 9)):
        assert not getattr(otro, "completar_documentos_primero", False)


def test_el_conector_de_agregadas_lee_los_pliegos_de_andalucia(monkeypatch):
    from scraper.connectors.placsp_agregadas import (
        URL_SINDICACION_1044,
        PlacspAgregadasConnector,
    )

    llamadas: list[str] = []

    def completar() -> dp.ResumenDocumentos:
        llamadas.append("andalucia")
        return dp.ResumenDocumentos()

    monkeypatch.setattr("scraper.documentos_plataforma.completar_documentos_andalucia", completar)

    PlacspAgregadasConnector(URL_SINDICACION_1044).completar_documentos()

    assert llamadas == ["andalucia"]


def test_el_historico_de_agregadas_no_relee_las_fichas_en_cada_mes(monkeypatch):
    from scraper.connectors.placsp_agregadas import PlacspAgregadasHistorico

    def completar() -> dp.ResumenDocumentos:
        raise AssertionError("el histórico no debe pedir fichas")

    monkeypatch.setattr("scraper.documentos_plataforma.completar_documentos_andalucia", completar)

    PlacspAgregadasHistorico(2026, 9, ya_existe=lambda _id: False).completar_documentos()


def test_el_conector_pscp_acota_el_paso_con_su_presupuesto(monkeypatch):
    from scraper.connectors import pscp

    recibido: dict[str, Any] = {}

    def completar(**kw: Any) -> dp.ResumenDocumentos:
        recibido.update(kw)
        return dp.ResumenDocumentos()

    monkeypatch.setattr("scraper.documentos_plataforma.completar_documentos_pscp", completar)

    pscp.PscpConnector().completar_documentos()

    assert recibido["presupuesto_s"] == pscp.PRESUPUESTO_DOCUMENTOS_S
    # Holgura para la resolución de empresas y los dedupes que vienen detrás,
    # dentro de los 10 minutos del step.
    assert 0 < pscp.PRESUPUESTO_DOCUMENTOS_S <= 180


def test_completar_pscp_no_deja_que_una_peticion_pase_del_presupuesto(repo_falso, monkeypatch):
    """Sin tope por petición, una ficha lenta podía alargar el paso 30 s más.

    El presupuesto se miraba solo **antes** de cada ficha; la petición en curso
    tenía el ``REQUEST_TIMEOUT`` entero (30 s) por delante. Con el reloj al
    borde, cada petición recibe lo que queda, y nunca más que el timeout global.
    """
    repo_falso([{"id_externo": f"pscp:{i}", "url": _FICHA_PSCP} for i in range(2)])
    monkeypatch.setattr(
        "services.dedupe.marcar_republicaciones_ted", lambda *a: RepublicacionesTed()
    )
    # Inicio; y por fila, la comprobación del presupuesto y el tope de su petición.
    instantes = iter([100.0, 100.0, 100.0, 108.0, 108.0])
    topes: list[float] = []

    def obtener(url: str, *, host: str, timeout_s: float | None = None) -> bytes:
        assert host == "contractaciopublica.cat"
        topes.append(float(timeout_s or 0))
        return _FIXTURE_PSCP.read_bytes()

    monkeypatch.setattr(dp, "_obtener", obtener)

    resumen = dp.completar_documentos_pscp(
        presupuesto_s=10, pausa_s=0, reloj=lambda: next(instantes)
    )

    assert resumen.candidatas == 2
    assert topes == [10.0, 2.0]


def test_la_ficha_del_anuncio_solo_tiene_lo_que_dejo_la_primera(repo_falso, monkeypatch):
    """Un expediente cerrado pide dos fichas; el tope de la segunda descuenta la primera."""
    repo_falso([{"id_externo": "pscp:cerrada", "url": _FICHA_CERRADA}])
    instantes = iter([100.0, 100.0, 100.0, 107.0])
    topes: list[float] = []
    por_publicacion = {"300751065": _FIXTURE_FORMALITZACIO, "300719618": _FIXTURE_ANUNCI}

    def obtener(url: str, *, host: str, timeout_s: float | None = None) -> bytes:
        topes.append(float(timeout_s or 0))
        return por_publicacion[url.rsplit("/", 1)[-1]].read_bytes()

    monkeypatch.setattr(dp, "_obtener", obtener)

    resumen = dp.completar_documentos_pscp(
        presupuesto_s=10, pausa_s=0, reloj=lambda: next(instantes)
    )

    assert topes == [10.0, 3.0]
    assert (resumen.con_documentos, resumen.referencias) == (1, 4)


# ── Red: un circuito por plataforma ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("host", "nombre"),
    [
        ("ted.europa.eu", "ted"),
        ("contractaciopublica.cat", "pscp"),
        ("www.juntadeandalucia.es", "andalucia"),
        ("hacienda.navarra.es", "navarra"),
        ("www.contratacion.euskadi.eus", "euskadi"),
        ("contratos-publicos.comunidad.madrid", "madrid"),
        ("contrataciondelestado.es", "placsp"),
        ("www.contrataciondelestado.es", "placsp"),
        ("eviltd.europa.eu.example", "placsp"),
        (None, "placsp"),
    ],
)
def test_breaker_por_host(host, nombre):
    from scraper.resilience import breaker_para_host

    assert breaker_para_host(host).name == nombre


def test_la_descarga_pasa_por_el_circuito_de_su_plataforma(monkeypatch):
    import scraper.document_fetcher as df

    usados: list[str | None] = []
    circuito = pybreaker.CircuitBreaker()

    def breaker(host: str | None) -> pybreaker.CircuitBreaker:
        usados.append(host)
        return circuito

    monkeypatch.setattr(df, "breaker_para_host", breaker)
    monkeypatch.setattr(
        df, "_download_bytes_con_reintentos", lambda uri: (b"%PDF", "application/pdf")
    )

    assert df._download_bytes("https://ted.europa.eu/es/notice/1-2026/pdf") == (
        b"%PDF",
        "application/pdf",
    )
    assert usados == ["ted.europa.eu"]


# ---------------------------------------------------------------------------
# Recorrido real contra Postgres
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _dia(desplazamiento: int) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC).date() + timedelta(days=desplazamiento)).isoformat()


def _insertar(c: Any, id_externo: str, **campos: Any) -> None:
    fila: dict[str, Any] = {
        "titulo": "Suministro de licencias de software de gestión documental",
        "organo_contratacion": "Ajuntament d'Esplugues de Llobregat",
        "cpv": "48000000",
        "importe": 120000.0,
        "url": None,
        "fecha_publicacion": _dia(-3),
        "fecha_limite": _dia(20),
        "estado": "PUB",
        "fuente": id_externo.split(":", 1)[0] if ":" in id_externo else "placsp",
        "fecha_extraccion": _dia(0),
        "tecnologia": None,
        "analysis_universe": "technology_observed",
    }
    fila.update(campos)
    columnas = ["id_externo", *fila]
    c.execute(
        f"INSERT INTO licitaciones ({', '.join(columnas)}) "  # noqa: S608 — columnas fijas del test
        f"VALUES ({', '.join(['%s'] * len(columnas))})",
        (id_externo, *fila.values()),
    )


def _documento(c: Any, licitacion_id: str) -> None:
    c.execute(
        "INSERT INTO documentos (licitacion_id, tipo, uri) VALUES (%s, 'legal', %s)",
        (licitacion_id, f"https://contrataciondelestado.es/{licitacion_id}.pdf"),
    )


def _marca(c: Any, licitacion_id: str) -> tuple[Any, ...] | None:
    fila = c.execute(
        "SELECT canonical_id, status FROM licitaciones_duplicados WHERE licitacion_id = %s",
        (licitacion_id,),
    ).fetchone()
    return tuple(fila) if fila else None


def test_integration_ted_vigentes_sin_documentos(db) -> None:
    from db.database import connect
    from db.repositories.documentos import DocumentosRepository

    with connect() as c:
        _insertar(c, "ted:1-2026")  # vigente, sin nada: entra
        _insertar(c, "ted:2-2026")
        _documento(c, "ted:2-2026")  # ya tiene documentos
        _insertar(c, "EXP-CANON")
        _insertar(c, "ted:3-2026")
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, clave_match, "
            " confianza, status) VALUES ('ted:3-2026', 'EXP-CANON', 'idEvl:x', 1.0, 'confirmed')"
        )
        _insertar(c, "ted:4-2026", fecha_limite=_dia(-1))  # plazo vencido
        _insertar(c, "ted:5-2026", estado="RES")  # adjudicación
        _insertar(c, "ted:6-2026", estado="PRE", fecha_limite=None)  # previo reciente: entra
        _insertar(c, "ted:7-2026", estado="PRE", fecha_limite=None, fecha_publicacion=_dia(-200))

    assert set(DocumentosRepository().ted_vigentes_sin_documentos()) == {"ted:1-2026", "ted:6-2026"}


def test_integration_ted_vigentes_sin_pliegos(db) -> None:
    """Las que van al portal de origen: su ficha no enseña más que, como mucho, el anuncio."""
    from db.database import connect
    from db.repositories.documentos import DocumentosRepository

    def emparejar(c: Any, ted: str, canonica: str, status: str = "confirmed") -> None:
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, clave_match, "
            " confianza, status) VALUES (%s, %s, 'expediente:x', 1.0, %s)",
            (ted, canonica, status),
        )

    with connect() as c:
        _insertar(c, "ted:1-2026", url="https://ted.europa.eu/es/notice/1-2026/pdf")  # sin nada
        _insertar(c, "ted:2-2026")  # solo el anuncio: sigue sin pliegos
        c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri, source_hash) "
            "VALUES ('ted:2-2026', 'additional', 'https://ted.europa.eu/2.pdf', 'ted-2-2026')"
        )
        _insertar(c, "ted:3-2026")
        _documento(c, "ted:3-2026")  # pliegos propios
        # Pareja navarra sin documentos: se piden para ella.
        _insertar(c, "placsp_agregadas:NA:1", url=_FICHA_NAVARRA)
        _insertar(c, "ted:4-2026")
        emparejar(c, "ted:4-2026", "placsp_agregadas:NA:1")
        # Pareja con pliegos: la ficha ya los enseña.
        _insertar(c, "placsp:O:2")
        _documento(c, "placsp:O:2")
        _insertar(c, "ted:5-2026")
        emparejar(c, "ted:5-2026", "placsp:O:2")
        # Pareja sin confirmar: la ficha lee los suyos, que no tiene.
        _insertar(c, "ted:6-2026")
        emparejar(c, "ted:6-2026", "placsp:O:2", status="pending")
        _insertar(c, "ted:7-2026", fecha_limite=_dia(-1))  # plazo vencido
        _insertar(c, "ted:8-2026", estado="PRE", fecha_limite=None)  # un previo no tiene pliegos
        _insertar(c, "ted:9-2026", estado="RES")

    filas = {f["id_externo"]: f for f in DocumentosRepository().ted_vigentes_sin_pliegos()}

    assert set(filas) == {"ted:1-2026", "ted:2-2026", "ted:4-2026", "ted:6-2026"}
    assert filas["ted:1-2026"] == {
        "id_externo": "ted:1-2026",
        "url": "https://ted.europa.eu/es/notice/1-2026/pdf",
        "destino": "ted:1-2026",
        "url_destino": None,
    }
    assert (filas["ted:4-2026"]["destino"], filas["ted:4-2026"]["url_destino"]) == (
        "placsp_agregadas:NA:1",
        _FICHA_NAVARRA,
    )
    assert filas["ted:6-2026"]["destino"] == "ted:6-2026"


def test_integration_los_pendientes_de_unas_licitaciones_con_el_pliego_por_delante(db) -> None:
    from db.database import connect
    from db.repositories.documentos import DocumentosRepository

    def doc(c: Any, lic: str, tipo: str, nombre: str, status: str = "pending") -> int:
        fila = c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri, status) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (lic, tipo, f"https://hacienda.navarra.es/{lic}/{nombre}", status),
        ).fetchone()
        return int(fila[0])

    with connect() as c:
        for lic in ("ted:1-2026", "placsp_agregadas:NA:1", "ted:9-2026"):
            _insertar(c, lic)
        anexo = doc(c, "ted:1-2026", "additional", "deuc.zip")
        pcap = doc(c, "ted:1-2026", "legal", "pcap.pdf")
        ppt = doc(c, "placsp_agregadas:NA:1", "technical", "ppt.pdf")
        leido = doc(c, "placsp_agregadas:NA:1", "legal", "ya.pdf", status="extracted")
        doc(c, "placsp_agregadas:NA:1", "acta", "acta.pdf")
        doc(c, "ted:9-2026", "legal", "otra.pdf")  # de una licitación que no se pide
        escaneado = doc(c, "ted:1-2026", "technical", "escaneado.pdf", status="sin_texto")

    repo = DocumentosRepository()
    pedidas = ["ted:1-2026", "placsp_agregadas:NA:1"]

    # Los dos pliegos de todas antes que ningún anexo; ni actas ni lo ya leído.
    assert [d["id"] for d in repo.list_pendientes_de(pedidas)] == [pcap, ppt, anexo]
    assert repo.list_pendientes_de([]) == []

    repo.reencolar_escaneado(escaneado)
    # Solo toca un `sin_texto`: lo que la noche o la ficha ya leyeron entretanto no vuelve.
    repo.reencolar_escaneado(leido)

    assert [d["id"] for d in repo.list_pendientes_de(pedidas)] == [pcap, ppt, escaneado, anexo]

    # El escaneado de verdad ya se bajó una vez: espera `pending` al OCR de la noche, y
    # la ingesta, que no lo tiene, no lo vuelve a pedir en cada pasada.
    with connect() as c:
        c.execute("UPDATE documentos SET fetched_at = '2026-11-19' WHERE id = %s", (escaneado,))

    assert [d["id"] for d in repo.list_pendientes_de(pedidas)] == [pcap, ppt, anexo]


def test_integration_ted_con_pliegos_en_cola(db) -> None:
    """Lo que una pasada registró en el portal de origen y no llegó a bajar."""
    from db.database import connect
    from db.repositories.documentos import DocumentosRepository

    def doc(c: Any, lic: str, uri: str, status: str = "pending") -> None:
        c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri, status) VALUES (%s, 'legal', %s, %s)",
            (lic, uri, status),
        )

    with connect() as c:
        _insertar(c, "ted:1-2026")
        doc(c, "ted:1-2026", "https://hacienda.navarra.es/sicpportal/doc?DOL=1")
        doc(c, "ted:1-2026", "https://hacienda.navarra.es/sicpportal/doc?DOL=2")  # una sola vez
        # Con pareja confirmada los pliegos están en la canónica, y es ella la que vuelve.
        _insertar(c, "placsp_agregadas:NA:1")
        doc(c, "placsp_agregadas:NA:1", "https://www.juntadeandalucia.es/apl/descargar/7")
        _insertar(c, "ted:2-2026")
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, clave_match, "
            " confianza, status) VALUES ('ted:2-2026', 'placsp_agregadas:NA:1', 'x', 1.0, "
            " 'confirmed')"
        )
        _insertar(c, "ted:3-2026")  # ya bajado
        doc(c, "ted:3-2026", "https://hacienda.navarra.es/sicpportal/doc?DOL=3", "extracted")
        _insertar(c, "ted:4-2026")  # pendiente, pero de otra plataforma: es del lote nocturno
        _documento(c, "ted:4-2026")
        _insertar(c, "ted:5-2026", fecha_limite=_dia(-1))  # plazo vencido
        doc(c, "ted:5-2026", "https://hacienda.navarra.es/sicpportal/doc?DOL=5")
        _insertar(c, "placsp:O:9")  # pendiente del portal, pero no es una convocatoria TED
        doc(c, "placsp:O:9", "https://www.juntadeandalucia.es/apl/descargar/9")
        _insertar(c, "ted:6-2026")  # escaneado que la ingesta devolvió a la cola: es de la noche
        doc(c, "ted:6-2026", "https://hacienda.navarra.es/sicpportal/doc?DOL=6")
        c.execute(
            "UPDATE documentos SET fetched_at = '2026-11-19' WHERE licitacion_id = 'ted:6-2026'"
        )

    en_cola = DocumentosRepository().ted_con_pliegos_en_cola(
        ("https://hacienda.navarra.es/", "https://www.juntadeandalucia.es/")
    )

    assert en_cola == ["placsp_agregadas:NA:1", "ted:1-2026"]


def test_integration_ted_vigentes_sin_pareja(db) -> None:
    """Lo que re-empareja cada pasada: vigentes sin pareja decidida, tengan o no el anuncio."""
    from db.database import connect
    from db.repositories import dedupe as dedupe_repo

    def marcar(c: Any, ted: str, status: str, *, resuelta: bool = False) -> None:
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, clave_match, "
            " confianza, status, resolved_at) VALUES (%s, 'EXP-CANON', 'x', 1.0, %s, %s)",
            (ted, status, _dia(0) if resuelta else None),
        )

    with connect() as c:
        _insertar(c, "EXP-CANON")
        _insertar(c, "ted:1-2026")  # vigente sin pareja: entra
        _insertar(c, "ted:2-2026")
        _documento(c, "ted:2-2026")  # con el anuncio puesto: entra igual
        _insertar(c, "ted:3-2026")
        marcar(c, "ted:3-2026", "confirmed")
        _insertar(c, "ted:4-2026")
        marcar(c, "ted:4-2026", "pending")  # sin decidir: entra
        _insertar(c, "ted:5-2026")
        marcar(c, "ted:5-2026", "rejected", resuelta=True)  # alguien dijo que no
        _insertar(c, "ted:6-2026", fecha_limite=_dia(-1))
        _insertar(c, "ted:7-2026", estado="RES")

    assert set(dedupe_repo.ted_vigentes_sin_pareja()) == {"ted:1-2026", "ted:2-2026", "ted:4-2026"}
    # Lo que la pasada ya evaluó se quita antes del LIMIT: si no, se comería el hueco.
    assert dedupe_repo.ted_vigentes_sin_pareja(limit=1, excluir=["ted:1-2026"]) == ["ted:2-2026"]


def test_integration_andalucia_para_documentos(db) -> None:
    from db.database import connect
    from db.repositories.documentos import DocumentosRepository

    with connect() as c:
        _insertar(c, "placsp_agregadas:EICE21:SIN-DOCS", url=_FICHA_ANDALUCIA)
        _insertar(c, "placsp_agregadas:EICE21:RECIENTE", url=_FICHA_ANDALUCIA)
        _documento(c, "placsp_agregadas:EICE21:RECIENTE")
        _insertar(
            c, "placsp_agregadas:EICE21:LEIDA", url=_FICHA_ANDALUCIA, fecha_publicacion=_dia(-40)
        )
        _documento(c, "placsp_agregadas:EICE21:LEIDA")
        _insertar(c, "placsp_agregadas:EICE21:ADJ", url=_FICHA_ANDALUCIA, estado="ADJ")
        _insertar(c, "placsp_agregadas:EICE21:VENCIDA", url=_FICHA_ANDALUCIA, fecha_limite=_dia(-1))
        _insertar(
            c, "placsp_agregadas:X:MADRID", url="https://contratos-publicos.comunidad.madrid/x"
        )
        _insertar(c, "placsp:1:EXP", url=_FICHA_ANDALUCIA)
        _insertar(c, "placsp_agregadas:EICE21:DUPLICADA", url=_FICHA_ANDALUCIA)
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, clave_match, "
            " confianza, status) VALUES ('placsp_agregadas:EICE21:DUPLICADA', 'placsp:1:EXP', "
            " 'x', 1.0, 'confirmed')"
        )

    filas = DocumentosRepository().andalucia_para_documentos()

    assert [f["id_externo"] for f in filas] == [
        "placsp_agregadas:EICE21:SIN-DOCS",
        "placsp_agregadas:EICE21:RECIENTE",
    ]


def test_integration_completar_ted_pone_el_anuncio_una_sola_vez(db) -> None:
    from db.database import connect, connect_read

    with connect() as c:
        _insertar(c, "ted:678766-2026")

    primera = dp.completar_documentos_ted()
    segunda = dp.completar_documentos_ted()

    assert (primera.con_documentos, segunda.candidatas) == (1, 0)
    with connect_read() as c:
        filas = c.execute(
            "SELECT tipo, uri, source_hash, status FROM documentos WHERE licitacion_id = %s",
            ("ted:678766-2026",),
        ).fetchall()
    assert [tuple(f) for f in filas] == [
        (
            "additional",
            "https://ted.europa.eu/es/notice/678766-2026/pdf",
            "ted-678766-2026",
            "pending",
        )
    ]


def _sembrar_pscp() -> None:
    """Convocatorias vigentes y expedientes ya cerrados de la PSCP."""
    from db.database import connect

    tic = {"analysis_universe": "pscp_observed", "tecnologia": "SAP"}

    def cambio(dias: int) -> str:
        """``fecha_actualizacion_fuente`` como la escribe Socrata."""
        return f"{_dia(dias)}T09:00:15.740Z"

    with connect() as c:
        _insertar(c, "pscp:SIN-DOCS", **tic)
        _insertar(c, "pscp:RECIENTE", **tic)
        _documento(c, "pscp:RECIENTE")
        _insertar(c, "pscp:YA-LEIDA", **tic, fecha_publicacion=_dia(-40))
        _documento(c, "pscp:YA-LEIDA")
        _insertar(c, "pscp:LIMPIEZA", analysis_universe="pscp_observed", tecnologia=None)
        # Solo por CPV 48/72: no se publica, pero su anuncio TED sí.
        _insertar(
            c,
            "pscp:SOLO-CPV",
            analysis_universe="pscp_observed",
            inclusion_reason="cpv_ti_universe",
        )
        # Cerradas: la ficha guarda su última fase, y los pliegos están en la del anuncio.
        _insertar(c, "pscp:CERRADA", **tic, estado="ADJ")  # sin cambio que fechar
        _insertar(c, "pscp:RESUELTA", **tic, estado="RES", fecha_actualizacion_fuente=cambio(-1))
        _insertar(
            c,
            "pscp:VENCIDA",
            **tic,
            fecha_limite=_dia(-5),
            fecha_actualizacion_fuente=cambio(-2),
        )
        _insertar(c, "pscp:LEIDA", **tic, estado="RES", fecha_actualizacion_fuente=cambio(-1))
        _documento(c, "pscp:LEIDA")
        _insertar(c, "pscp:AGREGADA", **tic, estado="AGR", fecha_actualizacion_fuente=cambio(-1))
        _insertar(c, "pscp:VIEJA", **tic, estado="RES", fecha_actualizacion_fuente=cambio(-30))
        _insertar(c, "pscp:SIN-ESTADO", **tic, estado=None, fecha_actualizacion_fuente=cambio(-3))
        # Republicación de una agregada de PLACSP: su ficha lee los pliegos de la canónica.
        _insertar(c, "placsp_agregadas:1:X", **tic, estado="ADJ")
        _insertar(c, "pscp:DUPLICADA", **tic, estado="ADJ", fecha_actualizacion_fuente=cambio(-1))
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, clave_match, "
            " confianza, status) VALUES ('pscp:DUPLICADA', 'placsp_agregadas:1:X', 'x', 1.0, "
            " 'confirmed')"
        )


def test_integration_pscp_para_documentos(db) -> None:
    from db.repositories.documentos import DocumentosRepository

    _sembrar_pscp()

    filas = DocumentosRepository().pscp_para_documentos()

    # Las vigentes delante (sin documentos primero), para que un retoque masivo del
    # dataset no deje sin presupuesto su refresco; las cerradas, solo si cambiaron
    # en la última semana. La vigente leída hace 40 días no se vuelve a pedir.
    assert [f["id_externo"] for f in filas] == [
        "pscp:SIN-DOCS",
        "pscp:SOLO-CPV",
        "pscp:RECIENTE",
        "pscp:RESUELTA",
        "pscp:VENCIDA",
        "pscp:SIN-ESTADO",
    ]


def test_integration_el_barrido_lee_todas_las_cerradas_sin_documentos(db) -> None:
    from db.repositories.documentos import DocumentosRepository

    _sembrar_pscp()

    filas = DocumentosRepository().pscp_para_documentos(dias_cambio=None)

    assert [f["id_externo"] for f in filas] == [
        "pscp:SIN-DOCS",
        "pscp:SOLO-CPV",
        "pscp:RECIENTE",
        "pscp:RESUELTA",
        "pscp:VENCIDA",
        "pscp:SIN-ESTADO",
        "pscp:VIEJA",
        "pscp:CERRADA",
    ]


def test_integration_reempareja_los_ted_antiguos_por_id_evl(db) -> None:
    from db.database import connect, connect_read
    from services.dedupe import reemparejar_ted_por_id_evl

    url = f"{_DEEPLINK}CEGLc1%2Fkxg%2FE6P%2FuLemXRw%3D%3D"
    with connect() as c:
        _insertar(c, "2025/EXP-1", url=url, organo_contratacion="Ministerio")
        _insertar(c, "ted:400000-2026", url=url.replace("%2F", "%2f"), fecha_publicacion=_dia(-60))
        _insertar(c, "ted:400001-2026", url="https://ted.europa.eu/es/notice/400001-2026/pdf")

    resultado = reemparejar_ted_por_id_evl()

    assert resultado.confirmados == 1
    with connect_read() as c:
        assert _marca(c, "ted:400000-2026") == ("2025/EXP-1", "confirmed")
        assert _marca(c, "ted:400001-2026") is None
    # Lo ya emparejado sale de la consulta: reejecutar no evalúa nada.
    assert reemparejar_ted_por_id_evl().evaluadas == 0


def test_integration_la_ficha_pscp_empareja_su_anuncio_ted(db) -> None:
    from db.database import connect, connect_read
    from services.dedupe import marcar_republicaciones_ted

    with connect() as c:
        _insertar(c, "pscp:2026/6150/1428", analysis_universe="pscp_observed", tecnologia="SAP")
        _insertar(c, "ted:675385-2026")

    resultado = marcar_republicaciones_ted("pscp:2026/6150/1428", ["675385-2026", "999-2026"])

    assert resultado == RepublicacionesTed(marcadas=["ted:675385-2026"])
    with connect_read() as c:
        assert _marca(c, "ted:675385-2026") == ("pscp:2026/6150/1428", "confirmed")


def test_integration_no_esconde_el_ted_tras_una_ficha_pscp_que_no_se_publica(db) -> None:
    from db.database import connect, connect_read
    from services.dedupe import marcar_republicaciones_ted

    with connect() as c:
        # Fuera del universo tecnológico: la superficie pública no la sirve.
        _insertar(c, "pscp:LIMPIEZA", analysis_universe="pscp_observed", tecnologia=None)
        _insertar(c, "ted:675386-2026")

    resultado = marcar_republicaciones_ted("pscp:LIMPIEZA", ["675386-2026"])

    assert resultado == RepublicacionesTed(sin_canonica_visible=["ted:675386-2026"])
    with connect_read() as c:
        assert _marca(c, "ted:675386-2026") is None


class _ConectorConUnaFila:
    """Un lote de una fila y un paso de documentos que cuenta sus llamadas."""

    source_id = "fake"

    def __init__(self, notices: list[str]) -> None:
        self.notices = notices
        self.completadas = 0

    def fetch(self, cursor: Any) -> Any:
        from scraper.connectors.base import RawNotice

        for natural_id in self.notices:
            yield RawNotice(natural_id=natural_id, payload={})

    def parse(self, raw: Any) -> Any:
        from db.upsert import Licitacion
        from scraper.connectors.base import ParsedTender

        return ParsedTender(
            licitacion=Licitacion(
                id_externo=f"fake:{raw.natural_id}",
                titulo="Suministro de licencias de software de gestión documental",
                fuente="fake",
                fecha_publicacion=_dia(-1),
            )
        )

    def new_cursor(self) -> None:
        return None

    def completar_documentos(self) -> None:
        self.completadas += 1


@pytest.mark.parametrize("notices", [["A"], []], ids=["con_lote", "sin_lote"])
def test_integration_el_paso_de_documentos_corre_una_vez_por_pasada(db, notices) -> None:
    """Con lote va dentro de ``_post_ingestion``; sin lote, directo. Nunca dos veces."""
    from scraper.connectors.base import run_connector

    conector = _ConectorConUnaFila(notices)

    resultado = run_connector(conector)

    assert resultado.parsed == len(notices)
    assert conector.completadas == 1
