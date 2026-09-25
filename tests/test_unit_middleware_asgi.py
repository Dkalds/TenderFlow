"""El stack de middlewares como ASGI puro, sin BD.

Hasta 2026-09 cinco capas eran ``BaseHTTPMiddleware`` y el rate limit consultaba
la BD **dentro del event loop** del único proceso uvicorn. Este módulo fija lo
que cambió (la comprobación va a un hilo, nada retiene los streams, el ETag
respeta la etiqueta que trae la caché) y lo que no podía cambiar (cabeceras,
correlation id, códigos, cuerpos de los 429 y orden del stack).

Casi todo se ejercita con ``TestClient`` sobre apps mínimas. Lo que depende de
*cuándo* sale cada mensaje (streams, peticiones concurrentes) se habla en ASGI
directamente: el ``TestClient`` de Starlette ejecuta la app entera antes de
devolver la respuesta, así que no ve si un middleware retiene el cuerpo.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient
from structlog.contextvars import get_contextvars

import api.middleware as mw
from api.middleware import (
    ETagMiddleware,
    ObservabilityMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from shared.etag import etag_debil

_SEGURIDAD = (
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "content-security-policy",
)

Message = dict[str, Any]


# ── Utilidades ASGI ──────────────────────────────────────────────────────────


def _scope(
    path: str, *, method: str = "GET", headers: dict[str, str] | None = None
) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("203.0.113.9", 50000),
        "server": ("testserver", 80),
    }


def _receive_vacio() -> Callable[[], Awaitable[Message]]:
    entregado = False

    async def receive() -> Message:
        nonlocal entregado
        if not entregado:
            entregado = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()  # como un cliente que no se va
        raise AssertionError("inalcanzable")

    return receive


async def _llamar(app: Any, path: str, headers: dict[str, str] | None = None) -> list[Message]:
    enviados: list[Message] = []

    async def send(message: Message) -> None:
        enviados.append(message)

    await app(_scope(path, headers=headers), _receive_vacio(), send)
    return enviados


def _cabeceras(inicio: Message) -> dict[str, str]:
    return {k.decode(): v.decode() for k, v in inicio["headers"]}


class _Limitador:
    """Doble del rate limiter: registra dónde y con qué se le consulta."""

    def __init__(self, *, permitir: bool = True) -> None:
        self.permitir = permitir
        self.llamadas: list[dict[str, Any]] = []

    def check(self, key: str, *, max_calls: int = 120, window_seconds: float = 60.0) -> bool:
        try:
            asyncio.get_running_loop()
            con_loop = True
        except RuntimeError:
            con_loop = False
        self.llamadas.append(
            {
                "key": key,
                "max_calls": max_calls,
                "hilo": threading.get_ident(),
                "con_loop": con_loop,
            }
        )
        return self.permitir


@pytest.fixture()
def limitador(monkeypatch: pytest.MonkeyPatch) -> _Limitador:
    doble = _Limitador()
    monkeypatch.setattr("api.middleware.get_rate_limiter", lambda: doble)
    # Un CapacityLimiter nuevo por test: el singleton del módulo es de proceso.
    monkeypatch.setattr(mw, "_hilos_cuota", None)
    return doble


# ── Rate limit ───────────────────────────────────────────────────────────────


def _app_con_rate_limit(**kwargs: Any) -> Starlette:
    hilos: list[int] = []

    async def ok(request: Request) -> Response:
        hilos.append(threading.get_ident())
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/api/v1/algo", ok), Route("/api/v1/health", ok)])
    app.add_middleware(RateLimitMiddleware, **kwargs)
    app.state.hilos_handler = hilos
    return app


class TestRateLimit:
    def test_permitida_llega_al_handler(self, limitador: _Limitador) -> None:
        resp = TestClient(_app_con_rate_limit()).get("/api/v1/algo")

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert [c["key"] for c in limitador.llamadas] == ["api:ip:testclient"]

    def test_denegada_responde_429_problem_json(self, limitador: _Limitador) -> None:
        limitador.permitir = False

        resp = TestClient(_app_con_rate_limit(max_calls=7, window_seconds=30)).get("/api/v1/algo")

        assert resp.status_code == 429
        assert resp.headers["content-type"] == "application/problem+json"
        assert resp.headers["Retry-After"] == "30"
        assert resp.headers["X-RateLimit-Limit"] == "7"
        assert resp.headers["X-RateLimit-Window"] == "30"
        assert resp.json() == {
            "type": "https://licitaciones-sap/errors/rate-limit-exceeded",
            "title": "Too Many Requests",
            "status": 429,
            "detail": "Límite de 7 requests por 30s excedido.",
        }

    def test_la_comprobacion_no_corre_en_el_hilo_del_event_loop(
        self, limitador: _Limitador
    ) -> None:
        """Era el fallo: ``check()`` hacía ~5 viajes a la BD con el loop parado."""
        app = _app_con_rate_limit()

        TestClient(app).get("/api/v1/algo")

        (llamada,) = limitador.llamadas
        (hilo_del_loop,) = app.state.hilos_handler
        assert llamada["con_loop"] is False, "check() corrió dentro de un event loop"
        assert llamada["hilo"] != hilo_del_loop

    def test_el_loop_sigue_atendiendo_mientras_una_comprobacion_espera(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Una comprobación lenta ya no para a las demás peticiones.

        La comprobación de ``/lenta`` espera a que la atienda ``/health`` (que
        está excluido del límite). Si ``check()`` corriera en el loop, ``/health``
        no llegaría a ejecutarse y la espera caducaría.
        """
        liberada = threading.Event()
        esperas: list[bool] = []

        class _Lento:
            def check(
                self, key: str, *, max_calls: int = 120, window_seconds: float = 60.0
            ) -> bool:
                esperas.append(liberada.wait(timeout=5))
                return True

        monkeypatch.setattr("api.middleware.get_rate_limiter", lambda: _Lento())
        monkeypatch.setattr(mw, "_hilos_cuota", None)

        async def lenta(request: Request) -> Response:
            return JSONResponse({"ok": True})

        async def health(request: Request) -> Response:
            liberada.set()
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route("/lenta", lenta), Route("/api/v1/health", health)])
        app.add_middleware(RateLimitMiddleware)

        async def main() -> None:
            primera = asyncio.create_task(_llamar(app, "/lenta"))
            await asyncio.sleep(0.05)
            await asyncio.wait_for(_llamar(app, "/api/v1/health"), timeout=2)
            await asyncio.wait_for(primera, timeout=5)

        asyncio.run(main())
        assert esperas == [True]

    def test_las_comprobaciones_simultaneas_no_pasan_del_cupo_de_hilos(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Con la BD de respaldo cada hilo retiene una conexión de escritura."""
        activos = 0
        maximo = 0
        cerrojo = threading.Lock()

        class _Ocupado:
            def check(
                self, key: str, *, max_calls: int = 120, window_seconds: float = 60.0
            ) -> bool:
                nonlocal activos, maximo
                with cerrojo:
                    activos += 1
                    maximo = max(maximo, activos)
                time.sleep(0.05)
                with cerrojo:
                    activos -= 1
                return True

        monkeypatch.setattr("api.middleware.get_rate_limiter", lambda: _Ocupado())
        monkeypatch.setattr(mw, "_hilos_cuota", None)
        app = _app_con_rate_limit()

        async def main() -> None:
            await asyncio.gather(*(_llamar(app, "/api/v1/algo") for _ in range(10)))

        asyncio.run(main())
        assert 2 <= maximo <= mw._HILOS_CUOTA, maximo

    def test_un_path_excluido_ni_consulta_el_limitador(self, limitador: _Limitador) -> None:
        limitador.permitir = False

        resp = TestClient(_app_con_rate_limit()).get("/api/v1/health")

        assert resp.status_code == 200
        assert limitador.llamadas == []

    def test_el_tier_de_la_api_key_se_consulta_fuera_del_loop(
        self, limitador: _Limitador, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """En un fallo de caché, el tier va a la BD: también tiene que ir a un hilo."""
        con_loop: list[bool] = []

        def _tier(key_hash: str) -> int | None:
            try:
                asyncio.get_running_loop()
                con_loop.append(True)
            except RuntimeError:
                con_loop.append(False)
            return 50

        monkeypatch.setattr(mw, "_tier_limit", _tier)

        TestClient(_app_con_rate_limit()).get("/api/v1/algo", headers={"X-API-Key": "k"})

        assert con_loop == [False]
        assert limitador.llamadas[0]["key"].startswith("apikey:")
        assert limitador.llamadas[0]["max_calls"] == 50

    def test_un_interrogante_codificado_en_el_path_no_esquiva_el_tope_pesado(
        self, limitador: _Limitador
    ) -> None:
        """Se decide con el path que enruta Starlette, no con la URL reconstruida,
        que cortaba en el ``?`` y dejaba ``/explain`` con el tope por defecto."""
        app = Starlette(routes=[])
        app.add_middleware(RateLimitMiddleware)

        asyncio.run(_llamar(app, "/api/v1/licitaciones/X?/explain"))

        assert limitador.llamadas[0]["max_calls"] == 30


# ── ETag ─────────────────────────────────────────────────────────────────────


def _app_etag(handler: Callable[[Request], Awaitable[Response]]) -> Starlette:
    app = Starlette(routes=[Route("/recurso", handler)])
    app.add_middleware(ETagMiddleware)
    return app


_CUERPO = b'{"items":[1,2,3]}'


async def _json_sin_etag(request: Request) -> Response:
    return Response(_CUERPO, media_type="application/json")


class TestETag:
    def test_sin_etag_previa_se_hashea_con_blake2b(self) -> None:
        resp = TestClient(_app_etag(_json_sin_etag)).get("/recurso")

        assert resp.status_code == 200
        assert resp.content == _CUERPO
        assert resp.headers["ETag"] == etag_debil(_CUERPO)
        assert re.fullmatch(r'W/"[0-9a-f]{32}"', resp.headers["ETag"])
        assert (
            resp.headers["ETag"]
            == 'W/"' + hashlib.blake2b(_CUERPO, digest_size=16).hexdigest() + '"'
        )

    def test_sin_etag_previa_304_si_coincide(self) -> None:
        client = TestClient(_app_etag(_json_sin_etag))
        etag = client.get("/recurso").headers["ETag"]

        resp = client.get("/recurso", headers={"If-None-Match": etag})

        assert resp.status_code == 304
        assert resp.content == b""
        assert resp.headers["ETag"] == etag

    def test_con_etag_previa_ni_se_hashea_ni_se_retiene(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Contrato con ``shared/cache.py``: la etiqueta que trae la respuesta manda."""

        def _prohibido(cuerpo: bytes) -> str:
            raise AssertionError("no debe hashear una respuesta que ya trae ETag")

        monkeypatch.setattr(mw, "etag_debil", _prohibido)

        async def cacheada(request: Request) -> Response:
            return Response(
                _CUERPO, media_type="application/json", headers={"ETag": 'W/"de-la-cache"'}
            )

        resp = TestClient(_app_etag(cacheada)).get("/recurso", headers={"X-API-Key": "k"})

        assert resp.status_code == 200
        assert resp.content == _CUERPO
        assert resp.headers["ETag"] == 'W/"de-la-cache"'
        assert resp.headers["Cache-Control"] == "private, no-cache"
        assert resp.headers["Vary"] == "Cookie, X-API-Key"

    def test_con_etag_previa_304_con_las_mismas_cabeceras_que_siempre(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El 304 de la etiqueta de la caché es el mismo que el del hash."""

        async def cacheada(request: Request) -> Response:
            return Response(
                _CUERPO,
                media_type="application/json",
                headers={"ETag": etag_debil(_CUERPO), "X-Request-Id": "r-1"},
            )

        async def fresca(request: Request) -> Response:
            return Response(_CUERPO, media_type="application/json", headers={"X-Request-Id": "r-1"})

        def _prohibido(cuerpo: bytes) -> str:
            raise AssertionError("no debe hashear")

        cabeceras_304 = []
        for handler in (fresca, cacheada):
            client = TestClient(_app_etag(handler))
            if handler is cacheada:
                monkeypatch.setattr(mw, "etag_debil", _prohibido)
            resp = client.get(
                "/recurso", headers={"If-None-Match": etag_debil(_CUERPO), "Cookie": "s=1"}
            )
            assert resp.status_code == 304
            assert resp.content == b""
            cabeceras_304.append(list(resp.headers.multi_items()))

        assert cabeceras_304[0] == cabeceras_304[1]
        assert dict(cabeceras_304[1]) == {
            "x-request-id": "r-1",
            "etag": etag_debil(_CUERPO),
            "cache-control": "private, no-cache",
            "vary": "Cookie, X-API-Key",
        }

    def test_if_none_match_compara_en_debil(self) -> None:
        """RFC 9110 §13.1.2: ``"x"`` y ``W/"x"`` son la misma etiqueta."""

        async def cacheada(request: Request) -> Response:
            return Response(_CUERPO, media_type="application/json", headers={"ETag": '"fuerte"'})

        client = TestClient(_app_etag(cacheada))

        assert client.get("/recurso", headers={"If-None-Match": 'W/"fuerte"'}).status_code == 304
        assert (
            client.get("/recurso", headers={"If-None-Match": '"otra", "fuerte"'}).status_code == 304
        )
        assert client.get("/recurso", headers={"If-None-Match": '"otra"'}).status_code == 200

    def test_la_etiqueta_de_la_cache_y_la_del_hash_revalidan_igual(self) -> None:
        """Un cliente que guardó la ETag de un fallo de caché revalida contra un acierto."""
        etag_de_un_fallo = TestClient(_app_etag(_json_sin_etag)).get("/recurso").headers["ETag"]

        async def acierto(request: Request) -> Response:
            return Response(
                _CUERPO, media_type="application/json", headers={"ETag": etag_debil(_CUERPO)}
            )

        resp = TestClient(_app_etag(acierto)).get(
            "/recurso", headers={"If-None-Match": etag_de_un_fallo}
        )

        assert resp.status_code == 304

    def test_el_cache_control_del_handler_se_conserva_junto_al_del_middleware(self) -> None:
        """Comportamiento heredado, conservado a propósito.

        La versión con ``BaseHTTPMiddleware`` añadía su ``Cache-Control`` sin
        quitar el del handler (su ``headers.get("Cache-Control", …)`` nunca
        encontraba la clave en minúscula). En ``/publico/*`` salen los dos y
        manda el más restrictivo. Cambiarlo decide la cacheabilidad de la
        superficie pública en el CDN: es una decisión de producto, no parte de
        la migración a ASGI puro.
        """

        async def publica(request: Request) -> Response:
            return Response(
                _CUERPO,
                media_type="application/json",
                headers={"Cache-Control": "public, max-age=300"},
            )

        resp = TestClient(_app_etag(publica)).get("/recurso")

        valores = [v for k, v in resp.headers.multi_items() if k == "cache-control"]
        assert valores == ["public, max-age=300", "no-cache"]

    def test_un_json_mayor_que_el_tope_pasa_sin_etag_y_sin_tocar(self) -> None:
        grande = b'{"x":"' + b"a" * (512 * 1024) + b'"}'

        async def enorme(request: Request) -> Response:
            return Response(grande, media_type="application/json")

        resp = TestClient(_app_etag(enorme)).get("/recurso", headers={"X-API-Key": "k"})

        assert resp.status_code == 200
        assert resp.content == grande
        assert "ETag" not in resp.headers

    def test_lo_que_no_es_get_pasa_intacto(self) -> None:
        async def crear(request: Request) -> Response:
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route("/recurso", crear, methods=["POST"])])
        app.add_middleware(ETagMiddleware)
        resp = TestClient(app).post("/recurso")

        assert "ETag" not in resp.headers
        assert "Vary" not in resp.headers


# ── Streams: nadie los retiene ───────────────────────────────────────────────


def _app_completa(ruta: Callable[..., Any]) -> FastAPI:
    """El stack real de ``api.app.register_middlewares`` sobre una ruta de prueba."""
    from api.app import register_middlewares

    target = FastAPI()
    target.add_api_route("/api/v1/stream", ruta, methods=["GET"])
    register_middlewares(target, cors_origins=["https://app.example.test"])
    return target


@pytest.mark.parametrize(
    ("media_type", "aceptada"),
    [
        ("text/event-stream", "identity"),
        ("text/event-stream", "br"),
        ("text/event-stream", "gzip"),
        ("text/csv; charset=utf-8", "identity"),
        # Un JSON troceado también es un stream: no se retiene para hashearlo.
        ("application/json", "identity"),
    ],
)
def test_el_primer_trozo_de_un_stream_sale_antes_de_que_el_stream_acabe(
    media_type: str, aceptada: str
) -> None:
    """Ninguna capa del stack retiene un stream hasta el final.

    La app manda un primer trozo y se queda esperando a que el cliente lo haya
    recibido. Si cualquier middleware lo retuviera, la espera caducaría. Lo
    ejercita el stack entero: ETag, compresión, access log y cabeceras.
    """

    async def main() -> list[Message]:
        recibido = asyncio.Event()
        liberar = asyncio.Event()

        async def generador() -> AsyncIterator[bytes]:
            yield b"data: uno\n\n"
            await liberar.wait()
            yield b"data: dos\n\n"

        async def ruta() -> StreamingResponse:
            return StreamingResponse(generador(), media_type=media_type)

        app = _app_completa(ruta)
        enviados: list[Message] = []

        async def send(message: Message) -> None:
            enviados.append(message)
            if message["type"] == "http.response.body" and message.get("body"):
                recibido.set()

        tarea = asyncio.create_task(
            app(
                _scope("/api/v1/stream", headers={"Accept-Encoding": aceptada}),
                _receive_vacio(),
                send,
            )
        )
        await asyncio.wait_for(recibido.wait(), timeout=5)
        assert not tarea.done()
        liberar.set()
        await asyncio.wait_for(tarea, timeout=5)
        return enviados

    enviados = asyncio.run(main())
    inicio = next(m for m in enviados if m["type"] == "http.response.start")
    cabeceras = _cabeceras(inicio)
    assert inicio["status"] == 200
    assert "etag" not in cabeceras
    for nombre in _SEGURIDAD:
        assert nombre in cabeceras, nombre
    assert cabeceras["x-correlation-id"]


def test_el_access_log_de_un_stream_sale_al_empezar_no_al_acabar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``BaseHTTPMiddleware`` medía hasta las cabeceras; se conserva."""
    lineas: list[str] = []

    class _Log:
        def info(self, evento: str, **campos: Any) -> None:
            lineas.append(evento)

        def warning(self, evento: str, **campos: Any) -> None:
            lineas.append(evento)

        def debug(self, *args: Any, **kwargs: Any) -> None:
            pass

    monkeypatch.setattr(mw, "log", _Log())

    async def main() -> None:
        liberar = asyncio.Event()
        empezado = asyncio.Event()

        async def generador() -> AsyncIterator[bytes]:
            yield b"data: uno\n\n"
            await liberar.wait()

        async def ruta() -> StreamingResponse:
            return StreamingResponse(generador(), media_type="text/event-stream")

        app = _app_completa(ruta)

        async def send(message: Message) -> None:
            if message["type"] == "http.response.body" and message.get("body"):
                empezado.set()

        tarea = asyncio.create_task(app(_scope("/api/v1/stream"), _receive_vacio(), send))
        await asyncio.wait_for(empezado.wait(), timeout=5)
        assert "http_request" in lineas, "el access log esperó al final del stream"
        liberar.set()
        await asyncio.wait_for(tarea, timeout=5)

    asyncio.run(main())
    assert lineas.count("http_request") == 1


# ── Correlation id, access log y coste ───────────────────────────────────────


class _LogGrabador:
    def __init__(self) -> None:
        self.lineas: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def info(self, evento: str, **campos: Any) -> None:
        self.lineas.append((evento, campos, dict(get_contextvars())))

    def warning(self, evento: str, **campos: Any) -> None:
        self.lineas.append((evento, campos, dict(get_contextvars())))

    def debug(self, *args: Any, **kwargs: Any) -> None:
        pass

    def de(self, evento: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        return [(campos, ctx) for ev, campos, ctx in self.lineas if ev == evento]


def _app_observada() -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/items/{item_id}")
    async def item(item_id: str) -> dict[str, Any]:
        return {"item": item_id, "correlation_id": get_contextvars().get("correlation_id")}

    @app.get("/api/v1/sincrono")
    def sincrono() -> dict[str, Any]:
        # Handler `def`: corre en el threadpool, con copia del contexto.
        return {"correlation_id": get_contextvars().get("correlation_id")}

    @app.get("/api/v1/revienta")
    async def revienta() -> dict[str, Any]:
        raise RuntimeError("fallo del handler")

    app.add_middleware(ObservabilityMiddleware)
    return app


class TestObservability:
    def test_el_correlation_id_de_la_peticion_vuelve_y_llega_al_handler(self) -> None:
        resp = TestClient(_app_observada()).get(
            "/api/v1/items/7", headers={"X-Correlation-Id": "abc-123"}
        )

        assert resp.headers["X-Correlation-Id"] == "abc-123"
        assert resp.json()["correlation_id"] == "abc-123"

    def test_sin_cabecera_se_genera_uno(self) -> None:
        resp = TestClient(_app_observada()).get("/api/v1/items/7")

        generado = resp.headers["X-Correlation-Id"]
        assert re.fullmatch(r"[0-9a-f-]{36}", generado)
        assert resp.json()["correlation_id"] == generado

    def test_llega_tambien_a_un_handler_del_threadpool(self) -> None:
        resp = TestClient(_app_observada()).get(
            "/api/v1/sincrono", headers={"X-Correlation-Id": "hilo-1"}
        )

        assert resp.json()["correlation_id"] == "hilo-1"

    def test_no_se_arrastra_de_una_peticion_a_la_siguiente(self) -> None:
        client = TestClient(_app_observada())
        client.get("/api/v1/items/1", headers={"X-Correlation-Id": "primera"})

        segunda = client.get("/api/v1/items/2")

        assert segunda.json()["correlation_id"] != "primera"

    def test_campos_del_access_log(self, monkeypatch: pytest.MonkeyPatch) -> None:
        grabador = _LogGrabador()
        monkeypatch.setattr(mw, "log", grabador)
        monkeypatch.setattr(mw, "_trusted_client_ip", lambda conexion: "198.51.100.4")

        TestClient(_app_observada()).get(
            "/api/v1/items/7",
            headers={"X-Correlation-Id": "log-1", "X-API-Key": "clave-secreta"},
        )

        ((campos, contexto),) = grabador.de("http_request")
        assert campos["method"] == "GET"
        assert campos["path"] == "/api/v1/items/{item_id}", "la plantilla, no el path crudo"
        assert campos["status"] == 200
        assert isinstance(campos["duration_ms"], float) and campos["duration_ms"] >= 0
        assert campos["key_prefix"] == hashlib.sha256(b"clave-secreta").hexdigest()[:12]
        assert campos["client_ip"] == "198.51.100.4"
        assert contexto["correlation_id"] == "log-1"

    def test_sin_api_key_el_prefijo_es_un_guion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        grabador = _LogGrabador()
        monkeypatch.setattr(mw, "log", grabador)

        TestClient(_app_observada()).get("/api/v1/items/7")

        ((campos, _),) = grabador.de("http_request")
        assert campos["key_prefix"] == "-"

    def test_una_excepcion_se_registra_como_500_y_sube_intacta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Como con ``BaseHTTPMiddleware``: el access log dice 500 y el
        ``ServerErrorMiddleware`` recibe la excepción original."""
        grabador = _LogGrabador()
        monkeypatch.setattr(mw, "log", grabador)

        with pytest.raises(RuntimeError, match="fallo del handler"):
            TestClient(_app_observada()).get("/api/v1/revienta")

        ((campos, _),) = grabador.de("http_request")
        assert campos["status"] == 500
        assert campos["path"] == "/api/v1/revienta"

        resp = TestClient(_app_observada(), raise_server_exceptions=False).get("/api/v1/revienta")
        assert resp.status_code == 500

    def test_coste_por_plantilla_de_ruta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import observability.runtime_metrics as metricas

        registrado: list[tuple[str, int]] = []

        class _Contador:
            def labels(self, *, operation: str) -> Any:
                class _Hijo:
                    def inc(self, valor: int) -> None:
                        registrado.append((operation, valor))

                return _Hijo()

        monkeypatch.setattr(metricas, "api_cost_estimate_total", _Contador())

        TestClient(_app_observada()).get("/api/v1/items/7")

        ((operacion, micros),) = registrado
        assert operacion == "/api/v1/items/{item_id}"
        assert micros >= 100  # el coste base: 0.0001 USD


# ── El stack completo ────────────────────────────────────────────────────────


class TestStack:
    def test_orden_de_ejecucion(self) -> None:
        """El orden no es cosmético (docstring de ``register_middlewares``)."""
        from fastapi.middleware.cors import CORSMiddleware

        from api.app import register_middlewares
        from api.middleware import _MaxBodyMiddleware, _RejectNulMiddleware

        target = FastAPI()
        register_middlewares(target, cors_origins=["https://app.example.test"])
        clases = [m.cls for m in target.user_middleware]

        compresion = clases[4]
        assert compresion.__name__ in {"BrotliMiddleware", "GZipMiddleware"}
        assert clases == [
            CORSMiddleware,
            SecurityHeadersMiddleware,
            ObservabilityMiddleware,
            RateLimitMiddleware,
            compresion,
            _MaxBodyMiddleware,
            _RejectNulMiddleware,
            ETagMiddleware,
        ]

    def test_ninguna_capa_de_la_app_real_es_base_http_middleware(self) -> None:
        from prometheus_fastapi_instrumentator.middleware import (
            PrometheusInstrumentatorMiddleware,
        )

        from api.app import app

        clases = [m.cls for m in app.user_middleware]
        assert not [c for c in clases if isinstance(c, type) and issubclass(c, BaseHTTPMiddleware)]
        assert not [m for m in app.user_middleware if "dispatch" in m.kwargs]
        # El del instrumentator se registra antes que el bloque y queda el más interno.
        assert clases[-1] is PrometheusInstrumentatorMiddleware

    def test_cabeceras_de_seguridad_y_correlacion_en_200_304_y_429(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doble = _Limitador()
        monkeypatch.setattr("api.middleware.get_rate_limiter", lambda: doble)
        monkeypatch.setattr(mw, "_hilos_cuota", None)

        target = FastAPI()

        @target.get("/api/v1/probe")
        async def probe() -> dict[str, bool]:
            return {"ok": True}

        from api.app import register_middlewares

        register_middlewares(target, cors_origins=["https://app.example.test"])
        client = TestClient(target)
        origen = {"Origin": "https://app.example.test"}

        ok = client.get("/api/v1/probe", headers=origen)
        no_modificado = client.get(
            "/api/v1/probe", headers={**origen, "If-None-Match": ok.headers["ETag"]}
        )
        doble.permitir = False
        limitado = client.get("/api/v1/probe", headers=origen)

        assert (ok.status_code, no_modificado.status_code, limitado.status_code) == (200, 304, 429)
        for resp in (ok, no_modificado, limitado):
            for nombre in _SEGURIDAD:
                assert nombre in resp.headers, (resp.status_code, nombre)
            assert resp.headers["access-control-allow-origin"] == "https://app.example.test"
            assert resp.headers["X-Correlation-Id"]

    def test_un_json_pequeno_llega_entero_a_la_compresion(self) -> None:
        """Con los relés de ``BaseHTTPMiddleware`` toda respuesta llegaba troceada a
        la compresión, que por eso comprimía hasta las de menos de 1 KB y quitaba
        ``Content-Length``. Ahora rige su ``minimum_size``."""
        target = FastAPI()

        @target.get("/api/v1/probe")
        async def probe() -> dict[str, bool]:
            return {"ok": True}

        from api.app import register_middlewares

        register_middlewares(target, cors_origins=[])
        resp = TestClient(target).get("/api/v1/probe", headers={"Accept-Encoding": "br, gzip"})

        assert resp.status_code == 200
        assert "content-encoding" not in resp.headers
        assert resp.headers["content-length"] == str(len(resp.content))
