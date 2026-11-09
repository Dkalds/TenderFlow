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


def test_emite_un_evento_por_oportunidad_con_el_responsable_de_seguidor() -> None:
    escritos: list[tuple[Any, ...]] = []

    with (
        patch.object(
            mod.PursuitRepository,
            "open_with_award_rows",
            return_value=[_fila(), _fila(pursuit_id=12, licitacion_id="LIC-2")],
        ),
        patch.object(mod, "get_events", return_value=[]),
        patch.object(mod, "append_domain_event", side_effect=lambda *a, **k: escritos.append(a)),
    ):
        assert mod.notify_detected_awards() == 2

    tipo, pursuit_id, agregado, payload = escritos[0]
    assert (tipo, pursuit_id, agregado) == (mod.EVENTO, 11, "pursuit")
    assert payload["seguidores"] == [{"user_id": 3, "organization_id": 7}]
    assert "Consultora Uno" in payload["detalle"]
    assert [e[3]["id_externo"] for e in escritos] == ["LIC-1", "LIC-2"]


def test_una_oportunidad_ya_avisada_no_se_vuelve_a_emitir() -> None:
    with (
        patch.object(mod.PursuitRepository, "open_with_award_rows", return_value=[_fila()]),
        patch.object(mod, "get_events", return_value=[{"id": 1}]),
        patch.object(mod, "append_domain_event") as append,
    ):
        assert mod.notify_detected_awards() == 0
    append.assert_not_called()


def test_sin_responsable_avisa_a_todo_el_equipo_activo() -> None:
    miembros = [
        {"user_id": 1, "email": "a@example.com", "status": "active"},
        {"user_id": 2, "email": "b@example.com", "status": "invited"},
        {"user_id": 3, "email": None, "status": "active"},
    ]
    with patch.object(mod.OrganizationRepository, "list_members", return_value=miembros):
        destinatarios = mod._destinatarios(_fila(responsible_user_id=None, responsible_email=None))
    assert destinatarios == [1]


def test_un_fallo_al_escribir_no_detiene_al_resto() -> None:
    llamadas: list[str] = []

    def _append(*args: Any, **kwargs: Any) -> int:
        llamadas.append(args[3]["id_externo"])
        if args[3]["id_externo"] == "LIC-1":
            raise RuntimeError("sin conexión")
        return 1

    with (
        patch.object(
            mod.PursuitRepository,
            "open_with_award_rows",
            return_value=[_fila(), _fila(pursuit_id=12, licitacion_id="LIC-2")],
        ),
        patch.object(mod, "get_events", return_value=[]),
        patch.object(mod, "append_domain_event", side_effect=_append),
    ):
        assert mod.notify_detected_awards() == 1
    assert llamadas == ["LIC-1", "LIC-2"]


def test_sin_pursuits_adjudicados_no_escribe_nada() -> None:
    with (
        patch.object(mod.PursuitRepository, "open_with_award_rows", return_value=[]),
        patch.object(mod, "append_domain_event") as append,
    ):
        assert mod.notify_detected_awards() == 0
    append.assert_not_called()
