#!/usr/bin/env python3
"""Espera a que la API sirva el commit que se acaba de desplegar.

Motivación (2026-10-15): ``deploy.yml`` daba la API por lista con el primer 200
de ``/health/ready``. Render despliega sin corte —la instancia anterior sigue
respondiendo hasta que la nueva está viva—, así que ese 200 lo daba casi
siempre la vieja, y el gate de schema y el smoke la verificaban a ella. En el
run 38766484577 la espera salió al primer intento (16:08:53), schema y smoke
terminaron a las 16:09:05 y el deploy encolado no quedó vivo hasta las
16:09:32. Con ``autoDeploy`` apagado, que es lo decidido (D4), el gate habría
verificado siempre el commit anterior: un deploy que no arranca —Render
mantiene viva la instancia vieja— salía en verde.

``/health/ready`` publica ahora ``commit`` (``RENDER_GIT_COMMIT``), y este
script sondea hasta que la respuesta es 200 **y** trae el commit esperado. Al
terminar deja ese payload en ``--salida``, para que el gate de schema juzgue la
instancia que se verificó en vez de volver a preguntar.

Uso::

    SMOKE_BASE_URL=https://api.example.com \
        python scripts/esperar_deploy.py --commit <sha> [--salida ready.json]

Exit 0 cuando responde el commit esperado; 1 si vence el plazo, con lo último
que respondió, o al momento si la API contesta ``commit: unknown``; 2 si falta
configuración. Solo stdlib, como ``smoke_prod.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.smoke_prod import _resolver_url  # noqa: E402

_RUTA = "/api/v1/health/ready"

#: Un SHA más corto que esto no identifica un commit con seguridad.
_LONGITUD_MINIMA = 7

Lectura = tuple[int, Any]

#: El proceso responde con la versión que publica ``commit`` pero no lo sabe:
#: le falta ``RENDER_GIT_COMMIT``. Reintentar no lo arregla, así que corta la
#: espera al primer intento. Una instancia anterior a este gate no manda el
#: campo, de modo que ``unknown`` solo puede venir de código que ya lo publica.
MOTIVO_SIN_COMMIT = "commit `unknown`: el proceso no ve RENDER_GIT_COMMIT"


def mismo_commit(servido: str, esperado: str) -> bool:
    """Si ``servido`` y ``esperado`` nombran el mismo commit.

    Acepta que uno sea un prefijo del otro (un SHA corto contra el completo),
    siempre que el tramo común tenga al menos ``_LONGITUD_MINIMA`` caracteres.
    """
    a, b = servido.strip().lower(), esperado.strip().lower()
    n = min(len(a), len(b))
    return n >= _LONGITUD_MINIMA and a[:n] == b[:n]


def evaluar(estado: int, payload: Any, esperado: str) -> str | None:
    """``None`` si la respuesta es la de la versión nueva; si no, por qué no."""
    if estado != 200:
        return f"HTTP {estado}"
    if not isinstance(payload, dict) or "commit" not in payload:
        return "sin campo `commit`: responde una versión anterior a este gate"
    servido = str(payload["commit"])
    if servido == "unknown":
        return MOTIVO_SIN_COMMIT
    if not mismo_commit(servido, esperado):
        return f"sirve {servido[:12]}, no {esperado[:12]}"
    return None


def leer(base: str) -> Lectura:
    """GET a ``/health/ready``. Un 503 con cuerpo también se lee."""
    url = _resolver_url(base, _RUTA)
    req = urllib.request.Request(url)  # noqa: S310 — esquema y host validados arriba
    try:
        # Destino fijado por `_resolver_url` contra SMOKE_BASE_URL, como en
        # `smoke_prod._fetch`; el `nosemgrep` va en la línea del match.
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310  # nosemgrep
            cuerpo = resp.read()
            return resp.status, json.loads(cuerpo) if cuerpo else None
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"null")
        except ValueError:
            return exc.code, None


def esperar(
    base: str,
    esperado: str,
    *,
    intentos: int,
    pausa: float,
    leer_fn: Callable[[str], Lectura] | None = None,
    dormir: Callable[[float], None] = time.sleep,
) -> tuple[Any, str | None]:
    """Sondea hasta que responde ``esperado``.

    Devuelve ``(payload, None)`` en cuanto lo ve, o ``(None, motivo)`` con el
    motivo del último intento si se agotan los ``intentos`` o en cuanto la
    respuesta es ``MOTIVO_SIN_COMMIT``. ``leer_fn`` se resuelve al llamar, no al
    definir, para que sustituir ``leer`` surta efecto.
    """
    leer_fn = leer_fn or leer
    motivo: str | None = "sin intentos"
    for intento in range(1, intentos + 1):
        try:
            estado, payload = leer_fn(base)
        except Exception as exc:  # red, timeout, JSON inválido
            estado, payload = 0, None
            motivo = f"{type(exc).__name__}: {exc}"
        else:
            motivo = evaluar(estado, payload, esperado)
        if motivo is None:
            print(f"La API sirve {esperado[:12]} tras {intento} intento(s).")
            return payload, None
        print(f"Intento {intento}/{intentos}: {motivo}.")
        if motivo == MOTIVO_SIN_COMMIT:
            return None, motivo
        if intento < intentos:
            dormir(pausa)
    return None, motivo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commit", required=True, help="SHA que tiene que servir la API")
    parser.add_argument("--salida", type=Path, help="Fichero donde dejar el payload verificado")
    parser.add_argument("--intentos", type=int, default=60)
    parser.add_argument("--pausa", type=float, default=15.0, help="Segundos entre intentos")
    args = parser.parse_args(argv)

    base = os.environ.get("SMOKE_BASE_URL", "")
    if not base:
        print("::error title=Falta SMOKE_BASE_URL::No hay URL que sondear.", file=sys.stderr)
        return 2
    if len(args.commit.strip()) < _LONGITUD_MINIMA:
        print(f"::error title=Commit inválido::--commit {args.commit!r} es demasiado corto.")
        return 2
    # Una base mal formada no se arregla reintentando: se rechaza antes del bucle.
    try:
        _resolver_url(base, _RUTA)
    except ValueError as exc:
        print(f"::error title=SMOKE_BASE_URL inválida::{exc}")
        return 2

    payload, motivo = esperar(base, args.commit, intentos=args.intentos, pausa=args.pausa)
    if motivo == MOTIVO_SIN_COMMIT:
        print(
            "::error title=La API no dice qué commit sirve::/health/ready responde "
            "`commit: unknown`, así que no se puede saber si es la versión desplegada. "
            "Comprobá que el servicio recibe RENDER_GIT_COMMIT (o definí GIT_SHA). Para "
            "un rollback urgente, relanzá con skip_smoke."
        )
        return 1
    if motivo is not None:
        minutos = round(args.intentos * args.pausa / 60)
        print(
            "::error title=La versión nueva no llegó a responder::"
            f"{minutos} min sin que /health/ready sirviera {args.commit[:12]}. "
            f"Último intento: {motivo}. Mirá Render → Events: el deploy puede haber "
            "fallado (Render mantiene la instancia anterior) o seguir construyendo."
        )
        return 1
    if args.salida is not None:
        args.salida.write_text(json.dumps(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
