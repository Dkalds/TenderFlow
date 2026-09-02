"""Contrato HTTP del hilo de comentarios de una oportunidad.

Fija lo que el cliente ve: el hilo vuelve en orden cronológico con el autor
resuelto y ``can_delete`` calculado; el contador viaja en el listado y en la
ficha; un ``viewer`` lee pero no escribe; un forastero recibe 403; el borrado
es del autor o de un moderador (owner/admin); y reenviar con la misma clave
de idempotencia no duplica el mensaje.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from api.routes.dual_auth import require_any_auth
from db.repositories.organizations import OrganizationRepository


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=email.split("@")[0],
    )


def _licitacion(id_externo: str = "LIC-COMMENTS") -> None:
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fecha_limite, fecha_extraccion) VALUES (%s, %s, %s, %s)",
            (id_externo, "Migración SAP", "2026-11-01T10:00:00+00:00", "2026-07-30T10:00:00+00:00"),
        )


@pytest.fixture()
def as_user(api_db) -> Iterator[object]:
    """Autentica la petición como el ``user_id`` que indique cada test."""
    from api.app import app

    class _Principal:
        user_id: int | None = None

        def __call__(self) -> dict[str, object]:
            return {
                "user_id": self.user_id,
                "auth_method": "session",
                "user_key": f"comments-{self.user_id}",
            }

    principal = _Principal()
    app.dependency_overrides[require_any_auth] = principal
    try:
        yield principal
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


def _team(prefix: str) -> tuple[int, int, int, int, int]:
    """Owner, member, viewer, forastero y la organización compartida de los tres primeros."""
    owner = _user(f"{prefix}-owner@example.test")
    member = _user(f"{prefix}-member@example.test")
    viewer = _user(f"{prefix}-viewer@example.test")
    outsider = _user(f"{prefix}-outsider@example.test")
    repo = OrganizationRepository()
    organization_id = int(repo.create_organization("Equipo Bid", owner)["id"])
    repo.add_membership(organization_id, member, "member")
    repo.add_membership(organization_id, viewer, "viewer")
    _licitacion()
    return owner, member, viewer, outsider, organization_id


def _open_pursuit(client, as_user, owner, organization_id, licitacion_id="LIC-COMMENTS"):
    as_user.user_id = owner
    created = client.post(
        "/api/v1/pursuits",
        json={"licitacion_id": licitacion_id, "organization_id": organization_id},
    )
    assert created.status_code == 201
    return int(created.json()["id"])


def _thread(pursuit_id: int) -> str:
    return f"/api/v1/pursuits/{pursuit_id}/comments"


def test_the_team_reads_the_thread_in_order_with_author_and_permissions(client, as_user):
    owner, member, viewer, _outsider, organization_id = _team("thread")
    pursuit_id = _open_pursuit(client, as_user, owner, organization_id)
    scope = {"organization_id": organization_id}

    as_user.user_id = member
    first = client.post(_thread(pursuit_id), params=scope, json={"body": "  ¿Vamos a por ella?  "})
    assert first.status_code == 201
    assert first.json()["body"] == "¿Vamos a por ella?"
    assert first.json()["author_user_id"] == member
    assert first.json()["author_name"] == "thread-member"
    assert first.json()["can_delete"] is True

    as_user.user_id = owner
    second = client.post(_thread(pursuit_id), params=scope, json={"body": "Sí, prepara el GO."})
    assert second.status_code == 201

    as_user.user_id = viewer
    listed = client.get(_thread(pursuit_id), params=scope)
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 2
    assert body["pursuit_id"] == pursuit_id
    assert body["organization_id"] == organization_id
    assert [item["body"] for item in body["items"]] == ["¿Vamos a por ella?", "Sí, prepara el GO."]
    # Un viewer no borra nada, ni siquiera lo que no es suyo.
    assert [item["can_delete"] for item in body["items"]] == [False, False]

    # El owner modera: puede borrar el comentario del member.
    as_user.user_id = owner
    as_owner = client.get(_thread(pursuit_id), params=scope).json()
    assert [item["can_delete"] for item in as_owner["items"]] == [True, True]

    # El contador viaja en la ficha y en el tablero.
    detail = client.get(f"/api/v1/pursuits/{pursuit_id}", params=scope)
    assert detail.json()["comments_count"] == 2
    board = client.get("/api/v1/pursuits", params=scope)
    assert board.json()["items"][0]["comments_count"] == 2


def test_the_thread_is_paginated_from_the_most_recent_comment(client, as_user):
    owner, _member, _viewer, _outsider, organization_id = _team("paging")
    pursuit_id = _open_pursuit(client, as_user, owner, organization_id)
    scope = {"organization_id": organization_id}

    for texto in ("uno", "dos", "tres"):
        posted = client.post(_thread(pursuit_id), params=scope, json={"body": texto})
        assert posted.status_code == 201

    latest = client.get(_thread(pursuit_id), params={**scope, "limit": 2}).json()
    older = client.get(_thread(pursuit_id), params={**scope, "limit": 2, "offset": 2}).json()

    assert latest["total"] == 3
    assert [item["body"] for item in latest["items"]] == ["dos", "tres"]
    assert [item["body"] for item in older["items"]] == ["uno"]


def test_a_viewer_can_read_but_not_write(client, as_user):
    owner, _member, viewer, _outsider, organization_id = _team("viewer")
    pursuit_id = _open_pursuit(client, as_user, owner, organization_id)
    scope = {"organization_id": organization_id}

    as_user.user_id = viewer
    assert client.get(_thread(pursuit_id), params=scope).status_code == 200
    denied = client.post(_thread(pursuit_id), params=scope, json={"body": "hola"})

    assert denied.status_code == 403
    assert "viewer" in denied.json()["detail"]


def test_an_outsider_is_denied_the_whole_thread(client, as_user):
    owner, _member, _viewer, outsider, organization_id = _team("outsider")
    pursuit_id = _open_pursuit(client, as_user, owner, organization_id)
    scope = {"organization_id": organization_id}
    posted = client.post(_thread(pursuit_id), params=scope, json={"body": "interno"})
    comment_id = posted.json()["id"]

    as_user.user_id = outsider
    assert client.get(_thread(pursuit_id), params=scope).status_code == 403
    assert client.post(_thread(pursuit_id), params=scope, json={"body": "x"}).status_code == 403
    assert client.delete(f"{_thread(pursuit_id)}/{comment_id}", params=scope).status_code == 403


def test_an_unknown_pursuit_is_404(client, as_user):
    as_user.user_id = _user("comments-404@example.test")

    assert client.get(_thread(424242)).status_code == 404
    assert client.post(_thread(424242), json={"body": "x"}).status_code == 404
    assert client.delete(f"{_thread(424242)}/1").status_code == 404


def test_an_empty_or_oversized_comment_is_422(client, as_user):
    owner, _member, _viewer, _outsider, organization_id = _team("validation")
    pursuit_id = _open_pursuit(client, as_user, owner, organization_id)
    scope = {"organization_id": organization_id}

    blank = client.post(_thread(pursuit_id), params=scope, json={"body": "   "})
    oversized = client.post(_thread(pursuit_id), params=scope, json={"body": "x" * 4001})
    missing = client.post(_thread(pursuit_id), params=scope, json={})

    assert blank.status_code == 422
    assert oversized.status_code == 422
    assert missing.status_code == 422
    assert client.get(_thread(pursuit_id), params=scope).json()["total"] == 0


def test_a_retried_post_with_the_same_idempotency_key_does_not_duplicate(client, as_user):
    owner, _member, _viewer, _outsider, organization_id = _team("idempotent")
    pursuit_id = _open_pursuit(client, as_user, owner, organization_id)
    scope = {"organization_id": organization_id}
    headers = {"X-Idempotency-Key": "comment-1"}

    first = client.post(
        _thread(pursuit_id), params=scope, json={"body": "una vez"}, headers=headers
    )
    retry = client.post(
        _thread(pursuit_id), params=scope, json={"body": "una vez"}, headers=headers
    )

    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    assert client.get(_thread(pursuit_id), params=scope).json()["total"] == 1


def test_only_the_author_or_a_moderator_can_delete(client, as_user):
    owner, member, viewer, _outsider, organization_id = _team("delete")
    pursuit_id = _open_pursuit(client, as_user, owner, organization_id)
    scope = {"organization_id": organization_id}

    as_user.user_id = member
    mine = client.post(_thread(pursuit_id), params=scope, json={"body": "mío 1"}).json()["id"]
    mine_too = client.post(_thread(pursuit_id), params=scope, json={"body": "mío 2"}).json()["id"]
    as_user.user_id = owner
    theirs = client.post(_thread(pursuit_id), params=scope, json={"body": "del owner"}).json()["id"]

    as_user.user_id = member
    assert client.delete(f"{_thread(pursuit_id)}/{theirs}", params=scope).status_code == 403
    assert client.delete(f"{_thread(pursuit_id)}/{mine}", params=scope).status_code == 204
    assert client.delete(f"{_thread(pursuit_id)}/{mine}", params=scope).status_code == 404

    as_user.user_id = viewer
    assert client.delete(f"{_thread(pursuit_id)}/{theirs}", params=scope).status_code == 403

    # El owner modera: borra un comentario ajeno.
    as_user.user_id = owner
    assert client.delete(f"{_thread(pursuit_id)}/{mine_too}", params=scope).status_code == 204

    remaining = client.get(_thread(pursuit_id), params=scope).json()
    assert [item["id"] for item in remaining["items"]] == [theirs]
    detail = client.get(f"/api/v1/pursuits/{pursuit_id}", params=scope)
    assert detail.json()["comments_count"] == 1


def test_a_comment_cannot_be_deleted_through_another_pursuit(client, as_user):
    owner, _member, _viewer, _outsider, organization_id = _team("crossed")
    _licitacion("LIC-COMMENTS-B")
    pursuit_a = _open_pursuit(client, as_user, owner, organization_id)
    pursuit_b = _open_pursuit(client, as_user, owner, organization_id, "LIC-COMMENTS-B")
    scope = {"organization_id": organization_id}
    comment_id = client.post(_thread(pursuit_a), params=scope, json={"body": "de A"}).json()["id"]

    crossed = client.delete(f"{_thread(pursuit_b)}/{comment_id}", params=scope)

    assert crossed.status_code == 404
    assert client.get(_thread(pursuit_a), params=scope).json()["total"] == 1
