"""Recordatorios de aplazamientos del Radar: el seguidor va por ``user_id``.

Desde v135 ``user_id`` es parte de la PK de ``radar_dismissals``, así que el
recordatorio ya no lleva la ``user_key`` como identidad de repuesto.
"""

from __future__ import annotations

from typing import Any

import pytest

from services import deadline_reminders as mod


def _fila(user_id: int) -> dict[str, Any]:
    return {
        "id_externo": "EXP-1",
        "hasta": "2026-11-22T08:00:00+00:00",
        "organization_id": 7,
        "user_id": user_id,
    }


def test_el_recordatorio_del_radar_nombra_al_seguidor_por_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capturados: list[Any] = []
    monkeypatch.setattr("db.radar_dismissals.pospuestos_vencidos", lambda **_k: [_fila(5)])
    monkeypatch.setattr(mod, "_emitir", lambda candidatos: capturados.extend(candidatos) or 0)

    mod.check_radar_postponements()

    assert len(capturados) == 1
    tipo, clave, payload, organization_id = capturados[0]
    assert tipo == "plazo.recordatorio"
    assert clave == "radar_recordatorio_2026-11-22:EXP-1:5:7"
    assert organization_id == 7
    assert payload["seguidores"] == [{"user_id": 5, "organization_id": 7}]
