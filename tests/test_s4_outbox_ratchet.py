"""Ratchet: quién escribe alertas y digests fuera del despachador (S4.1).

El outbox solo es el backbone si las salidas salen **de él**. Mientras un
productor siga escribiendo directamente en ``user_notifications`` o en
``pending_digests``, ese aviso no tiene evento detrás: no se puede reproducir,
no se puede enrutar a un webhook, y «¿por qué me llegó esto?» no tiene
respuesta.

Migrarlos todos de golpe habría tocado cinco módulos de cinco áreas en el mismo
PR. En vez de eso, este test **congela la lista de hoy y solo permite que
encoja** — mismo mecanismo que el ratchet TID251 (AGENTS.md §3.10), el de
``check_openapi_contract.py`` y el de ``test_organization_sql_isolation.py``.

Reglas:

- Añadir un módulo a :data:`PRODUCTORES_DIRECTOS` está **prohibido**: un
  productor nuevo escribe su evento y deja que el despachador reparta.
- Quitar uno (porque migró al outbox) exige borrar su línea aquí, y el test lo
  obliga: si un módulo de la lista deja de escribir directamente, falla.

No se cuentan como productores ni las **puertas** (``db/notifications.py`` y
``db/repositories/watchlist.py``, que son el SQL de esas dos tablas y tienen
que existir) ni el propio despachador, que es a donde se quiere llegar.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[1]

#: Módulos que HOY escriben una alerta in-app o un digest sin pasar por el
#: outbox. La lista solo puede encoger.
PRODUCTORES_DIRECTOS: frozenset[str] = frozenset(
    {
        # Alertas de reglas de watchlist: escribe el INSERT a mano y encola el
        # digest. Es el productor más antiguo y el que más filas escribe.
        "scheduler/watchlist_rules_alerts.py",
        # Watchlist de empresas (v36): encola digests de sus coincidencias.
        "scheduler/watchlist_alerts.py",
        # Recordatorios de vencimiento y de renovación.
        "services/deadline_reminders.py",
        # Adjudicación detectada sobre una oportunidad abierta.
        "services/pursuit_awards.py",
        # `services/pursuits.py` (asignación) salió el 2026-10-25: el
        # repositorio escribe `pursuit.assigned` en la transacción de la
        # asignación y lo reparte el despachador.
    }
)

#: El SQL de las dos tablas. No son productores: son la puerta por la que pasa
#: cualquier escritura, incluida la del despachador.
_PUERTAS: frozenset[str] = frozenset(
    {
        "db/notifications.py",
        "db/repositories/watchlist.py",
        "services/watchlist.py",
    }
)

#: A donde se quiere llegar: el único módulo que puede escribir estas salidas
#: sin ser una puerta.
_DESPACHADOR = "scheduler/jobs/event_dispatch.py"

#: Las dos puertas de escritura. Llamarlas, o importarlas con otro nombre, es
#: escribir la salida.
_FUNCIONES_PUERTA = frozenset({"insert_user_notification", "store_pending_digest"})

#: El ``INSERT`` a mano en cualquiera de las dos tablas, en cualquier caja y
#: con el esquema delante o no.
_SQL_DIRECTO = re.compile(
    r"insert\s+into\s+(?:public\.)?(?:user_notifications|pending_digests)\b", re.IGNORECASE
)

_AREAS = (
    "api",
    "config",
    "db",
    "llm",
    "mcp_server",
    "observability",
    "scheduler",
    "scraper",
    "scripts",
    "services",
    "shared",
)

#: Las migraciones no producen alertas y son append-only (AGENTS.md §3.3): una
#: que hiciera un backfill no podría salir nunca de la lista.
_EXCLUIDOS = ("db/alembic/",)


def _modulos() -> list[Path]:
    ficheros: list[Path] = []
    for area in _AREAS:
        ficheros.extend(sorted((_RAIZ / area).rglob("*.py")))
    return [
        f
        for f in ficheros
        if "__pycache__" not in f.parts and not _relativo(f).startswith(_EXCLUIDOS)
    ]


def _relativo(path: Path) -> str:
    return path.relative_to(_RAIZ).as_posix()


def _nombre_llamado(llamada: ast.Call) -> str | None:
    funcion = llamada.func
    if isinstance(funcion, ast.Name):
        return funcion.id
    if isinstance(funcion, ast.Attribute):
        return funcion.attr
    return None


def _escribe_salida_directa(path: Path) -> bool:
    """¿Este módulo escribe una alerta in-app o un digest?

    Se lee el AST, no el texto: una mención en un docstring o un comentario no
    es una escritura, y una llamada no deja de serlo porque el docstring del
    mismo módulo nombre la función entre comillas invertidas (el filtro de
    texto anterior la perdía). Cuenta como escritura:

    - llamar a una de las puertas (``insert_user_notification``,
      ``store_pending_digest``), sea como nombre o como atributo;
    - importar una puerta con ``from … import`` —también con alias, que es
      como se escaparía una llamada—;
    - un literal de cadena, fuera de docstrings, con ``INSERT INTO`` sobre
      una de las dos tablas.
    """
    arbol = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = {
        id(nodo.value)
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Expr)
        and isinstance(nodo.value, ast.Constant)
        and isinstance(nodo.value.value, str)
    }
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call) and _nombre_llamado(nodo) in _FUNCIONES_PUERTA:
            return True
        if isinstance(nodo, ast.ImportFrom) and any(
            alias.name in _FUNCIONES_PUERTA for alias in nodo.names
        ):
            return True
        if (
            isinstance(nodo, ast.Constant)
            and isinstance(nodo.value, str)
            and id(nodo) not in docstrings
            and _SQL_DIRECTO.search(nodo.value)
        ):
            return True
    return False


def _productores_actuales() -> set[str]:
    encontrados: set[str] = set()
    for path in _modulos():
        rel = _relativo(path)
        if rel in _PUERTAS or rel == _DESPACHADOR:
            continue
        if _escribe_salida_directa(path):
            encontrados.add(rel)
    return encontrados


def test_ningun_productor_nuevo_escribe_alertas_fuera_del_outbox():
    """Un módulo nuevo en la lista es una regresión, no una excepción."""
    nuevos = _productores_actuales() - PRODUCTORES_DIRECTOS
    assert not nuevos, (
        "Estos módulos escriben en user_notifications/pending_digests sin pasar "
        f"por el outbox: {sorted(nuevos)}. Escribí el evento con "
        "db.events.append_domain_event y dejá que scheduler/jobs/event_dispatch.py "
        "reparta; el ratchet de tests/test_s4_outbox_ratchet.py solo encoge."
    )


def test_el_ratchet_no_conserva_entradas_ya_migradas():
    """Si un módulo migró al outbox, su línea sale de la lista en el mismo PR."""
    obsoletos = PRODUCTORES_DIRECTOS - _productores_actuales()
    assert not obsoletos, (
        f"Estos módulos ya no escriben directamente: {sorted(obsoletos)}. "
        "Quitalos de PRODUCTORES_DIRECTOS — un ratchet que no encoge no mide nada."
    )


def test_el_despachador_es_el_camino_al_que_se_quiere_llegar():
    """Guardia del propio ratchet: si el despachador dejara de escribir estas
    salidas, la lista de arriba estaría midiendo otra cosa."""
    assert _escribe_salida_directa(_RAIZ / _DESPACHADOR)


# ── Guardias del detector ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("lineas", "escribe"),
    [
        pytest.param(
            (
                '"""Pasa por `insert_user_notification`."""',
                "from db.notifications import insert_user_notification",
                "insert_user_notification(user_id=1)",
            ),
            True,
            id="llamada-con-mencion-en-docstring",
        ),
        pytest.param(
            ('"""Solo la nombra: `insert_user_notification`."""',),
            False,
            id="solo-docstring",
        ),
        pytest.param(
            ("# INSERT INTO user_notifications en un comentario", "X = 1"),
            False,
            id="solo-comentario",
        ),
        pytest.param(
            ("from db.notifications import insert_user_notification as avisar",),
            True,
            id="import-con-alias",
        ),
        pytest.param(
            ("def f(repo):", "    repo.store_pending_digest(user_key='k')"),
            True,
            id="llamada-como-atributo",
        ),
        pytest.param(
            ("SQL = 'insert into public.pending_digests (a) values (1)'",),
            True,
            id="sql-en-minusculas-con-esquema",
        ),
        pytest.param(
            ("SQL = 'SELECT 1 FROM user_notifications'",),
            False,
            id="lectura",
        ),
    ],
)
def test_el_detector_ve_escrituras_y_no_menciones(tmp_path, lineas, escribe):
    modulo = tmp_path / "modulo.py"
    modulo.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    assert _escribe_salida_directa(modulo) is escribe
