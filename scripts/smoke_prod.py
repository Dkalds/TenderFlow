#!/usr/bin/env python3
"""Chequeo sintético post-deploy: los endpoints insignia devuelven datos reales.

Motivación (revisión de arquitectura 2026-08): dos incidentes seguidos en los
que producción respondía 200 con payloads vacíos sin que nada lo detectara —
la pantalla de Resumen en blanco (cortacircuitos full-table, ADR-023) y
Oportunidades siempre vacío (gate de organización en el frontend). Un job
verde de healthcheck no cubre "el endpoint responde pero no dice nada".

Uso::

    SMOKE_BASE_URL=https://api.example.com SMOKE_SESSION_COOKIE=... \
        python scripts/smoke_prod.py

    # o con API key (endpoints que la aceptan):
    SMOKE_BASE_URL=... SMOKE_API_KEY=... python scripts/smoke_prod.py

Los checks de ``/api/v1/publico/*`` son los que más importan, aunque en la
lista sean los últimos en llegar: son la única superficie que consume un
visitante anónimo —y Googlebot—, así que un fallo ahí lo ve todo internet antes
de que ningún cliente autenticado se entere. Y no es hipotético: el 2026-08-28
la superficie pública entera respondió 500 durante horas y este smoke salió
VERDE (run de las 09:44 UTC) porque no tocaba ni un endpoint público. Además,
al no exigir credenciales, no pueden degradar al camino "401: check omitido"
que sí puede vaciar de contenido a los checks privados cuando el runner corre
sin secretos.

Exit 0 si todos los checks pasan; 1 con el detalle de los que fallan. Pensado
para un workflow programado o `make smoke-prod` tras cada deploy.

Solo stdlib: corre en cualquier runner sin instalar dependencias.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

Check = tuple[str, str, Callable[[Any], str | None]]


def _non_empty_list(key: str) -> Callable[[Any], str | None]:
    def _check(payload: Any) -> str | None:
        items = payload.get(key) if isinstance(payload, dict) else None
        if not items:
            return f"'{key}' vacío — posible payload degradado (ADR-023)"
        return None

    return _check


def _positive(key: str) -> Callable[[Any], str | None]:
    def _check(payload: Any) -> str | None:
        value = payload.get(key) if isinstance(payload, dict) else None
        if not value:
            return f"'{key}' es 0/None — posible payload degradado"
        return None

    return _check


def _non_empty_lists(*keys: str) -> Callable[[Any], str | None]:
    """Exige que **todas** las listas nombradas traigan algo.

    ``/publico/hubs`` devuelve dos índices independientes en la misma respuesta
    (``ccaa`` y ``cpv``) y cada uno alimenta su propia página de índice: mirar
    solo uno dejaría que la mitad del árbol público se vaciara en verde.
    """

    def _check(payload: Any) -> str | None:
        for key in keys:
            problema = _non_empty_list(key)(payload)
            if problema:
                return problema
        return None

    return _check


# Estados de `schema_revision` (api/routes/health.py) que significan "el código
# desplegado y el schema aplicado NO son la misma generación". Es el agujero que
# describe S6.2: `deploy.yml` puede publicar código que exige la revisión N+1
# sobre una BD en N y todos los gates salen verdes, que es exactamente el
# incidente de `column "lote_id" of relation "adjudicaciones" does not exist`.
_SCHEMA_DESALINEADO = ("behind", "ahead")


def _status_ok(payload: Any) -> str | None:
    """Valida `/health/ready`: estado global **y** alineación del schema.

    ``degraded`` se sigue aceptando como estado global —Redis o disco tocados no
    hacen inservible a la API—, pero un ``schema_revision`` desalineado sí es
    fallo: la superficie responde 200 mientras cualquier consulta que toque una
    columna nueva revienta.

    Si la clave no viene (una versión de la API anterior a este cambio, o un
    despliegue a medias), no se inventa un fallo: se deja pasar. Un smoke que
    falla contra binarios viejos no distingue "roto" de "todavía no desplegado".
    """
    if not isinstance(payload, dict):
        return f"status inesperado: {payload!r}"
    status = payload.get("status")
    if status not in ("healthy", "ok", "ready", "degraded"):
        return f"status inesperado: {status!r}"
    schema = payload.get("schema_revision")
    if isinstance(schema, str) and schema.startswith(_SCHEMA_DESALINEADO):
        return (
            f"schema desalineado ({schema}) — el código desplegado y la BD no son "
            "la misma generación; aplicá migrate.yml (mode=apply) antes de dar el "
            "deploy por bueno"
        )
    return None


# Rutas que un anónimo tiene que poder leer. Un 401/403 aquí no se puede
# perdonar como "el smoke corre sin credenciales" (ver `main`): es exactamente
# el fallo que el router público existe para evitar — que el catch-all
# autenticado de `/api/v1/licitaciones/{id:path}` ensombrezca una ruta pública.
_PREFIJO_PUBLICO = "/api/v1/publico/"

# Endpoints insignia: si alguno responde vacío, la pantalla principal
# correspondiente está rota aunque el HTTP sea 200.
#
# Los `publico_*` cierran el agujero que describe el docstring del módulo: sin
# ellos, la superficie anónima podía caerse entera sin que este script se
# inmutara.
CHECKS: list[Check] = [
    ("health", "/api/v1/health/ready", _status_ok),
    ("overview", "/api/v1/analytics/overview", _positive("total_licitaciones")),
    ("resumen_hoy", "/api/v1/analytics/resumen/hoy", _positive("total_activas")),
    ("licitaciones", "/api/v1/licitaciones?limit=1", _non_empty_list("items")),
    ("trends", "/api/v1/analytics/trends?group_by=month", _non_empty_list("series")),
    ("publico_sitemap", "/api/v1/publico/sitemap/resumen", _positive("total")),
    ("publico_hubs", "/api/v1/publico/hubs", _non_empty_lists("ccaa", "cpv")),
    ("publico_licitaciones", "/api/v1/publico/licitaciones?limit=1", _non_empty_list("items")),
]


# `http://` solo contra la máquina local: ahí no hay red que interceptar y es el
# modo en que se usa `make smoke-prod` contra una API levantada a mano. Cualquier
# otro destino tiene que ir por TLS — este script manda `SMOKE_API_KEY` y la
# cookie de sesión en cada petición.
_HOSTS_SIN_TLS = frozenset({"localhost", "127.0.0.1", "::1"})


def _resolver_url(base: str, path: str) -> str:
    """Compone y **valida** la URL final contra la base esperada.

    El guard anterior era un ``startswith(("https://", "http://"))`` sobre la
    cadena ya concatenada, que acepta ``http://`` contra cualquier host de
    internet y no comprueba en absoluto que el destino final siga siendo el
    servicio que se quería sondear. Aquí se exige, en este orden:

    1. ``SMOKE_BASE_URL`` parseable, con esquema ``https`` (o ``http`` solo
       contra loopback) y con host.
    2. ``path`` relativo — un ``path`` absoluto (``https://otro-host/...``)
       reescribiría el destino entero al concatenar.
    3. La URL resultante conserva esquema, host y puerto de la base.

    El punto 3 es lo que convierte a ``urlopen`` en una llamada de destino
    conocido: aunque ``CHECKS`` son constantes de este módulo, la comprobación
    no depende de que sigan siéndolo.
    """
    partes_base = urllib.parse.urlsplit(base.rstrip("/"))
    if partes_base.scheme not in ("https", "http"):
        raise ValueError(f"SMOKE_BASE_URL debe ser https (o http en local): {base!r}")
    if not partes_base.hostname:
        raise ValueError(f"SMOKE_BASE_URL no tiene host: {base!r}")
    if partes_base.scheme == "http" and partes_base.hostname not in _HOSTS_SIN_TLS:
        raise ValueError(
            f"SMOKE_BASE_URL usa http contra un host remoto ({partes_base.hostname}): "
            "las credenciales del smoke viajarían en claro. Usá https."
        )
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError(f"El path del check debe ser relativo a la base: {path!r}")

    url = base.rstrip("/") + path
    partes = urllib.parse.urlsplit(url)
    if (partes.scheme, partes.hostname, partes.port) != (
        partes_base.scheme,
        partes_base.hostname,
        partes_base.port,
    ):
        raise ValueError(f"La URL compuesta apunta fuera de SMOKE_BASE_URL: {url!r}")
    return url


def _fetch(base: str, path: str) -> tuple[int, Any]:
    url = _resolver_url(base, path)
    req = urllib.request.Request(url)  # noqa: S310 — esquema y host validados arriba
    api_key = os.environ.get("SMOKE_API_KEY", "")
    if api_key:
        req.add_header("X-API-Key", api_key)
    cookie = os.environ.get("SMOKE_SESSION_COOKIE", "")
    if cookie:
        req.add_header("Cookie", f"session={cookie}")
    # `url` sale de SMOKE_BASE_URL (config de despliegue, no de un request de
    # usuario) y `_resolver_url` ya fijó esquema, host y puerto contra esa base,
    # que es más de lo que la regla pide (teme un `file://` o una redirección de
    # destino). Este módulo es stdlib-only a propósito — ver el docstring —, así
    # que cambiar a `requests`, la alternativa que sugiere la regla, no es una
    # opción. El `nosemgrep` va en la MISMA línea del match: en la línea anterior
    # no lo aplicaba (el hallazgo seguía apareciendo en el escaneo del 2026-08-17
    # y con él `security.yml` en rojo).
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310  # nosemgrep
        body = resp.read()
        return resp.status, json.loads(body) if body else None


def main() -> int:
    base = os.environ.get("SMOKE_BASE_URL", "")
    if not base:
        print("SMOKE_BASE_URL no definida", file=sys.stderr)
        return 2

    failures: list[str] = []
    for name, path, validate in CHECKS:
        try:
            status, payload = _fetch(base, path)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403) and not path.startswith(_PREFIJO_PUBLICO):
                # Sin credenciales el endpoint exige auth: se reporta pero no
                # se considera fallo de datos (el check de datos exige correr
                # con SMOKE_API_KEY o SMOKE_SESSION_COOKIE).
                #
                # La excepción son las rutas de `_PREFIJO_PUBLICO`: ahí nadie
                # tiene que autenticarse, así que un 401/403 cae al camino de
                # fallo de abajo en vez de convertirse en un check omitido —
                # que es como esta indulgencia habría tragado en silencio el
                # incidente que motivó añadirlos.
                print(f"  ~ {name}: {exc.code} (sin credenciales; check omitido)")
                continue
            failures.append(f"{name}: HTTP {exc.code}")
            continue
        except Exception as exc:  # red, timeout, JSON inválido
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            continue

        problem = validate(payload) if status == 200 else f"HTTP {status}"
        if problem:
            failures.append(f"{name}: {problem}")
        else:
            print(f"  ✓ {name}")

    if failures:
        print(f"\n{len(failures)} check(s) sintéticos fallaron:", file=sys.stderr)
        for f in failures:
            print(f"  ✗ {f}", file=sys.stderr)
        return 1

    print("\nTodos los checks sintéticos en verde.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
