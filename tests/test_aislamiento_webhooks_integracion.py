"""Qué webhooks lee el despachador, contra Postgres (auditoría 2026-11).

Versión con BD de `tests/test_unit_webhooks_aislamiento_tenant.py`: allí se fija
la decisión con dobles; aquí, que el predicado SQL de `list_active_subscribers`
deja fuera los webhooks de las demás organizaciones.
"""

from __future__ import annotations

from db.repositories.organizations import OrganizationRepository
from db.repositories.webhooks import WebhookRepository
from db.users import create_user


def _organizacion(email: str) -> int:
    user_id = create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=email.split("@")[0],
    )
    return int(OrganizationRepository().ensure_personal_organization(user_id)["id"])


def test_los_suscriptores_de_un_evento_son_los_de_su_organizacion_y_los_globales(tmp_db):
    org_a = _organizacion("aislamiento-wh-a@example.test")
    org_b = _organizacion("aislamiento-wh-b@example.test")
    repo = WebhookRepository()
    id_a, _ = repo.create(
        name="a", url="https://hooks.example.com/a", event_types=["*"], organization_id=org_a
    )
    id_b, _ = repo.create(
        name="b", url="https://hooks.example.com/b", event_types=["*"], organization_id=org_b
    )
    id_global, _ = repo.create(name="g", url="https://hooks.example.com/g", event_types=["*"])

    assert {w["id"] for w in repo.list_active_subscribers(organization_id=org_a)} == {
        id_a,
        id_global,
    }
    assert {w["id"] for w in repo.list_active_subscribers(organization_id=org_b)} == {
        id_b,
        id_global,
    }
    # Un evento sin organización no es de ninguna: solo la integración de instancia.
    assert {w["id"] for w in repo.list_active_subscribers()} == {id_global}
