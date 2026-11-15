"""Payloads de ``pursuit.created``, ``pursuit.state_changed`` y ``pursuit.decided``.

Salen por webhook a sistemas de terceros: lo que se fija aquí es que cumplen el
catálogo, que solo se publican cuando el valor cambia de verdad y que no llevan
ni correos ni el texto libre de la decisión. Que se escriban en la transacción
del cambio lo prueba ``test_s4_outbox.py`` contra Postgres.
"""

from __future__ import annotations

from typing import Any

import pytest

from shared.events import (
    especificacion,
    eventos_de_cambio_pursuit,
    payload_creacion_pursuit,
    validar_payload,
)


def _fila(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 5,
        "organization_id": 7,
        "licitacion_id": "LIC-1",
        "lote_numero": None,
        "tender_title": "Servicio TI",
        "status": "qualifying",
        "decision": "pending",
        "decision_reason": None,
        "responsible_name": "ana@example.test",
    }
    base.update(extra)
    return base


def test_la_creacion_cumple_el_catalogo_y_no_lleva_correos() -> None:
    payload = payload_creacion_pursuit(_fila(status="identified"))

    validar_payload("pursuit.created", payload)
    assert payload["estado"] == "identified"
    assert payload["titulo"] == "Servicio TI"
    assert "@" not in str(payload)


def test_sin_titulo_de_expediente_el_payload_usa_su_id() -> None:
    assert payload_creacion_pursuit(_fila(tender_title=None))["titulo"] == "LIC-1"


def test_cambiar_de_estado_publica_state_changed_con_los_dos_estados() -> None:
    ((tipo, payload),) = eventos_de_cambio_pursuit(_fila(), {"status": "go_no_go"})

    assert tipo == "pursuit.state_changed"
    validar_payload(tipo, payload)
    assert (payload["estado_anterior"], payload["estado_nuevo"]) == ("qualifying", "go_no_go")


def test_decidir_publica_decided_sin_el_motivo_escrito() -> None:
    eventos = eventos_de_cambio_pursuit(
        _fila(),
        {
            "decision": "no_go",
            "decision_reason": "El cliente nos debe dinero",
            "status": "withdrawn",
        },
    )

    assert [tipo for tipo, _ in eventos] == ["pursuit.state_changed", "pursuit.decided"]
    for tipo, payload in eventos:
        validar_payload(tipo, payload)
        assert "decision_reason" not in payload
        assert "El cliente nos debe dinero" not in str(payload)
        assert "@" not in str(payload)
    assert eventos[1][1]["decision"] == "no_go"


@pytest.mark.parametrize(
    "changes",
    [
        {"decision": "pending"},
        {"decision": "go"},
        {"status": "qualifying"},
        {"next_action": "Llamar al órgano"},
        {},
    ],
    ids=["vuelta-a-pending", "misma-decision", "mismo-estado", "otro-campo", "sin-cambios"],
)
def test_lo_que_no_cambia_estado_ni_decide_no_publica_nada(changes: dict[str, Any]) -> None:
    assert eventos_de_cambio_pursuit(_fila(decision="go"), changes) == []


def test_los_tres_eventos_salen_solo_por_webhook() -> None:
    """Sin ``cache``: la señal es global y cada cambio privado la dispararía."""
    for tipo in ("pursuit.created", "pursuit.state_changed", "pursuit.decided"):
        assert especificacion(tipo).canales == ("webhook",)
