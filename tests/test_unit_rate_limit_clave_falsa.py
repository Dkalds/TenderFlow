"""Una ``X-API-Key`` inventada no abre cubo propio ni esquiva los topes de IP.

``RateLimitMiddleware`` abría un cubo ``apikey:<hash>`` con cualquier valor de la
cabecera sin comprobar que la clave existiera, y lo usaba **en lugar** del cubo
de la IP: rotar cadenas aleatorias estrenaba cuota en cada petición y dejaba sin
efecto el tope global (120/min), los de los endpoints pesados (``/ask``…) y el
del formulario público de solicitudes (5/min). Aquí se ejercita el middleware
entero —con un limitador en memoria que cuenta de verdad, y la BD de claves
simulada— y se comprueba que:

* muchas claves falsas desde una IP topan con el límite de esa IP;
* una clave viva conserva su cubo y su tier (C2.3) y no gasta cuota de IP;
* una IPv6 cuenta por su /64.

Sin BD ni red: todo con ``monkeypatch``.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

import api.middleware as mw
from api.middleware import RateLimitMiddleware, _regla_pesada
from services.rate_limiting import ip_de_cuota

Message = dict[str, Any]

_VIVA = "clave-viva-de-un-cliente"  # pragma: allowlist secret
_SOLICITUDES = "/api/v1/publico/solicitudes-acceso"


class _LimitadorEnMemoria:
    """Cuenta de verdad por clave: ``check`` permite hasta ``max_calls`` y niega el resto."""

    def __init__(self) -> None:
        self.cuentas: Counter[str] = Counter()

    def check(self, key: str, *, max_calls: int = 120, window_seconds: float = 60.0) -> bool:
        if self.cuentas[key] >= max_calls:
            return False
        self.cuentas[key] += 1
        return True


class _BdDeClaves:
    """Doble de ``tier_de_clave_por_hash``: solo ``_VIVA`` existe, con un tope de 7."""

    def __init__(self, hash_viva: str) -> None:
        self.hash_viva = hash_viva
        self.lecturas: list[str] = []

    def __call__(self, key_hash: str) -> tuple[bool, int | None]:
        self.lecturas.append(key_hash)
        return (True, 7) if key_hash == self.hash_viva else (False, None)


@pytest.fixture()
def limitador(monkeypatch: pytest.MonkeyPatch) -> _LimitadorEnMemoria:
    doble = _LimitadorEnMemoria()
    monkeypatch.setattr("api.middleware.get_rate_limiter", lambda: doble)
    monkeypatch.setattr(mw, "_hilos_cuota", None)
    mw.reset_tier_cache()
    yield doble
    mw.reset_tier_cache()


@pytest.fixture()
def bd_de_claves(monkeypatch: pytest.MonkeyPatch) -> _BdDeClaves:
    import db.repositories.api_keys as repo
    from api.auth import hash_api_key

    doble = _BdDeClaves(hash_api_key(_VIVA))
    monkeypatch.setattr(repo, "tier_de_clave_por_hash", doble)
    return doble


def _app() -> Starlette:
    async def ok(request: Request) -> Response:
        return JSONResponse({"ok": True})

    rutas = [
        Route("/api/v1/algo", ok, methods=["GET", "POST"]),
        Route("/api/v1/ask", ok, methods=["GET", "POST"]),
        Route(_SOLICITUDES, ok, methods=["POST"]),
    ]
    app = Starlette(routes=rutas)
    app.add_middleware(RateLimitMiddleware)
    return app


def _scope(
    path: str, *, ip: str, headers: dict[str, str] | None = None, method: str = "GET"
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
        "client": (ip, 50000),
        "server": ("testserver", 80),
    }


async def _una(app: Any, path: str, *, ip: str, clave: str | None, method: str = "GET") -> int:
    """Código HTTP de una petición ASGI con la clave dada (o sin cabecera)."""
    inicio: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            inicio.append(message)

    cabeceras = {"x-api-key": clave} if clave is not None else None
    await app(_scope(path, ip=ip, headers=cabeceras, method=method), receive, send)
    return int(inicio[0]["status"])


def _rafaga(
    path: str,
    n: int,
    *,
    ip: str = "198.51.100.7",
    claves: Callable[[int], str | None],
    method: str = "GET",
) -> list[int]:
    app = _app()

    async def main() -> list[int]:
        return [await _una(app, path, ip=ip, clave=claves(i), method=method) for i in range(n)]

    return asyncio.run(main())


# ── Claves falsas ────────────────────────────────────────────────────────────


def test_claves_falsas_desde_una_ip_topan_con_el_limite_global(
    limitador: _LimitadorEnMemoria, bd_de_claves: _BdDeClaves
) -> None:
    codigos = _rafaga("/api/v1/algo", 130, claves=lambda i: f"inventada-{i}")

    assert codigos[:120] == [200] * 120
    assert set(codigos[120:]) == {429}, "rotar claves estrenaba cuota en cada petición"
    assert set(limitador.cuentas) == {"api:ip:198.51.100.7"}


def test_claves_falsas_no_evaden_el_tope_de_un_endpoint_pesado(
    limitador: _LimitadorEnMemoria, bd_de_claves: _BdDeClaves
) -> None:
    codigos = _rafaga("/api/v1/ask", 14, claves=lambda i: f"inventada-{i}", method="POST")

    assert codigos == [200] * 10 + [429] * 4
    assert set(limitador.cuentas) == {"pesado:/api/v1/ask:api:ip:198.51.100.7"}


def test_claves_falsas_no_evaden_el_tope_del_formulario_publico(
    limitador: _LimitadorEnMemoria, bd_de_claves: _BdDeClaves
) -> None:
    codigos = _rafaga(_SOLICITUDES, 8, claves=lambda i: f"inventada-{i}", method="POST")

    # Pasadas las cinco, el corte redirige a la página de gracias (303), no 429.
    assert codigos == [200] * 5 + [303] * 3
    assert set(limitador.cuentas) == {"solicitudes:ip:198.51.100.7"}


def test_una_clave_inventada_cuenta_igual_que_no_traer_cabecera(
    limitador: _LimitadorEnMemoria, bd_de_claves: _BdDeClaves
) -> None:
    """Mezclar falsas y sin cabecera desde la misma IP comparte un solo cubo."""
    codigos = _rafaga("/api/v1/algo", 125, claves=lambda i: None if i % 2 else f"falsa-{i}")

    assert codigos[:120] == [200] * 120
    assert set(codigos[120:]) == {429}


def test_una_clave_repetida_e_inexistente_solo_cuesta_una_lectura(
    limitador: _LimitadorEnMemoria, bd_de_claves: _BdDeClaves
) -> None:
    _rafaga("/api/v1/algo", 20, claves=lambda i: "siempre-la-misma")

    assert len(bd_de_claves.lecturas) == 1


# ── Claves vivas: el comportamiento de C2.3 se conserva ──────────────────────


def test_una_clave_viva_conserva_su_cubo_y_el_tope_de_su_tier(
    limitador: _LimitadorEnMemoria, bd_de_claves: _BdDeClaves
) -> None:
    codigos = _rafaga("/api/v1/algo", 10, claves=lambda i: _VIVA)

    assert codigos == [200] * 7 + [429] * 3, "el tier de la clave fija el tope (7)"
    (cubo,) = limitador.cuentas
    assert cubo.startswith("apikey:")
    assert _VIVA not in cubo, "el token no sale a la clave del limitador"


def test_el_cubo_de_una_clave_viva_no_depende_de_la_ip(
    limitador: _LimitadorEnMemoria, bd_de_claves: _BdDeClaves
) -> None:
    """Dos IP con la misma clave comparten cuota; la IP no gasta la suya."""
    app = _app()

    async def main() -> list[int]:
        return [
            await _una(app, "/api/v1/algo", ip=f"198.51.100.{i}", clave=_VIVA) for i in range(1, 10)
        ]

    codigos = asyncio.run(main())

    assert codigos == [200] * 7 + [429] * 2
    assert all(not k.startswith("api:ip:") for k in limitador.cuentas)


# ── IPv6 por /64 ─────────────────────────────────────────────────────────────


def test_ip_de_cuota_agrupa_ipv6_por_64_y_deja_el_resto() -> None:
    assert ip_de_cuota("2001:db8:1:2:aaaa:bbbb:cccc:dddd") == "2001:db8:1:2::/64"
    assert ip_de_cuota("2001:db8:1:2::1") == "2001:db8:1:2::/64"
    assert ip_de_cuota("2001:db8:1:3::1") == "2001:db8:1:3::/64"
    assert ip_de_cuota("203.0.113.9") == "203.0.113.9"
    assert ip_de_cuota("::ffff:203.0.113.9") == "203.0.113.9"
    assert ip_de_cuota("unknown") == "unknown"


def test_direcciones_ipv6_de_un_mismo_64_comparten_cubo(
    limitador: _LimitadorEnMemoria, bd_de_claves: _BdDeClaves
) -> None:
    app = _app()

    async def main() -> list[int]:
        return [
            await _una(app, "/api/v1/algo", ip=f"2001:db8:1:2:{i:x}::{i:x}", clave=None)
            for i in range(1, 131)
        ]

    codigos = asyncio.run(main())

    assert codigos[:120] == [200] * 120
    assert set(codigos[120:]) == {429}
    assert set(limitador.cuentas) == {"api:ip:2001:db8:1:2::/64"}


# ── Rutas pesadas asíncronas ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ruta",
    [
        "/api/v1/licitaciones/PA-S 2026/000058/ficha-pliego/extract-async",
        "/api/v1/licitaciones/123/embeddings-async",
        "/api/v1/licitaciones/123/guion",
    ],
)
def test_las_rutas_async_de_la_ficha_y_el_guion_son_pesadas(ruta: str) -> None:
    regla = _regla_pesada(ruta)

    assert regla is not None
    assert regla[1] == 10


def test_el_resto_de_rutas_de_la_ficha_siguen_al_tope_por_defecto() -> None:
    assert _regla_pesada("/api/v1/licitaciones/123/ficha-pliego/estado") is None
    assert _regla_pesada("/api/v1/licitaciones/123/guion.pdf") is None
