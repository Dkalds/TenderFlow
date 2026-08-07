"""Test de arquitectura (SEPARADO de test_user_key_sql_isolation.py): guarda
contra el riesgo "user_key se huerfana si cambia el email".

``shared/identity.py::user_key_from_email`` deriva ``user_key`` así::

    sha256((email or f"user:{user_id}").strip().lower())[:16]

``user_key`` es una clave DERIVADA del email, usada como clave de
particionado (manual) en las 10 tablas user-scoped auditadas en
``test_user_key_sql_isolation.py``. Si algún día se añade un flujo de
"cambiar mi email" que haga ``UPDATE users SET email = %s`` con un valor
NUEVO (no NULL) sin recalcular y migrar ``user_key`` en todas esas tablas, el
usuario queda huérfano: sus datos históricos (watchlist, notificaciones,
perfil de scoring...) seguirían indexados bajo el ``user_key`` VIEJO,
invisibles desde el nuevo email -- una pérdida de datos silenciosa, no un
crash.

Hoy la ÚNICA sentencia en ``db/users.py`` que toca la columna ``email`` de
``users`` vía UPDATE es la de anonimización GDPR (``anonymize_user``, Art.17
erasure), que la pone a NULL -- nunca a un valor nuevo:

    UPDATE users SET email = NULL, display_name = NULL, oauth_sub = NULL,
        deactivated_at = COALESCE(deactivated_at, %s) WHERE id = %s

Este test falla ruidosamente en dos escenarios:
  1. Aparece OTRA función en ``db/users.py`` que también hace
     ``UPDATE users SET ... email = ...`` (un flujo de cambio de email real).
  2. La función de anonimización deja de poner ``email`` a ``NULL`` (p. ej.
     alguien la reutiliza para "actualizar" el email a un valor nuevo).

En cualquiera de los dos casos, el fix correcto NO es tocar este test: es
recalcular ``user_key_from_email`` con el email nuevo y migrar/re-escribir
todas las filas user-scoped bajo la nueva clave ANTES de tocar `email`, y
solo entonces actualizar ``_ALLOWED_EMAIL_UPDATERS``/las aserciones de este
archivo conscientemente.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_USERS_PY = _REPO_ROOT / "db" / "users.py"

# Captura solo la cláusula SET (hasta WHERE o fin de cadena) -- así
# `UPDATE users SET is_admin = ? WHERE email = ?` (filtra POR email, no lo
# escribe) no cuenta como "escribe email". `re.DOTALL` porque el pool une
# varios literales de cadena con "\n" y una sentencia puede quedar partida
# en varias constantes adyacentes.
_UPDATE_USERS_SET = re.compile(
    r"UPDATE\s+users\s+SET\s+(.*?)(?:\bWHERE\b|\Z)", re.IGNORECASE | re.DOTALL
)
_EMAIL_ASSIGNED = re.compile(r"\bemail\s*=", re.IGNORECASE)
_EMAIL_SET_TO_NULL = re.compile(r"\bemail\s*=\s*NULL\b", re.IGNORECASE)

# Única función permitida para tocar `users.email` vía UPDATE: el camino de
# anonimización GDPR. Ratchet de una sola entrada -- si aparece OTRA función,
# o esta se renombra, el test falla y obliga a revisar conscientemente si la
# migración de user_key está cubierta antes de aceptar el cambio.
_ALLOWED_EMAIL_UPDATERS: frozenset[str] = frozenset({"anonymize_user"})


def _own_string_constants(node: ast.AST) -> list[str]:
    """Literales de cadena del cuerpo de ``node``, sin bajar a funciones
    anidadas (no aplica hoy en db/users.py, pero mantiene la heurística
    consistente con test_user_key_sql_isolation.py)."""
    out: list[str] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            out.append(child.value)
        out.extend(_own_string_constants(child))
    return out


def _iter_functions(node: ast.AST, prefix: str = ""):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from _iter_functions(child, prefix=f"{prefix}{child.name}.")
        elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            qualname = f"{prefix}{child.name}"
            yield qualname, child
            yield from _iter_functions(child, prefix=f"{qualname}.")


def _functions_that_set_email() -> dict[str, str]:
    """``qualname -> pool de strings`` de cada función de ``db/users.py``
    cuyo SQL hace ``UPDATE users SET ... email = ...``."""
    source = _USERS_PY.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_USERS_PY))
    result: dict[str, str] = {}
    for qualname, func_node in _iter_functions(tree):
        pool = "\n".join(_own_string_constants(func_node))
        set_clauses = _UPDATE_USERS_SET.findall(pool)
        if any(_EMAIL_ASSIGNED.search(clause) for clause in set_clauses):
            result[qualname] = pool
    return result


def test_only_gdpr_anonymization_updates_users_email() -> None:
    """``db/users.py`` no debe tener ningún ``UPDATE users SET email`` fuera
    del camino de anonimización GDPR (que la pone a NULL, nunca a un valor
    nuevo)."""
    setters = _functions_that_set_email()

    nuevas = sorted(set(setters) - _ALLOWED_EMAIL_UPDATERS)
    assert not nuevas, (
        "Nueva(s) función(es) en db/users.py cambian `email` vía UPDATE "
        f"fuera del camino GDPR: {nuevas}. Si esto es un flujo real de "
        "cambio de email, hay que migrar/recalcular `user_key` "
        "(shared/identity.py::user_key_from_email) en TODAS las tablas "
        "user-scoped ANTES de añadir esto a _ALLOWED_EMAIL_UPDATERS -- ver "
        "docstring de este módulo."
    )

    obsoletas = sorted(_ALLOWED_EMAIL_UPDATERS - set(setters))
    assert not obsoletas, (
        f"{obsoletas} ya no actualiza `email` en db/users.py -- bórralo de "
        "_ALLOWED_EMAIL_UPDATERS (el ratchet solo puede encoger)."
    )

    for qualname in _ALLOWED_EMAIL_UPDATERS & set(setters):
        pool = setters[qualname]
        assert _EMAIL_SET_TO_NULL.search(pool), (
            f"`{qualname}` cambia `email` pero no lo pone a NULL -- "
            "¿es un cambio de email real (no anonimización)? Si es así, "
            "falta migrar `user_key` (ver docstring de este módulo) antes "
            "de tocar esto."
        )
