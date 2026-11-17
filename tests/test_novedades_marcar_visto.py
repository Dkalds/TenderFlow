"""F5.4 — «marcar todo como visto» mueve la última visita.

La marca de la banda «desde tu última visita» es ``MAX(read_at)`` de
``notification_reads`` y solo avanzaba leyendo notificaciones concretas en la
campana: el Resumen no tenía cómo decir «ya lo he visto todo». Ahora
``POST /analytics/resumen/desde-mi-ultima-visita/visto`` escribe una fila
reservada (una por usuario, que se actualiza) y la siguiente lectura empieza
ahí.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

import api.routes.analytics as rutas
from db.notifications import MARCA_VISITA

# ── La ruta, sin base de datos ───────────────────────────────────────────────


def test_la_ruta_marca_con_la_identidad_del_principal() -> None:
    llamadas: list[tuple[Any, ...]] = []

    def _marcar(*, user_id: int) -> str:
        llamadas.append((user_id,))
        return "2026-09-19T10:00:00+00:00"

    with patch.object(rutas, "marcar_visita", _marcar):
        respuesta = asyncio.run(
            rutas.resumen_marcar_visto(ctx={"user_key": "clave-del-principal", "user_id": "7"})
        )

    assert llamadas == [(7,)]
    assert respuesta.visto_en == "2026-09-19T10:00:00+00:00"


def test_la_marca_reservada_no_parece_un_expediente() -> None:
    """Un ``id_externo`` nunca empieza por doble guion bajo: la fila de la
    marca no puede aparecer como «leída» para ningún expediente."""
    assert MARCA_VISITA.startswith("__")


# ── Contra Postgres ──────────────────────────────────────────────────────────


@pytest.fixture()
def user_id(tmp_db: Any) -> int:
    from db.users import create_user

    return create_user(
        email="visto@novedades.test",
        password_hash="test-hash",  # pragma: allowlist secret
        display_name="Visto",
    )


def test_marcar_visita_mueve_la_ultima_visita(user_id: int) -> None:
    from db.notifications import get_last_seen_ts, marcar_visita, mark_read

    mark_read("LIC-1", user_id=user_id)
    antes = get_last_seen_ts(user_id=user_id)
    marca = marcar_visita(user_id=user_id)

    assert get_last_seen_ts(user_id=user_id) == marca
    assert marca >= str(antes)


def test_marcar_dos_veces_no_crece(user_id: int) -> None:
    from db.database import connect
    from db.notifications import marcar_visita

    marcar_visita(user_id=user_id)
    segunda = marcar_visita(user_id=user_id)
    with connect() as c:
        filas = c.execute(
            "SELECT read_at FROM notification_reads WHERE user_id = %s",
            (user_id,),
        ).fetchall()
    assert [f[0] for f in filas] == [segunda]


def test_la_marca_no_cuenta_como_notificacion_leida(user_id: int) -> None:
    from db.notifications import get_unread_ids, marcar_visita

    marcar_visita(user_id=user_id)
    assert get_unread_ids(["LIC-9"], user_id=user_id) == ["LIC-9"]
