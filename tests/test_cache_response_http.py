"""``cache_response`` por HTTP: la respuesta cacheada sale serializada y con ETag.

Sin BD: una app FastAPI mínima con el decorador y el backend en memoria. Lo
que se fija aquí es el contrato que el cambio no puede romper:

- El cuerpo que sirve el decorador es **byte a byte** el que serializaría
  FastAPI con el ``response_model`` (mismo JSON en fallo y en acierto).
- En un acierto el wrapper devuelve una ``Response`` con el cuerpo guardado y
  su ``ETag``: FastAPI no revalida el dict contra el modelo en el event loop.
- El OpenAPI no cambia (el parámetro que inyecta la respuesta temporal no se
  documenta).
- Lo que las dependencias fijan en la respuesta temporal (cabeceras) llega.
- Un handler que devuelve algo que no cumple su contrato es un 500, no un 400.
- En las rutas reales, ``response_model`` coincide con la anotación de retorno
  del handler: es lo que hace que serializar con esa anotación sea serializar
  como FastAPI.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import typing
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import Depends, FastAPI, Query, Response
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from shared.etag import etag_debil


class _Item(BaseModel):
    nombre: str
    importe: float | None = None
    fecha: date | None = None
    con_alias: int = Field(default=0, alias="conAlias")


class _Resultado(BaseModel):
    total: int
    items: list[_Item]
    cuando: datetime
    ratio: float


def _resultado() -> _Resultado:
    return _Resultado(
        total=2,
        # `ñ`, un float grande y un alias: los tres sitios donde un serializador
        # distinto del de FastAPI se delataría en los bytes.
        items=[_Item(nombre="ñandú", importe=1e16, fecha=date(2026, 9, 1), conAlias=3)],
        cuando=datetime(2026, 9, 24, 10, 0, tzinfo=UTC),
        ratio=0.1,
    )


def _dependencia(response: Response) -> dict[str, Any]:
    response.headers["X-Desde-Dependencia"] = "si"
    return {"user_key": "u-1"}


@pytest.fixture()
def cache_mod(monkeypatch: pytest.MonkeyPatch) -> Any:
    import config as config_mod
    import shared.cache as mod

    class _SinRedis:
        REDIS_URL = ""

    monkeypatch.setattr(config_mod, "settings", _SinRedis())
    mod.reset_cache()
    yield mod
    mod.reset_cache()


def _apps(cache_mod: Any, namespace: str) -> tuple[FastAPI, FastAPI, dict[str, int]]:
    """La misma ruta con y sin ``cache_response``, y un contador de llamadas."""
    llamadas = {"n": 0}

    def handler(
        ccaa: str | None = Query(default=None),
        _user: dict[str, Any] = Depends(_dependencia),
    ) -> _Resultado:
        llamadas["n"] += 1
        return _resultado()

    con_cache = FastAPI()
    sin_cache = FastAPI()
    con_cache.get("/r", response_model=_Resultado)(
        cache_mod.cache_response(ttl=60, namespace=namespace)(handler)
    )
    sin_cache.get("/r", response_model=_Resultado)(handler)
    return con_cache, sin_cache, llamadas


def test_fallo_y_acierto_sirven_los_bytes_de_fastapi_con_la_misma_etag(cache_mod: Any) -> None:
    con_cache, sin_cache, llamadas = _apps(cache_mod, "http-bytes")
    cliente = TestClient(con_cache)

    fallo = cliente.get("/r?ccaa=Madrid")
    acierto = cliente.get("/r?ccaa=Madrid")
    referencia = TestClient(sin_cache).get("/r?ccaa=Madrid")

    assert fallo.status_code == acierto.status_code == 200
    assert fallo.content == acierto.content == referencia.content
    assert fallo.headers["content-type"] == referencia.headers["content-type"]
    # La ETag es la del middleware (`shared.etag`): calculada una vez al guardar.
    assert fallo.headers["etag"] == acierto.headers["etag"] == etag_debil(fallo.content)
    # Con caché: una llamada del handler (el fallo) + una de la app sin caché.
    assert llamadas["n"] == 2


def test_las_cabeceras_de_las_dependencias_llegan_en_fallo_y_en_acierto(cache_mod: Any) -> None:
    con_cache, _sin_cache, _ = _apps(cache_mod, "http-cabeceras")
    cliente = TestClient(con_cache)

    fallo = cliente.get("/r")
    acierto = cliente.get("/r")

    assert fallo.headers["x-desde-dependencia"] == "si"
    assert acierto.headers["x-desde-dependencia"] == "si"


def test_el_openapi_no_cambia(cache_mod: Any) -> None:
    con_cache, sin_cache, _ = _apps(cache_mod, "http-openapi")

    assert con_cache.openapi() == sin_cache.openapi()


def test_la_entrada_guarda_el_json_ya_serializado(cache_mod: Any) -> None:
    con_cache, _sin_cache, _ = _apps(cache_mod, "http-entrada")
    respuesta = TestClient(con_cache).get("/r?ccaa=Galicia")

    backend = cache_mod.get_cache("http-entrada")
    (clave,) = backend.keys("handler|*")
    entrada = backend.get_respuesta(clave)
    assert isinstance(entrada, cache_mod._RespuestaCacheada)
    assert entrada.cuerpo == respuesta.content
    assert entrada.etag == respuesta.headers["etag"]


def test_en_un_acierto_el_wrapper_devuelve_una_response(cache_mod: Any) -> None:
    """FastAPI entrega una ``Response`` tal cual: sin validar ni serializar."""
    llamadas = {"n": 0}

    @cache_mod.cache_response(ttl=60, namespace="http-response")
    def handler(*, _user: dict[str, Any]) -> _Resultado:
        llamadas["n"] += 1
        return _resultado()

    async def _dos_veces() -> tuple[Any, Any]:
        primera = await handler(_user={"user_key": "u"}, _cache_response_temporal=Response())
        segunda = await handler(_user={"user_key": "u"}, _cache_response_temporal=Response())
        return primera, segunda

    primera, segunda = asyncio.run(_dos_veces())

    assert isinstance(primera, Response)
    assert isinstance(segunda, Response)
    assert primera.body == segunda.body
    assert segunda.headers["etag"] == etag_debil(segunda.body)
    assert segunda.media_type == "application/json"
    assert llamadas["n"] == 1


def test_llamada_directa_conserva_el_contrato_de_siempre(cache_mod: Any) -> None:
    """Sin respuesta temporal (tests, scripts): el modelo en el fallo, un dict en el acierto."""

    @cache_mod.cache_response(ttl=60, namespace="http-directa")
    def handler(*, _user: dict[str, Any]) -> _Resultado:
        return _resultado()

    async def _dos_veces() -> tuple[Any, Any]:
        return await handler(_user={}), await handler(_user={})

    fallo, acierto = asyncio.run(_dos_veces())

    assert isinstance(fallo, _Resultado)
    assert acierto == fallo.model_dump(mode="json", by_alias=True)


def test_un_handler_que_incumple_su_contrato_es_un_500(cache_mod: Any) -> None:
    """El ValidationError de pydantic es un ValueError: sin traducirlo, la app
    lo convertiría en un 400 (``api/errors.py``). FastAPI lo da como 500."""
    from fastapi.exceptions import ResponseValidationError

    @cache_mod.cache_response(ttl=60, namespace="http-invalido")
    def handler(*, _user: dict[str, Any]) -> _Resultado:
        return {"total": "no-es-un-numero"}  # type: ignore[return-value]  # el error es el caso de prueba

    with pytest.raises(ResponseValidationError):
        asyncio.run(handler(_user={}, _cache_response_temporal=Response()))


def test_rechaza_handlers_que_reciben_una_response(cache_mod: Any) -> None:
    """FastAPI solo inyecta la respuesta temporal en un parámetro por endpoint."""

    def handler(response: Response) -> _Resultado:
        return _resultado()

    with pytest.raises(TypeError, match="Response"):
        cache_mod.cache_response(ttl=60)(handler)


def test_la_serializacion_y_el_handler_corren_fuera_del_event_loop(
    cache_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    hilos: dict[str, int] = {}
    etag_real = cache_mod.etag_debil

    def _etag_espia(cuerpo: bytes) -> str:
        hilos["serializacion"] = threading.get_ident()
        return str(etag_real(cuerpo))

    monkeypatch.setattr(cache_mod, "etag_debil", _etag_espia)

    @cache_mod.cache_response(ttl=60, namespace="http-hilos")
    def handler(*, _user: dict[str, Any]) -> _Resultado:
        hilos["handler"] = threading.get_ident()
        return _resultado()

    async def _una() -> int:
        await handler(_user={}, _cache_response_temporal=Response())
        return threading.get_ident()

    hilo_del_loop = asyncio.run(_una())

    assert hilos["handler"] != hilo_del_loop
    assert hilos["serializacion"] != hilo_del_loop


def test_handler_async_serializa_en_un_hilo(
    cache_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    hilos: dict[str, int] = {}
    etag_real = cache_mod.etag_debil

    def _etag_espia(cuerpo: bytes) -> str:
        hilos["serializacion"] = threading.get_ident()
        return str(etag_real(cuerpo))

    monkeypatch.setattr(cache_mod, "etag_debil", _etag_espia)

    @cache_mod.cache_response(ttl=60, namespace="http-async")
    async def handler(*, _user: dict[str, Any]) -> _Resultado:
        return _resultado()

    async def _una() -> tuple[Any, int]:
        respuesta = await handler(_user={}, _cache_response_temporal=Response())
        return respuesta, threading.get_ident()

    respuesta, hilo_del_loop = asyncio.run(_una())

    assert isinstance(respuesta, Response)
    assert hilos["serializacion"] != hilo_del_loop


# ── Las rutas reales ─────────────────────────────────────────────────────────


def _rutas_cacheadas() -> list[Any]:
    from fastapi.routing import APIRoute

    from api.routes import analytics, predicciones
    from shared.cache import _PARAM_RESPUESTA

    rutas = []
    for router in (analytics.router, predicciones.router):
        for ruta in router.routes:
            if not isinstance(ruta, APIRoute):
                continue
            if _PARAM_RESPUESTA in inspect.signature(ruta.endpoint).parameters:
                rutas.append(ruta)
    return rutas


def test_hay_rutas_cacheadas_que_verificar() -> None:
    """Si esta lista quedara vacía, el test de abajo no probaría nada."""
    assert len(_rutas_cacheadas()) >= 20


def test_el_openapi_de_las_rutas_reales_es_el_de_sus_handlers_sin_cache() -> None:
    """Las rutas cacheadas de verdad documentan lo mismo que sus handlers desnudos.

    Se monta cada ruta dos veces —con el endpoint decorado y con
    ``__wrapped__``— y se comparan los OpenAPI: el parámetro por el que llega la
    respuesta temporal no se documenta, y nombre, descripción y operationId
    salen iguales porque ``functools.wraps`` los copia.
    """
    decoradas = FastAPI()
    desnudas = FastAPI()
    for ruta in _rutas_cacheadas():
        comunes = {
            "response_model": ruta.response_model,
            "methods": sorted(ruta.methods),
            "summary": ruta.summary,
            "description": ruta.description,
            "deprecated": ruta.deprecated,
            "responses": ruta.responses,
            "tags": ruta.tags,
            "name": ruta.name,
        }
        decoradas.add_api_route(ruta.path, ruta.endpoint, **comunes)
        desnudas.add_api_route(ruta.path, ruta.endpoint.__wrapped__, **comunes)

    assert decoradas.openapi() == desnudas.openapi()


def test_cada_ruta_real_tiene_huella_de_su_dto() -> None:
    """Sin esquema JSON la huella caería a un valor fijo y un DTO cambiado no
    invalidaría lo guardado por el despliegue anterior."""
    from shared.cache import _adaptador_de_retorno

    sin_esquema = []
    for ruta in _rutas_cacheadas():
        adaptador = _adaptador_de_retorno(ruta.endpoint.__wrapped__)
        if adaptador is None:
            sin_esquema.append(ruta.path)
            continue
        try:
            adaptador.json_schema(mode="serialization", by_alias=True)
        except Exception as exc:
            sin_esquema.append(f"{ruta.path}: {exc!r}")
    assert not sin_esquema, sin_esquema


def test_response_model_coincide_con_la_anotacion_de_retorno() -> None:
    """El decorador serializa con la anotación de retorno del handler; FastAPI
    serializaría con el ``response_model``. Tienen que ser el mismo tipo, y la
    ruta no puede declarar otro código de estado: el decorador responde 200."""
    discrepancias = []
    for ruta in _rutas_cacheadas():
        desnuda = ruta.endpoint.__wrapped__
        retorno = typing.get_type_hints(desnuda).get("return")
        if ruta.response_model is not retorno:
            discrepancias.append(f"{ruta.path}: {ruta.response_model} != {retorno}")
        if ruta.status_code not in (None, 200):
            discrepancias.append(f"{ruta.path}: status_code={ruta.status_code}")
    assert not discrepancias, discrepancias
