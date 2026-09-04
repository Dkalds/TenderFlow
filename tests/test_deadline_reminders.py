"""Tests para services/deadline_reminders.py.

El módulo no tenía ningún test que lo mencionara (auditoría 2026-08-07) pese a
ejecutar SQL propio y correr desde el job de alertas del scheduler. Cubre:

- Las tres ventanas (30/7/1 días) y su tipo de notificación.
- ``fecha_fin`` genera ``renovacion_*`` y ``fecha_limite`` genera ``deadline_*``.
- Idempotencia: re-ejecutar no duplica (ON CONFLICT DO NOTHING).
- Las licitaciones ya vencidas no generan aviso.
- ``check_all_users_deadlines`` recorre a todos los usuarios con favoritos.
- El aviso hereda la ``organization_id`` del favorito (S4.3): sin ella la fila
  existe pero la campana, que lee con ámbito, no la devuelve nunca.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest


def _iso_in(days: float) -> str:
    """Fecha a ``days`` del ahora. Acepta fracciones a propósito.

    El módulo calcula ``(dt - now).days``, que trunca hacia abajo: un offset de
    exactamente 0 días se vuelve negativo en los microsegundos que pasan entre
    construir la fecha y evaluarla, y la licitación se descarta por vencida. Con
    medio día el resultado es 0 de forma estable.
    """
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


@pytest.fixture()
def organizacion(tmp_db) -> int:
    """Organización real a la que pertenecen los favoritos sembrados.

    Desde S4.3 ``WatchlistRepository.add_item`` exige ``organization_id`` y ya
    no tiene rama ``None``: la tuvo, y quien la omitía escribía una fila con
    organización nula, invisible para siempre a la consulta con ámbito. La
    organización necesita un dueño real porque ``organizations`` referencia
    ``users``.
    """
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    owner = create_user(
        email="plazos-owner@example.test",
        password_hash="test-hash",  # pragma: allowlist secret
    )
    return int(OrganizationRepository().create_organization("Equipo de plazos", owner)["id"])


@pytest.fixture()
def seeded(tmp_db, organizacion):
    """Una licitación y un favorito de ``alice``; la fecha la pone cada test.

    ``alice`` y ``bob`` son dos claves de usuario de la MISMA organización, que
    es el caso real de dos personas de un equipo: cada una recibe sus propios
    avisos y los dos llevan el ámbito del equipo.
    """
    db_mod, _ = tmp_db

    def _seed(id_externo: str, user_key: str = "alice", **fechas: str | None) -> None:
        from db.repositories.watchlist import WatchlistRepository

        with db_mod.connect() as c:
            # `fecha_extraccion` es NOT NULL en `licitaciones`: omitirla aborta
            # el INSERT entero.
            c.execute(
                "INSERT INTO licitaciones "
                "(id_externo, titulo, fecha_limite, fecha_fin, fecha_extraccion) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    id_externo,
                    f"Licitación {id_externo}",
                    fechas.get("fecha_limite"),
                    fechas.get("fecha_fin"),
                    datetime.now(UTC).isoformat(),
                ),
            )
        WatchlistRepository().add_item(
            user_key=user_key,
            user_id=None,
            id_externo=id_externo,
            organization_id=organizacion,
        )

    return db_mod, _seed


def _notifications(db_mod, user_key: str = "alice") -> list[tuple[str, str]]:
    with db_mod.connect_read() as c:
        rows = c.execute(
            "SELECT type, licitacion_id FROM user_notifications WHERE user_key = %s ORDER BY type",
            (user_key,),
        ).fetchall()
    return [(str(r[0]), str(r[1])) for r in rows]


@pytest.mark.parametrize(
    ("days_left", "expected"),
    [(0.5, "deadline_1"), (5, "deadline_7"), (20, "deadline_30")],
)
def test_deadline_window_picks_the_tightest_type(seeded, days_left, expected):
    """Cada plazo cae en su ventana más ajustada."""
    from services.deadline_reminders import check_deadlines_and_notify

    db_mod, seed = seeded
    seed("EXP-1", fecha_limite=_iso_in(days_left))

    assert check_deadlines_and_notify("alice") >= 1
    tipos = {t for t, _ in _notifications(db_mod)}
    assert expected in tipos


def test_fecha_fin_genera_renovacion_no_deadline(seeded):
    """``fecha_fin`` es fin de contrato: su aviso es de renovación."""
    from services.deadline_reminders import check_deadlines_and_notify

    db_mod, seed = seeded
    seed("EXP-2", fecha_fin=_iso_in(5))

    check_deadlines_and_notify("alice")
    tipos = {t for t, _ in _notifications(db_mod)}
    assert "renovacion_7" in tipos
    assert not any(t.startswith("deadline_") for t in tipos)


def test_es_idempotente_entre_ejecuciones(seeded):
    """Re-ejecutar el job no duplica avisos (UNIQUE + ON CONFLICT DO NOTHING).

    Es la propiedad que hace seguro correrlo cada día desde el scheduler.
    """
    from services.deadline_reminders import check_deadlines_and_notify

    db_mod, seed = seeded
    seed("EXP-3", fecha_limite=_iso_in(5))

    primera = check_deadlines_and_notify("alice")
    tras_primera = _notifications(db_mod)
    segunda = check_deadlines_and_notify("alice")

    assert primera >= 1
    assert segunda == 0
    assert _notifications(db_mod) == tras_primera


def test_licitacion_vencida_no_genera_aviso(seeded):
    """Un plazo ya pasado no avisa: no hay nada que preparar."""
    from services.deadline_reminders import check_deadlines_and_notify

    db_mod, seed = seeded
    seed("EXP-4", fecha_limite=_iso_in(-3))

    assert check_deadlines_and_notify("alice") == 0
    assert _notifications(db_mod) == []


def test_fecha_ilegible_no_rompe_el_job(seeded):
    """Una fecha con forma ISO pero inexistente se salta sin abortar el resto.

    No vale cualquier basura: ``ck_licitaciones_fecha_limite_iso`` (v59) exige
    que el valor empiece por ``AAAA-MM-DD``, así que "no-es-una-fecha" ni entra
    en la tabla. Lo que la constraint NO comprueba es que la fecha exista —
    valida la forma con una regex—, y ahí es donde vive el guard del módulo:
    ``2026-13-45`` pasa el CHECK y revienta ``datetime.fromisoformat``. La
    constraint además se creó ``NOT VALID``, así que las filas anteriores a v59
    pueden contener cualquier cosa.
    """
    from services.deadline_reminders import check_deadlines_and_notify

    db_mod, seed = seeded
    seed("EXP-5", fecha_limite="2026-13-45")
    seed("EXP-6", fecha_limite=_iso_in(5))

    assert check_deadlines_and_notify("alice") >= 1
    assert {lic for _, lic in _notifications(db_mod)} == {"EXP-6"}


def test_check_all_users_recorre_cada_usuario_con_favoritos(seeded):
    """El job del scheduler cubre a todos los usuarios, no solo al primero."""
    from services.deadline_reminders import check_all_users_deadlines

    db_mod, seed = seeded
    seed("EXP-7", user_key="alice", fecha_limite=_iso_in(5))
    seed("EXP-8", user_key="bob", fecha_limite=_iso_in(5))

    total = check_all_users_deadlines()

    assert total >= 2
    assert _notifications(db_mod, "alice")
    assert _notifications(db_mod, "bob")


# ── Ámbito de organización del aviso (S4.3) ──────────────────────────────────


def _organizaciones_de_avisos(db_mod, user_key: str = "alice") -> set[int | None]:
    with db_mod.connect_read() as c:
        rows = c.execute(
            "SELECT organization_id FROM user_notifications WHERE user_key = %s",
            (user_key,),
        ).fetchall()
    return {r[0] for r in rows}


def test_el_aviso_hereda_la_organizacion_del_favorito(seeded, organizacion):
    """Un aviso sin organización existe en la tabla y no lo ve nadie.

    ``services/notifications.get_user_alerts`` y sus vecinas filtran por
    ``organization_id``, y la ruta se lo pasa siempre resuelto (``api/tenancy``
    nunca manda ``None``). Hasta 2026-09 este job escribía su propio ``INSERT``
    sin la columna: la fila quedaba fuera del alcance de la campana para
    siempre. Es la misma clase de bug que S4.3 cerró en los repositorios de
    tenencia, y este era el productor de alertas que se había quedado fuera.
    """
    from services.deadline_reminders import check_deadlines_and_notify
    from services.notifications import get_user_alerts

    db_mod, seed = seeded
    seed("EXP-ORG", fecha_limite=_iso_in(5))

    assert check_deadlines_and_notify("alice") >= 1

    assert _organizaciones_de_avisos(db_mod) == {organizacion}
    # Y lo que importa de verdad: la lectura CON ámbito —la que hace la
    # campana— los devuelve. Un plazo a 5 días cae en dos ventanas.
    avisos = get_user_alerts("alice", organization_id=organizacion)
    assert {a["licitacion_id"] for a in avisos} == {"EXP-ORG"}
    assert {a["type"] for a in avisos} == {"deadline_30", "deadline_7"}


def test_un_favorito_legacy_sin_organizacion_no_genera_un_aviso_invisible(seeded):
    """Un favorito anterior al ámbito no produce una alerta huérfana.

    Esas filas existen: se escribieron cuando ``organization_id`` era opcional
    y por eso hay un backfill (``scripts/asignar_organizacion_huerfanos.py``).
    Avisar sobre ellas escribiría una notificación que nadie ve y que además
    quema la clave ``UNIQUE(user_key, licitacion_id, type)``; saltarlas es
    reversible: en cuanto el backfill adjudica el favorito, la siguiente pasada
    del job —corre en cada ciclo de la pipeline— sí avisa.
    """
    from services.deadline_reminders import check_deadlines_and_notify

    db_mod, _seed = seeded
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fecha_limite, fecha_extraccion) VALUES (%s, %s, %s, %s)",
            ("EXP-LEGACY", "Favorito legacy", _iso_in(5), datetime.now(UTC).isoformat()),
        )
        # A propósito por SQL crudo: el repositorio ya no permite construir
        # esta fila, y es justo la que hay en producción desde antes de S4.3.
        c.execute(
            "INSERT INTO watchlist_items (user_key, user_id, id_externo, organization_id) "
            "VALUES (%s, %s, %s, NULL)",
            ("alice", None, "EXP-LEGACY"),
        )

    assert check_deadlines_and_notify("alice") == 0
    assert _notifications(db_mod) == []


# ── La misma regla, sin base de datos ────────────────────────────────────────
#
# Los dos tests de arriba necesitan Postgres. Estos comprueban la misma regla
# —de dónde sale la ``organization_id`` del aviso— sustituyendo la lectura por
# filas ya cargadas y la escritura por un registro en memoria, para que la
# propiedad quede cubierta también donde no hay motor (mismo patrón que
# ``tests/test_unit_deadline_reminders_pursuits.py``).


class _CursorFalso:
    def __init__(self, filas: list[tuple[Any, ...]], columnas: list[str] | None = None) -> None:
        self._filas = filas
        self.description = None if columnas is None else [(c,) for c in columnas]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._filas


class _ConexionFalsa:
    """Responde a las dos lecturas del módulo, distinguidas por su tabla."""

    def __init__(
        self, favoritos: list[tuple[Any, ...]], licitaciones: list[tuple[Any, ...]]
    ) -> None:
        self._favoritos = favoritos
        self._licitaciones = licitaciones

    def execute(self, sql: str, params: Any = None) -> _CursorFalso:
        if "watchlist_items" in sql:
            return _CursorFalso(self._favoritos)
        return _CursorFalso(
            self._licitaciones,
            ["id_externo", "titulo", "fecha_limite", "fecha_fin"],
        )

    def __enter__(self) -> _ConexionFalsa:
        return self

    def __exit__(self, *_: Any) -> bool:
        return False


def test_unit_el_aviso_lleva_la_organizacion_del_favorito_y_salta_al_huerfano():
    """La ``organization_id`` sale del favorito; el favorito sin ámbito no escribe.

    La conexión falsa devuelve a propósito la licitación del favorito huérfano
    —la consulta real ya no la pediría— para ejercitar también el guard que
    impide que un ``None`` llegue a la escritura por cualquier otro camino.
    """
    import services.deadline_reminders as mod

    escritas: list[dict[str, Any]] = []

    def _insert(**kwargs: Any) -> bool:
        escritas.append(kwargs)
        return True

    conexion = _ConexionFalsa(
        favoritos=[("EXP-A", 42), ("EXP-HUERFANO", None)],
        licitaciones=[
            ("EXP-A", "Con ámbito", _iso_in(5), None),
            ("EXP-HUERFANO", "Legacy sin ámbito", _iso_in(5), None),
        ],
    )

    with (
        patch.object(mod, "connect_read", return_value=conexion),
        patch.object(mod, "insert_user_notification", side_effect=_insert),
    ):
        total = mod.check_deadlines_and_notify("alice")

    # Un plazo a 5 días cae en las ventanas de 30 y 7, y solo para EXP-A.
    assert total == len(escritas) == 2
    assert {e["licitacion_id"] for e in escritas} == {"EXP-A"}
    assert {e["organization_id"] for e in escritas} == {42}
    assert sorted(e["type_"] for e in escritas) == ["deadline_30", "deadline_7"]


def test_unit_todos_los_favoritos_huerfanos_equivalen_a_no_tener_favoritos():
    import services.deadline_reminders as mod

    conexion = _ConexionFalsa(favoritos=[("EXP-X", None)], licitaciones=[])

    with (
        patch.object(mod, "connect_read", return_value=conexion),
        patch.object(mod, "insert_user_notification") as insert,
    ):
        assert mod.check_deadlines_and_notify("alice") == 0

    insert.assert_not_called()
