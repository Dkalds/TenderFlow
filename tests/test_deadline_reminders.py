"""Tests para services/deadline_reminders.py.

El módulo no tenía ningún test que lo mencionara (auditoría 2026-08-07) pese a
ejecutar SQL propio y correr desde el job de alertas del scheduler. Cubre:

- Las tres ventanas (30/7/1 días) y su tipo de notificación.
- ``fecha_fin`` genera ``renovacion_*`` y ``fecha_limite`` genera ``deadline_*``.
- Idempotencia: re-ejecutar no duplica (ON CONFLICT DO NOTHING).
- Las licitaciones ya vencidas no generan aviso.
- ``check_all_users_deadlines`` recorre a todos los usuarios con favoritos.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
def seeded(tmp_db):
    """Una licitación y un favorito de ``alice``; la fecha la pone cada test."""
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
        WatchlistRepository().add_item(user_key=user_key, user_id=None, id_externo=id_externo)

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
