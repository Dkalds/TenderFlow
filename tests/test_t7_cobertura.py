"""Cobertura declarada (T7 / D16): estados, exclusiones y endpoint público.

Lo que fija este fichero es que la página `/cobertura` no pueda volver a ser
prosa: las fuentes y sus estados salen de ``scraper.connectors`` y viajan por
``GET /api/v1/publico/cobertura``, y lo que queda fuera del producto está
declarado con fecha en el mismo sitio que lo que sí entra.

Sin BD: el endpoint es el único de la superficie pública que no consulta nada,
así que se monta un router pelado y se ejercita con ``TestClient``.
"""

from __future__ import annotations

import re
from typing import Any, get_args
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.publico import EstadoCoberturaApi, router
from scraper.connectors import (
    FUERA_DE_ALCANCE,
    REGISTERED_SOURCES,
    REGISTERED_SOURCES_BY_ID,
    VIA_DE_ENTRADA_FUERA_DE_ALCANCE,
    AmbitoExcluido,
    EstadoCobertura,
    RegisteredSource,
)

_RUTA = "/api/v1/publico/cobertura"


def _app() -> FastAPI:
    """API mínima con solo el router público. No abre Postgres."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


@pytest.fixture(scope="module")
def cliente() -> TestClient:
    return TestClient(_app())


@pytest.fixture(scope="module")
def payload(cliente: TestClient) -> dict[str, Any]:
    respuesta = cliente.get(_RUTA)
    assert respuesta.status_code == 200
    datos: dict[str, Any] = respuesta.json()
    return datos


# ---------------------------------------------------------------------------
# El vocabulario de estados
# ---------------------------------------------------------------------------


def test_el_contrato_publico_declara_los_mismos_tres_estados() -> None:
    """``api.routes.publico`` copia el ``Literal`` en vez de importarlo.

    La copia existe para no arrastrar ``requests``/``lxml``/el diccionario de
    ``scraper.filters`` al arranque de la API. Este test es el precio de esa
    decisión: si el inventario abriera un cuarto estado, el endpoint lo
    rechazaría en producción y aquí falla antes.
    """
    assert set(get_args(EstadoCoberturaApi)) == set(get_args(EstadoCobertura))
    assert set(get_args(EstadoCobertura)) == {"activa", "opcional", "fuera_de_alcance"}


def test_opcional_sigue_derivandose_del_estado() -> None:
    """``scheduler/healthcheck.py`` pregunta ``fuente.opcional``, no el estado.

    El tercer estado no puede haber cambiado esa respuesta para ninguna de las
    fuentes que ya existían, o el healthcheck empezaría a alertar (o a callarse)
    por un cambio que era de vocabulario.
    """
    for source_id in ("pscp", "tacrc", "placsp_watched_company_awards"):
        assert REGISTERED_SOURCES_BY_ID[source_id].estado == "opcional"
        assert REGISTERED_SOURCES_BY_ID[source_id].opcional

    for source_id in ("placsp", "ted", "galicia_rss", "euskadi_rss"):
        assert REGISTERED_SOURCES_BY_ID[source_id].estado == "activa"
        assert not REGISTERED_SOURCES_BY_ID[source_id].opcional


def test_una_fuente_fuera_de_alcance_no_se_le_exige_frescura() -> None:
    """El tercer estado tiene que significar algo en el healthcheck.

    Si ``fuera_de_alcance`` solo pintara distinto en la página, retirar una
    fuente seguiría generando la misma alerta cada seis horas que retirarla mal.
    """
    from scheduler.healthcheck import comprobar_frescura_fuentes

    retirada = RegisteredSource(
        source_id="portal_retirado",
        nombre="Portal retirado",
        modulo="scraper.connectors.retirado",
        max_lag_hours=24,
        motivo="No corre.",
        alcance="Ya no se ingiere.",
        estado="fuera_de_alcance",
    )

    class _RepoVacio:
        def list_health(self) -> list[dict[str, Any]]:
            return []

    with patch("scraper.connectors.REGISTERED_SOURCES", (retirada,)):
        resultado = comprobar_frescura_fuentes(_RepoVacio())

    assert resultado["sin_registro"] == []
    assert resultado["fuentes"] == {}


# ---------------------------------------------------------------------------
# Lo que se declara
# ---------------------------------------------------------------------------


def test_toda_fuente_declara_nombre_y_alcance_publicables() -> None:
    """Una fuente sin alcance escrito es la que acaba leyéndose como censo."""
    for fuente in REGISTERED_SOURCES:
        assert fuente.nombre.strip(), fuente.source_id
        assert fuente.alcance.strip(), fuente.source_id
        assert fuente.estado in get_args(EstadoCobertura), fuente.source_id


def test_lo_que_queda_fuera_esta_declarado_con_fecha_y_decision() -> None:
    ambitos = " | ".join(a.ambito.lower() for a in FUERA_DE_ALCANCE)
    assert "contratos menores" in ambitos
    assert "boe" in ambitos
    assert "portales autonómicos" in ambitos

    for excluido in FUERA_DE_ALCANCE:
        assert isinstance(excluido, AmbitoExcluido)
        assert excluido.motivo.strip(), excluido.ambito
        assert excluido.decision == "D16", excluido.ambito
        # Fecha ISO y no prosa: «fuera de alcance» sin fecha no se distingue de
        # «todavía no llegamos», y la segunda caduca sola.
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", excluido.desde), excluido.ambito


def test_la_via_de_entrada_es_la_peticion_escrita_que_fijo_d16() -> None:
    assert "por escrito" in VIA_DE_ENTRADA_FUERA_DE_ALCANCE.lower()


#: Marcas de relleno de ``web/src/lib/legal-placeholder.ts``. Se replican aquí
#: —importarlas entre lenguajes no es posible— porque desde T7 estos campos SON
#: copy publicado: los pinta `/cobertura`. El criterio de aceptación del plan
#: («el copy pasa `lib/legal-placeholder.ts`») dejaría de significar nada si la
#: mitad del texto de la página entrara por el JSON sin pasar por él.
_MARCAS_DE_RELLENO = (
    "placeholder",
    "por completar",
    "pendiente de",
    "sin definir",
    "a rellenar",
    "cambiar esto",
    "no desplegar",
    "sin validez",
    "lorem",
    "dummy",
    "tbd",
    "xxx",
)


def test_ningun_texto_publicado_es_un_relleno() -> None:
    textos = [
        *(f.nombre for f in REGISTERED_SOURCES),
        *(f.alcance for f in REGISTERED_SOURCES),
        *(a.ambito for a in FUERA_DE_ALCANCE),
        *(a.motivo for a in FUERA_DE_ALCANCE),
        VIA_DE_ENTRADA_FUERA_DE_ALCANCE,
    ]
    for texto in textos:
        bajo = texto.lower()
        for marca in _MARCAS_DE_RELLENO:
            assert marca not in bajo, f"{marca!r} en {texto!r}"


# ---------------------------------------------------------------------------
# El endpoint
# ---------------------------------------------------------------------------


def test_responde_sin_autenticacion_y_es_cacheable(cliente: TestClient) -> None:
    respuesta = cliente.get(_RUTA)

    assert respuesta.status_code == 200
    assert "public" in respuesta.headers.get("cache-control", "")


def test_publica_cada_fuente_del_inventario(payload: dict[str, Any]) -> None:
    publicadas = {f["source_id"]: f for f in payload["fuentes"]}

    assert set(publicadas) == set(REGISTERED_SOURCES_BY_ID)
    for source_id, fuente in publicadas.items():
        declarada = REGISTERED_SOURCES_BY_ID[source_id]
        assert fuente["nombre"] == declarada.nombre
        assert fuente["estado"] == declarada.estado
        assert fuente["alcance"] == declarada.alcance
        assert fuente["max_lag_hours"] == declarada.max_lag_hours


def test_no_publica_el_modulo_ni_el_motivo_del_umbral(payload: dict[str, Any]) -> None:
    """Ruta de import y razonamiento operativo: ninguno es dato del visitante."""
    for fuente in payload["fuentes"]:
        assert set(fuente) == {"source_id", "nombre", "estado", "alcance", "max_lag_hours"}


def test_publica_lo_que_queda_fuera_junto_a_lo_que_entra(payload: dict[str, Any]) -> None:
    """Las dos listas viajan en la misma respuesta.

    Separadas, una página puede pintar la primera y olvidarse de la segunda, que
    es justo la mitad que el lector necesita para saber si esto le sirve.
    """
    assert set(payload) == {"fuentes", "fuera_de_alcance", "via_de_entrada"}
    assert [a["ambito"] for a in payload["fuera_de_alcance"]] == [
        a.ambito for a in FUERA_DE_ALCANCE
    ]
    assert payload["via_de_entrada"] == VIA_DE_ENTRADA_FUERA_DE_ALCANCE


def test_la_operacion_nace_tipada_y_no_opaca() -> None:
    """Invariante 5 de AGENTS.md, comprobado con el predicado del propio gate.

    ``scripts/check_openapi_contract.py`` corre sobre ``api/openapi.json``, que
    es un artefacto que hay que regenerar; esto mide lo mismo sobre el esquema
    que FastAPI emite ahora mismo, así que el fallo aparece en el commit y no
    en el siguiente ``make openapi``.
    """
    from scripts.check_openapi_contract import _is_opaque

    spec = _app().openapi()
    respuesta = spec["paths"][_RUTA]["get"]["responses"]["200"]
    esquema = respuesta["content"]["application/json"]["schema"]

    assert not _is_opaque(esquema)
    referencia = esquema["$ref"].rsplit("/", 1)[-1]
    assert referencia == "Cobertura"

    componentes = spec["components"]["schemas"]
    assert not _is_opaque(componentes["Cobertura"])
    assert not _is_opaque(componentes["FuenteCobertura"])
    assert not _is_opaque(componentes["AmbitoFueraDeAlcance"])
    # El estado viaja como enumeración cerrada, no como `str` libre: es lo que
    # permite al cliente TS distinguir los tres casos sin repetir la lista.
    assert set(componentes["FuenteCobertura"]["properties"]["estado"]["enum"]) == set(
        get_args(EstadoCobertura)
    )


def test_la_respuesta_no_lleva_ni_una_cifra_de_cuota(payload: dict[str, Any]) -> None:
    """Regla dura de ``docs/regional-source-coverage.md``.

    Los feeds regionales son cobertura de descubrimiento. Cualquier total,
    porcentaje o recuento en esta respuesta se leería en la página como cuota de
    mercado, y el backend no puede ofrecer siquiera la tentación.
    """
    claves = {
        *payload,
        *(k for f in payload["fuentes"] for k in f),
        *(k for a in payload["fuera_de_alcance"] for k in a),
    }
    prohibidas = {"total", "totales", "cuota", "porcentaje", "count", "n"}
    assert claves & prohibidas == set()
