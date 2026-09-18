"""`_MaxBodyMiddleware` real ante cuerpos que llegan troceados y sin `Content-Length`.

`test_unit_maxbody_middleware.py` prueba una copia del middleware escrita dentro
del propio test, no la clase de `api.middleware`. Aquí se prueba la clase real
por su camino lento (`limiting_receive`, que suma los bytes mensaje a mensaje).
Es el único que limita un cuerpo sin `Content-Length`, porque el camino rápido
solo mira esa cabecera: el caso de un cliente que manda el cuerpo con
`Transfer-Encoding: chunked`.

Casi todo se habla en ASGI directamente y no con `TestClient`: el de Starlette
junta en un único mensaje `http.request` el cuerpo que se le da por trozos, y lo
que se fija aquí es que el límite se aplica a la **suma** de los trozos, no a
cada uno. La excepción es el test de la ruta FastAPI, donde lo que se fija es la
respuesta que ve el cliente y no cómo llega el cuerpo.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.middleware import _BodyTooLargeError, _MaxBodyMiddleware

LIMITE = _MaxBodyMiddleware._MAX_BYTES
TROZO = 256 * 1024
METODOS_CON_CUERPO = ("POST", "PUT", "PATCH")


async def _leer_todo(receive: Receive) -> int:
    """Consume el cuerpo entero, como `Request.body()`, y devuelve cuántos bytes leyó."""
    leidos = 0
    while True:
        mensaje = await receive()
        leidos += len(mensaje.get("body", b""))
        if not mensaje.get("more_body", False):
            return leidos


class _AppQueLeeTodo:
    """App ASGI que consume el cuerpo entero y responde 200."""

    def __init__(self) -> None:
        self.bytes_recibidos = 0
        self.leyo_el_cuerpo_entero = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def contando() -> Message:
            mensaje = await receive()
            self.bytes_recibidos += len(mensaje.get("body", b""))
            return mensaje

        await _leer_todo(contando)
        self.leyo_el_cuerpo_entero = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


async def _app_que_convierte_el_error_en_400(scope: Scope, receive: Receive, send: Send) -> None:
    """Lo que hace FastAPI con una ruta con cuerpo: el error de lectura acaba en un 400."""
    try:
        await _leer_todo(receive)
    except Exception:
        await send({"type": "http.response.start", "status": 400, "headers": []})
        await send({"type": "http.response.body", "body": b"There was an error parsing the body"})


async def _app_que_responde_antes_de_leer(scope: Scope, receive: Receive, send: Send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await _leer_todo(receive)
    await send({"type": "http.response.body", "body": b"ok"})


def _ejecutar(app: ASGIApp, metodo: str, trozos: list[bytes], enviados: list[Message]) -> None:
    """Pasa `trozos` por el middleware real, un mensaje por trozo y sin `Content-Length`.

    Lo que el middleware manda al servidor queda en `enviados`, también si lanza.
    """
    pendientes = list(trozos)

    async def receive() -> Message:
        cuerpo = pendientes.pop(0)
        return {"type": "http.request", "body": cuerpo, "more_body": bool(pendientes)}

    async def send(mensaje: Message) -> None:
        enviados.append(mensaje)

    scope: Scope = {
        "type": "http",
        "method": metodo,
        "path": "/",
        "headers": [(b"content-type", b"application/json")],
    }
    asyncio.run(_MaxBodyMiddleware(app)(scope, receive, send))


def _enviar_troceado(metodo: str, trozos: list[bytes]) -> tuple[_AppQueLeeTodo, list[Message]]:
    app = _AppQueLeeTodo()
    enviados: list[Message] = []
    _ejecutar(app, metodo, trozos, enviados)
    return app, enviados


def _inicios(enviados: list[Message]) -> list[Message]:
    return [m for m in enviados if m["type"] == "http.response.start"]


_CUERPO_413: Message = {"type": "http.response.body", "body": _MaxBodyMiddleware._413_BODY}


@pytest.mark.parametrize("metodo", METODOS_CON_CUERPO)
def test_trozos_que_juntos_pasan_del_limite_dan_413(metodo: str) -> None:
    """Ningún trozo pasa del límite por sí solo; la suma sí.

    La app no llega a leer el cuerpo entero ni a responder, recibe como mucho el
    límite, y el cliente ve el 413 `problem+json` del middleware.
    """
    trozos = [b"x" * TROZO] * 8  # 2 MiB en trozos de 256 KiB
    assert max(map(len, trozos)) < LIMITE < sum(map(len, trozos))

    app, enviados = _enviar_troceado(metodo, trozos)

    inicios = _inicios(enviados)
    assert [m["status"] for m in inicios] == [413]
    assert (b"content-type", b"application/problem+json") in inicios[0]["headers"]
    assert enviados[-1] == _CUERPO_413
    assert app.leyo_el_cuerpo_entero is False
    assert app.bytes_recibidos <= LIMITE


@pytest.mark.parametrize("metodo", METODOS_CON_CUERPO)
def test_trozos_que_suman_justo_el_limite_llegan_enteros(metodo: str) -> None:
    """El límite es inclusivo: 1 MiB exacto en cuatro trozos pasa y la app lo lee todo."""
    trozos = [b"x" * TROZO] * 4
    assert sum(map(len, trozos)) == LIMITE

    app, enviados = _enviar_troceado(metodo, trozos)

    assert [m["status"] for m in _inicios(enviados)] == [200]
    assert app.leyo_el_cuerpo_entero is True
    assert app.bytes_recibidos == LIMITE


def test_un_byte_por_encima_del_limite_en_el_ultimo_trozo_ya_es_413() -> None:
    trozos = [b"x" * TROZO] * 4 + [b"x"]

    app, enviados = _enviar_troceado("POST", trozos)

    assert [m["status"] for m in _inicios(enviados)] == [413]
    assert app.leyo_el_cuerpo_entero is False


def test_si_la_app_responde_al_error_de_lectura_el_cliente_solo_ve_el_413() -> None:
    """La respuesta que la app dé tras el corte se descarta entera: el servidor
    recibe solo el 413 del middleware, sin el `http.response.start` ni el cuerpo
    del 400."""
    enviados: list[Message] = []

    _ejecutar(_app_que_convierte_el_error_en_400, "POST", [b"x" * TROZO] * 8, enviados)

    assert [m["status"] for m in _inicios(enviados)] == [413]
    assert enviados[-1] == _CUERPO_413
    assert len(enviados) == 2


def test_si_la_app_ya_habia_empezado_a_responder_el_corte_no_manda_otro_inicio() -> None:
    """Un segundo `http.response.start` rompería el protocolo ASGI: la respuesta
    empezada pasa tal cual y el error del corte sale del middleware."""
    enviados: list[Message] = []

    with pytest.raises(_BodyTooLargeError):
        _ejecutar(_app_que_responde_antes_de_leer, "POST", [b"x" * TROZO] * 8, enviados)

    assert [m["status"] for m in _inicios(enviados)] == [200]
    assert _CUERPO_413 not in enviados


def test_una_ruta_fastapi_con_cuerpo_json_tambien_responde_413() -> None:
    """Mismo caso a través de FastAPI: cuerpo sin `Content-Length` hacia una ruta con
    cuerpo JSON.

    FastAPI convierte el error de lectura en su 400 «There was an error parsing
    the body»; aun así el cliente recibe el 413 `problem+json` del middleware y
    la ruta no llega a ejecutarse. El relleno son espacios: si el middleware no
    cortara, FastAPI leería los 2 MiB y respondería 422 por JSON inválido.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    api = FastAPI()
    ejecuciones: list[int] = []

    @api.put("/json")
    async def _con_cuerpo(body: list[int]) -> dict[str, int]:
        ejecuciones.append(len(body))
        return {"n": len(body)}

    api.add_middleware(_MaxBodyMiddleware)

    def _cuerpo() -> Iterator[bytes]:
        for _ in range(8):
            yield b" " * TROZO

    respuesta = TestClient(api, raise_server_exceptions=False).put(
        "/json", content=_cuerpo(), headers={"content-type": "application/json"}
    )
    assert "content-length" not in respuesta.request.headers, (
        "la petición lleva Content-Length: no ejercita el camino lento"
    )
    assert respuesta.status_code == 413
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert respuesta.content == _MaxBodyMiddleware._413_BODY
    assert ejecuciones == []
