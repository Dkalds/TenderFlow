"""Genera la matriz de scopes de ``docs/api-design.md`` desde ``api/scopes.py``.

La tabla de scopes del documento tenía ocho filas frente a las ~20 familias que
``required_scope_for_request`` resuelve de verdad (hecho 30 del plan
complementario 2026-09). Una tabla escrita a mano sobre una política que vive en
código se desfasa el día que alguien añade una rama al ``if``; esta es la razón
de que se genere.

La fuente **no** es el texto de ``api/scopes.py`` sino su comportamiento: se
enumeran las rutas reales de la app (``api.app``, sin lifespan, igual que
``scripts/export_openapi.py``) y se le pregunta a
``required_scope_for_request`` qué scope exige cada par método/ruta. Así la
tabla no puede describir una política que el código no aplica.

Uso::

    python scripts/gen_scopes_doc.py           # reescribe el bloque en el doc
    python scripts/gen_scopes_doc.py --check   # falla si el doc está desfasado
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# `Settings` exige `SIGNING_KEY` en `ENV=prod` (su default) y **este script
# corre en pre-commit**, donde no hay entorno cargado: sin esto, importar
# `api.app` revienta con un `ValidationError` que `check_agent_docs` reporta
# como «matriz de scopes desfasada» — un diagnóstico que manda a mirar el
# documento equivocado.
#
# `setdefault` y no asignación: si quien ejecuta ya eligió un entorno, manda el
# suyo. Aquí sólo se introspecciona metadata de rutas; no se sirve tráfico ni se
# firma nada, así que el perfil de desarrollo es el correcto.
os.environ.setdefault("ENV", "dev")
os.environ.setdefault("APP_PROFILE", "api")
_DOC = _REPO_ROOT / "docs" / "api-design.md"

# Delimitadores del bloque generado. Todo lo que hay entre ellos se reescribe;
# la prosa de alrededor es de quien edita el documento.
_BEGIN = "<!-- BEGIN scopes (generado por scripts/gen_scopes_doc.py — no editar a mano) -->"
_END = "<!-- END scopes -->"

_METHODS = ("GET", "POST", "PATCH", "PUT", "DELETE")

# Scopes que no salen de una ruta: los concede el operador, no la política de
# ``required_scope_for_request``.
_SCOPES_SIN_RUTA: dict[str, str] = {
    "*": "Acceso total explícito. Solo para claves de operación.",
}


def _iter_routes() -> list[tuple[str, str]]:
    """Devuelve los pares ``(método, path)`` de la API, ordenados."""
    from api.app import app

    pares: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods or not path.startswith("/api/v1"):
            continue
        for method in methods:
            if method in _METHODS:
                pares.add((method, path))
    return sorted(pares, key=lambda p: (p[1], p[0]))


def _familia(path: str) -> str:
    """Prefijo legible de una ruta: ``/api/v1/me/keys/rotate`` -> ``/me/keys``.

    Se corta en el primer segmento paramétrico para que ``/licitaciones/{id}``
    y ``/licitaciones/{otro}`` no cuenten como dos familias.
    """
    segmentos = path[len("/api/v1") :].strip("/").split("/")
    utiles: list[str] = []
    for seg in segmentos[:2]:
        if seg.startswith("{"):
            break
        utiles.append(seg)
    return "/" + "/".join(utiles) if utiles else "/"


def build_matrix() -> dict[str, dict[str, set[str]]]:
    """``{scope: {familia: {métodos}}}`` calculado sobre las rutas reales."""
    from api.scopes import required_scope_for_request

    matriz: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for method, path in _iter_routes():
        scope = required_scope_for_request(method, path)
        matriz[scope][_familia(path)].add(method)
    return matriz


def _render_metodos(metodos: set[str]) -> str:
    if metodos >= {"GET", "POST", "PATCH", "PUT", "DELETE"}:
        return "todos"
    return "/".join(m for m in _METHODS if m in metodos)


def render_table(matriz: dict[str, dict[str, set[str]]]) -> str:
    filas: list[str] = [
        "| Scope | Métodos | Familias de ruta |",
        "|---|---|---|",
    ]
    for scope in sorted(matriz):
        familias = matriz[scope]
        metodos: set[str] = set()
        for m in familias.values():
            metodos |= m
        rutas = ", ".join(f"`{f}`" for f in sorted(familias))
        filas.append(f"| `{scope}` | {_render_metodos(metodos)} | {rutas} |")
    for scope, nota in sorted(_SCOPES_SIN_RUTA.items()):
        filas.append(f"| `{scope}` | — | {nota} |")
    return "\n".join(filas)


def render_block() -> str:
    matriz = build_matrix()
    n_scopes = len(matriz) + len(_SCOPES_SIN_RUTA)
    cabecera = (
        f"Los scopes los resuelve `api/scopes.py::required_scope_for_request` a partir "
        f"del método y la ruta; hoy son **{n_scopes}** familias. Esta tabla se genera "
        f"con `python scripts/gen_scopes_doc.py` y CI la verifica con `--check`."
    )
    return f"{_BEGIN}\n\n{cabecera}\n\n{render_table(matriz)}\n\n{_END}"


def _reemplaza_bloque(texto: str, bloque: str) -> str:
    inicio = texto.find(_BEGIN)
    fin = texto.find(_END)
    if inicio == -1 or fin == -1:
        raise SystemExit(
            f"{_DOC.relative_to(_REPO_ROOT)}: faltan los delimitadores del bloque de scopes.\n"
            f"Añadí las líneas {_BEGIN!r} y {_END!r} donde deba ir la tabla."
        )
    return texto[:inicio] + bloque + texto[fin + len(_END) :]


def main() -> int:
    check = "--check" in sys.argv
    actual = _DOC.read_text(encoding="utf-8")
    esperado = _reemplaza_bloque(actual, render_block())

    if actual == esperado:
        print(f"OK: la matriz de scopes de {_DOC.relative_to(_REPO_ROOT)} está al día.")
        return 0
    if check:
        print(
            f"ERROR: {_DOC.relative_to(_REPO_ROOT)} tiene la matriz de scopes desfasada "
            f"respecto de api/scopes.py.\nRegenerá con: python scripts/gen_scopes_doc.py",
            file=sys.stderr,
        )
        return 1
    _DOC.write_text(esperado, encoding="utf-8", newline="\n")
    print(f"Actualizada la matriz de scopes en {_DOC.relative_to(_REPO_ROOT)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
