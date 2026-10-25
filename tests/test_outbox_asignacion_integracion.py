"""La asignación de una oportunidad sale del outbox (ADR-027) — contra Postgres.

Hasta 2026-10 ``services/pursuits.py`` escribía el aviso directamente en
``user_notifications`` después del commit. Ahora el repositorio escribe
``pursuit.assigned`` en la misma transacción que la asignación y el
despachador lo reparte. Lo que se fija aquí:

- crear o reasignar escribe **un** evento, y el reintento idempotente de la
  creación no escribe otro;
- asignarse a uno mismo no escribe evento;
- el aviso que llega a la campana tiene el mismo ``type``, título y cuerpo que
  antes, y repartir dos veces no lo duplica.
"""

from __future__ import annotations

from typing import Any

import pytest

from db.events import get_events
from db.repositories.organizations import OrganizationRepository
from services.pursuits import create_pursuit, update_pursuit
from shared.dto import PursuitCreate, PursuitUpdate


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(email=email, password_hash="test-hash", display_name=email.split("@")[0])


def _licitacion(db_mod: Any, id_externo: str) -> None:
    with db_mod.connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fecha_limite, fecha_extraccion) VALUES (%s, %s, %s, %s)",
            (id_externo, "Servicio SAP", "2026-12-01T12:00:00+00:00", "2026-07-30T10:00:00+00:00"),
        )


@pytest.fixture
def equipo(tmp_db: Any) -> dict[str, int]:
    db_mod, _ = tmp_db
    owner = _user("owner@example.test")
    member = _user("member@example.test")
    otra = _user("otra@example.test")
    repo = OrganizationRepository()
    organization_id = int(repo.create_organization("Equipo", owner)["id"])
    repo.add_membership(organization_id, member, "member")
    repo.add_membership(organization_id, otra, "member")
    _licitacion(db_mod, "LIC-OUTBOX-1")
    _licitacion(db_mod, "LIC-OUTBOX-2")
    return {"owner": owner, "member": member, "otra": otra, "org": organization_id}


def _asignaciones(pursuit_id: int) -> list[dict[str, Any]]:
    return get_events("pursuit", pursuit_id, event_type="pursuit.assigned")


def _notificaciones(db_mod: Any, user_id: int) -> list[dict[str, Any]]:
    with db_mod.connect_read() as conn:
        cur = conn.execute(
            "SELECT type, title, body, licitacion_id, organization_id "
            "FROM user_notifications WHERE user_id = %s ORDER BY id",
            (user_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, fila, strict=False)) for fila in cur.fetchall()]


@pytest.fixture
def sin_salidas_externas(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Correo y webhooks fuera: lo que se prueba es la campana."""
    from scheduler.jobs import event_dispatch

    correos: list[str] = []
    monkeypatch.setattr(event_dispatch, "_canal_webhook", lambda _e, _s: 0)
    monkeypatch.setattr(
        "observability.alerts.enviar_email_transaccional",
        lambda **kw: correos.append(str(kw.get("to_addr"))) or True,
    )
    return correos


def test_crear_para_otra_persona_escribe_un_evento_y_el_reintento_ninguno(
    equipo: dict[str, int],
) -> None:
    cuerpo = PursuitCreate(
        licitacion_id="LIC-OUTBOX-1",
        organization_id=equipo["org"],
        responsible_user_id=equipo["member"],
    )
    creada, _ = create_pursuit(equipo["owner"], cuerpo, idempotency_key="k-1")
    create_pursuit(equipo["owner"], cuerpo, idempotency_key="k-1")

    (evento,) = _asignaciones(creada.id)
    assert evento["payload"]["responsible_user_id"] == equipo["member"]
    assert evento["payload"]["actor_user_id"] == equipo["owner"]
    assert "owner@example.test" not in str(evento["payload"])


def test_asignarse_a_uno_mismo_no_escribe_evento(equipo: dict[str, int]) -> None:
    creada, _ = create_pursuit(
        equipo["member"],
        PursuitCreate(licitacion_id="LIC-OUTBOX-2", organization_id=equipo["org"]),
    )
    assert _asignaciones(creada.id) == []


def test_reasignar_escribe_un_evento_y_reasignarse_ninguno(equipo: dict[str, int]) -> None:
    creada, _ = create_pursuit(
        equipo["member"],
        PursuitCreate(licitacion_id="LIC-OUTBOX-1", organization_id=equipo["org"]),
    )
    tras_otra = update_pursuit(
        equipo["member"],
        creada.id,
        PursuitUpdate(responsible_user_id=equipo["otra"]),
        organization_id=equipo["org"],
    )
    assert [e["payload"]["responsible_user_id"] for e in _asignaciones(creada.id)] == [
        equipo["otra"]
    ]

    update_pursuit(
        equipo["owner"],
        creada.id,
        PursuitUpdate(responsible_user_id=equipo["owner"], expected_version=tras_otra.version),
        organization_id=equipo["org"],
    )
    assert len(_asignaciones(creada.id)) == 1, "el owner se asignó a sí mismo"


def test_la_campana_recibe_el_mismo_aviso_una_sola_vez(
    tmp_db: Any, equipo: dict[str, int], sin_salidas_externas: list[str]
) -> None:
    from scheduler.jobs.event_dispatch import dispatch_pending

    db_mod, _ = tmp_db
    create_pursuit(
        equipo["owner"],
        PursuitCreate(
            licitacion_id="LIC-OUTBOX-1",
            organization_id=equipo["org"],
            responsible_user_id=equipo["member"],
        ),
    )

    assert _notificaciones(db_mod, equipo["member"]) == [], "no se escribe en la request"
    dispatch_pending()
    dispatch_pending()

    (aviso,) = _notificaciones(db_mod, equipo["member"])
    assert aviso["type"] == "pursuit_asignada"
    assert aviso["title"] == "Te han asignado: Servicio SAP"
    assert aviso["body"] == (
        "owner te asignó esta oportunidad. Ábrela para ver la decisión pendiente "
        "y la próxima acción."
    )
    assert aviso["licitacion_id"] == "LIC-OUTBOX-1"
    assert aviso["organization_id"] == equipo["org"]
    # S4.6: la asignación llega además por correo (`immediate` por defecto).
    assert sin_salidas_externas == ["member@example.test"]
    assert _notificaciones(db_mod, equipo["owner"]) == []
