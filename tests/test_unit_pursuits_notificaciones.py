"""Aviso de asignación y adjudicación detectada, con los repositorios sustituidos."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import services.pursuits as mod


def _fila(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 5,
        "organization_id": 7,
        "licitacion_id": "LIC-1",
        "tender_title": "Servicio TI",
        "responsible_user_id": 3,
        "status": "qualifying",
    }
    base.update(extra)
    return base


# El aviso de asignación sale del outbox desde 2026-10 (ADR-027): el
# repositorio escribe `pursuit.assigned` en la transacción de la asignación y
# el servicio solo pide una pasada a demanda del despachador. El texto de la
# campana lo fija `shared.events.payload_asignacion`; que llegue a
# `user_notifications` lo prueba `test_outbox_asignacion_integracion.py`.


def test_asignarse_a_uno_mismo_no_avisa() -> None:
    with patch.object(mod, "solicitar_despacho_de_eventos") as solicitar:
        mod._adelantar_aviso_de_asignacion(_fila(responsible_user_id=3), actor_user_id=3)
        mod._adelantar_aviso_de_asignacion(_fila(responsible_user_id=None), actor_user_id=3)
    solicitar.assert_not_called()


def test_asignar_a_otra_persona_le_escribe_una_alerta_con_quien_lo_hizo() -> None:
    from shared.events import payload_asignacion, validar_payload

    with patch.object(mod, "solicitar_despacho_de_eventos") as solicitar:
        mod._adelantar_aviso_de_asignacion(_fila(), actor_user_id=9)
    solicitar.assert_called_once_with("pursuit.assigned")

    payload = payload_asignacion(
        pursuit_id=5,
        licitacion_id="LIC-1",
        organization_id=7,
        responsible_user_id=3,
        actor_user_id=9,
        titulo="Servicio TI",
        actor_nombre="Luis",
    )
    validar_payload("pursuit.assigned", payload)
    assert payload["aviso_titulo"] == "Te han asignado"
    assert payload["titulo"] == "Servicio TI"
    assert payload["detalle"].startswith("Luis te asignó esta oportunidad.")


def test_el_aviso_no_guarda_el_email_del_actor_y_no_se_propaga() -> None:
    """El evento vive para siempre en una tabla append-only: el actor viaja por
    nombre visible, nunca por correo. Y pedir la pasada nunca lanza: si la cola
    no responde, el evento sale en el siguiente cierre."""
    from services.jobs import solicitar_despacho_de_eventos
    from shared.events import ACTOR_ANONIMO_ASIGNACION, payload_asignacion

    payload = payload_asignacion(
        pursuit_id=5,
        licitacion_id="LIC-1",
        organization_id=7,
        responsible_user_id=3,
        actor_user_id=9,
        titulo=None,
        actor_nombre="  ",
    )
    assert payload["detalle"].startswith(ACTOR_ANONIMO_ASIGNACION)
    assert payload["titulo"] == "LIC-1"
    assert "@" not in str(payload)

    with patch("services.jobs.enqueue", side_effect=RuntimeError("cola caída")):
        assert solicitar_despacho_de_eventos("pursuit.assigned") is None


def test_sin_adjudicacion_publicada_no_hay_propuesta_de_cierre() -> None:
    with patch.object(mod._adj_repo, "list_for_licitacion", return_value=[]):
        assert mod._adjudicacion_detectada(_fila()) is None


def test_la_propuesta_agrega_importes_y_ofertas_y_declara_si_queda_cierre() -> None:
    filas = [
        {
            "nombre": "Consultora Uno",
            "nif": "B1",
            "importe_adjudicado": 100000.0,
            "fecha_adjudicacion": "2026-08-20T00:00:00",
            "n_ofertas_recibidas": 3,
            "lote_id": 1,
        },
        {
            "nombre": None,
            "nif": None,
            "importe_adjudicado": 20000.0,
            "fecha_adjudicacion": None,
            "n_ofertas_recibidas": None,
            "lote_id": 2,
        },
    ]
    with (
        patch.object(mod._adj_repo, "list_for_licitacion", return_value=filas),
        patch.object(mod._lic_repo, "get_by_id", return_value={"estado": "ADJ"}),
    ):
        detectada = mod._adjudicacion_detectada(_fila(status="submitted"))
        cerrada = mod._adjudicacion_detectada(_fila(status="won"))

    assert detectada is not None
    assert detectada.estado_licitacion == "ADJ"
    assert detectada.importe_total == 120000.0
    assert detectada.n_ofertas == 3
    assert detectada.adjudicatarios[0].fecha_adjudicacion == "2026-08-20"
    assert detectada.adjudicatarios[1].nombre == "Adjudicatario sin nombre publicado"
    assert detectada.cierre_pendiente is True
    assert cerrada is not None and cerrada.cierre_pendiente is False
