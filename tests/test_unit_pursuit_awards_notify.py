"""``notify_detected_awards`` sin base de datos: destinatarios, conteo y fallos."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import services.pursuit_awards as mod


def _fila(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "pursuit_id": 11,
        "organization_id": 7,
        "licitacion_id": "LIC-1",
        "responsible_user_id": 3,
        "responsible_email": "ana@example.com",
        "titulo": "Servicio TI",
        "estado": "ADJ",
        "adjudicatarios": "Consultora Uno",
        "importe_total": 120000.0,
    }
    base.update(extra)
    return base


def test_avisa_al_responsable_y_cuenta_solo_las_inserciones_nuevas() -> None:
    escritas: list[dict[str, Any]] = []

    def _insert(**kwargs: Any) -> bool:
        escritas.append(kwargs)
        return len(escritas) == 1  # la segunda fila ya estaba avisada

    with (
        patch.object(
            mod.PursuitRepository,
            "open_with_award_rows",
            return_value=[_fila(), _fila(pursuit_id=12, licitacion_id="LIC-2")],
        ),
        patch.object(mod, "insert_user_notification", side_effect=_insert),
    ):
        assert mod.notify_detected_awards() == 1

    assert [e["licitacion_id"] for e in escritas] == ["LIC-1", "LIC-2"]
    assert escritas[0]["type_"] == mod.TIPO_NOTIFICACION
    assert "Consultora Uno" in escritas[0]["body"]
    assert escritas[0]["organization_id"] == 7


def test_sin_responsable_avisa_a_todo_el_equipo_activo() -> None:
    miembros = [
        {"user_id": 1, "email": "a@example.com", "status": "active"},
        {"user_id": 2, "email": "b@example.com", "status": "invited"},
        {"user_id": 3, "email": None, "status": "active"},
    ]
    with patch.object(mod.OrganizationRepository, "list_members", return_value=miembros):
        destinatarios = mod._destinatarios(_fila(responsible_user_id=None, responsible_email=None))
    assert destinatarios == [(1, "a@example.com")]


def test_un_fallo_al_escribir_no_detiene_al_resto() -> None:
    llamadas: list[str] = []

    def _insert(**kwargs: Any) -> bool:
        llamadas.append(kwargs["licitacion_id"])
        if kwargs["licitacion_id"] == "LIC-1":
            raise RuntimeError("sin conexión")
        return True

    with (
        patch.object(
            mod.PursuitRepository,
            "open_with_award_rows",
            return_value=[_fila(), _fila(pursuit_id=12, licitacion_id="LIC-2")],
        ),
        patch.object(mod, "insert_user_notification", side_effect=_insert),
    ):
        assert mod.notify_detected_awards() == 1
    assert llamadas == ["LIC-1", "LIC-2"]


def test_sin_pursuits_adjudicados_no_escribe_nada() -> None:
    with (
        patch.object(mod.PursuitRepository, "open_with_award_rows", return_value=[]),
        patch.object(mod, "insert_user_notification") as insert,
    ):
        assert mod.notify_detected_awards() == 0
    insert.assert_not_called()
