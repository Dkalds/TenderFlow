"""Re-entrega manual de una entrega de webhook, contra Postgres (C2.4).

``POST /webhooks/{id}/deliveries/{delivery_id}/redeliver`` exigía
``require_admin`` —el dueño de la organización no podía usarla desde su
equipo— y, peor, no miraba de quién era la entrega: con el id de cualquier
entrega de cualquier organización, un administrador de instancia la reencolaba
a través de un webhook propio. Ahora va con el mismo alcance que
``rotate-secret``: permiso de escritura en la organización, y el webhook y la
entrega tienen que ser suyos, o 404.
"""

from __future__ import annotations

import pytest

from api.app import app
from api.routes.dual_auth import require_any_auth
from db.repositories.organizations import OrganizationRepository
from db.repositories.webhooks import crear_entrega


def _usuario(email: str) -> tuple[int, int]:
    """Usuario con su organización personal. Devuelve ``(user_id, org_id)``."""
    from db.users import create_user

    user_id = create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=email.split("@")[0],
    )
    org_id = int(OrganizationRepository().ensure_personal_organization(user_id)["id"])
    return user_id, org_id


def _como(user_id: int) -> None:
    # `is_admin: False` a propósito: lo que se prueba es que el dueño de la
    # organización, sin ser administrador de la instancia, puede reenviar.
    app.dependency_overrides[require_any_auth] = lambda: {
        "user_id": user_id,
        "auth_method": "session",
        "user_key": f"user-{user_id}",
        "email": f"u{user_id}@example.test",
        "is_admin": False,
    }


@pytest.fixture(autouse=True)
def _sin_ssrf(monkeypatch):
    """Solo se retira la sustitución que pone este fichero (ver test_webhooks_rotate_secret)."""
    monkeypatch.setattr("api.routes.webhooks.validate_outbound_url", lambda url, **_: url)
    yield
    app.dependency_overrides.pop(require_any_auth, None)


def _webhook(client, *, organization_id: int) -> int:
    respuesta = client.post(
        "/api/v1/webhooks",
        json={
            "name": "integración",
            "url": "https://hooks.example.com/reentrega",
            "event_types": ["pursuit.*"],
            "organization_id": organization_id,
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return int(respuesta.json()["id"])


def _entrega(webhook_id: int, *, estado: str = "failed") -> int:
    delivery_id = crear_entrega(
        webhook_id=webhook_id,
        event_type="pursuit.updated",
        payload_json='{"evento": "pursuit.updated"}',
        delivery_uid=f"uid-{webhook_id}-{estado}",
        estado=estado,
        status_code=500 if estado != "delivered" else 200,
        success=estado == "delivered",
        proximo_intento=None,
        error=None,
    )
    assert delivery_id is not None
    return delivery_id


def _estado(delivery_id: int) -> tuple[str, str | None]:
    from db.database import connect_read

    with connect_read() as c:
        fila = c.execute(
            "SELECT estado, proximo_intento FROM webhook_deliveries WHERE id = %s",
            (delivery_id,),
        ).fetchone()
    return str(fila[0]), (str(fila[1]) if fila[1] is not None else None)


def _ruta(webhook_id: int, delivery_id: int) -> str:
    return f"/api/v1/webhooks/{webhook_id}/deliveries/{delivery_id}/redeliver"


def test_el_dueno_de_la_organizacion_reencola_una_entrega_fallida(client, api_db):
    user_id, org_id = _usuario("reentrega-ok@example.test")
    _como(user_id)
    webhook_id = _webhook(client, organization_id=org_id)
    delivery_id = _entrega(webhook_id)

    respuesta = client.post(_ruta(webhook_id, delivery_id))
    assert respuesta.status_code == 202, respuesta.text
    assert respuesta.json() == {"status": "encolada"}

    estado, proximo = _estado(delivery_id)
    assert estado == "pending"
    assert proximo is not None, "sin próximo intento el job de reintento no la recoge"


def test_el_historial_dice_en_que_estado_esta_cada_entrega(client, api_db):
    """La UI ofrece reenviar solo lo que falló: necesita el estado, no solo `success`."""
    user_id, org_id = _usuario("reentrega-estado@example.test")
    _como(user_id)
    webhook_id = _webhook(client, organization_id=org_id)
    fallida = _entrega(webhook_id, estado="failed")
    entregada = _entrega(webhook_id, estado="delivered")

    historial = {d["id"]: d for d in client.get(f"/api/v1/webhooks/{webhook_id}/deliveries").json()}
    assert historial[fallida]["estado"] == "failed"
    assert historial[entregada]["estado"] == "delivered"


def test_una_entrega_ya_completada_es_409(client, api_db):
    user_id, org_id = _usuario("reentrega-409@example.test")
    _como(user_id)
    webhook_id = _webhook(client, organization_id=org_id)
    delivery_id = _entrega(webhook_id, estado="delivered")

    assert client.post(_ruta(webhook_id, delivery_id)).status_code == 409
    assert _estado(delivery_id)[0] == "delivered"


def test_una_entrega_de_otro_webhook_es_404_aunque_sea_de_la_misma_organizacion(client, api_db):
    """El par (webhook, entrega) tiene que casar: la ruta no es un atajo a cualquier entrega."""
    user_id, org_id = _usuario("reentrega-par@example.test")
    _como(user_id)
    uno = _webhook(client, organization_id=org_id)
    otro = _webhook(client, organization_id=org_id)
    delivery_id = _entrega(otro)

    assert client.post(_ruta(uno, delivery_id)).status_code == 404
    assert _estado(delivery_id)[0] == "failed", "un 404 no puede haber reencolado nada"


def test_la_entrega_de_otra_organizacion_es_404_y_no_se_toca(client, api_db):
    """Autorización cruzada: B no reencola la entrega de A, ni por el webhook de A ni por el suyo."""
    user_a, org_a = _usuario("reentrega-a@example.test")
    user_b, org_b = _usuario("reentrega-b@example.test")

    _como(user_a)
    webhook_a = _webhook(client, organization_id=org_a)
    entrega_a = _entrega(webhook_a)

    _como(user_b)
    webhook_b = _webhook(client, organization_id=org_b)
    assert client.post(_ruta(webhook_a, entrega_a)).status_code == 404
    assert client.post(_ruta(webhook_b, entrega_a)).status_code == 404
    assert _estado(entrega_a)[0] == "failed"


def test_un_viewer_no_puede_reenviar(client, api_db):
    """Reenviar es escritura: mismo requisito de rol que rotar el secret."""
    owner_id, _ = _usuario("reentrega-owner@example.test")
    viewer_id, _ = _usuario("reentrega-viewer@example.test")
    organizations = OrganizationRepository()
    org_id = int(organizations.create_organization("Equipo", owner_id)["id"])
    organizations.add_membership(org_id, viewer_id, "viewer")

    _como(owner_id)
    webhook_id = _webhook(client, organization_id=org_id)
    delivery_id = _entrega(webhook_id)

    _como(viewer_id)
    respuesta = client.post(_ruta(webhook_id, delivery_id), params={"organization_id": org_id})
    assert respuesta.status_code == 403, respuesta.text
    assert _estado(delivery_id)[0] == "failed"
