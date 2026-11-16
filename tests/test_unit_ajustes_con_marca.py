"""Los ajustes de la organización se leen aunque el blob lleve claves ajenas al modelo.

``settings_json`` guarda la marca ``alerta_por_defecto`` junto a la
configuración. ``OrganizationSettings`` es ``extra="forbid"``: validar el blob
entero tiraba toda la configuración y el valor ponderado volvía a los defaults.
"""

from __future__ import annotations

from unittest.mock import patch

_BLOB = {
    "probabilidades_etapa": {"identified": 50},
    "alerta_por_defecto": {"reglas": [1], "user_id": 7, "creada_en": "2026-11-01T00:00:00+00:00"},
}


def test_direccion_conserva_las_probabilidades_propias() -> None:
    from services import direccion

    with patch.object(direccion.OrganizationRepository, "get_settings", return_value=_BLOB):
        ajustes = direccion._ajustes(1)

    assert ajustes.probabilidades_etapa["identified"] == 50
