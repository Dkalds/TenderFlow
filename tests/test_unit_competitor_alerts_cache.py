"""``scheduler/competitor_alerts.check_and_notify``: una consulta por empresa y pasada.

Dos personas de organizaciones distintas siguen a la misma empresa. Antes cada
entrada repetía sus consultas; ahora se piden una vez por pasada, y el motivo
«en tu segmento» de una organización no se cuela en el aviso de la otra.
"""

from __future__ import annotations

from unittest.mock import patch

_MOD = "scheduler.competitor_alerts"


def _entrada(id_: int, email: str, org: int) -> dict[str, object]:
    return {
        "id": id_,
        "email": email,
        "empresa_id": 9,
        "nombre_canonico": "Rival SA",
        "organization_id": org,
        "user_id": id_,
        "last_notified_at": "2026-11-01T00:00:00+00:00",
    }


def test_consulta_una_vez_por_empresa_y_no_mezcla_organizaciones():
    adjudicacion = {
        "licitacion_id": "L1",
        "titulo": "Soporte",
        "organo_contratacion": "Ayto",
        "cpv": "72",
    }
    cuerpos: dict[str, str] = {}
    with (
        patch(
            f"{_MOD}.list_all",
            return_value=[_entrada(1, "a@x.test", 10), _entrada(2, "b@x.test", 20)],
        ),
        patch(f"{_MOD}.nuevas_adjudicaciones_de_empresa", return_value=[adjudicacion]) as nuevas,
        patch(f"{_MOD}._vencimientos_proximos", return_value=[]) as vencimientos,
        patch(f"{_MOD}._en_mi_segmento", return_value=[(10, {"motivo": "organo"})]) as segmento,
        patch(f"{_MOD}.update_last_notified"),
        patch(f"{_MOD}._emitir_en_segmento", return_value=0),
        patch(
            f"{_MOD}.notify",
            side_effect=lambda _nivel, _titulo, cuerpo, **kw: cuerpos.__setitem__(
                kw["to_addr"], cuerpo
            ),
        ),
    ):
        from scheduler.competitor_alerts import check_and_notify

        assert check_and_notify() == 2

    assert nuevas.call_count == 1
    assert vencimientos.call_count == 1
    assert segmento.call_count == 1
    # La fila de la caché no se anotó: cada entrada trabajó sobre su copia.
    assert "_motivo_segmento" not in adjudicacion
    assert cuerpos["a@x.test"] != cuerpos["b@x.test"]
