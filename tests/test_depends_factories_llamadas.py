"""Guardarraíl: una dependencia-factoría en `Depends()` tiene que ir llamada.

El bug que lo motiva
--------------------
`api/routes/dual_auth.py::require_recent_session` es una **factoría**: devuelve
la dependencia, no es la dependencia. Escrita sin paréntesis,
``Depends(require_recent_session)`` le pide a FastAPI que inyecte *el resultado
de llamar a la factoría* —o sea, la función interna— como si fuera el contexto
del usuario. El handler recibe una función, hace ``ctx.get("user_id")`` y
revienta con ``'function' object has no attribute 'get'``.

Pasó de verdad en `DELETE /me/sessions/{session_id}` (C2.1): la ruta que el
plan complementario añadió para revocar **una** sesión devolvía 500 en todas sus
llamadas. Lo encontró el fuzzing de la API en CI, no un test: los tests de esa
ruta mockean el contexto, así que nunca ejercitan la resolución real de la
dependencia, y ni mypy ni ruff modelan esta diferencia — ambas formas son
llamables y ambas tipan.

Es una clase de fallo barata de prevenir y cara de encontrar: no falla al
arrancar, no falla al importar, y el 500 solo aparece cuando alguien usa la
ruta. Por eso hay un test estructural en vez de confiar en acordarse.

Cómo se detecta una factoría
----------------------------
Por su tipo de retorno declarado: una función cuya anotación de retorno es un
``Callable[...]`` devuelve algo para llamar después. Es la misma señal que usa
quien lee el código, y no depende de mantener una lista a mano.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_API = _REPO_ROOT / "api"


def _es_anotacion_callable(nodo: ast.expr | None) -> bool:
    """``True`` si la anotación de retorno es un ``Callable[...]``."""
    if nodo is None:
        return False
    objetivo = nodo.value if isinstance(nodo, ast.Subscript) else nodo
    if isinstance(objetivo, ast.Name):
        return objetivo.id == "Callable"
    if isinstance(objetivo, ast.Attribute):
        return objetivo.attr == "Callable"
    return False


def _factorias() -> set[str]:
    """Nombres de funciones de `api/` que devuelven una dependencia."""
    nombres: set[str] = set()
    for fichero in sorted(_API.rglob("*.py")):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"), filename=str(fichero))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.FunctionDef | ast.AsyncFunctionDef) and _es_anotacion_callable(
                nodo.returns
            ):
                nombres.add(nodo.name)
    return nombres


def _depends_sin_llamar(factorias: set[str]) -> list[str]:
    """``fichero:linea Depends(nombre)`` de cada factoría pasada sin llamar."""
    hallazgos: list[str] = []
    for fichero in sorted(_API.rglob("*.py")):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"), filename=str(fichero))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call):
                continue
            fn = nodo.func
            invocado = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if invocado not in {"Depends", "Security"}:
                continue
            for arg in nodo.args:
                # `Depends(f)` con `f` a secas. `Depends(f())` es un `ast.Call`
                # y no entra aquí, que es justo lo correcto.
                if isinstance(arg, ast.Name) and arg.id in factorias:
                    ruta = fichero.relative_to(_REPO_ROOT).as_posix()
                    hallazgos.append(f"{ruta}:{nodo.lineno} {invocado}({arg.id})")
    return hallazgos


def test_la_factoria_de_sesion_reciente_esta_declarada_como_tal() -> None:
    """Sin esto, el test de abajo pasaría por no encontrar ninguna factoría."""
    assert "require_recent_session" in _factorias(), (
        "require_recent_session dejó de anotar `-> Callable[...]`; este guardarraíl "
        "se apoya en esa anotación para saber qué es una factoría"
    )


def test_ninguna_factoria_se_pasa_a_depends_sin_llamar() -> None:
    hallazgos = _depends_sin_llamar(_factorias())
    assert not hallazgos, (
        "Dependencia-factoría pasada a Depends() sin llamar. FastAPI inyectará la "
        "función interna en vez del contexto, y el handler dará 500 en cuanto "
        "alguien use la ruta. Añadí los paréntesis:\n  " + "\n  ".join(hallazgos)
    )
