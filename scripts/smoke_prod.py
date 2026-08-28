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


def _status_ok(payload: Any) -> str | None:
    status = payload.get("status") if isinstance(payload, dict) else None
    if status not in ("healthy", "ok", "ready", "degraded"):
        return f"status inesperado: {status!r}"
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


def _fetch(base: str, path: str) -> tuple[int, Any]:
    url = base.rstrip("/") + path
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"SMOKE_BASE_URL debe ser http(s), no: {url!r}")
    req = urllib.request.Request(url)  # noqa: S310 — esquema validado arriba
    api_key = os.environ.get("SMOKE_API_KEY", "")
    if api_key:
        req.add_header("X-API-Key", api_key)
    cookie = os.environ.get("SMOKE_SESSION_COOKIE", "")
    if cookie:
        req.add_header("Cookie", f"session={cookie}")
    # `url` sale de SMOKE_BASE_URL (config de despliegue, no de un request de
    # usuario) y el guard de arriba ya rechaza cualquier esquema que no sea
    # http(s), que es justo lo que la regla teme (`file://`). Este módulo es
    # stdlib-only a propósito — ver el docstring —, así que cambiar a
    # `requests`, la alternativa que sugiere la regla, no es una opción.
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — URL de config propia
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
