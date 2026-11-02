"""Lo que deja quien sale de una organización, contra Postgres (auditoría 2026-11).

Versión con BD de `tests/test_unit_organizations_baja_y_cuotas.py`: allí se fija
qué SQL se emite; aquí, que las filas quedan como se espera.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from db.database import connect
from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuit_tasks import PursuitTasksRepository
from db.repositories.user_profiles import get_user_profile, upsert_user_profile
from db.repositories.webhooks import WebhookRepository
from db.users import create_user

_HOY = "2026-11-01"


def _user(email: str) -> int:
    return create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=email.split("@")[0],
    )


@pytest.fixture()
def equipo(tmp_db):
    """Una organización con un owner y un miembro que ha dejado cosas creadas."""
    repo = OrganizationRepository()
    owner = _user("baja-owner@example.test")
    miembro = _user("baja-miembro@example.test")
    organization_id = int(repo.create_organization("Equipo de baja", owner)["id"])
    repo.add_membership(organization_id, miembro, "admin")

    webhooks = WebhookRepository()
    del_miembro, _ = webhooks.create(
        name="del-miembro",
        url="https://hooks.example.com/miembro",
        event_types=["*"],
        organization_id=organization_id,
        created_by=miembro,
    )
    del_owner, _ = webhooks.create(
        name="del-owner",
        url="https://hooks.example.com/owner",
        event_types=["*"],
        organization_id=organization_id,
        created_by=owner,
    )
    repo.create_invitation(
        organization_id,
        "alias@example.test",
        "admin",
        token_hash="a" * 64,  # pragma: allowlist secret
        invited_by_user_id=miembro,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    upsert_user_profile(
        {"weights": {"encaje": 3}}, organization_id, "organization", user_id=miembro
    )
    return {
        "repo": repo,
        "owner": owner,
        "miembro": miembro,
        "organization_id": organization_id,
        "webhook_miembro": del_miembro,
        "webhook_owner": del_owner,
    }


def _webhook_activo(webhook_id: int) -> bool:
    with connect() as c:
        fila = c.execute("SELECT active FROM webhooks WHERE id = %s", (webhook_id,)).fetchone()
    return bool(fila and fila[0])


def _invitaciones_pendientes(organization_id: int) -> int:
    return len(OrganizationRepository().list_invitations(organization_id))


def _comprobar_baja(equipo: dict) -> None:
    assert not _webhook_activo(equipo["webhook_miembro"])
    assert _webhook_activo(equipo["webhook_owner"]), "el webhook de otro no se toca"
    assert _invitaciones_pendientes(equipo["organization_id"]) == 0
    perfil = get_user_profile(
        "user-key-que-no-existe", equipo["organization_id"], user_id=equipo["owner"]
    )
    assert perfil is None, "el perfil del que salió ya no lo hereda el equipo"


def test_salir_deja_inactivos_sus_webhooks_revoca_sus_invitaciones_y_retira_su_perfil(equipo):
    assert equipo["repo"].salir(equipo["organization_id"], equipo["miembro"]) is True

    _comprobar_baja(equipo)


def test_que_un_admin_lo_retire_hace_lo_mismo(equipo):
    equipo["repo"].add_membership(
        equipo["organization_id"],
        equipo["miembro"],
        "admin",
        invited_by_user_id=equipo["owner"],
        status="revoked",
    )

    _comprobar_baja(equipo)


def test_la_tarea_de_quien_salio_vence_sin_destinatario(equipo):
    organization_id = equipo["organization_id"]
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, estado, fecha_limite, fecha_publicacion, fecha_extraccion) "
            "VALUES ('BAJA-1', 'Expediente', 'PUB', '2026-12-01', '2026-09-01', '2026-09-01')"
        )
        pursuit_id = int(
            c.execute(
                "INSERT INTO pursuits (organization_id, licitacion_id, responsible_user_id, "
                " status, created_at, updated_at, version) "
                "VALUES (%s, 'BAJA-1', %s, 'identified', '2026-09-01', '2026-09-01', 1) "
                "RETURNING id",
                (organization_id, equipo["owner"]),
            ).fetchone()[0]
        )
    tareas = PursuitTasksRepository()
    tareas.create(
        pursuit_id=pursuit_id,
        organization_id=organization_id,
        titulo="Pedir el pliego",
        responsable_user_id=equipo["miembro"],
        vence=_HOY,
    )

    assert tareas.vencen_en(fecha=_HOY)[0]["responsable_user_id"] == equipo["miembro"]

    equipo["repo"].salir(organization_id, equipo["miembro"])

    assert tareas.vencen_en(fecha=_HOY)[0]["responsable_user_id"] is None


def test_un_aviso_de_cuenta_sin_verificar_no_gasta_el_enlace_vigente_del_titular(tmp_db):
    """G1-7-5: repetir el alta no mata el enlace de recuperación que el titular pidió."""
    from db.password_reset import (
        consume_reset_token,
        create_reset_token_for_email,
        create_reset_token_for_user,
    )

    user_id = _user("titular-reset@example.test")
    futuro = "2999-01-01T00:00:00+00:00"
    assert create_reset_token_for_email("titular-reset@example.test", "1" * 64, futuro)

    assert create_reset_token_for_user(user_id, "2" * 64, futuro)

    assert consume_reset_token("1" * 64, "hash-nuevo") == user_id
