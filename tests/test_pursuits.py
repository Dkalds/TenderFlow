"""Regresión de organizaciones, workflow, aislamiento y ledger de pursuits."""

from __future__ import annotations

import psycopg.errors
import pytest

from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuits import PursuitRepository
from services.organizations import OrganizationAccessError
from services.pursuits import (
    PursuitTransitionError,
    create_pursuit,
    get_metrics,
    list_pursuits,
    update_pursuit,
)
from shared.dto import PursuitCreate, PursuitUpdate


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(email=email, password_hash="test-hash", display_name=email.split("@")[0])


def _licitacion(db_mod, id_externo: str = "LIC-PURSUIT-1") -> None:
    with db_mod.connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fecha_limite, fecha_extraccion) VALUES (%s, %s, %s, %s)",
            (id_externo, "Servicio SAP", "2026-12-01T12:00:00+00:00", "2026-07-30T10:00:00+00:00"),
        )


def _shared_team(db_mod) -> tuple[int, int, int, int]:
    owner = _user("owner@example.test")
    member = _user("member@example.test")
    outsider = _user("outsider@example.test")
    organization_repo = OrganizationRepository()
    organization = organization_repo.create_organization("Equipo", owner)
    organization_id = int(organization["id"])
    organization_repo.add_membership(organization_id, member, "member")
    _licitacion(db_mod)
    return owner, member, outsider, organization_id


def test_personal_organization_is_idempotent(tmp_db):
    _db_mod, _ = tmp_db
    user_id = _user("personal@example.test")
    repo = OrganizationRepository()

    first = repo.ensure_personal_organization(user_id)
    second = repo.ensure_personal_organization(user_id)

    assert first["id"] == second["id"]
    assert first["role"] == "owner"
    with _db_mod.connect_read() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM organizations WHERE personal_owner_user_id = %s",
            (user_id,),
        ).fetchone()
    assert count[0] == 1


def test_shared_members_see_same_pursuit_and_outsider_is_denied(tmp_db):
    db_mod, _ = tmp_db
    owner, member, outsider, organization_id = _shared_team(db_mod)

    created, was_created = create_pursuit(
        owner,
        PursuitCreate(
            licitacion_id="LIC-PURSUIT-1",
            organization_id=organization_id,
            responsible_user_id=member,
        ),
    )
    duplicate, duplicate_created = create_pursuit(
        member,
        PursuitCreate(
            licitacion_id="LIC-PURSUIT-1",
            organization_id=organization_id,
        ),
    )

    assert was_created is True
    assert duplicate_created is False
    assert duplicate.id == created.id
    assert list_pursuits(member, organization_id=organization_id).total == 1
    with pytest.raises(OrganizationAccessError):
        list_pursuits(outsider, organization_id=organization_id)
    assert len(PursuitRepository().list_events(organization_id, created.id)) == 1


def test_workflow_events_and_metrics(tmp_db):
    db_mod, _ = tmp_db
    owner, _member, _outsider, organization_id = _shared_team(db_mod)
    pursuit, _ = create_pursuit(
        owner,
        PursuitCreate(licitacion_id="LIC-PURSUIT-1", organization_id=organization_id),
    )

    with pytest.raises(PursuitTransitionError):
        update_pursuit(
            owner,
            pursuit.id,
            PursuitUpdate(status="won", awarded_amount_eur=100),
            organization_id=organization_id,
        )

    detail = update_pursuit(
        owner,
        pursuit.id,
        PursuitUpdate(status="qualifying"),
        organization_id=organization_id,
    )
    detail = update_pursuit(
        owner,
        pursuit.id,
        PursuitUpdate(status="go_no_go", decision="go", decision_reason="Encaje estratégico"),
        organization_id=organization_id,
    )
    detail = update_pursuit(
        owner,
        pursuit.id,
        PursuitUpdate(status="preparing"),
        organization_id=organization_id,
    )
    detail = update_pursuit(
        owner,
        pursuit.id,
        PursuitUpdate(status="submitted", offer_price_eur=900),
        organization_id=organization_id,
    )
    detail = update_pursuit(
        owner,
        pursuit.id,
        PursuitUpdate(status="won", awarded_amount_eur=950),
        organization_id=organization_id,
        idempotency_key="close-won-1",
    )
    retried = update_pursuit(
        owner,
        pursuit.id,
        PursuitUpdate(status="won", awarded_amount_eur=950),
        organization_id=organization_id,
        idempotency_key="close-won-1",
    )

    assert detail.status == "won"
    assert detail.outcome == "won"
    assert retried.version == detail.version
    assert len(detail.events) == 6
    metrics = get_metrics(owner, organization_id=organization_id)
    assert metrics.pursuits_identified == 1
    assert metrics.pursuits_submitted == 1
    assert metrics.pursuits_won == 1
    assert metrics.win_rate == 1
    assert metrics.awarded_amount_eur == 950


def test_pursuit_events_reject_update_and_delete(tmp_db):
    db_mod, _ = tmp_db
    owner, _member, _outsider, organization_id = _shared_team(db_mod)
    pursuit, _ = create_pursuit(
        owner,
        PursuitCreate(licitacion_id="LIC-PURSUIT-1", organization_id=organization_id),
    )

    with pytest.raises((psycopg.errors.DatabaseError, ValueError), match="append-only"):
        with db_mod.connect() as conn:
            conn.execute(
                "UPDATE pursuit_events SET event_type = 'tampered' WHERE pursuit_id = %s",
                (pursuit.id,),
            )
    with pytest.raises((psycopg.errors.DatabaseError, ValueError), match="append-only"):
        with db_mod.connect() as conn:
            conn.execute("DELETE FROM pursuit_events WHERE pursuit_id = %s", (pursuit.id,))
