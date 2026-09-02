"""RGPD sobre el hilo de comentarios: portabilidad y anonimización del autor."""

from __future__ import annotations

from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuit_comments import PursuitCommentRepository
from services.gdpr import anonymize_user_data, export_collaboration_data
from services.pursuit_comments import add_comment, list_comments
from services.pursuits import create_pursuit
from shared.dto import PursuitCommentCreate, PursuitCreate


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(email=email, password_hash="test-hash", display_name=email.split("@")[0])


def _licitacion(db_mod, id_externo: str = "LIC-COMMENT-GDPR") -> None:
    with db_mod.connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fecha_limite, fecha_extraccion) VALUES (%s, %s, %s, %s)",
            (id_externo, "Servicio SAP", "2026-12-01T12:00:00+00:00", "2026-07-30T10:00:00+00:00"),
        )


def test_export_returns_only_the_requesters_comments_and_anonymize_unlinks_them(tmp_db):
    db_mod, _ = tmp_db
    owner = _user("gdpr-owner@example.test")
    member = _user("gdpr-member@example.test")
    repo = OrganizationRepository()
    organization_id = int(repo.create_organization("Equipo", owner)["id"])
    repo.add_membership(organization_id, member, "member")
    _licitacion(db_mod)
    pursuit, _ = create_pursuit(
        owner, PursuitCreate(licitacion_id="LIC-COMMENT-GDPR", organization_id=organization_id)
    )

    mine = add_comment(
        member,
        pursuit.id,
        PursuitCommentCreate(body="lo escribí yo"),
        organization_id=organization_id,
    )
    add_comment(
        owner,
        pursuit.id,
        PursuitCommentCreate(body="lo escribió el owner"),
        organization_id=organization_id,
    )

    exported = export_collaboration_data(member)["pursuit_comments"]
    assert [row["body"] for row in exported] == ["lo escribí yo"]

    anonymize_user_data("gdpr-member-key", user_id=member)

    # El texto sigue siendo trabajo del equipo; el vínculo personal desaparece.
    row = PursuitCommentRepository().get(organization_id, pursuit.id, mine.id)
    assert row is not None
    assert row["author_user_id"] is None
    assert row["body"] == "lo escribí yo"

    thread = list_comments(owner, pursuit.id, organization_id=organization_id)
    assert thread.total == 2
    orphan = next(item for item in thread.items if item.id == mine.id)
    assert orphan.author_user_id is None
    assert orphan.author_name is None
    # Sin autor, solo un moderador puede borrarlo; el owner lo es.
    assert orphan.can_delete is True
