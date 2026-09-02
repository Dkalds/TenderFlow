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


def test_asignarse_a_uno_mismo_no_avisa() -> None:
    with patch.object(mod, "insert_user_notification") as insert:
        mod._notificar_asignacion(_fila(responsible_user_id=3), actor_user_id=3)
    insert.assert_not_called()


def test_asignar_a_otra_persona_le_escribe_una_alerta_con_quien_lo_hizo() -> None:
    usuarios = {
        3: {"id": 3, "email": "ana@example.com", "display_name": "Ana"},
        9: {"id": 9, "email": "luis@example.com", "display_name": "Luis"},
    }
    with (
        patch.object(mod, "get_user_by_id", side_effect=lambda uid: usuarios.get(uid)),
        patch.object(mod, "insert_user_notification", return_value=True) as insert,
    ):
        mod._notificar_asignacion(_fila(), actor_user_id=9)
    kwargs = insert.call_args.kwargs
    assert kwargs["type_"] == mod.TIPO_NOTIFICACION_ASIGNACION
    assert kwargs["licitacion_id"] == "LIC-1" and kwargs["organization_id"] == 7
    assert "Servicio TI" in kwargs["title"]
    assert "Luis" in kwargs["body"]


def test_si_el_responsable_no_existe_o_la_escritura_falla_no_se_propaga() -> None:
    with (
        patch.object(mod, "get_user_by_id", return_value=None),
        patch.object(mod, "insert_user_notification") as insert,
    ):
        mod._notificar_asignacion(_fila(), actor_user_id=9)
    insert.assert_not_called()

    with (
        patch.object(mod, "get_user_by_id", return_value={"id": 3, "email": "a@x.com"}),
        patch.object(mod, "insert_user_notification", side_effect=RuntimeError("caída")),
    ):
        mod._notificar_asignacion(_fila(), actor_user_id=9)  # no lanza


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
