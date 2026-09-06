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

from pathlib import Path

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
        # Asignación de una oportunidad. Migra en la ola de S3, que es quien
        # posee `services/pursuits.py`.
        "services/pursuits.py",
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

_SENALES_IN_APP = ("insert_user_notification", "INSERT INTO user_notifications")
_SENALES_DIGEST = ("store_pending_digest", "INSERT INTO pending_digests")

_AREAS = ("api", "db", "services", "scheduler", "scraper", "shared", "llm", "scripts")


def _modulos() -> list[Path]:
    ficheros: list[Path] = []
    for area in _AREAS:
        ficheros.extend(sorted((_RAIZ / area).rglob("*.py")))
    return [f for f in ficheros if "__pycache__" not in f.parts]


def _relativo(path: Path) -> str:
    return path.relative_to(_RAIZ).as_posix()


def _escribe_salida_directa(path: Path) -> bool:
    """¿Este módulo escribe una alerta in-app o un digest?

    Se mira el texto y no el AST porque las dos señales son de naturaleza
    distinta —una llamada a la puerta y un literal SQL— y un escáner de AST
    tendría que entender las dos formas para no perder ninguna. El coste de
    mirar texto es un falso positivo si alguien nombra así una variable; el de
    perder una escritura es que el ratchet no ratchetee.
    """
    fuente = path.read_text(encoding="utf-8", errors="ignore")
    # Fuera de docstrings y comentarios no se puede distinguir sin AST, así que
    # se descarta lo obvio: una mención en prosa lleva comillas invertidas.
    return any(
        senal in fuente and f"`{senal}`" not in fuente
        for senal in (*_SENALES_IN_APP, *_SENALES_DIGEST)
    )


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
