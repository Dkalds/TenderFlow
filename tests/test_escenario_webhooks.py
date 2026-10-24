"""Escenario: el equipo mantiene su integración por webhook.

Recorrido completo por la API con sesión real (ver ``tests/escenarios.py``).
La salida HTTP se dobla —el escenario no puede llamar a Slack—, y la entrega
fallida se siembra en la tabla como ``sembrar_licitacion`` siembra expedientes:
la produce el despachador de eventos, no el usuario.
"""

from __future__ import annotations

import pytest

from tests.escenarios import abrir_sesion


@pytest.fixture(autouse=True)
def _sin_salida_http(monkeypatch):
    monkeypatch.setattr("api.routes.webhooks.validate_outbound_url", lambda url, **_: url)
    monkeypatch.setattr(
        "api.routes.webhooks._post_pinned_webhook", lambda url, payload, headers: 200
    )


def _entrega_fallida(webhook_id: int) -> int:
    from db.repositories.webhooks import crear_entrega

    delivery_id = crear_entrega(
        webhook_id=webhook_id,
        event_type="pursuit.updated",
        payload_json='{"evento": "pursuit.updated"}',
        delivery_uid=f"escenario-{webhook_id}",
        estado="failed",
        status_code=500,
        success=False,
        proximo_intento=None,
        error="HTTP 500",
    )
    assert delivery_id is not None
    return delivery_id


def test_cu31_webhook_probar_rotar_el_secreto_y_reenviar_lo_fallido(client, api_db):
    """CU-33 — alta, prueba, rotación del secreto y reenvío de una entrega fallida, solo en su equipo."""
    duena = abrir_sesion("integra-webhook@example.com", client)

    creado = duena.post(
        "/webhooks",
        json={
            "name": "Slack del equipo",
            "url": "https://hooks.example.com/equipo",
            "event_types": ["pursuit.*"],
            "formato": "slack_blocks",
            "organization_id": duena.organization_id,
        },
    )
    assert creado.status_code == 201, creado.text
    webhook_id = creado.json()["id"]
    secreto_inicial = creado.json()["secret"]

    prueba = duena.post(f"/webhooks/{webhook_id}/ping")
    assert prueba.status_code == 200, prueba.text
    assert prueba.json()["success"] is True

    # Rotar entrega un secreto nuevo, una sola vez: el detalle no lo repite.
    rotado = duena.post(f"/webhooks/{webhook_id}/rotate-secret")
    assert rotado.status_code == 200, rotado.text
    assert rotado.json()["secret"] != secreto_inicial
    assert "secret" not in duena.get(f"/webhooks/{webhook_id}").json()

    # Una entrega que agotó sus reintentos se ve en el historial y se reenvía.
    fallida = _entrega_fallida(webhook_id)
    historial = {d["id"]: d for d in duena.get(f"/webhooks/{webhook_id}/deliveries").json()}
    assert historial[fallida]["estado"] == "failed"
    reenvio = duena.post(f"/webhooks/{webhook_id}/deliveries/{fallida}/redeliver")
    assert reenvio.status_code == 202, reenvio.text
    historial = {d["id"]: d for d in duena.get(f"/webhooks/{webhook_id}/deliveries").json()}
    assert historial[fallida]["estado"] == "pending"

    # Otra organización no ve el webhook ni puede tocarlo.
    ajena = abrir_sesion("otra-webhook@example.com")
    assert ajena.get("/webhooks").json() == []
    assert ajena.post(f"/webhooks/{webhook_id}/rotate-secret").status_code == 404
    assert ajena.post(f"/webhooks/{webhook_id}/deliveries/{fallida}/redeliver").status_code == 404
